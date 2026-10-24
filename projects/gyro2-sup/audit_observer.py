#!/usr/bin/env python3
"""Bounded official-image evidence for the shared Gyro2 observer seam.

No firmware bytes are emitted: report hashes, addresses and disassembly only.
This pins exact images; correspondence is not runtime lifetime/capacity proof.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BASE = 0xC0000000
HASHES = (
    'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622',
    'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9',
)
# Complete small routines, or explicitly named bounded call-site windows.
WINDOWS = (
    ('subject', 0xC00577F0, 0xC0054E28, 0x40),
    ('attach', 0xC00D2958, 0xC00CF208, 0xB0),
    ('add_tag', 0xC00BA378, 0xC00B6B20, 0x68),
    ('rate_including_jump_table', 0xC00C9BD0, 0xC00C6378, 0x120),
    ('notify', 0xC00559F0, 0xC0053028, 0xC8),
    ('dispatch', 0xC0055FE0, 0xC0053618, 0x68),
    ('take_build_window', 0xC038A138, 0xC038A350, 0x38),
    ('datapool_factory_prefix', 0xC00558F8, 0xC0052F30, 0x58),
    ('build_dispatch_window', 0xC00559B0, 0xC0052FE8, 0x1C),
    ('serialized_window', 0xC0378EB0, 0xC03790C8, 0xC4),
    ('frame_notify_window', 0xC038C6D8, 0xC038C8F0, 0x2C),
    ('template_owner', 0xC038A0F8, 0xC038A310, 0x40),
    ('template_pointer', 0xC038A318, 0xC038A530, 0x10),
    ('event_get', 0xC0055DB0, 0xC00533E8, 0x14),
    ('event_set', 0xC0055DF8, 0xC0053430, 0x28),
    ('builder_get', 0xC0056748, 0xC0053D80, 0x20),
    ('sensor_mode', 0xC032C720, 0xC032C7C0, 0x14),
    ('timing_row', 0xC0320FC8, 0xC03250E0, 0x60),
    ('geometry_row', 0xC0321028, 0xC0325140, 0x60),
    ('correction_owner', 0xC00467B0, 0xC0043ED8, 0x50),
    ('correction_population_call_window', 0xC0049660, 0xC0046D00, 0x24),
)
EDGES = (
    (0xC038A144, 0xC038A35C, 0xC00577F0, 0xC0054E28),
    (0xC038A154, 0xC038A36C, 0xC00558F8, 0xC0052F30),
    (0xC00559C8, 0xC0053000, 0xC00559F0, 0xC0053028),
    (0xC0378F58, 0xC0379170, 0xC00577F0, 0xC0054E28),
    (0xC0378F70, 0xC0379188, 0xC00559F0, 0xC0053028),
    (0xC038C700, 0xC038C918, 0xC00559F0, 0xC0053028),
    (0xC0055A8C, 0xC00530C4, 0xC0055FE0, 0xC0053618),
    (0xC00BA3A0, 0xC00B6B48, 0xC00BFDC0, 0xC00BC568),
    (0xC00BA3B0, 0xC00B6B58, 0xC00BD340, 0xC00B9AE8),
    (0xC00BA3CC, 0xC00B6B74, 0xC00BA290, 0xC00B6A38),
)


def audit(fp, fpl):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    images = [Path(fp).read_bytes(), Path(fpl).read_bytes()]
    for data, expected in zip(images, HASHES):
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('official MAIN fingerprint mismatch')
    rows = []
    for name, a, b, length in WINDOWS:
        row = {'name': name, 'bytes': length}
        for model, data, address in zip(('fp', 'fpl'), images, (a, b)):
            code = data[address-BASE:address-BASE+length]
            row[model] = {'address': hex(address), 'sha256': hashlib.sha256(code).hexdigest(),
                          'instructions': [f'{i.address:08x}: {i.mnemonic} {i.op_str}'
                                           for i in md.disasm(code, address)]}
        rows.append(row)
    for a, b, x, y in EDGES:
        for data, address, target in zip(images, (a, b), (x, y)):
            i = next(md.disasm(data[address-BASE:address-BASE+4], address))
            if (i.mnemonic, i.op_str) != ('bl', '#' + hex(target)):
                raise ValueError('call edge mismatch at ' + hex(address))
    # Both native CinemaDNG DataPool vtables: event getter/setter and builder getter.
    tables = []
    for data, table, targets in zip(images, (0xC0735A04, 0xC07333D4),
                                    ((0xC0056748, 0xC0055DB0, 0xC0055DF8),
                                     (0xC0053D80, 0xC00533E8, 0xC0053430))):
        actual = [struct.unpack_from('<I', data, table-BASE+slot)[0] for slot in (0x2C, 0x40, 0x44)]
        if actual != list(targets):
            raise ValueError('native DataPool vtable mismatch at ' + hex(table))
        tables.append({'address': hex(table), 'slots': dict(zip(('0x2c', '0x40', '0x44'), map(hex, actual)))})
    return {'images': [dict(sha256=h, bytes=len(d)) for h, d in zip(HASHES, images)],
            'windows': rows, 'call_edges': [[hex(v) for v in e] for e in EDGES], 'datapool_vtables': tables}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp-image', type=Path, required=True)
    p.add_argument('--fpl-image', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.fp_image, a.fpl_image), indent=2))
