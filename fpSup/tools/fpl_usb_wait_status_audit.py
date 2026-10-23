#!/usr/bin/env python3
"""Offline stock fp/fp L wait-chain audit; synthetic syscalls/MMIO, no device I/O."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                              UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R12,
                              UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

BASE = 0xC0000000
ROOT = Path.home() / '.local/share/fpsup/firmware'
PROFILES = {
    'fpl': ('FPL_V302', 49310208,
            'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9', 0, 0),
    'fp': ('FP__V502', 49245696,
           'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622',
           0x3780, 0x1C00),
}
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


def signed(value):
    return value - 0x100000000 if value & 0x80000000 else value


def run(image, profile, *, flags=None, syscall=0, hwo=0, logical=1,
        configured=1, status=0, marker=0, device=0, pre_end=False,
        disconnect=False, platform_off=False, suspended=0, mutate=None):
    """Run real Wait/lower/dispatcher/completion/device/reset/end/retry/clock bodies.

    Stub the syscall gateway (not its veneer), controller command, controller
    stop, IRQ API, and device-reset ancillary helpers. HWO writes are synthetic.
    """
    _, _, _, delta, data_delta = PROFILES[profile]
    code = lambda a: a + delta
    data = lambda a: a + data_delta
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, 0x4000000)
    u.mem_map(0x21000000, 0x10000)
    u.mem_map(0x30000000, 0x100000)
    u.mem_write(BASE, image)
    put = lambda a, v: u.mem_write(a, struct.pack('<I', v & 0xffffffff))
    get = lambda a: struct.unpack('<I', u.mem_read(a, 4))[0]
    stop, stack, trb = 0xC3FF0000, 0xC3FE0000, 0xC3F00000
    control = trb + logical * 0x100 + 12
    completion_bit = 1 << (logical + 17)
    wait_mask = 0x90000000 | completion_bit | (1 << (logical + 5))
    if flags is None:
        flags = completion_bit
    drv = data(0xC31E1610)
    for ep in range(7):
        put(drv + 0x54 + ep * 4, trb + ep * 0x100)
        put(drv + 0x678 + ep * 16, 1)  # bulk
        put(drv + 0x67C + ep * 16, int(ep != 1))
        put(trb + ep * 0x100 + 12, 1)
    for i in range(3):
        put(drv + 0x44 + i * 4, trb + 0x1000 + i * 0x100)
    put(drv + 0x14, trb + 0x2000)
    # Reset uses this additional descriptor pointer (different global per image).
    reset_global = 0xC2F24E0C if profile == 'fpl' else 0xC2F165CC
    marker_addr = 0xC3032A8F if profile == 'fpl' else 0xC3032A93
    put(reset_global, trb + 0x3000)
    put(drv, 0x1234)
    put(drv + 0x75C, configured)
    put(drv + 0x700 + logical * 4, status)
    put(drv + 0x6EC, suspended)
    put(drv + 0x764, 1)
    put(drv + 0x7F8, 1)
    put(drv + 0x77C, 0x24)
    put(drv + 0x6F0, device)
    put(marker_addr, marker)
    put(0x300B0000, 0 if platform_off else 0x10)
    put(0x2100C700, 8)
    put(0x2100C70C, 0x100000 if disconnect else 0)
    trace, waits, times = [], [], [0]
    if mutate == 'hide-minus4':
        # Preserve control flow, replace wrapper's teardown call with two NOPs.
        assert image[code(0xC01E1730)-BASE:code(0xC01E1730)-BASE+4] == bytes.fromhex('02f022f8')
        u.mem_write(code(0xC01E1730), bytes.fromhex('00bf00bf'))
    if mutate == 'ignore-configured':
        u.mem_write(code(0xC01E13D6), bytes.fromhex('4ff00034'))
    if mutate == 'ignore-reset-marker':
        u.mem_write(code(0xC01E1464), bytes.fromhex('4ff00034'))
    if mutate == 'erase-default-minus5':
        assert image[code(0xC01E3A74)-BASE:code(0xC01E3A74)-BASE+4] == bytes.fromhex('6ff0040a')
        u.mem_write(code(0xC01E3A74), bytes.fromhex('4ff0000a'))

    def ret(value=0):
        u.reg_write(UC_ARM_REG_R0, value & 0xffffffff)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

    def hook(uc, pc, size, _):
        if pc == stop:
            uc.emu_stop()
        elif pc == 0xC00011D0:
            service = uc.reg_read(UC_ARM_REG_R12)
            r = [uc.reg_read(reg) for reg in REGS]
            if service == 0x80240500:  # real C0016C08 veneer passes fifth arg via r4
                assert r[:3] == [0x1234, wait_mask, 0x21], r
                assert get(uc.reg_read(UC_ARM_REG_R4)) == 20
                waits.append({'service': hex(service), 'mask': hex(r[1]),
                              'mode': r[2], 'timeout': 20, 'status': syscall,
                              'flags': hex(flags), 'hwo_before': get(control) & 1,
                              'hwo_after': hwo})
                put(r[3], flags)
                put(control, hwo)
                ret(syscall)
            else:
                raise AssertionError(f'unexpected syscall {service:#x}')
        elif pc == 0xC0016B30:  # clock only; real clock arithmetic remains
            times[0] += 101
            put(uc.reg_read(UC_ARM_REG_R0), 0)
            put(uc.reg_read(UC_ARM_REG_R0) + 4, times[0])
            ret()
        elif pc in (0xC0016B9C, 0xC00169C8):
            trace.append(['set-flags' if pc == 0xC0016B9C else 'clear-flags',
                          hex(uc.reg_read(UC_ARM_REG_R1))])
            ret()
        elif pc == 0xC0015058:
            r = [uc.reg_read(reg) for reg in REGS]
            uc.mem_write(r[0], bytes([r[1] & 255]) * r[2])
            ret(r[0])
        elif pc in (code(0xC01E32C8), code(0xC01DFC98),
                    code(0xC01E26F8), code(0xC01E26A0), code(0xC01E2B28),
                    code(0xC01E14D8), code(0xC01F555C), code(0xC01F5244)):
            trace.append([hex(pc), uc.reg_read(UC_ARM_REG_R0)])
            if pc == code(0xC01E32C8) and pre_end:
                put(control, hwo)  # synthetic controller cancellation outcome
            ret()
        elif pc in (code(0xC01E3778), code(0xC01E35C8), code(0xC01E3078)):
            trace.append([hex(pc), uc.reg_read(UC_ARM_REG_R0)])

    u.hook_add(UC_HOOK_CODE, hook)

    def invoke(entry, args):
        u.reg_write(UC_ARM_REG_SP, stack)
        u.reg_write(UC_ARM_REG_LR, stop)
        for reg, arg in zip(REGS, args):
            u.reg_write(reg, arg)
        u.emu_start(code(entry) | 1, stop, count=100000)
        assert u.reg_read(UC_ARM_REG_PC) == stop, 'instruction budget exhausted'
        assert u.reg_read(UC_ARM_REG_SP) == stack, 'unbalanced stack'
        return signed(u.reg_read(UC_ARM_REG_R0))

    if pre_end:
        # Register a waiting endpoint so real EndTransfer publishes completion bit.
        put(drv + 0x674, completion_bit)
        invoke(0xC01E35C8, [logical])
    result = invoke(0xC01E1700, [logical, 20])
    return {'status': result, 'hwo': get(control) & 1,
            'endpoint_status': get(drv + 0x700 + logical * 4), 'configured': get(drv + 0x75C) & 255,
            'marker': get(marker_addr) & 255, 'waits': waits, 'trace': trace}


def checks(image, profile):
    delta = PROFILES[profile][3]
    cases = [
        ('completion-clear', {}, 0),
        ('completion-stale-HWO', {'hwo': 1}, 0),
        ('logical2-completion', {'logical': 2}, 0),
        ('logical2-event-eaten', {'logical': 2, 'flags': 0, 'syscall': -50}, -5),
        ('logical2-marker-event-eaten', {'logical': 2, 'marker': 1, 'flags': 0, 'syscall': -50}, -1),
        ('bulk-suspended', {'suspended': 1}, -2),
        ('no-event', {'flags': 0}, -5),
        ('syscall-minus1', {'syscall': -1, 'flags': 0}, -5),
        ('syscall-minus50', {'syscall': -50, 'flags': 0}, -5),
        ('syscall-positive7', {'syscall': 7, 'flags': 0}, -5),
        ('unconfigured', {'configured': 0}, -1),
        ('endpoint-status2', {'status': 2}, -1),
        ('reset-marker-event-eaten', {'marker': 1, 'syscall': -50, 'flags': 0}, -1),
        ('device-bit1', {'flags': 0x10000000, 'device': 1}, -4),
        ('device-bit1-marker-overwrite', {'flags': 0x10000000, 'device': 1, 'marker': 1}, -1),
        ('device-bit200', {'flags': 0x10000000, 'device': 0x200}, -1),
        ('device-bit800', {'flags': 0x10000000, 'device': 0x800}, -1),
        ('device-reset', {'flags': 0x10000000, 'device': 2}, -1),
        ('device-reset-HWO', {'flags': 0x10000000, 'device': 2, 'hwo': 1}, -1),
        ('reset-plus-completion', {'flags': 0x10040000, 'device': 2}, 0),
        ('retry-disconnect', {'flags': 0, 'disconnect': True}, -4),
        ('platform-off', {'platform_off': True}, -1),
        ('cancel-clear', {'pre_end': True}, -1),
        ('cancel-HWO', {'pre_end': True, 'hwo': 1}, -1),
    ]
    results = {}
    for name, args, expected in cases:
        result = run(image, profile, **args)
        assert result['status'] == expected, (profile, name, result)
        if name in ('device-bit1', 'retry-disconnect'):
            assert any(x[0] == hex(0xC01E3778 + delta) for x in result['trace'])
        results[name] = result
    assert results['completion-stale-HWO']['hwo'] == 1
    assert results['cancel-clear']['hwo'] == 0
    assert ['set-flags', '0x40000'] in results['cancel-clear']['trace']
    assert results['reset-marker-event-eaten']['hwo'] == 0
    assert results['device-reset']['configured'] == 0
    assert results['device-reset']['marker'] == 1
    assert not any(x[0] == hex(0xC01E3778 + delta)
                   for x in results['device-bit1-marker-overwrite']['trace'])
    assert results['reset-plus-completion']['configured'] == 0
    assert any(x[0] == hex(0xC01E3078 + delta)
               for x in results['reset-plus-completion']['trace'])
    mutations = []
    for mutation, case, oracle in (
            ('hide-minus4', {'flags': 0x10000000, 'device': 1},
             lambda r: any(x[0] == hex(0xC01E3778 + delta) for x in r['trace'])),
            ('ignore-configured', {'configured': 0}, lambda r: r['status'] == -1),
            ('ignore-reset-marker', {'marker': 1, 'syscall': -50, 'flags': 0},
             lambda r: r['status'] == -1),
            ('erase-default-minus5', {'syscall': -50, 'flags': 0},
             lambda r: r['status'] == -5)):
        assert not oracle(run(image, profile, mutate=mutation, **case)), mutation
        mutations.append(mutation)
    return {'cases': results, 'mutations_detected': mutations}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--profile', choices=(*PROFILES, 'both'), default='both')
    p.add_argument('--range', action='append', default=[], help='hex start:end:a|t')
    a = p.parse_args()
    for name in PROFILES if a.profile == 'both' else [a.profile]:
        directory, length, sha, _, _ = PROFILES[name]
        image = (a.root / directory / 'MAIN.bin').read_bytes()
        if len(image) != length or hashlib.sha256(image).hexdigest() != sha:
            p.error(f'{name}: not audited official MAIN')
        if not a.range:
            print(json.dumps({'profile': name, 'sha256': sha, **checks(image, name)}, indent=2))
        for spec in a.range:
            start, end, mode = spec.split(':')
            start, end = int(start, 16), int(end, 16)
            if mode not in ('a', 't') or not BASE <= start < end <= BASE + len(image):
                p.error('invalid range')
            cs = Cs(CS_ARCH_ARM, CS_MODE_ARM if mode == 'a' else CS_MODE_THUMB)
            for i in cs.disasm(image[start-BASE:end-BASE], start):
                print(f'{name} {i.address:08x} {i.bytes.hex():10s} {i.mnemonic:10s} {i.op_str}')


if __name__ == '__main__':
    main()
