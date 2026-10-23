#!/usr/bin/env python3
"""Offline MOV callback/result producer audit; no device or deployment access."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint, instructions, normalized

BINDINGS = [
    ('owner_callback_install', 0xC0388814, 0xC0388A2C, 0x2C, False),
    ('register_callback', 0xC06B0A28, 0xC06AE568, 0x28, False),
    ('callback_store', 0xC06B1128, 0xC06AEC68, 0x20, False),
    ('engine_callback_argument', 0xC06B0DAC, 0xC06AE8EC, 0x18, False),
    ('engine_notification', 0xC06B1178, 0xC06AECB8, 0xD0, False),
    ('convert_prefix', 0xC06B14F8, 0xC06AF038, 0x20, False),
    ('convert_cases', 0xC06B1524, 0xC06AF064, 0x64, False),
    ('recorder_callback', 0xC03899A0, 0xC0389BB8, 0x78, False),
    ('enqueue', 0xC03A9580, 0xC03A9798, 0x110, False),
    ('token_store', 0xC03A97F0, 0xC03A9A08, 0x28, False),
    ('notification', 0xC0396E80, 0xC0397098, 0x160, False),
    ('engine_start_body', 0xC07101C0, 0xC070DD10, 0x1B8, True),
    ('engine_start_success_suffix', 0xC0710350, 0xC070DEA0, 0x14, True),
    ('engine_stop_result_suffix', 0xC0710962, 0xC070E4B2, 0x16, True),
    ('engine_callback_copy', 0xC070F800, 0xC070D350, 0xA, True),
]
CONVERT = [0, 1, 1, 2, 3, 4, 5, 6, 7, 2, 2]


def check(ok, message):
    if not ok:
        raise ValueError(message)


def static(fp, fpl):
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    rows = []
    for name, a, b, size, thumb in BINDINGS:
        left, right = instructions(fp, a, size, thumb), instructions(fpl, b, size, thumb)
        check([normalized(i, a, size) for i in left] ==
              [normalized(i, b, size) for i in right], name)
        rows.append(dict(name=name, fp=hex(a), fpl=hex(b), bytes=size,
                         isa='Thumb' if thumb else 'ARM',
                         changed_operands=[dict(offset=hex(x.address-a), fp=x.op_str, fpl=y.op_str)
                                           for x, y in zip(left, right) if x.op_str != y.op_str]))
    check(fpl[0x6AF058:0x6AF064] == bytes([2, 5, 5, 7, 9, 11, 13, 15, 17, 7, 7, 19]),
          'converter byte table')
    check(fp[0x6B1518:0x6B1524] == fpl[0x6AF058:0x6AF064], 'fp converter table')
    check(struct.unpack_from('<I', fpl, 0xBC2098)[0] == 0xC0389BB8, 'installed callback +C')
    return rows


def run(data, phase='callback', raw=0, present=True, prior_error=0, final_error=0,
        token=42, notification_kind=15, mutation=None):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP,
        UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR)
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, (len(data)+4095)&~4095, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, data)
    if mutation:
        address, value, width = mutation
        u.mem_write(address, value.to_bytes(width, 'little'))
    ram = 0x10000000
    u.mem_map(ram, 0x40000)
    u.mem_map(0xC2F2F000, 0x1000)
    owner, cbstate, config, pool, ptable, allocated, settings, live = [ram+n for n in
        (0x1000, 0x4000, 0x5000, 0x6000, 0x7000, 0x8000, 0x9000, 0xA000)]
    end, pool_count = ram+0x3F000, ram+0x3F004
    regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
    def put(a, v):
        u.mem_write(a, struct.pack('<I', v))
    def get(a):
        return struct.unpack('<I', u.mem_read(a, 4))[0]
    def ret(v=0):
        u.reg_write(UC_ARM_REG_R0, v)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
    put(0xC2F2F838, pool)
    put(pool, ptable)
    put(ptable+0x14, pool_count)
    put(config+0x54, 0xC06AECB8)
    put(settings+8, live)
    events, notifications, calls, visited = [], [], [], []
    stop_at = set()
    stopped = False
    bounds = [(0xC0388A2C, 0xC0388A58), (0xC06AE568, 0xC06AE590),
              (0xC06AEC68, 0xC06AEC88), (0xC06AECB8, 0xC06AED88),
              (0xC06AF038, 0xC06AF058), (0xC06AF064, 0xC06AF0C8),
              (0xC0389BB8, 0xC0389C30), (0xC03A9798, 0xC03A98A8),
              (0xC070DEA0, 0xC070DEB4), (0xC070E4B2, 0xC070E4C8),
              (0xC03A9A08, 0xC03A9A30), (0xC03A99E0, 0xC03A9A08),
              (0xC0397098, 0xC03971F8)]
    noops = {0xC0019DC0, 0xC001A048, 0xC001CCE0, 0xC001CD18,
             0xC0016B9C, 0xC00CA6F0, 0xC00CA9D0, 0xC03A0968, 0xC03971F8}
    def code(uc, address, size, _):
        nonlocal stopped
        visited.append(address)
        if address == end or address in stop_at or address == 0xC0011100:
            stopped = True
            uc.emu_stop()
            return
        args = [uc.reg_read(r) for r in regs]
        if address == 0xC0015058:
            uc.mem_write(args[0], bytes([args[1]&255])*args[2])
            ret(args[0])
        elif address == 0xC0014DAC:
            uc.mem_write(args[0], bytes(uc.mem_read(args[1], args[2])))
            ret(args[0])
        elif address == 0xC036DB60:
            check(args[0] == owner+8, 'wrong recorder mailbox owner')
            events.append(bytes(uc.mem_read(args[2], 0x168)))
            ret(0)
        elif address == 0xC03A0E58:
            notifications.append(bytes(uc.mem_read(args[1], 0x174)))
            ret(1)
        elif address in noops:
            calls.append(hex(address))
            ret()
        elif address in (0xC06AEC30, 0xC0388BA8, 0xC03A9B88, 0xC03AB468,
                         0xC03AC518, pool_count, 0xC0723250):
            ret({0xC06AEC30: cbstate, 0xC0388BA8: owner, 0xC03A9B88: settings,
                 0xC03AB468: live, 0xC03AC518: allocated, pool_count: 8,
                 0xC0723250: final_error}[address])
        else:
            check(any(a <= address < b for a, b in bounds), f'unmodelled edge {address:x}')

    u.hook_add(UC_HOOK_CODE, code)
    def execute(entry, args=(), stops=()):
        nonlocal stopped, stop_at
        stopped, stop_at = False, set(stops)
        u.reg_write(UC_ARM_REG_CPSR, 0x13)
        u.reg_write(UC_ARM_REG_SP, ram+0x3E000)
        u.reg_write(UC_ARM_REG_LR, end)
        for r, v in zip(regs, args):
            u.reg_write(r, v)
        u.emu_start(entry, end+8, count=3000)
        check(stopped, 'instruction budget')

    # Execute the actual callback-subobject constructor stores, then registration.
    u.reg_write(UC_ARM_REG_R4, owner)
    u.reg_write(UC_ARM_REG_R6, 0)
    execute(0xC0388A2C, stops=(0xC0388A58,))
    execute(0xC06AE568, (config, owner+0xE8 if present else 0))
    check(get(cbstate+8) == (owner+0xE8 if present else 0), 'callback registration')
    execute(0xC03A9A08, (owner, 2, token))
    if phase == 'callback':
        execute(0xC06AECB8, (raw,))
    elif phase == 'start':
        u.reg_write(UC_ARM_REG_R5, prior_error)
        u.reg_write(UC_ARM_REG_R6, config)
        execute(0xC070DEA1, stops=(0xC070DEB4,))
    elif phase == 'stop':
        u.reg_write(UC_ARM_REG_R4, prior_error)
        put(ram+0x3E000+0x10, config)
        execute(0xC070E4B3, stops=(0xC070E4D8, 0xC070E4CE))
    elif phase == 'notification':
        execute(0xC0397098, (0, notification_kind, 1, 0))
    else:
        raise ValueError('unknown phase')
    def event_summary(e):
        return dict(id=struct.unpack_from('<I', e, 4)[0],
                    status=struct.unpack_from('<I', e, 0xE0)[0],
                    subtype=struct.unpack_from('<I', e, 0xC)[0],
                    e8=struct.unpack_from('<I', e, 0xE8)[0],
                    token_f4=struct.unpack_from('<I', e, 0xF4)[0],
                    nonzero_offsets=[n for n, v in enumerate(e) if v])
    return dict(phase=phase, raw=raw, present=present, prior_error=prior_error,
                final_error=final_error, token=token, notification_kind=notification_kind,
                events=[event_summary(e) for e in events],
                notification_tokens=[struct.unpack_from('<I', n, 0x170)[0] for n in notifications],
                asserted=0xC0011100 in visited,
                stored_token=get(owner+0xE4), visited=[hex(a) for a in visited], calls=calls)


def validate(row):
    phase = row['phase']
    expected = []
    if phase == 'notification':
        check(row['notification_tokens'] == [row['token']], 'global notification token')
    elif row['present']:
        if phase == 'callback':
            if row['raw'] >= 11:
                check(row['asserted'], 'invalid engine enum assertion')
            elif CONVERT[row['raw']] != 3:
                expected = [CONVERT[row['raw']]]
        elif phase == 'start' and not row['prior_error'] and not row['final_error']:
            expected = [0]
        elif phase == 'stop':
            expected = [1]  # engine 1 AND engine 2 collapse to recorder result 1
    check([e['status'] for e in row['events']] == expected, 'result status/delivery')
    for event in row['events']:
        check(event['id'] == 0x30, 'result event ID')
        check(event['subtype'] == event['e8'] == event['token_f4'] == 0, 'no result token/subtype')
        check(set(event['nonzero_offsets']) <= {4, 0xE0}, 'result event fields')
    check(row['stored_token'] == row['token'], 'request token slot')


def self_test(data):
    cases = ([dict(raw=r) for r in range(13)] + [dict(raw=0, present=False)]
             + [dict(phase='start', prior_error=p, final_error=f) for p, f in ((0,0),(1,0),(0,1))]
             + [dict(phase='stop', prior_error=e) for e in (0,1)]
             + [dict(phase='notification', token=t, notification_kind=k)
                for t in (42,77) for k in (15,17,19)])
    rows = [run(data, **c) for c in cases]
    for row in rows:
        validate(row)
    mutations = [
        ('event_id', {}, (0xC0389C10, 0xE3A0202F, 4)),
        ('status_field', dict(raw=1), (0xC0389C18, 0xE58D40F4, 4)),
        ('suppression', dict(raw=4), (0xC0389BF4, 0x0A000001, 4)),
        ('start_status', dict(phase='start'), (0xC070DEB0, 0x2001, 2)),
        ('stop_status', dict(phase='stop'), (0xC070E4B8, 0x2000, 2)),
        ('token_slot', dict(phase='notification'), (0xC0397164, 0xE3A01001, 4)),
    ]
    negatives = []
    for name, case, mutation in mutations:
        try:
            validate(run(data, mutation=mutation, **case))
        except ValueError as exc:
            check(not str(exc).startswith('unmodelled'), 'mutation escaped CFG')
            negatives.append(dict(name=name, assertion=str(exc)))
        else:
            raise ValueError(f'undetected mutation {name}')
    return rows, negatives


def main():
    root = Path.home()/'.local/share/fpsup/firmware'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fp', type=Path, default=root/'FP__V502/MAIN.bin')
    parser.add_argument('--fpl', type=Path, default=root/'FPL_V302/MAIN.bin')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    bindings = static(fp, fpl)
    cases, negatives = self_test(fpl) if args.self_test else ([], [])
    print(json.dumps(dict(hardware_tested=False,
        fingerprints={n: dict(bytes=len(d), sha256=hashlib.sha256(d).hexdigest())
                      for n,d in [('fp',fp),('fpl',fpl)]},
        correspondences=bindings, cases=cases, negatives=negatives,
        summary=dict(correspondences=len(bindings), arm_thumb_cases=len(cases), mutations=len(negatives)),
        read_proposal=dict(address='0xc2f2f808', bytes=16, event_id='0x30',
                           expected_candidate='0xc03abbd0', observed=False)), indent=2))


if __name__ == '__main__':
    main()
