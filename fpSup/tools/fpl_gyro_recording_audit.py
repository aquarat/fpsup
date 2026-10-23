#!/usr/bin/env python3
"""Offline recording-binding evidence; never imports deployers or opens a device.

Requires Capstone and sibling fpl_gyro_audit.py. Output contains addresses and
operand correspondence, not firmware bytes. No code or card is generated.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint, instructions, normalized

# Bounds are explicit: *_prefix is deliberately not a full-function claim.
BINDINGS = [
    ('record_start_step', 0xC0378A50, 0xC0378C68, 0x7D8),
    ('record_stop_step', 0xC038C3C0, 0xC038C5D8, 0x238),
    ('audio_start', 0xC01FB338, 0xC01F7BB8, 0x1D0),
    ('audio_stop_prefix', 0xC01FB508, 0xC01F7D88, 0x170),
    ('sensor_mode', 0xC032C720, 0xC032C7C0, 0x14),
    ('current_mode_field', 0xC03212F8, 0xC0325410, 0x10),
    ('sensor_instance', 0xC0322E88, 0xC0326E48, 0x18),
    ('sensor_singleton', 0xC03255F8, 0xC0329E08, 0x48),
    ('sensor_ctor', 0xC03255B0, 0xC0329DC0, 0x48),
    ('timing_row', 0xC0320FC8, 0xC03250E0, 0x60),
    ('geometry_row', 0xC0321028, 0xC0325140, 0x60),
    ('geometry_index', 0xC0320B38, 0xC0324C50, 0x68),
    ('timing_index', 0xC0320BA0, 0xC0324CB8, 0x60),
    ('settings_singleton', 0xC0206E98, 0xC0203B70, 0x48),
    ('settings_live_block', 0xC0207088, 0xC0203D60, 0x10),
    ('context_owner', 0xC0021C00, 0xC0021B20, 0x40),
    ('context_get', 0xC0021C40, 0xC0021B60, 0x10),
    ('file_manager_prefix', 0xC0444658, 0xC04408B8, 0x40),
    ('volume_prefix', 0xC0444698, 0xC04408F8, 0x50),
    ('file_ctor', 0xC0365E90, 0xC03660A8, 0x40),
    ('file_dtor_prefix', 0xC0365ED0, 0xC03660E8, 0x60),
    ('file_open', 0xC0365FB0, 0xC03661C8, 0x70),
    ('file_close', 0xC0366020, 0xC0366238, 0x40),
    ('file_write_prefix', 0xC03660E8, 0xC0366300, 0x80),
    ('file_seek_prefix', 0xC03661E0, 0xC03663F8, 0x40),
    ('file_stamp_prefix', 0xC0369310, 0xC0369528, 0x40),
    ('thread_create', 0xC036E108, 0xC036E320, 0x60),
    ('thread_destroy_prefix', 0xC036E168, 0xC036E380, 0x50),
    ('thread_attach', 0xC036E1B8, 0xC036E3D0, 0x40),
    ('thread_join', 0xC036E1F8, 0xC036E410, 0x20),
    ('mailbox_create_prefix', 0xC01F88A4, 0xC01F5124, 0x24),
    ('mailbox_send_prefix', 0xC01F8D48, 0xC01F55C8, 0x24),
    ('mailbox_receive_prefix', 0xC01F8B74, 0xC01F53F4, 0x24),
    ('mailbox_delete_prefix', 0xC0682FA4, 0xC0680C54, 0x24),
]
HOOKS = [
    ('accel', 0xC050D4C8, 0xC0509730, 0xE3A02000),
    ('start', 0xC03790B8, 0xC03792D0, 0xE5DB25CE),
    ('stop', 0xC038C484, 0xC038C69C, 0xE3500000),
]


def compare(fp, fpl, binding):
    name, a, b, size = binding
    left = instructions(fp, a, size, False)
    right = instructions(fpl, b, size, False)
    if [normalized(i, a, size) for i in left] != [normalized(i, b, size) for i in right]:
        raise ValueError(f'normalized mismatch: {name}')
    # Include unchanged branches and immediates too: a shared address is evidence.
    edges = []
    literals = []
    for x, y in zip(left, right):
        row = dict(offset=hex(x.address-a), fp=x.op_str, fpl=y.op_str)
        if x.mnemonic.startswith('b') and '#' in x.op_str:
            edges.append(dict(mnemonic=x.mnemonic, **row))
        if x.mnemonic in ('movw', 'movt'):
            literals.append(dict(mnemonic=x.mnemonic, **row))
    return dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                normalized_match=True, direct_edges=edges, materialized_immediates=literals)


def audit(fp, fpl):
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    rows = [compare(fp, fpl, item) for item in BINDINGS]
    for name, a, b, word in HOOKS:
        for data, address in ((fp, a), (fpl, b)):
            if struct.unpack_from('<I', data, address-BASE)[0] != word:
                raise ValueError(f'wrong stock hook word: {name}')
    return dict(hardware_tested=False, bindings=rows,
                hashes={k: hashlib.sha256(v).hexdigest() for k, v in [('fp', fp), ('fpl', fpl)]},
                journal_candidates=[dict(name=n, fp=hex(a), fpl=hex(b),
                                         word=hex(w), little_endian=struct.pack('<I', w).hex())
                                    for n, a, b, w in HOOKS])


def self_test(fp, fpl):
    count = 0
    for kind, data in [('fp', fp), ('fpl', fpl)]:
        for at in (0, 0x3792D0, len(data)-1, None):
            changed = bytearray(data)
            if at is None:
                changed.pop()
            else:
                changed[at] ^= 1
            try:
                fingerprint(changed, kind)
            except ValueError:
                count += 1
            else:
                raise AssertionError('fingerprint mutation accepted')
    # Bypass the fingerprint deliberately: prove that structural comparison
    # itself notices a changed state offset and a changed internal branch.
    for at in (0x3792D0, 0x38C67C):
        changed = bytearray(fpl)
        changed[at] ^= 4
        binding = BINDINGS[0 if at == 0x3792D0 else 1]
        try:
            compare(fp, changed, binding)
        except ValueError:
            count += 1
        else:
            raise AssertionError('structural mutation accepted')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fp', required=True, type=Path)
    parser.add_argument('--fpl', required=True, type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    result = audit(fp, fpl)
    result['negative_cases'] = self_test(fp, fpl) if args.self_test else 0
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
