"""Offline pre-write contract for the evidenced native formatter size ledger.

Callables read/call are supplied by the offline harness. This does not discover
a camera object, prove its lifetime, or infer a RAW boundary from the ledger.
The pointer range below is the harness arena convention, not an ownership map.
The caller must keep both the graph and separate IFD metadata frozen from
measurement through serialization; this helper supplies no lock or allocator.
"""
from dataclasses import dataclass
import struct
import audit_formatter as A
from tag_capacity import CapacityError, admit_serialization, TYPE_BYTES


@dataclass(frozen=True)
class Snapshot:
    root: int
    graph: bytes
    reserved_bytes: int


def snapshot(read, call, root):
    def word(p):
        return struct.unpack('<I', read(p, 4))[0]
    def pointer(p):
        if type(p) is not int or not 0x40000000 <= p < 0x80000000 or p % 4:
            raise CapacityError('missing/out-of-arena probe object pointer')
        return p
    pointer(root)
    graph = bytes(read(root, 12))
    left, right, vt = struct.unpack('<3I', graph)
    if vt not in (A.BASE_VTABLE, A.SELECTED_VTABLE) or word(vt+0x10) != A.SIZE_FN:
        raise CapacityError('unexpected native size vtable')
    total = 0
    for leaf in (left, right):
        pointer(leaf)
        graph += bytes(read(leaf, 24))
        ledger = pointer(word(leaf+0xC))
        body = bytes(read(ledger, 0x4C))
        graph += struct.pack('<I', ledger)+body
        words = struct.unpack('<19I', body)
        for reserved, used in zip(words[8:18:2], words[9:18:2]):
            if used > reserved:
                raise CapacityError('native used row exceeds reservation')
            total += reserved
    if total > 0xFFFFFFFF:
        raise CapacityError('native 32-bit size sum would wrap')
    native = call(A.SIZE_FN, root)
    if native != total:
        raise CapacityError('native size accessor disagrees with ledger')
    return Snapshot(root, graph, native)


def admit(before, current, *, allocation, allocation_bytes, native_ifd_bytes,
          prefix_bytes, raw_start):
    """Bind a native measurement to the same probe graph and explicit owner facts.

    raw_start=None deliberately refuses: formatter reservation is NOT RAW start.
    Caller must supply separately evidenced RAW start and live allocation size.
    """
    if before != current:
        raise CapacityError('formatter metadata changed since measurement')
    if type(allocation) is not int or not 0x40000000 <= allocation < 0x80000000 or allocation % 64:
        raise CapacityError('missing/alignment-invalid template allocation')
    if type(allocation_bytes) is not int or allocation_bytes != before.reserved_bytes:
        raise CapacityError('allocation does not match native reserved size')
    if allocation+allocation_bytes > 0x80000000:
        raise CapacityError('allocation range wraps/exceeds USER RAM')
    if raw_start is None:
        raise CapacityError('RAW start not evidenced by formatter reservations')
    return admit_serialization(native_ifd_bytes=native_ifd_bytes, prefix_bytes=prefix_bytes,
                               owner_bytes=allocation_bytes, raw_start=raw_start)


@dataclass(frozen=True)
class Ownership:
    """Caller-evidenced live extents and lifetime token; never inferred from MAIN.

    generation must change on release/reallocation even if the address is reused.
    This is an offline evidence interface, not a tracker of camera allocations.
    """
    allocation: int
    allocation_bytes: int
    generation: int
    frame_start: int
    frame_end: int


@dataclass(frozen=True)
class FrozenTransfer:
    formatter: Snapshot
    ownership: Ownership
    ifd_graph: tuple
    owner: int
    recording: int
    owner_fields: bytes
    raw: int
    length: int
    destination: int
    recording_layout: tuple = ()


