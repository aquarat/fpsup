"""Offline runtime-owned retained image builder. No transport or live CLI.

One zero-reference template; initialize only symbol-derived data words before
cache publication/execution. Caller supplies genuinely owned zeroed 64 KiB and
retains it for the boot. Address validation is not allocator ownership proof.
"""
from pathlib import Path
import struct
import tempfile

import armasm
import fpl_gyro_latched as lat

SOURCE = Path(__file__).resolve().parent/'asm/fpl_gyro_task_retained.S'
SIZE, IMAGE_SIZE = 0x10000, 0x3000


def template(*, cancel=False, sleep_reason=0):
    if type(cancel) is not bool or type(sleep_reason) is not int or not 0 <= sleep_reason <= 0xFFFFFFFF:
        raise ValueError('invalid offline build options')
    capture, cs = lat.runtime_body(cancel=cancel)
    if len(capture) > lat.CODE_ROOM:
        raise ValueError('capture exceeds reservation')
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)/'capture.bin'
        path.write_bytes(capture.ljust(lat.CODE_ROOM, b'\0'))
        defs = ['RT_RUNTIME_OWNED=1', f'RT_CAPTURE_REFS={cs["runtime_refs"]}',
                f'SLEEP_REASON={sleep_reason}', f'CAPTURE_FILE="{path}"']
        image, syms = armasm.assemble(SOURCE, defs), armasm.symbols(SOURCE, defs)
    if (len(image) != IMAGE_SIZE or syms['resident_image'] != 0x1000 or
            syms['capture_image'] != 0x2000 or syms['entry'] != 0 or
            not 0x1000 <= syms['runtime_owner'] <= 0x1FFC):
        raise ValueError('runtime wrapper layout changed')
    reference_offsets(syms, cs)  # ensure exact disjoint words
    return image, syms, cs


def reference_offsets(syms, cs):
    """The six pre-execution data words, NOT a post-execution mutable mask."""
    offsets = (syms['runtime_owner'], *(syms['capture_image']+cs['runtime_refs']+i*4 for i in range(5)))
    if (cs['runtime_refs_end']-cs['runtime_refs'] != 20 or len(set(offsets)) != 6 or
            any(o % 4 or not 0 <= o <= IMAGE_SIZE-4 for o in offsets)):
        raise ValueError('invalid runtime reference offsets')
    return offsets


def validate(staging, owner):
    if (type(staging) is not int or type(owner) is not int or staging % 4 or
            not 0x40000000 <= staging <= 0x80000000-IMAGE_SIZE or
            owner % SIZE or not 0x44400000 <= owner <= 0x46400100-SIZE or
            staging < owner+SIZE and owner < staging+IMAGE_SIZE):
        raise ValueError('invalid or overlapping staging/USER owner')


def initialize(artifact, staging, owner):
    """Simulate a future allocator caller; never patches an instruction."""
    validate(staging, owner)
    image, syms, cs = artifact
    offsets = reference_offsets(syms, cs)
    if len(image) != IMAGE_SIZE or any(struct.unpack_from('<I', image, o)[0] for o in offsets):
        raise ValueError('fresh zero-reference template required; no rearm')
    result = bytearray(image)
    for offset, value in zip(offsets, (owner, owner+0x4000, 2048, owner+0x5000, 11264, 1200)):
        struct.pack_into('<I', result, offset, value)
    return bytes(result)


def verify_resident(initialized, wrapper, capture, syms, cs, *, cancel=False):
    """Owner/ref tables are immutable; only the capture's exact mask may vary."""
    if len(initialized) != IMAGE_SIZE or wrapper != initialized[0x1000:0x2000]:
        raise RuntimeError('resident wrapper/owner reference changed')
    lat.verify_code(initialized[0x2000:], capture, cs, cancel=cancel)
