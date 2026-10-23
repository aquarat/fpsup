#!/usr/bin/env python3
"""Offline Base take_path audit. Requires Capstone; --self-test also Unicorn.

Reads official MAIN files only. No device, filesystem firmware call, deployment,
or card-writing interfaces. Emulation writes exclusively to synthetic RAM.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint, instructions, normalized

BINDINGS = [
    ('manager_selector', 0xC03092F8, 0xC030D390, 0x298),
    ('cinema_ctor', 0xC030ADD8, 0xC030EE70, 0xB0),
    ('sync_media', 0xC030AE88, 0xC030EF20, 0x1E0),
    ('next_path_object', 0xC030B068, 0xC030F100, 0xF0),
    ('clear_identity', 0xC030B158, 0xC030F1F0, 0x28),
    ('clear_numbers', 0xC030B180, 0xC030F218, 0x28),
    ('advance_take', 0xC030B1A8, 0xC030F240, 0x140),
    ('save_take', 0xC030B4C8, 0xC030F560, 0xC0),
    ('load_take', 0xC030B588, 0xC030F620, 0x150),
    ('reconcile_identity', 0xC030B6D8, 0xC030F770, 0x2C8),
    ('scan_media_names', 0xC030B9A0, 0xC030FA38, 0xE0),
    ('peek_number_tuple', 0xC030BA80, 0xC030FB18, 0xA8),
    ('next_number_tuple', 0xC030BB28, 0xC030FBC0, 0x78),
    ('parse_reel', 0xC030BBA0, 0xC030FC38, 0x50),
    ('parse_take', 0xC030BBF0, 0xC030FC88, 0x50),
    ('number_upper_bounds', 0xC030BC40, 0xC030FCD8, 0x30),
    ('format_path', 0xC030ABE0, 0xC030EC78, 0xC0),
    ('path_extension', 0xC030ACA0, 0xC030ED38, 0xE8),
    ('settings_changed', 0xC030BCE8, 0xC030FD80, 0x148),
    ('manager_gates', 0xC030BEF8, 0xC030FF90, 0x30),
    ('context_owner', 0xC0021C00, 0xC0021B20, 0x40),
    ('context_pointer', 0xC0021C40, 0xC0021B60, 0x10),
    ('start_path_to_hook', 0xC037900C, 0xC0379224, 0xB0),
]

# Literal pairs are extracted from corresponding instructions, not a data delta.
# Each tuple gives the MOVW and MOVT offsets relative to the named function.
LITERALS = [
    ('manager_selector', 8, 16, 0xC3438398, 0xC34392D0),
    ('cinema_ctor', 0x1C, 0x20, 0xC0B55D8C, 0xC0B8D874),
    ('context_owner', 4, 8, 0xC30751D4, 0xC3075194),
    ('save_take', 0x40, 0x44, 0xC3074954, 0xC3074914),
    ('next_path_object', 0x88, 0x8C, 0xC0B55E58, 0xC0B8D940),
]
STRINGS = [
    ('manager_selector', 0x14, 0x18, b'SD'),
    ('manager_selector', 0x38, 0x3C, b'SSD'),
    ('format_path', 0x50, 0x58,
     b'\\CINEMA\\%c%03d_%03d\\%c%03d_%03d_%04d%02d%02d.XXX'),
    ('format_path', 0x8C, 0x94, b'\\CINEMA\\%c%03d_%03d_%04d%02d%02d.XXX'),
    ('path_extension', 0x1C, 0x20, b'MOV'),
    ('path_extension', 0x58, 0x5C, b'WAV'),
    ('path_extension', 0x90, 0x94, b'DNG'),
    ('path_extension', 0xB0, 0xB4, b'_%06d.%s'),
    ('advance_take', 0x20, 0x24, b'AutoRstFlg'),
    ('save_take', 0x90, 0x94, b'SaveTakeNo'),
]


def check(ok, message):
    if not ok:
        raise ValueError(message)


def materialized(data, start, low, high):
    seq = [instructions(data, start+x, 4, False)[0] for x in (low, high)]
    check([i.mnemonic for i in seq] == ['movw', 'movt'], 'literal instruction')
    check(seq[0].op_str.split(',')[0] == seq[1].op_str.split(',')[0], 'literal register')
    return sum(int(i.op_str.split('#')[1], 0) << (16*n) for n, i in enumerate(seq))


def compare(fp, fpl, row):
    name, a, b, size = row
    x, y = instructions(fp, a, size, False), instructions(fpl, b, size, False)
    check([normalized(i, a, size) for i in x] == [normalized(i, b, size) for i in y], name)
    return dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                correspondence=[dict(offset=hex(i.address-a), instruction=i.mnemonic,
                                     fp=i.op_str, fpl=j.op_str)
                                for i, j in zip(x, y)
                                if i.mnemonic in ('movw', 'movt') or
                                (i.mnemonic.startswith('b') and '#' in i.op_str)])


def static_checks(fp, fpl):
    rows = [compare(fp, fpl, row) for row in BINDINGS]
    names = {r[0]: r for r in BINDINGS}
    strings = []
    for name, lo, hi, a, b in LITERALS:
        for data, start, expected in ((fp, names[name][1], a), (fpl, names[name][2], b)):
            check(materialized(data, start, lo, hi) == expected, 'materialized '+name)
    for name, lo, hi, text in STRINGS:
        addresses = []
        for data, start in ((fp, names[name][1]), (fpl, names[name][2])):
            address = materialized(data, start, lo, hi)
            check(data[address-BASE:address-BASE+len(text)+1] == text+b'\0', 'string '+name)
            addresses.append(hex(address))
        strings.append(dict(text=text.decode(), fp=addresses[0], fpl=addresses[1]))
    # Constructor-installed table, indexed exactly as firmware virtual calls do.
    slots = {0x14: 'sync_media', 0x18: 'next_path_object', 0x24: 'advance_take'}
    for slot, name in slots.items():
        for data, table, target in ((fp, 0xC0B55D8C, names[name][1]),
                                    (fpl, 0xC0B8D874, names[name][2])):
            check(struct.unpack_from('<I', data, table-BASE+slot)[0] == target, 'vtable '+name)
    for data, table, target in ((fp, 0xC0B55E58, names['path_extension'][1]),
                                (fpl, 0xC0B8D940, names['path_extension'][2])):
        check(struct.unpack_from('<I', data, table-BASE+0xC)[0] == target, 'path-object extension slot')
    return dict(bindings=rows, strings=strings,
                cinema_vtable_slots={hex(k): v for k, v in slots.items()},
                path_object_vtable_slots={'0xc': 'path_extension'})


def execution_tests(data, kind):
    """Execute only stock selector/peek/next/validator; all services are stubs.

    Guards report already initialized, so selector never constructs anything.
    Calls outside these bounds or explicitly stubbed services fail the oracle.
    """
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    idx = 1 if kind == 'fp' else 2
    selected = {r[0]: (r[idx], r[3]) for r in BINDINGS}
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, 0x4000000)
    u.mem_write(BASE, bytes(data))
    ram, end = 0x10000000, 0x1000F800
    u.mem_map(ram, 0x10000)
    manager, context, output, following = ram+0x1000, ram+0x3000, ram+0x4000, ram+0x5000
    bounds = []
    owner, getter = selected['context_owner'][0], selected['context_pointer'][0]
    strcmp = 0xC01F575C if kind == 'fp' else 0xC01F1FDC

    def on_code(uc, address, size, _):
        if address in (owner, getter):
            uc.reg_write(UC_ARM_REG_R0, context)
        elif address == 0xC0013090:
            uc.reg_write(UC_ARM_REG_R0, 0)  # initialized: never run constructor
        elif address == strcmp:
            a, b, n = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
            uc.reg_write(UC_ARM_REG_R0, int(uc.mem_read(a, n) != uc.mem_read(b, n)))
        else:
            check(any(a <= address < b for a, b in bounds), f'unexpected execution {address:08x}')
            return
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def on_write(uc, access, address, size, value, _):
        check(ram <= address and address+size <= ram+0x10000, 'write outside synthetic RAM')

    u.hook_add(UC_HOOK_CODE, on_code)
    u.hook_add(UC_HOOK_MEM_WRITE, on_write)

    def run(name, *args):
        start, size = selected[name]
        bounds[:] = [(start, start+size)]
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args):
            u.reg_write(reg, value)
        u.reg_write(UC_ARM_REG_SP, ram+0xF000)
        u.reg_write(UC_ARM_REG_LR, end)
        u.emu_start(start, end, count=10000)
        check(u.reg_read(UC_ARM_REG_PC) == end, 'execution did not return')
        return u.reg_read(UC_ARM_REG_R0)

    count = 0
    for volume, offset in ((b'SSD\0', 0), (b'SD\0', 0x68)):
        u.mem_write(output, struct.pack('<I', 1))
        u.mem_write(following, volume)
        base = 0xC3438398 if kind == 'fp' else 0xC34392D0
        check(run('manager_selector', output, following) == base+offset, 'selector result')
        count += 1
    for flag, current, saved, reel in ((0, 4, 9, 1), (1, 4, 9, 1), (2, 4, 9, 1),
                                      (0, 9, 4, 1), (0, 9, 9, 1), (0, 0, 0, 1),
                                      (0, 998, 0, 999), (0, 999, 0, 1),
                                      (0, 1, 0, 1000), (0, -1, 4, 1)):
        blob = bytearray(0x68)
        struct.pack_into('<7I', blob, 8, ord('A'), reel, current & 0xFFFFFFFF, 0, 0, 0, 0)
        struct.pack_into('<I', blob, 0x2C, saved)
        u.mem_write(manager, bytes(blob))
        u.mem_write(context+0x5D5, bytes([flag]))
        run('peek_number_tuple', output, manager)
        expected = current if flag else max(current, saved)  # signed firmware comparison
        check(struct.unpack('<I', u.mem_read(output+8, 4))[0] == expected & 0xFFFFFFFF, 'peek')
        run('next_number_tuple', following, manager, output)
        check(struct.unpack('<I', u.mem_read(following+8, 4))[0] == (expected+1) & 0xFFFFFFFF, 'next')
        check(run('number_upper_bounds', following) == int(reel < 1000 and expected+1 < 1000), 'bounds')
        check(u.mem_read(manager, len(blob)) == bytes(blob), 'peek changed manager')
        count += 1
    return count


def negatives(fp, fpl):
    count = 0
    for kind, data in [('fp', fp), ('fpl', fpl)]:
        for at in (0, 0x30F258, len(data)-1, None):
            mutated = bytearray(data)
            if at is None:
                mutated.pop()
            else:
                mutated[at] ^= 1
            try:
                fingerprint(mutated, kind)
            except ValueError:
                count += 1
            else:
                raise AssertionError('fingerprint negative accepted')
    # Bypass fingerprinting: wrong flag field, signed condition, manager literal,
    # and format string must fail the corresponding independent static checks.
    for at in (0x30F258, 0x30F2A7, 0x30D398, 0xB8D6C2):
        mutated = bytearray(fpl)
        mutated[at] ^= 1
        try:
            static_checks(fp, mutated)
        except ValueError:
            count += 1
        else:
            raise AssertionError('static negative accepted')
    # A changed increment is rejected by actual execution, independent of hashes
    # and normalization. Change ADD #1 to ADD #2 in next_number_tuple.
    for at, value in ((0x30FBF8, 2), (0x30FB8F, 0x2A)):
        mutated = bytearray(fpl)
        mutated[at] = value  # second case: BGE -> BHS (signed -> unsigned)
        try:
            execution_tests(mutated, 'fpl')
        except ValueError:
            count += 1
        else:
            raise AssertionError('execution negative accepted')
    return count


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp', required=True, type=Path)
    p.add_argument('--fpl', required=True, type=Path)
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    result = static_checks(fp, fpl)
    result['hashes'] = {k: hashlib.sha256(v).hexdigest() for k, v in [('fp', fp), ('fpl', fpl)]}
    result['hardware_tested'] = False
    result['execution_cases'] = sum(execution_tests(v, k) for k, v in [('fp', fp), ('fpl', fpl)]) if args.self_test else 0
    result['negative_cases'] = negatives(fp, fpl) if args.self_test else 0
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
