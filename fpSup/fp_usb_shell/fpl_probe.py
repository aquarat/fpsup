#!/usr/bin/env python3
"""First fp L trial: stock AutoRun memory-to-file commands, no injected code.

Build and inspect are offline. Neither command opens USB or installs a card.
This is a diagnostic script, not a replacement for the shared sup loader.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from firmware import get_camera

CAMERA = get_camera('fp-l-3.02')
BASE = 0xC0000000
# Addresses traced in the official 3.02 image; provenance: docs/FPL_PORT.md.
# Only RAM/image reads: no MMIO, calibration/settings commands or memory writes.
REGIONS = (
    ('ARUN', 0xC03DA610, 0x200, True, 'AutoRun wrapper and surrounding code'),
    ('SHELL', 0xC0BD2398, 77 * 24 + 24, True, '77 shell entries and terminator'),
    ('FILES', 0xC03660A8, 0x300, True, 'File constructor and file I/O wrappers'),
    ('IMUFW', 0xC072A4C0, 0x6200, True, 'Whole embedded IMU image, including the proposed cave'),
    ('IMUMDL', 0xC307A0B0, 8, False, 'IMU image pointer and length'),
    ('IMUCTL', 0xC31E23D4, 0x20, False, 'IMU driver configuration pointer/length pairs'),
    ('IMUFLAG', 0xC31F5CB8, 4, False, 'IMU image load-once flag'),
    ('HEAPS', 0xC30739D8, 0x40, False, 'Allocator class-to-channel pointers and trailing word'),
    ('POOL', 0xC37588BC, 16, False, 'Shell bufmem descriptor; no allocation requested'),
    ('DONE', 0xC03DA970, 76, True, 'AutoRun start body; written last as completion marker'),
)


def autorun():
    return ''.join(f'mem save \\FPLPROBE\\{name}.BIN 0x{addr:08X},,0x{size:X}\n'
                   for name, addr, size, _, _ in REGIONS).encode('ascii')


def build(main, out):
    image = CAMERA.verify_main(main)
    # Exclusive creation: never replace a previous trial or a user's card files.
    out.mkdir(parents=True, exist_ok=False)
    card = out / 'card'
    (card / 'FPLPROBE').mkdir(parents=True)
    script = autorun()
    (card / 'AutoRun.txt').write_bytes(script)
    manifest = {
        'camera': CAMERA.name,
        'kind': 'stock-AutoRun-read-probe',
        'camera_tested': False,
        'main_sha256': CAMERA.main_sha256,
        'autorun_sha256': hashlib.sha256(script).hexdigest(),
        'commands': len(REGIONS),
        'output_bytes': sum(r[2] for r in REGIONS),
        'regions': [dict(name=name + '.BIN', address=f'0x{addr:08x}', size=size,
                         purpose=purpose, immutable=immutable,
                         expected_sha256=hashlib.sha256(image[addr-BASE:addr-BASE+size]).hexdigest()
                         if immutable else None)
                    for name, addr, size, immutable, purpose in REGIONS],
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def inspect(main, results):
    image = CAMERA.verify_main(main)
    records = []
    for name, addr, size, immutable, purpose in REGIONS:
        path = results / (name + '.BIN')
        row = dict(name=path.name, address=f'0x{addr:08x}', purpose=purpose)
        if not path.is_file():
            row.update(ok=False, error='missing')
        else:
            data = path.read_bytes()
            row.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
            if len(data) != size:
                row.update(ok=False, error=f'expected exactly {size} bytes')
            elif immutable:
                row['ok'] = data == image[addr-BASE:addr-BASE+size]
                row['matches_official_image'] = row['ok']
            else:
                row.update(ok=True, words=[f'0x{w:08x}' for w in struct.unpack(f'<{size//4}I', data)])
        records.append(row)
    return dict(camera=CAMERA.name, complete=all(r['ok'] for r in records), regions=records,
                scope='Snapshots only; unchanged IMU zeros do not establish free memory or lifetime. '
                      'Use an empty FPLPROBE directory for each trial to exclude stale results.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='create a new offline diagnostic card directory')
    b.add_argument('--main', type=Path, required=True, help='inspected official fp L 3.02 MAIN.bin')
    b.add_argument('--out', type=Path, required=True, help='new local output directory, not a mounted card')
    i = sub.add_parser('inspect', help='validate downloaded snapshots against the official image')
    i.add_argument('--main', type=Path, required=True)
    i.add_argument('--results', type=Path, required=True, help='local copy of FPLPROBE')
    args = ap.parse_args()
    try:
        report = build(args.main, args.out) if args.command == 'build' else inspect(args.main, args.results)
    except (OSError, ValueError) as exc:
        ap.exit(1, f'{exc}\n')
    print(json.dumps(report, indent=2))
    if args.command == 'inspect' and not report['complete']:
        ap.exit(1)


if __name__ == '__main__':
    main()
