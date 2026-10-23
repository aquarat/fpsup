#!/usr/bin/env python3
"""Offline Base metadata correspondence, not a port or calibration certificate.

Only reads the two official MAINs. Requires Capstone and fpl_gyro_audit.py.
JSON includes all instructions in explicitly bounded evidence windows.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

from fpl_gyro_audit import BASE, fingerprint, instructions, normalized

# Bounds ending in _window/_prefix do not claim a complete function.
BINDINGS = [
    ('guard_acquire', 0xC0013090, 0xC0013090, 0x154),
    ('guard_release', 0xC00131E4, 0xC00131E4, 0x98),
    ('settings_ctor', 0xC0206D98, 0xC0203A70, 0xC0),
    ('settings_singleton', 0xC0206E98, 0xC0203B70, 0x48),
    ('settings_block', 0xC0207088, 0xC0203D60, 0x10),
    ('context_owner', 0xC0021C00, 0xC0021B20, 0x40),
    ('context_get', 0xC0021C40, 0xC0021B60, 0x10),
    ('sensor_mode', 0xC032C720, 0xC032C7C0, 0x14),
    ('timing_row', 0xC0320FC8, 0xC03250E0, 0x60),
    ('geometry_row', 0xC0321028, 0xC0325140, 0x60),
    ('lens_cache_ctor', 0xC03341A0, 0xC03343B8, 0x28),
    ('lens_cache', 0xC03341C8, 0xC03343E0, 0x40),
    ('lens_refresh', 0xC0334208, 0xC0334420, 0x1F8),
    ('lens_name_focal_producer_prefix', 0xC03344B0, 0xC03346C8, 0xC0),
    ('focus_wrappers_window', 0xC035FD48, 0xC035FF60, 0xE0),
    ('focus_owner_ctor', 0xC03600E8, 0xC0360300, 0x40),
    ('focus_owner', 0xC0360128, 0xC0360340, 0x38),
    ('focus_position_dispatch', 0xC0360160, 0xC0360378, 0x28),
    ('focus_distance_dispatch', 0xC03602F8, 0xC0360510, 0x48),
    ('geometry_query', 0xC0437140, 0xC0437358, 0xB0),
    ('geometry_context_prefix', 0xC0436B80, 0xC0436D98, 0x1E0),
    ('geometry_allocate', 0xC0438B60, 0xC0438D78, 0x48),
    ('geometry_construct', 0xC0438A78, 0xC0438C90, 0xE8),
    ('geometry_move', 0xC04386B0, 0xC04388C8, 0x38),
    ('geometry_free', 0xC022EDB0, 0xC022C028, 0x60),
    ('geometry_free_local', 0xC0438828, 0xC0438A40, 0x60),
    ('geometry_free_caller_window', 0xC0437530, 0xC0437748, 0x80),
    ('correction_owner', 0xC00467B0, 0xC0043ED8, 0x50),
    ('correction_ctor_update_window', 0xC0049590, 0xC0046C30, 0x1E8),
    ('correction_populate', 0xC0053010, 0xC0050648, 0x260),
    ('four_double_store', 0xC0047298, 0xC0044938, 0x30),
]

# Explicit edges disambiguate short wrappers and generic destructors.
# (window, instruction offset, fp destination, fp L destination)
EDGES = [
    ('settings_ctor', 0x30, 0xC0021C00, 0xC0021B20),
    ('settings_ctor', 0x34, 0xC0021C40, 0xC0021B60),
    ('lens_cache', 0x28, 0xC03341A0, 0xC03343B8),
    ('lens_refresh', 0xBC, 0xC03344B0, 0xC03346C8),
    ('focus_wrappers_window', 4, 0xC0360128, 0xC0360340),
    ('focus_wrappers_window', 8, 0xC0360160, 0xC0360378),
    ('focus_wrappers_window', 0xC8, 0xC0360128, 0xC0360340),
    ('focus_wrappers_window', 0xD0, 0xC03602F8, 0xC0360510),
    ('focus_owner', 0x20, 0xC03600E8, 0xC0360300),
    ('geometry_query', 0x38, 0xC0436B80, 0xC0436D98),
    ('geometry_query', 0x7C, 0xC0438B60, 0xC0438D78),
    ('geometry_query', 0x88, 0xC04386B0, 0xC04388C8),
    ('geometry_query', 0x94, 0xC0438828, 0xC0438A40),
    ('geometry_allocate', 0x2C, 0xC0438A78, 0xC0438C90),
    ('geometry_free_caller_window', 0x6C, 0xC022EDB0, 0xC022C028),
    ('correction_owner', 0x28, 0xC0049590, 0xC0046C30),
    ('correction_ctor_update_window', 0xE0, 0xC0053010, 0xC0050648),
    ('correction_populate', 0x110, 0xC0047298, 0xC0044938),
]
LITERALS = [
    ('settings_singleton', 4, 8, 0xC31F865C, 0xC31F6A7C),
    ('lens_cache', 4, 8, 0xC3464980, 0xC3465794),
    ('lens_cache', 12, 16, 0xC34763F4, 0xC3477208),
    ('focus_owner', 4, 8, 0xC347FA6C, 0xC3480880),
    ('correction_owner', 4, 8, 0xC307BC38, 0xC307A81C),
]


def check(ok, message):
    if not ok:
        raise ValueError(message)


def compare(fp, fpl, row):
    name, a, b, size = row
    x, y = instructions(fp, a, size, False), instructions(fpl, b, size, False)
    check([normalized(i, a, size) for i in x] ==
          [normalized(i, b, size) for i in y], 'structure: '+name)
    return dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                instructions=[dict(offset=hex(i.address-a), mnemonic=i.mnemonic,
                                   fp=i.op_str, fpl=j.op_str) for i, j in zip(x, y)])


def structural_checks(fp, fpl):
    rows = [compare(fp, fpl, row) for row in BINDINGS]
    names = {r[0]: r for r in BINDINGS}
    for name, offset, a, b in EDGES:
        for data, start, target in ((fp, names[name][1], a), (fpl, names[name][2], b)):
            ins = instructions(data, start+offset, 4, False)[0]
            check(ins.mnemonic == 'bl' and ins.op_str == '#'+hex(target), 'edge: '+name)
    for name, lo, hi, a, b in LITERALS:
        for data, start, expected in ((fp, names[name][1], a), (fpl, names[name][2], b)):
            ins = [instructions(data, start+o, 4, False)[0] for o in (lo, hi)]
            check([i.mnemonic for i in ins] == ['movw', 'movt'], 'literal opcode')
            check(ins[0].op_str.split(',')[0] == ins[1].op_str.split(',')[0], 'literal register')
            value = sum(int(i.op_str.split('#')[1], 0) << (16*n) for n, i in enumerate(ins))
            check(value == expected, 'literal: '+name)
    # MOVW offsets are normalized as relocations by the shared comparator.
    # Pin the important non-address MOVWs explicitly too.
    for name, offset, operand in [
        ('correction_ctor_update_window', 0xD0, 'r2, #0x11b8'),
        ('lens_cache_ctor', 4, 'r1, #0x469c'),
    ]:
        for data, start in ((fp, names[name][1]), (fpl, names[name][2])):
            ins = instructions(data, start+offset, 4, False)[0]
            check(ins.mnemonic == 'movw' and ins.op_str == operand, 'field constant: '+name)
    # Static-address return, not ldr r0,[r4]; block getter adds 0x40 once.
    for name, offset, mnemonic, operand in [
        ('settings_singleton', 0x40, 'mov', 'r0, r4'),
        ('settings_singleton', 0xC, 'movw', 'r0, #0x634'),
        ('settings_singleton', 0x10, 'add', 'r0, r0, r4'),
        ('settings_block', 4, 'add', 'r1, ip, #0x40'),
        ('settings_block', 8, 'mov', 'r0, r1'),
        ('lens_cache', 0x38, 'mov', 'r0, r4'),
        ('guard_acquire', 0x38, 'cmp', 'r0, #1'),
        ('guard_release', 0x2C, 'moveq', 'r0, #1'),
        ('guard_release', 0x30, 'streq', 'r0, [r7]'),
        ('guard_release', 0x4C, 'mov', 'r0, #1'),
        ('guard_release', 0x50, 'str', 'r0, [r7]'),
    ]:
        for data, start in ((fp, names[name][1]), (fpl, names[name][2])):
            ins = instructions(data, start+offset, 4, False)[0]
            check((ins.mnemonic, ins.op_str) == (mnemonic, operand), 'accessor/guard: '+name)
    return rows


def source_checks(json_source, ring_source, task_source):
    """Tie Base's direct singleton-relative reads to the audited block getter."""
    def code(text):
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
        text = re.sub(r'@[^\n]*', '', text)
        return ' '.join(text.split())

    j, r, t = map(code, (json_source, ring_source, task_source))
    for pattern in (r'\.equ F_CAMSETTING, 0xC0206E98\b',
                    r'\.equ SETTING_DIMS, 0x40\b',
                    r'\.equ SETTING_FORMAT, SETTING_DIMS \+ 0x0C\b'):
        check(re.search(pattern, r) is not None, 'Base source constant: '+pattern)
    direct_call = ('movw ip, #:lower16:F_CAMSETTING '
                   'movt ip, #:upper16:F_CAMSETTING blx ip cmp r0, #0 beq ')
    check(direct_call+'9f add r0, r0, #SETTING_DIMS ldr r1, [r0, #4] ldr r0, [r0]' in j,
          'Base dimension source must add singleton-relative offset exactly once')
    check(direct_call+'2f ldr r0, [r0, #SETTING_FORMAT]' in t,
          'Base format source must use singleton-relative offset')
    singleton = 0xC31F6A7C
    block = singleton+0x40
    return dict(singleton=hex(singleton), live_block=hex(block),
                fields=[dict(name=name, singleton_offset=hex(off),
                             live_block_offset=hex(off-0x40),
                             address=hex(singleton+off), units='unknown')
                        for name, off in [('width_raw', 0x40), ('height_raw', 0x44),
                                          ('format_raw', 0x4C)]],
                source_sha256={name: hashlib.sha256(text.encode()).hexdigest()
                               for name, text in [('gyro/gcsv_json.S', json_source),
                                                  ('gyro/ring_task.inc.S', ring_source),
                                                  ('gyro/gcsv_task.S', task_source)]})


