"""Strict host admission of a serialized single-strip header's Gyro2 write span.

This validates supplied allocation/serialization evidence, not camera free space.
The caller must obtain owner_bytes/raw_start from the actual buffer owner. No
fp/fp L hard-coded header maximum, calibration or second FSG2 format is defined.
"""
import struct
import fsg2


class CapacityError(ValueError):
    pass


TYPE_BYTES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4,
              10: 8, 11: 4, 12: 8}


def admit_serialization(*, native_ifd_bytes, prefix_bytes, owner_bytes, raw_start):
    """Pre-write check using the native measured size and explicit owner bounds.

    This does not call the serializer. Its four-argument native ABI has no length
    parameter, so rejecting only after writing is too late for memory safety.
    """
    values = (native_ifd_bytes, prefix_bytes, owner_bytes, raw_start)
    if not all(type(v) is int and 0 <= v <= 0xFFFFFFFF for v in values):
        raise CapacityError('invalid pre-serialization bounds')
    total = native_ifd_bytes+prefix_bytes
    if native_ifd_bytes < 6 or total > min(owner_bytes, raw_start, 0xFFFFFFFF):
        raise CapacityError('native measured size exceeds owner/RAW bound')
    return total


def validate_header(buf, *, serialized_bytes, owner_bytes, raw_start, tag_bytes):
    """Return (aligned writable start, end), after strict structural preflight.

    Restricted to one root/Exif/Sigma MakerNote chain, no next IFDs or SubIFDs,
    one LONG StripOffsets scalar. Other layouts are refused, not inferred safe.
    Native serializer success/adder r0 alone is never admission evidence.
    """
    def require(ok, why):
        if not ok:
            raise CapacityError(why)

    require(all(type(v) is int and v >= 0 for v in
                (serialized_bytes, owner_bytes, raw_start, tag_bytes)), 'invalid bounds')
    require(0 < serialized_bytes <= len(buf) and serialized_bytes <= owner_bytes,
            'serialized header exceeds supplied allocation/bytes')
    require(serialized_bytes <= raw_start <= 0xFFFFFFFF, 'header overlaps RAW')
    buf = bytes(buf[:serialized_bytes])
    require(len(buf) >= 8 and buf[:4] == b'II\x2a\0', 'unsupported TIFF identity')
    structures = [(0, 8)]
    leaves = []

    def span(off, n, why):
        require(0 <= off <= len(buf) and n <= len(buf)-off, why)
        return off, off+n

    def directory(off, label):
        span(off, 2, 'IFD count outside header')
        count = struct.unpack_from('<H', buf, off)[0]
        end = span(off, 2+12*count+4, 'IFD entries outside header')[1]
        require(not any(off < y and x < end for x, y in structures), 'overlapping IFD structure')
        structures.append((off, end))
        require(struct.unpack_from('<I', buf, end-4)[0] == 0, 'next IFD unsupported')
        entries = {}
        for i in range(count):
            tag, typ, n, val = struct.unpack_from('<HHII', buf, off+2+12*i)
            require(tag not in entries, 'duplicate tag')
            require(typ in TYPE_BYTES, 'unsupported TIFF type')
            require(n > 0, 'zero tag count')
            require(tag not in (0x14A, 0x8825, 0xA005), 'additional IFD graph unsupported')
            require(tag != 0x8769 or label == 'root', 'unexpected Exif pointer')
            require(tag != 0x927C or label == 'exif', 'unexpected MakerNote pointer')
            entries[tag] = (typ, n, val)
            size = n*TYPE_BYTES[typ]
            if size > 4 and not (label == 'exif' and tag == 0x927C):
                leaves.append((label, tag, *span(val, size, 'tag value outside serialized header')))
        return entries

    root = directory(struct.unpack_from('<I', buf, 4)[0], 'root')
    require(root.get(0x111) == (4, 1, raw_start), 'RAW offset not independently consistent')
    require(0x8769 in root and root[0x8769][:2] == (4, 1), 'missing Exif pointer')
    exif = directory(root[0x8769][2], 'exif')
    require(0x927C in exif and exif[0x927C][0] == 7, 'missing MakerNote')
    _, mn_n, mn = exif[0x927C]
    span(mn, mn_n, 'MakerNote outside header')
    require(mn_n >= 16 and buf[mn:mn+8] == b'SIGMA\0\0\0', 'invalid Sigma MakerNote')
    signature = span(mn, 10, 'MakerNote signature outside header')
    require(not any(signature[0] < y and x < signature[1] for x, y in structures),
            'MakerNote signature overlaps IFD')
    structures.append(signature)
    maker = directory(mn+10, 'maker')
    require(structures[-1][1] <= mn+mn_n, 'MakerNote directory exceeds container')
    require(fsg2.GTAG in maker, 'native tag absent')
    typ, count, off = maker[fsg2.GTAG]
    require(typ == 7 and count == tag_bytes and count > 4, 'native tag type/count mismatch')
    for label, tag, start, end in leaves:
        require(not any(start < y and x < end for x, y in structures), 'tag value overlaps directory')
    for i, (_, _, start, end) in enumerate(leaves):
        require(not any(start < y and x < end for _, _, x, y in leaves[i+1:]),
                'overlapping tag values (including Lossless)')
    # Reuse the existing format parser after the duplicate/bounds preflight.
    area = fsg2.gtag_area(buf)
    require(area == ((off+3) & ~3, off+count), 'FSG2 area disagreement')
    require(area[0] < area[1] <= min(serialized_bytes, owner_bytes, raw_start),
            'write area outside header ownership')
    require(area[1]-area[0] > 60+288, 'tag cannot hold the existing frame/event reserve')
    return area
