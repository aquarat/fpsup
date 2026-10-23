#!/usr/bin/env python3
"""Offline, fingerprint-checked fp L USB lifecycle disassembly. No device I/O."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

BASE = 0xC0000000
SHA = 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'

def checks(image):
    """Real Thumb bodies; synthetic RAM, explicit callees, no DWC3 model."""
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                  UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
                                  UC_ARM_REG_CPSR)
    stop, stack, trb = 0xC3FF0000, 0xC3FE0000, 0xC3F00000

    def run(entry, args, setup, stubs, changed=None, observe=None):
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(BASE, 0x4000000)
        u.mem_map(0x21000000, 0x10000)  # synthetic controller registers
        u.mem_map(0x30000000, 0x100000)  # synthetic platform registers
        u.mem_write(BASE, image)
        put = lambda a, v: u.mem_write(a, struct.pack('<I', v & 0xffffffff))
        get = lambda a: struct.unpack('<I', u.mem_read(a, 4))[0]
        setup(put)
        if changed:
            u.mem_write(*changed)
        calls = []
        def hook(uc, pc, size, _):
            if observe:
                observe(uc, pc)
            if pc == stop:
                uc.emu_stop()
            elif pc in stubs:
                calls.append((pc, uc.reg_read(UC_ARM_REG_R0)))
                value = stubs[pc]
                if callable(value):
                    value = value(uc)
                uc.reg_write(UC_ARM_REG_R0, value & 0xffffffff)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE, hook)
        u.reg_write(UC_ARM_REG_SP, stack)
        u.reg_write(UC_ARM_REG_LR, stop)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2), args):
            u.reg_write(reg, value & 0xffffffff)
        u.emu_start(entry, stop, count=10000)
        assert u.reg_read(UC_ARM_REG_PC) == stop, 'instruction budget exhausted'
        assert u.reg_read(UC_ARM_REG_SP) == stack, 'unbalanced stack'
        return get, calls, u.reg_read(UC_ARM_REG_R0)

    results = []
    def reset_setup(p):
        p(0xC2F24E0C, trb + 0x200)
        p(0xC31E1664, trb)
        p(0xC31E1654, trb + 0x100)
        p(0xC31E1D74, 1)
        p(0xC31E1E08, 1)
    def memset(u):
        u.mem_write(u.reg_read(UC_ARM_REG_R0),
                    bytes([u.reg_read(UC_ARM_REG_R1) & 255]) * u.reg_read(UC_ARM_REG_R2))
        return u.reg_read(UC_ARM_REG_R0)
    get, _, _ = run(0xC01E3079, [], reset_setup, {0xC0015058: memset})
    assert get(0xC31E1D74) == 0 and get(0xC31E1E08) == 0
    results.append('driver reset clears OUT_BUSY and consumed flag')
    # mode -> backend driver selector: execute real switch including its TBB.
    for mode, expected in ((4, 0), (5, 1), (8, 2), (12, 3), (13, 2), (3, 255)):
        _, calls, result = run(0xC01E4F81, [mode], lambda p: None,
                               {0xC01E47A8: 0})
        assert calls == [(0xC01E47A8, expected)] and result == 0, (mode, calls, result)
        results.append(f'active mode {mode} -> backend selector {expected}')

    # Completion handler: its actual guards, writes and selector helper run.
    def completion(busy, consumed, request, mutate=False):
        def setup(p):
            p(0xC31E1668, trb)
            p(trb + 12, 0)
            p(trb + 8, 0)
            p(0xC31E1C98, 1)  # logical 1 descriptor type bulk
            p(0xC31E1C9C, 0)  # direction OUT
            p(0xC31E1D74, busy)
            p(0xC31E1E08, consumed)
            p(0xC3025744, 0x45000000)
        changed = (0xC01E41BC, bytes.fromhex('0023')) if mutate else None
        get, calls, result = run(0xC01E4001, [request, 2, 0], setup,
                                {0xC01E1608: 1, 0xC01E2918: 1024,
                                 0xC01E3400: 0}, changed)
        return get, [x for x in calls if x[0] == 0xC01E3400], result
    for busy, consumed, req, rearm in ((0, 0, 0x10000005, True),
                                      (1, 0, 0x10000005, False),
                                      (0, 1, 0x10000005, False),
                                      (1, 0, 0x10000002, False),
                                      (1, 0, -1, False)):
        get, starts, result = completion(busy, consumed, req)
        assert bool(starts) == rearm
        if rearm:
            assert starts == [(0xC01E3400, 2)]
            assert get(trb) == 0x05000000 and get(trb+12) == 0x813
        if req in (0x10000002, -1):
            assert get(0xC31E1E08) == 1 and get(0xC31E1D74) == 0
        results.append(f'completion busy={busy} consumed={consumed} request={req:#x}: rearm={rearm}')
    # Deliberately breaking the consumed-store reopens rearm on our completion.
    _, starts, _ = completion(1, 0, 0x10000002, mutate=True)
    assert starts == [(0xC01E3400, 2)], 'mutation did not expose rearm'
    results.append('sensitivity: mutate consumed=1 to 0 -> own completion rearms stock buffer')

    for status in (-4, -1, 0):
        _, calls, result = run(0xC01E1701, [1, 20], lambda p: None,
                               {0xC01E2888: 0, 0xC01E13B0: status,
                                0xC01E3778: 0})
        assert result == status & 0xffffffff
        assert any(pc == 0xC01E3778 for pc, _ in calls) == (status == -4)
        results.append(f'Wait lower return {status}: global teardown called={status == -4}')
    _, calls, _ = run(0xC01E3779, [], lambda p: p(0xC31E1D8C, 0xA7),
                     {0xC01E15F0: lambda u: 0 if u.reg_read(UC_ARM_REG_R0) == 1 else 1,
                      0xC01E35C8: 0, 0xC01DFC98: 0, 0xC01DFB98: 0})
    assert [arg for pc, arg in calls if pc == 0xC01E35C8] == [1, 2, 3]
    assert calls[-2][0] == 0xC01DFC98 and calls[-1] == (0xC01DFB98, 1)
    results.append('global teardown mask A7 ends logical 1/2/3 then stops controller')
    # The controller run/stop semaphore is narrower than transfer ownership.
    lock_id = 0x1234
    lock_trace = []
    def acquire(u):
        assert u.reg_read(UC_ARM_REG_R0) == lock_id
        assert u.reg_read(UC_ARM_REG_R1) == 1
        assert u.reg_read(UC_ARM_REG_R2) == 0xffffffff
        lock_trace.append('acquire')
        return 0
    def release(u):
        assert u.reg_read(UC_ARM_REG_R0) == lock_id
        assert u.reg_read(UC_ARM_REG_R1) == 1
        lock_trace.append('release')
        return 0
    locks = {0xC01F570C: acquire, 0xC01F555C: release}
    def controller_setup(p):
        p(0xC31E161C, lock_id)
        p(0x2100C704, 0x80000000)
        p(0xC31E1B48, 0)  # take the no-halt-poll branch
    for entry, expected, locked in ((0xC01DFC51, 0x80000000, True),
                                    (0xC01DFC99, 0, True),
                                    (0xC01DFD69, 0, False)):
        lock_trace.clear()
        get, _, _ = run(entry, [], controller_setup, locks)
        assert get(0x2100C704) == expected
        assert lock_trace == (['acquire', 'release'] if locked else [])
        results.append(f'controller {entry:#x}: run={bool(expected)} semaphore={locked}')

    for entry, args, setup, stubs, check_addr, expected in (
            (0xC01E3401, [2], lambda p: None,
             {0xC01E1608: 1, 0xC01E32C8: 0}, 0xC31E1D74, 1),
            (0xC01E35C9, [1], lambda p: p(0xC31E1E38, 7),
             {0xC01E15F0: 0, 0xC01E1608: 1, 0xC01E32C8: 0,
              0xC01E29F0: 6, 0xC00169C8: 0, 0xC01E14D8: 0},
             0xC31E1E38, 0x80),
            (0xC01E3079, [], reset_setup, {0xC0015058: memset},
             0xC31E1E08, 0),
            (0xC01DFB99, [1], lambda p: p(0x300B0000, 0x1c), {},
             0x300B0000, 0)):
        lock_trace.clear()
        get, _, _ = run(entry, args, setup, {**locks, **stubs})
        assert get(check_addr) == expected and lock_trace == []
        results.append(f'{entry:#x} mutates state without controller semaphore (callees stubbed)')

    # Execute the real endpoint-command loop with a scripted CMDACT register.
    # The busy branch runs the real retry helper, whose disconnect path tears down.
    for busy in (False, True):
        def command_setup(p):
            for offset in (0, 4, 8, 12):
                p(trb + offset, 0)
        def command_observe(u, pc):
            if pc == 0xC01E338C:
                u.mem_write(0x2100C82C, struct.pack('<I', 0x400 if busy else 7 << 16))
        _, calls, result = run(0xC01E32C9, [2, 6, trb], command_setup,
                              {0xC01E2FD8: 0, 0xC01E3818: 0,
                               0xC01E2888: 0, 0xC01DFB98: 0,
                               0xC01E28A8: 1, 0xC01DFDD8: -1,
                               0xC01E3778: 0, 0xC01E3030: 0},
                              observe=command_observe)
        assert result == (0xfffffffc if busy else 0)
        assert any(pc == 0xC01E3778 for pc, _ in calls) == busy
        assert calls[-1][0] == 0xC01E3030
        results.append(f'real command loop CMDACT={busy}: nested teardown={busy}')

    # Real high-level stop is synchronous calls, not a posted task request.
    _, calls, _ = run(0xC002F620, [5], lambda p: p(0xC3077794, 5),
                     {0xC00306D0: 0, 0xC00313D0: 0, 0xC002FD98: 0})
    assert [pc for pc, _ in calls] == [0xC00306D0, 0xC00313D0, 0xC002FD98]
    results.append('mode-5 exit calls clear-state then stop then finalizer synchronously')
    # Execute save/restore CPSR helpers, mocking only the interrupt-controller API.
    for held in (0, 1):
        masks = []
        def irq_observe(u, pc):
            if pc == 0xC01E26F8:
                u.reg_write(UC_ARM_REG_CPSR, u.reg_read(UC_ARM_REG_CPSR) & ~0xc0)
            if pc in (0xC01E26F8, 0xC01E2700, 0xC01E271C):
                masks.append(u.reg_read(UC_ARM_REG_CPSR) & 0xc0)
        _, calls, _ = run(0xC01E26F9, [], lambda p: p(0xC31E1E1C, held),
                         {0xC000FCA0: 0}, observe=irq_observe)
        assert masks == [0, 0xc0, 0]
        assert calls == ([] if held else [(0xC000FCA0, 0x34)])
        results.append(f'IRQ reenable helper held={held}: CPU mask restored before return')

    def mask_setup(p):
        p(0x2100C70C, 0)  # real speed decoder selects 1
        p(0x2100C200, 0x141)
    get, calls, _ = run(0xC01E2FD9, [], mask_setup, locks)
    assert get(0x2100C200) == 1 and get(0xC31E1E28) == 0x140 and calls == []
    results.append('command preamble clears controller bits 0x140 without a lock')

    def event_setup(p):
        p(0xC31E1D00, 2)
        p(0x2100C700, 8)  # enter reset branch
        p(0xC31E1D8C, 0x24)
    _, calls, _ = run(0xC01E3D19, [0], event_setup,
                     {0xC01E15F0: lambda u: 1 if u.reg_read(UC_ARM_REG_R0) == 2 else 0,
                      0xC01E35C8: 0, 0xC01E26A0: 0,
                      0xC01E3078: 0, 0xC01E2B28: 0, **locks})
    relevant = [pc for pc, _ in calls if pc != 0xC01E15F0]
    assert relevant == [0xC01E35C8, 0xC01E35C8, 0xC01E26A0, 0xC01E3078, 0xC01E2B28]
    results.append('device event mask 0x2 ends enabled endpoints before reset, without semaphore')
    return {'execution': 'real firmware; lower wait/type/length/start/teardown stubs',
            'checks': results, 'count': len(results)}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path, required=True)
    p.add_argument('--range', action='append', default=[],
                   help='hex start:end:a|t; repeat for additional ranges')
    p.add_argument('--check', action='store_true', help='run bounded Unicorn evidence checks')
    a = p.parse_args()
    image = a.main.read_bytes()
    if len(image) != 49310208 or hashlib.sha256(image).hexdigest() != SHA:
        p.error('not the audited official fp L 3.02 MAIN')
    if a.check:
        print(json.dumps(checks(image), indent=2))
        if not a.range:
            return
    ranges = a.range or ['c0031720:c00317d0:a', 'c01e1700:c01e1750:t',
                         'c01e3f38:c01e4000:t', 'c01e41e8:c01e4270:t']
    for spec in ranges:
        start, end, mode = spec.split(':')
        start, end = int(start, 16), int(end, 16)
        if mode not in ('a', 't') or not BASE <= start < end <= BASE + len(image):
            p.error('invalid range')
        cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB if mode == 't' else CS_MODE_ARM)
        print(f'\n# {spec} (official SHA-256 {SHA})')
        for i in cs.disasm(image[start-BASE:end-BASE], start):
            print(f'{i.address:08x}  {i.bytes.hex():10s} {i.mnemonic:10s} {i.op_str}')

if __name__ == '__main__':
    main()
