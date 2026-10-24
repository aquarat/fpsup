"""One fp L level-site absolute transfer, offline/quiescent model only.

No transport, borrowed cave, alias conversion, generic installer or live gate.
"""
from array import array
from functools import lru_cache
import hashlib
from pathlib import Path
import struct

import armasm
from v3 import build_v3

HERE = Path(__file__).resolve().parent
SOURCE = HERE/'fpl_level_transfer.S'
BASE, SITE, RESUME = 0xC0000000, 0xC0509730, 0xC0509748
SHA256 = 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'
STOCK = struct.pack('<II', 0xE3A02000, 0xEA000003)


def bl_reachable(site, target):
    if (site | target) & 3 or not 0 <= target <= 0xffffffff:
        return False
    delta = (target-site-8) & 0xffffffff
    if delta & 0x80000000:
        delta -= 0x100000000
    return -(1 << 25) <= delta < (1 << 25)


def direct_candidates(image, base, low, high):
    """Conservative mixed-mode scan, including data and overlapping decodes.

    ARM B/BL/BLX, Thumb B/conditional-B/CBZ/CBNZ/B.W/BL/BLX immediate.
    This is NOT an indirect-control-flow or code/data classification proof.
    """
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from capstone.arm import ARM_OP_IMM
    words, half = array('I'), array('H')
    words.frombytes(image[:len(image)//4*4])
    half.frombytes(image[:len(image)//2*2])
    import sys
    if sys.byteorder != 'little':
        words.byteswap(); half.byteswap()
    hits = []
    for i, w in enumerate(words):
        if w & 0x0e000000 != 0x0a000000:
            continue
        off = (w & 0xffffff) << 2
        if off & 0x2000000:
            off -= 0x4000000
        target = (base+i*4+8+off+(((w >> 23) & 2) if w >> 28 == 15 else 0)) & 0xffffffff
        if low <= target < high:
            hits.append(('ARM', base+i*4, target))
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True
    for i in range(len(half)-1):
        w = half[i]
        if not (w & 0xf800 == 0xe000 or
                w & 0xf000 == 0xd000 and ((w >> 8) & 15) < 14 or
                w & 0xf500 == 0xb100 or
                w & 0xf800 == 0xf000 and half[i+1] & 0x8000):
            continue
        for ins in md.disasm(image[i*2:i*2+4], base+i*2, count=1):
            if not ins.mnemonic.startswith(('b', 'cb')):
                continue
            for op in ins.operands:
                target = op.imm & 0xfffffffe
                if op.type == ARM_OP_IMM and low <= target < high:
                    hits.append(('Thumb', base+i*2, target))
    return hits


@lru_cache(maxsize=1)
def audit(image):
    if hashlib.sha256(image).hexdigest() != SHA256:
        raise ValueError('official fp L 3.02 MAIN fingerprint required')
    if image[SITE-BASE:SITE-BASE+8] != STOCK:
        raise ValueError('both stock words required')
    # These apparent Thumb branches are the upper halves of ARM instructions
    # in the bounded native ARM functions C0508F08..C05091F4 and
    # C05093E0..C0509410. Keep the exclusions visible, exact and image-bound.
    excluded = [('Thumb', 0xC0508FF2, SITE+6), ('Thumb', 0xC05093F2, SITE+6)]
    hits = direct_candidates(image, BASE, SITE, SITE+8)
    if hits != excluded:
        raise ValueError(f'unreviewed direct entry candidate: {hits!r}')
    for address, word in ((0xC0508FF0, 0xE3A03000), (0xC05093F0, 0xE1A0000D),
                          (0xC05094B8, 0xE92D45F0), (0xC050972C, 0xEBEC1AE7)):
        if struct.unpack_from('<I', image, address-BASE)[0] != word:
            raise ValueError('native ARM context mismatch')
    return dict(site=SITE, resume=RESUME, patch_bytes=8,
                raw_direct_candidates=hits, mode_exclusions=excluded,
                indirect_entries_proved_absent=False, live_install_authorized=False)


def build(image, *, site=SITE, offline_quiescent_model=False):
    if site != SITE:
        raise ValueError('only the audited level-success site is supported')
    if not offline_quiescent_model:
        raise ValueError('no live quiescence binding; explicit offline model required')
    evidence = audit(image)
    body = armasm.assemble(SOURCE)
    symbols = armasm.symbols(SOURCE)
    if body[symbols['stock']:symbols['stock']+8] != STOCK:
        raise ValueError('installer stock table mismatch')
    product = build_v3.make_sup(body, 32+symbols['entry'], 'LV8T', min_svc=2)
    return product, {k: 32+v for k, v in symbols.items()}, evidence
