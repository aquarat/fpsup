#!/usr/bin/env python3
"""Build Gyro2 as a loader v3 sup.

    python3 -B build.py            -> build/40GYR2.BIN

Uses fpSup's v3 helpers read-only (make_sup, the reference image) and its
assembler; nothing in fpSup is written.
"""
import pathlib, re, struct, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
V3 = ROOT / 'fpSup' / 'fp_usb_shell' / 'v3'
sys.path.insert(0, str(V3))
sys.path.insert(0, str(V3.parent))

import build_v3 as B                       # noqa: E402
from armasm import assemble                # noqa: E402

SRC = HERE / 'src' / 'gyr2.S'
OUT = HERE / 'build' / '40GYR2.BIN'
SUP_ID = 'GYR2'
VERSION = 0x00000006                       # frames written from the tag observer, no DMA patch

ACCEL_SITE = 0xC050D4C8


class BuildError(RuntimeError):
    pass


def equ(name, src=SRC):
    m = re.search(rf'^\.equ\s+{name},\s*(0x[0-9A-Fa-f]+|\d+)', pathlib.Path(src).read_text(), re.M)
    if not m:
        raise BuildError(f'{name} not found in {SRC.name}')
    return int(m.group(1), 0)


def build(src=SRC):
    """(file bytes, info).  `src`: another copy of the source (mutation tests)."""
    code = assemble(src)
    image = B.IMAGE.read_bytes()
    # The header DMA (0xC038C77C) is not patched any more: the frames are
    # written from the firmware's own tag-observer notify.
    accel = struct.pack('<I', 0xE3A02000)
    if B.stock(ACCEL_SITE, 4, image) != accel:
        raise BuildError(f'the image has {B.stock(ACCEL_SITE, 4, image).hex()} at {ACCEL_SITE:#x}, not mov r2, #0')
    if equ('WRITER', src) != VERSION:
        raise BuildError('WRITER in the source is not the build VERSION')
    if equ('ACCEL_SITE', src) != ACCEL_SITE:
        raise BuildError('ACCEL_SITE in the source and the build disagree')
    # Position independence: no word in the code may point into the code as
    # if it sat at 0 -- armasm already refuses relocations other than local
    # bl and pc-relative ldr, so absolute self-pointers cannot be emitted.
    body = code
    # The gyro and level buffers sit past the file; the loader zeroes them.
    file_len = B.SL_HEADER_LEN + len(body)
    file_len += -file_len % 4
    try:
        bss = equ('GLOG_N', src) * 6 + equ('ELOG_N', src) * 12
        try:
            bss += equ('VLOG_N', src) * 8           # the Vd ring
            bss += equ('GTAG_MAX', src)            # zeros for the tag observer
        except BuildError:
            pass
    except BuildError:                       # an older stage (P0-P3): no buffers
        bss = None
    block = None if bss is None else file_len + 8 + bss   # + 8: gbuf is 8-aligned
    sup = B.make_sup(body, B.SL_HEADER_LEN, SUP_ID, version=VERSION, block_size=block)
    return sup, {'code': len(code), 'file': len(sup), 'block': block or len(sup)}


def observer_probe(fp_image, fpl_image, *, sample_hz, tag_capacity, frame_callback):
    """Raw callable fp L observer seam, never a loader sup or an installer.

    All three experiment inputs are mandatory. Their values are not firmware
    calibration/capacity claims. The owner must allocate and zero the returned
    text/state, and own the callback; this API only builds offline bytes.
    """
    from audit_observer import audit
    from armasm import symbols
    if not 1 <= sample_hz <= 10000:
        raise BuildError('sample_hz must be an explicit bounded experiment value')
    if not 352 <= tag_capacity <= 4096:
        raise BuildError('tag_capacity must be 352..4096; native free space remains unverified')
    if not 0x40000000 <= frame_callback < 0x80000000 or frame_callback % 4:
        raise BuildError('frame_callback must be an aligned owned ARM address')
    evidence = audit(fp_image, fpl_image)
    defines = ['GYR2_FPL_OBSERVER=1', f'GYR2_SAMPLE_HZ={sample_hz}',
               f'GYR2_TAG_CAPACITY={tag_capacity}', f'GYR2_FRAME_CALLBACK={frame_callback}']
    code = assemble(SRC, defines)
    offsets = symbols(SRC, defines)
    if 'entry' in offsets or 'drain' in offsets or 'mode_info' in offsets:
        raise BuildError('observer-only probe unexpectedly includes product/capture code')
    import hashlib
    profile = HERE / 'src/profiles/fpl302_observer.inc.S'
    evidence['probe'] = {
        'sha256': hashlib.sha256(code).hexdigest(), 'bytes': len(code),
        'sample_hz_experiment': sample_hz, 'tag_capacity_experiment': tag_capacity,
        'frame_callback': hex(frame_callback), 'symbols': offsets,
        'sources': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (HERE / 'build.py', SRC, profile, HERE / 'audit_observer.py')},
    }
    return code, offsets, evidence


def main():
    import argparse, hashlib, json
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=pathlib.Path, help='write DIR/40GYR2.BIN and DIR/build.json (for fpSup/tools/release_v3.py)')
    a = ap.parse_args()
    sup, info = build()
    out = a.out / OUT.name if a.out else OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(sup)
    if a.out:
        root = HERE.parents[1]
        sources = [HERE / 'build.py', SRC]
        (a.out / 'build.json').write_text(json.dumps({
            'product': 'fpSup-Gyro2, Loader v3 sup', 'file': OUT.name, 'sup_id': SUP_ID,
            'version': VERSION, 'sha256': hashlib.sha256(sup).hexdigest(), 'facts': info,
            'sources': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        }, indent=1) + '\n')
    print(f'{out}: {info["file"]} bytes (code {info["code"]}), block {info["block"]}')


if __name__ == '__main__':
    main()
