#!/usr/bin/env python3
"""Read-only, bounded fp L format/state audit. No device or deployment imports."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint
from fpl_gyro_recording_audit import compare
from fpl_recording_failure_audit import check, word

BINDINGS = [
    ('format_snapshot', 0xC00A7D38, 0xC00A4310, 0xA0),
    ('snapshot_dispatch', 0xC00912F8, 0xC008D508, 0xE8),
    ('snapshot_copy', 0xC0021D88, 0xC0021CA8, 0x34),
    ('context_publish', 0xC0021C50, 0xC0021B70, 0x68),
    ('context_block', 0xC0021B00, 0xC0021A20, 0x40),
    ('rec_settings_ctor', 0xC03A9910, 0xC03A9B28, 0x60),
    ('format_selection', 0xC0393D60, 0xC0393F78, 0xF0),
    ('mov_start', 0xC038A3E8, 0xC038A600, 0x3E0),
    ('mov_stop', 0xC038A7C8, 0xC038A9E0, 0x198),
    ('recstart_result', 0xC0392B70, 0xC0392D88, 0x108),
    ('rec_stop_request', 0xC0391A10, 0xC0391C28, 0x38),
    ('start_thunk', 0xC03AB8A0, 0xC03ABAB8, 0x38),
    ('stop_thunk', 0xC03AB8D8, 0xC03ABAF0, 0x38),
    ('result_thunk', 0xC03AB9B8, 0xC03ABBD0, 0x38),
    ('recstart_get', 0xC038AFE0, 0xC038B1F8, 0x58),
    ('rec_get', 0xC038B038, 0xC038B250, 0x58),
    ('thr_get', 0xC038AED0, 0xC038B0E8, 0x58),
]


def static_checks(fp, fpl):
    rows = [compare(fp, fpl, row) for row in BINDINGS]
    for address, expected in (
        (0xC073F7DC, 0xC00A4310), (0xC073F7E0, 0xC00A5190),
        (0xC0743ACC, 0xC00B2220), (0xC0726270, 0xC0021CA8),
        (0xC0BC3164, 0xC0393F78), (0xC0BC2F4C, 0xC0392D88),
        (0xC0BC2D3C, 0xC0391C28), (0xC0BC2D5C, 0xC0391DE0)):
        check(word(fpl, address) == expected, f'table {address:x}')
    for address, text in ((0xC073F810, b'MenuItemMovieRecFormat'),
                          (0xC0BE3484, b'SetMovRecFormat'),
                          (0xC0BC216C, b'MOV'), (0xC0BC21B8, b'MOV'),
                          (0xC0BC2484, b'MovRecFuncStateCinemaDng'),
                          (0xC0BC2E90, b'MovRecFuncStateRECSTART'),
                          (0xC0BC2CA4, b'MovRecFuncStateREC')):
        off = address-BASE
        check(fpl[off:off+len(text)+1] == text+b'\0', f'string {address:x}')
    check(list(fpl[0x391E48:0x391E50]) == [73, 27, 19, 25, 1, 13, 13, 7],
          'REC result jump table')
    return rows


def run(data, phase, value=1, accepted=1, error=0, stop_busy=0, mutation=None):
    """Execute stock ARM only inside explicit bounds; every external edge is named.

    select stubs the *whole* start helper; start_tail separately executes its
    post-submission suffix with an injected ABI frame. Neither is an IO test.
    Descriptor-to-thunk delivery is deliberately not fabricated here.
    """
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, (len(data)+4095)&~4095, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, data)
    if mutation:
        u.mem_write(mutation[0], struct.pack('<I', mutation[1]))
    ram = 0x10000000
    u.mem_map(ram, 0x30000)
    obj, event, settings, snapshot, menu, provider, table, live = [ram+x for x in
        (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000, 0x8000)]
    end, virtual = ram+0x2F000, ram+0x2F004
    regs = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    def put(a, v):
        u.mem_write(a, struct.pack('<I', v))
    def get(a):
        return struct.unpack('<I', u.mem_read(a, 4))[0]
    def ret(v=0):
        u.reg_write(UC_ARM_REG_R0, v)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
    state = 1 if phase == 'select' else 4 if phase == 'result' else 5
    put(obj, live)
    put(obj+0xC, state)
    put(obj+0x10, {1: 0xC0BC30F0, 4: 0xC0BC2EB4, 5: 0xC0BC2CC4}[state])
    put(event+4, 0x1234)  # sentinel, NOT a claimed firmware event ID
    put(event+0xF4, 42)
    put(event+0xE0, error)
    put(settings+4, snapshot)
    put(snapshot+0xC, value)
    put(menu+0xC, 0xC073F7C8)
    put(provider, table)
    put(table+0xC, virtual)
    u.reg_write(UC_ARM_REG_SP, ram+0x2E000)
    u.reg_write(UC_ARM_REG_LR, end)
    u.reg_write(UC_ARM_REG_R0, obj)
    u.reg_write(UC_ARM_REG_R1, event)
    u.reg_write(UC_ARM_REG_R2, live)
    starts = {'snapshot': 0xC008D508, 'select': 0xC03ABAB8,
              'result': 0xC03ABBD0, 'stop': 0xC03ABAF0,
              'stop_result': 0xC03ABBD0, 'start_tail': 0xC038A8F8}
    bounds = {
        'snapshot': [(0xC008D508, 0xC008D5F0), (0xC00A4310, 0xC00A43B0),
                     (0xC00A5250, 0xC00A5260)],
        'select': [(0xC03ABAB8, 0xC03ABAF0), (0xC0393F78, 0xC0394068),
                   (0xC03AB458, 0xC03AB468)],
        'result': [(0xC03ABBD0, 0xC03ABC08), (0xC0392D88, 0xC0392E90)],
        'stop': [(0xC03ABAF0, 0xC03ABB28), (0xC0391C28, 0xC0391C60),
                 (0xC038A9E0, 0xC038AB78)],
        'stop_result': [(0xC03ABBD0, 0xC03ABC08), (0xC0391DE0, 0xC0391E48),
                        (0xC0391E50, 0xC0391FB0)],
        'start_tail': [(0xC038A8F8, 0xC038A9D4)],
    }[phase]
    if phase == 'snapshot':
        u.reg_write(UC_ARM_REG_R0, menu)
        u.reg_write(UC_ARM_REG_R1, snapshot)
        u.reg_write(UC_ARM_REG_R2, 0)
        u.reg_write(UC_ARM_REG_R3, 0)
        put(ram+0x2E000, 0)  # non-propagating dispatch, real vtable+14 call
    if phase == 'start_tail':
        u.reg_write(UC_ARM_REG_R0, accepted)
        u.reg_write(UC_ARM_REG_R4, obj)
    calls, visited = [], []
    stopped = None
    noops = {0xC0372C20, 0xC0373B38, 0xC039A268, 0xC0397098,
             0xC03A66E0, 0xC0396030, 0xC0396218, 0xC0019DC0,
             0xC001A048, 0xC03A94C8, 0xC03A9CB8, 0xC03A9508,
             0xC039CE10, 0xC0013090, 0xC0425770, 0xC03963F0,
             0xC0389650, 0xC0019FD8, 0xC03A4838, 0xC03A4980,
             0xC03AC2B0, 0xC03A8AC0, 0xC03BD8B8, 0xC03BE2C8,
             0xC0388BA8, 0xC01F7B78, 0xC01F7EC0, 0xC0386020,
             0xC0389E98, 0xC001A288, 0xC0017CA0}
    fixed = {0xC03A9B88: settings, 0xC0396CD8: 1,
             0xC008D608: 0, 0xC0066470: value,
             0xC06AE258: live, 0xC06AE400: stop_busy,
             0xC0389E28: provider, 0xC038A250: provider,
             0xC00178D8: live, 0xC0017AC8: live}

    def code(uc, address, size, _):
        nonlocal stopped
        visited.append(address)
        if address == end:
            stopped = 'return'
            uc.emu_stop()
            return
        if phase == 'start_tail' and address in (0xC038A9D0, 0xC0011100):
            stopped = 'local_acceptance' if address == 0xC038A9D0 else 'fatal_assert'
            uc.emu_stop()
            return
        args = [uc.reg_read(r) for r in regs]
        if address == 0xC038A600 and phase == 'select':
            calls.append([hex(address), args])
            ret(accepted)
        elif address == 0xC0398078 and phase == 'select':
            calls.append([hex(address), args])
            if accepted:
                put(args[2], 15)  # injected raw classification, explicitly not proved here
            ret(accepted)
        elif address == 0xC038A9E0 and phase in ('result', 'stop_result'):
            calls.append([hex(address), args])
            ret(1)
        elif address == virtual:
            check(args[1] == 0xC0BC21B8, 'stop MOV path literal')
            calls.append([hex(address), args])
            ret(snapshot)
        elif address in noops or address in fixed:
            calls.append([hex(address), args])
            ret(fixed.get(address, 0))
        else:
            check(any(a <= address < b for a, b in bounds), f'unmodelled edge {address:x}')

    u.hook_add(UC_HOOK_CODE, code)
    u.emu_start(starts[phase], end+8, count=5000)
    check(stopped is not None, 'instruction limit')
    return dict(phase=phase, value=value, accepted=accepted, error=error,
                stop_busy=stop_busy, stop=stopped, result=u.reg_read(UC_ARM_REG_R0),
                snapshot=get(snapshot+0xC), busy=bytes(u.mem_read(settings+0x5F0, 1))[0],
                calls=calls, visited=[hex(a) for a in visited])


def validate(row):
    p = row['phase']
    targets = [a for a, _ in row['calls']]
    if p == 'snapshot':
        check(row['snapshot'] == (row['value'] if row['value'] <= 1 else 1), 'snapshot clamp')
    elif p == 'select':
        raw = row['value'] == 0
        check(('0xc0398078' in targets) == raw, 'raw selection')
        check(('0xc038a600' in targets) == (not raw), 'MOV selection')
        check(row['result'] == (15 if raw else 4) if row['accepted'] else row['result'] == 1,
              'selection result')
        if not raw:
            args = next(args for a, args in row['calls'] if a == '0xc038a600')
            check(args[1] == 42, 'MOV request token')
    elif p == 'result':
        check(row['result'] == (5 if row['error'] == 0 else 1), 'RECSTART result')
        check(('0xc038a9e0' in targets) == (row['error'] != 0), 'failed-start stop')
    elif p == 'stop':
        check(row['result'] == 5, 'stop request remains REC')
        check('0xc06ae400' in targets and row['busy'] == 0, 'stop helper')
        check(('0xc03be2c8' in targets) == bool(row['stop_busy']), 'stop followup')
    elif p == 'stop_result':
        check(row['result'] == (1 if row['error'] == 1 else 5), 'REC result return')
        check(('0xc0396cd8' in targets) == (row['error'] == 1), 'REC terminal branch')
    elif p == 'start_tail':
        check(row['stop'] == ('local_acceptance' if row['accepted'] else 'fatal_assert'), 'start tail')
        check(row['busy'] == bool(row['accepted']), 'start busy publication')


def self_test(data):
    cases = ([dict(phase='snapshot', value=v) for v in (0, 1, 2, 0xFFFFFFFF)]
             + [dict(phase='select', value=v, accepted=a) for v in (0, 1, 2) for a in (0, 1)]
             + [dict(phase='result', error=e) for e in (0, 1, 7)]
             + [dict(phase='stop', stop_busy=b) for b in (0, 1)]
             + [dict(phase='stop_result', error=e) for e in range(9)]
             + [dict(phase='start_tail', accepted=a) for a in (0, 1)])
    results = [run(data, **case) for case in cases]
    for row in results:
        validate(row)
    mutations = [
        ('clamp', dict(phase='snapshot', value=2), 0xC00A4390, 0x3A000002),
        ('format branch', dict(phase='select', value=1), 0xC0393FBC, 0x0A000007),
        ('RECSTART number', dict(phase='select'), 0xC0394050, 0xE3A03005),
        ('acceptance condition', dict(phase='select'), 0xC0393FF0, 0x0A000016),
        ('REC number', dict(phase='result'), 0xC0392DE4, 0xE3A03004),
        ('start busy byte', dict(phase='start_tail'), 0xC038A9B0, 0xE3A03000),
        ('stop followup branch', dict(phase='stop'), 0xC038AA84, 0x0A00000F),
    ]
    negatives = []
    for name, case, address, replacement in mutations:
        check(word(data, address) != replacement, 'ineffective mutation')
        try:
            validate(run(data, mutation=(address, replacement), **case))
        except ValueError as exc:
            check(not str(exc).startswith('unmodelled'), 'mutation escaped its CFG')
            negatives.append(dict(name=name, rejected_by=str(exc)))
        else:
            raise ValueError(f'undetected mutation: {name}')
    return results, negatives


def main():
    root = Path.home()/'.local/share/fpsup/firmware'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fp', type=Path, default=root/'FP__V502/MAIN.bin')
    parser.add_argument('--fpl', type=Path, default=root/'FPL_V302/MAIN.bin')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    rows = static_checks(fp, fpl)
    tests, negatives = self_test(fpl) if args.self_test else ([], [])
    print(json.dumps(dict(hardware_tested=False,
        fingerprints={name: dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                      for name, data in [('fp', fp), ('fpl', fpl)]},
        correspondences=rows, arm_cases=tests, rejected_mutations=negatives,
        summary=dict(correspondences=len(rows), arm_cases=len(tests), negatives=len(negatives)),
        limits=['No observed format/event descriptor supplied',
                'Raw state F in selection test is injected, not an end-to-end proof',
                'No scheduler, encoder, filesystem or durable-close emulation']), indent=2))


if __name__ == '__main__':
    main()
