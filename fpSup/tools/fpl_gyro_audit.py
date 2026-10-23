#!/usr/bin/env python3
"""Offline Base IMU bindings. Reads two private MAINs; no device interface.

Requires capstone. --self-test checks fingerprint refusal on mutated inputs.
Optional disassembly output is exclusive-create and should stay outside git.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

BASE = 0xC0000000
IMAGES = {
    'fp': (49245696, 'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622'),
    'fpl': (49310208, 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'),
}
# (name, fp address, fp L address, byte length, Thumb). Bounds exclude literals.
BINDINGS = [
    ('model_ctor', 0xC0043410, 0xC0041020, 0x178, False),
    ('accel_ctor', 0xC050D028, 0xC0509290, 0xB0, False),
    ('accel_cached_get', 0xC050D1E8, 0xC0509450, 0x64, False),
    ('accel_sample_prefix', 0xC050D250, 0xC05094B8, 0x100, False),
    # Nine-byte switch table and three-byte padding at D350 are data.
    ('accel_sample_remap_publish_return', 0xC050D35C, 0xC05095C4, 0x190, False),
    ('axis_value_set', 0xC050C5D0, 0xC0508838, 0x18, False),
    ('body_motion_loop', 0xC00D0738, 0xC00CCFE8, 0xC8, False),
    ('processed_gyro_get', 0xC01EC6F8, 0xC01E8F78, 0x7E, True),
    ('raw_ring_get', 0xC01EC8C0, 0xC01E9140, 0x3A, True),
    ('imu_pointer_callback', 0xC01EDE98, 0xC01EA718, 0x68, True),
    ('imu_load_once', 0xC01EDF18, 0xC01EA798, 0x9A, True),
    ('thread_create', 0xC036E108, 0xC036E320, 0x60, False),
    ('thread_attach', 0xC036E1B8, 0xC036E3D0, 0x40, False),
    ('thread_join', 0xC036E1F8, 0xC036E410, 0x20, False),
]


def fingerprint(data, kind):
    size, digest = IMAGES[kind]
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(f'not the audited official {kind} MAIN')


def instructions(data, address, size, thumb):
    dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    result = list(dis.disasm(data[address-BASE:address-BASE+size], address))
    if sum(i.size for i in result) != size:
        raise ValueError(f'incomplete disassembly at {address:08x}')
    return result


def normalized(ins, start, size):
    """Preserve registers, memory offsets, constants and internal branch graph.

    Only MOVW/MOVT immediates and external direct branch destinations are
    masked. Report the masked operands separately: equality is not proof that
    their targets mean the same thing. No register renaming or delta guessing.
    """
    op = ins.op_str
    if ins.mnemonic in ('movw', 'movt'):
        op = re.sub(r'#(?:0x[0-9a-f]+|[0-9]+)', '#RELOC', op)
    elif (ins.mnemonic.startswith('b') or ins.mnemonic in ('cbz', 'cbnz')):
        m = re.search(r'#0x([0-9a-f]+)$', op)
        if m:
            dest = int(m[1], 16)
            target = f'LOCAL+{dest-start:x}' if start <= dest < start+size else 'EXTERNAL'
            op = op[:m.start()] + target
    return (ins.size, ins.mnemonic, op)


def audit(fp, fpl, listing=None):
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    records = []
    for name, a, b, size, thumb in BINDINGS:
        left = instructions(fp, a, size, thumb)
        right = instructions(fpl, b, size, thumb)
        assert [normalized(i, a, size) for i in left] == [normalized(i, b, size) for i in right], name
        differences = [{'offset': hex(x.address-a), 'fp': x.op_str, 'fpl': y.op_str}
                       for x, y in zip(left, right) if x.op_str != y.op_str]
        records.append(dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                            isa='Thumb' if thumb else 'ARM', normalized_match=True,
                            operand_differences=differences))
        if listing:
            for label, seq in [('fp', left), ('fpl', right)]:
                listing.write(f'\n{name} {label}\n')
                for i in seq:
                    listing.write(f'{i.address:08x} {i.mnemonic:12} {i.op_str}\n')
    assert fp[0x50D350:0x50D35C] == fpl[0x5095B8:0x5095C4]
    assert struct.unpack_from('<I', fp, 0x50D4C8)[0] == 0xE3A02000
    assert struct.unpack_from('<I', fpl, 0x509730)[0] == 0xE3A02000
    embedded = fp[0x72CA40:0x732C40]
    assert len(embedded) == 0x6200 and embedded == fpl[0x72A4C0:0x7306C0]
    # Embedded Cortex-M image: PC-relative literal loads, not host address deltas.
    literals = {0x5D8: 0x6004, 0x5DC: 0x644C, 0x5E0: 0x7710,
                0x9F4: 0x644C, 0x9F8: 0x6004}
    for offset, value in literals.items():
        assert struct.unpack_from('<I', embedded, offset)[0] == value
    if listing:
        dis = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        for start, end in [(0x4B4, 0x516), (0x92C, 0x9DE)]:
            listing.write('\nIdentical embedded IMU code, LOCAL addresses\n')
            for i in dis.disasm(embedded[start:end], start):
                listing.write(f'{i.address:08x} {i.mnemonic:12} {i.op_str}\n')
    return dict(hardware_tested=False, bindings=records,
                main_sha256={k: hashlib.sha256(v).hexdigest() for k,v in [('fp',fp),('fpl',fpl)]},
                embedded_sha256=hashlib.sha256(embedded).hexdigest(),
                embedded_bytes=len(embedded), embedded_literals={hex(k):hex(v) for k,v in literals.items()})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp', required=True, type=Path)
    p.add_argument('--fpl', required=True, type=Path)
    p.add_argument('--disassembly', type=Path)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    # Validate before creating output.
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    if args.self_test:
        for kind, data in [('fp', fp), ('fpl', fpl)]:
            for at in (0, 0x509730, len(data)-1):
                changed = bytearray(data)
                changed[at] ^= 1
                try:
                    fingerprint(changed, kind)
                except ValueError:
                    pass
                else:
                    raise AssertionError('altered image accepted')
            try:
                fingerprint(data[:-1], kind)
            except ValueError:
                pass
            else:
                raise AssertionError('truncated image accepted')
    if args.disassembly:
        with args.disassembly.open('x') as out:
            result = audit(fp, fpl, out)
    else:
        result = audit(fp, fpl)
    result['fingerprint_negative_cases'] = 8 if args.self_test else 0
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