def source_texts():
    root = Path(__file__).resolve().parent.parent / 'gyro'
    return tuple((root/name).read_text() for name in ('gcsv_json.S', 'ring_task.inc.S', 'gcsv_task.S'))


def audit(fp, fpl):
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    return dict(hardware_tested=False, calibration_validated=False,
                images={k: dict(bytes=len(v), sha256=hashlib.sha256(v).hexdigest())
                        for k, v in [('fp', fp), ('fpl', fpl)]},
                bindings=structural_checks(fp, fpl),
                source_relative_cross_check=source_checks(*source_texts()))


def self_test(fp, fpl):
    count = 0
    for kind, data in [('fp', fp), ('fpl', fpl)]:
        for at in (0, 0x3343E0, len(data)-1, None):
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
    # Deliberately bypass fingerprinting: field, local branch, external call,
    # singleton literal and normalized MOVW field each have independent checks.
    for address in (0xC0334770, 0xC0334400, 0xC035FF68, 0xC03343E4, 0xC0046D00):
        changed = bytearray(fpl)
        changed[address-BASE] ^= 4
        try:
            structural_checks(fp, changed)
        except ValueError:
            count += 1
        else:
            raise AssertionError('structural mutation accepted: '+hex(address))
    j, r, t = source_texts()
    for changed in ((j.replace('add     r0, r0, #SETTING_DIMS', 'add     r0, r0, #0x80'), r, t),
                    (j, r.replace('SETTING_DIMS,   0x40', 'SETTING_DIMS,   0x80'), t),
                    (j, r, t.replace('[r0, #SETTING_FORMAT]', '[r0, #0x0C]'))):
        check(changed != (j, r, t), 'source negative fixture did not mutate')
        try:
            source_checks(*changed)
        except ValueError:
            count += 1
        else:
            raise AssertionError('source-relative mutation accepted')
    changed = bytearray(fpl)
    # Replace mov r0,r4 with ldr r0,[r4]: extra pointer dereference must fail.
    changed[0x203BB0:0x203BB4] = bytes.fromhex('000094e5')
    try:
        structural_checks(fp, changed)
    except ValueError:
        count += 1
    else:
        raise AssertionError('singleton pointer-indirection mutation accepted')
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