def freeze_transfer(read, call, root, ifd, owner, recording, *, ownership,
                    prefix_bytes, require_recording_headroom=False):
    """Bind one flat native IFD to the evidenced template/DMA field contract.

    Restricted to a childless native TiffIfd and owned native byte values. Full
    selected-format serialization mutates IFDs; freeze only after those mutations
    and final length publication, before a bounded reserialization/copy. Missing
    allocation/frame lifetime evidence refuses. No selected mode is inferred.
    """
    if not isinstance(ownership, Ownership):
        raise CapacityError('missing live ownership evidence')
    o = ownership
    if not all(type(v) is int for v in (o.allocation, o.allocation_bytes,
                                       o.generation, o.frame_start, o.frame_end)):
        raise CapacityError('invalid ownership fields')
    if (o.generation < 0 or o.allocation_bytes <= 0 or
            not 0 < o.frame_start < o.frame_end <= 0xFFFFFFFF):
        raise CapacityError('invalid lifetime/frame extent')
    graph = []

    def take(p, n):
        if not 0x40000000 <= p < 0x80000000 or n < 0 or p+n > 0x80000000:
            raise CapacityError('IFD outside probe arena')
        b = bytes(read(p, n))
        if len(b) != n:
            raise CapacityError('short IFD read')
        graph.append((p, b))
        return b

    def word(p):
        return struct.unpack('<I', read(p, 4))[0]

    head = take(ifd, 0x24)
    words = struct.unpack('<9I', head)
    if words[0] != 0xC07444A0 or words[7]:
        raise CapacityError('unsupported IFD vtable/next graph')
    vector, count, capacity = words[4:7]
    if not 0 < count <= min(capacity, 65535):
        raise CapacityError('invalid IFD count/capacity')
    entries = struct.unpack('<%dI' % count, take(vector, count*4))
    expected = 6+12*count
    seen = set()
    for entry in entries:
        e = take(entry, 24)
        tag, typ, count_value, value, child = struct.unpack_from('<HHIII', e, 8)
        if child or tag in seen or typ not in TYPE_BYTES or count_value == 0:
            raise CapacityError('unsupported child/duplicate/type/count')
        seen.add(tag)
        v = struct.unpack('<5I', take(value, 20))
        n = count_value*TYPE_BYTES[typ]
        if v[0] != 0xC07442D4 or n != v[3] or n > v[4] or n > 0x100000:
            raise CapacityError('incomplete/unbounded native value')
        take(v[2], n)
        if n > 4:
            expected += (n+1) & ~1
    if call(0xC00BAB08, ifd) != expected:
        raise CapacityError('IFD measurement disagrees')
    fmt = snapshot(read, call, root)
    source = word(owner+0x10)
    length = word(recording+0x14C)
    raw = word(recording+0x4C)
    fields = bytes(read(owner+8, 12))
    if word(owner+8) != root or source != o.allocation:
        raise CapacityError('formatter/allocation no longer owned')
    if length != word(owner+0xC) or length != expected+prefix_bytes:
        raise CapacityError('published length differs from frozen IFD')
    # RAW is an absolute destination boundary. It is NOT an offset into source.
    if not o.frame_start <= raw-length < raw <= o.frame_end:
        raise CapacityError('header destination outside live frame extent')
    if source < o.frame_end and o.frame_start < source+o.allocation_bytes:
        raise CapacityError('source and frame allocations overlap')
    admit(fmt, fmt, allocation=source, allocation_bytes=o.allocation_bytes,
          native_ifd_bytes=expected, prefix_bytes=prefix_bytes,
          raw_start=o.allocation_bytes)  # source-only end; frame checked above
    layout = ()
    if require_recording_headroom:
        layout = recording_layout(read, recording, serialized_bytes=length,
                                  frame_bytes=o.frame_end-o.frame_start)
        if layout[0] != o.frame_start:
            raise CapacityError('recording base differs from live frame extent')
    return FrozenTransfer(fmt, o, tuple(graph), owner, recording, fields,
                          raw, length, raw-length, layout)


def recording_layout(read, recording, *, serialized_bytes, frame_bytes):
    """Pre-retreat header layout only; no hard-coded mode size or phase inference.

    frame_bytes is caller-evidenced extent (a measured stride alone is not a
    lifetime/allocation proof). This classifies an offline snapshot; callers
    still need frozen IFD metadata and a live owner before actual writing.
    Return base, headroom, RAW boundary, H, destination, extent for comparison.
    """
    def word(offset):
        return struct.unpack('<I', read(recording+offset, 4))[0]
    base, headroom, raw, length, alternate = map(word, (0x68, 0x128, 0x4C, 0x14C, 0x12C))
    if (type(serialized_bytes) is not int or type(frame_bytes) is not int or
            not 0 < serialized_bytes == length <= headroom < frame_bytes or
            not 0 < base < base+frame_bytes <= 0xFFFFFFFF):
        raise CapacityError('invalid measured headroom/length/frame bounds')
    if alternate or raw != base+headroom:
        raise CapacityError('not the pre-retreat RAW-boundary layout')
    return (base, headroom, raw, length, raw-length, frame_bytes)


def admit_transfer(before, current):
    """Require unchanged metadata AND owner epoch/fields before the transfer."""
    if not isinstance(before, FrozenTransfer) or before != current:
        raise CapacityError('IFD/owner/frame/lifetime changed since freeze')
    return current.ownership.allocation, current.destination, current.length
