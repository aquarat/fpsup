#!/usr/bin/env python3
"""Offline lifecycle evidence: bounded stock ARM, never camera/deployer access.

Synthetic callee results are assumptions, not firmware/media success. JSON lists
the assumptions, call traces, raw aligned xrefs and unresolved integration edges.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint, instructions
from fpl_gyro_recording_audit import compare
from fpl_gyro_path_audit import materialized

BINDINGS = [
    ('start', 0xC0378A50, 0xC0378C68, 0x7D8),
    ('stop', 0xC038C3C0, 0xC038C5D8, 0x238),
    ('owner_ctor', 0xC0377288, 0xC03774A0, 0xC0),
    ('owner_get', 0xC0377348, 0xC0377560, 0x48),
    ('dispatch_cinema_branch', 0xC0377C90, 0xC0377EA8, 0x88),
    ('dispatch_return_tail', 0xC037848C, 0xC03786A4, 0xCC),
    ('result_callback', 0xC0377210, 0xC0377428, 0x48),
    ('selector_consumer', 0xC0379E08, 0xC037A020, 0x788),
    ('other_start_selector', 0xC0379BE0, 0xC0379DF8, 0x64),
    ('cinema_state_ctor', 0xC038B258, 0xC038B470, 0x50),
    ('cinema_state_reset', 0xC038BD78, 0xC038BF90, 0x20),
    ('stop_worker', 0xC0398D88, 0xC0398FA0, 0x390),
    ('frame_advance', 0xC030B2E8, 0xC030F380, 0x38),
    ('owner_worker_dispatch', 0xC0377150, 0xC0377368, 0xA8),
    ('callback_setter', 0xC03771F8, 0xC0377410, 0x18),
    ('callback_installation', 0xC0381658, 0xC0381870, 0xC8),
    ('result_event_callback', 0xC0385760, 0xC0385978, 0x120),
    ('cinema_state_get', 0xC038B1B8, 0xC038B3D0, 0x50),
    ('media_finalizer', 0xC03A5190, 0xC03A53A8, 0xB8),
]


def check(ok, message):
    if not ok:
        raise ValueError(message)


def word(data, address):
    return struct.unpack_from('<I', data, address-BASE)[0]


def xrefs(data, targets):
    """Aligned word scan, explicitly NOT a code/data or reachability proof."""
    result = {hex(t): {'branches': [], 'pointers': []} for t in targets}
    for off, (w,) in enumerate(struct.iter_unpack('<I', data)):
        address = BASE+off*4
        if w in targets:
            result[hex(w)]['pointers'].append(hex(address))
        if w & 0x0E000000 == 0x0A000000 and w >> 28 != 15:
            rel = w & 0xFFFFFF
            if rel & 0x800000:
                rel -= 0x1000000
            target = (address+8+rel*4) & 0xFFFFFFFF
            if target in targets:
                result[hex(target)]['branches'].append(hex(address))
    return result


def static_checks(fp, fpl):
    rows = [compare(fp, fpl, row) for row in BINDINGS]
    check(materialized(fpl, 0xC0377560, 0x18, 0x1C) == 0xC3520F24, 'raw owner address')
    check(materialized(fpl, 0xC03774A0, 0x14, 0x18) == 0xC0BBF82C, 'raw owner vtable')
    check(materialized(fpl, 0xC038B3D0, 0x18, 0x1C) == 0xC358EAC0, 'Cinema state address')
    check(materialized(fpl, 0xC038B470, 0x14, 0x18) == 0xC0BC24AC, 'Cinema state table')
    check(word(fpl, 0xC0B8D89C) == 0xC030F380, 'Cinema slot +28')
    check(word(fp, 0xC0B55DB4) == 0xC030B2E8, 'fp Cinema slot +28')
    check(word(fpl, 0xC0BBF844) == 0xC0377C48, 'owner dispatch slot +18')
    check(word(fpl, 0xC0BC15E4) == 0xC0BC1A5C, 'result callback table publication')
    check(word(fpl, 0xC0BC1A68) == 0xC0385978, 'result callback slot +C')
    check(fpl[0xBBF858:0xBBF880].split(b'\0')[0] == b'XC_StillCreateRaw', 'owner RTTI')
    check(fpl[0xBC2484:0xBC24AC].split(b'\0')[0] == b'MovRecFuncStateCinemaDng', 'stop RTTI')
    refs = xrefs(fpl, {0xC0378C68, 0xC038C5D8, 0xC0377C48, 0xC037A020,
                       0xC0377410, 0xC038B470})
    check(refs['0xc0378c68']['branches'] == ['0xc0377f14'], 'start direct callers')
    check(refs['0xc038c5d8']['branches'] == [hex(a) for a in (
        0xC038BA58, 0xC038BDE8, 0xC038C044, 0xC038C16C,
        0xC038C23C, 0xC038C320, 0xC038C33C)], 'stop direct callers')
    accesses = [dict(address=hex(i.address), instruction=i.mnemonic+' '+i.op_str)
                for i in instructions(fpl, 0xC03774A0, 0x3300, False)
                if '#0xa0]' in i.op_str]
    return dict(bindings=rows, aligned_xrefs_not_complete_cfg=refs,
                bounded_A0_operand_scan_not_alias_analysis=accesses)


def execute_case(data, phase, audio=0, media='SD', result=1, retry=0, fmt=2,
                 callback=True, mutation=None):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, 0x3000000, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, bytes(data))
    if mutation:
        u.mem_write(mutation[0], struct.pack('<I', mutation[1]))
    ram, end = 0x10000000, 0x1001F000
    u.mem_map(ram, 0x20000)
    owner, settings, manager, path, obj, req, dummy = [ram+n for n in
        (0x1000, 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000)]
    sp = ram+0x18000
    def put(a, v):
        u.mem_write(a, struct.pack('<I', v))
    def get(a):
        return struct.unpack('<I', u.mem_read(a, 4))[0]
    def reg(r, value):
        u.reg_write(r, value)
    put(owner+0xA0, 13)
    put(owner+0xC, obj if callback else 0)
    put(obj, obj+0x100)
    put(obj+0x10C, 0xC0385978)
    put(manager+4, 0xC0B8D874)
    put(manager+0xC, 1)
    put(manager+0x10, 7)
    put(path, 0xC0B8D940)
    u.mem_write(settings+0xE0, bytes([audio]))
    u.mem_write(settings+0x5CE, b'\1')
    u.mem_write(dummy+0x100, media.encode()+b'\0')
    u.mem_write(owner+0x20, bytes([retry]))
    put(owner+0x14, 0x80000000)
    put(owner+0xC, obj if phase == 'caller' and callback else 17)
    if phase == 'caller' and not callback:
        put(owner+0xC, 0)
    events, visited, submitted = [], set(), []
    # Explicit whitelist: other external execution fails. Services return zero
    # unless listed below; no real service body or asynchronous task is executed.
    noop = {
        0xC0203B70, 0xC04408B8, 0xC04408F8, 0xC01F7B78, 0xC01F7BB8,
        0xC01F7D60, 0xC0123248, 0xC02B15C0, 0xC01F7EC0, 0xC0374438,
        0xC0376DB0, 0xC037F768, 0xC0310800, 0xC0397098, 0xC00CA6F0,
        0xC00CA9D0, 0xC0019DC0, 0xC001A288, 0xC0377838, 0xC01F8328,
        0xC0396030, 0xC03963F0, 0xC01F7D88, 0xC01F8198, 0xC0399368,
        0xC0399380, 0xC03AC2B0, 0xC0380028, 0xC039A268, 0xC03A66E0,
        0xC001A450, 0xC0013090, 0xC0386B78, 0xC00102D0, 0xC0388BA8,
        0xC0019FD8, 0xC038A310, 0xC038A508, 0xC03754B8, 0xC001A048,
        0xC03A4EA0,
    }
    pointers = {0xC0203D60: settings, 0xC0440990: dummy+0x100,
                0xC0377560: dummy, 0xC0380318: dummy, 0xC03A4EA0: dummy}
    returns = {0xC0311030: result, 0xC0398FA0: result,
               0xC0310AC8: fmt, 0xC0396CD8: 23,
               0xC03A4F18: 0, 0xC038A4A0: 0,
               0xC0376518: fmt, 0xC03A53A8: 0}
    if phase == 'start':
        start, bounds = 0xC0379204, [(0xC0379204, 0xC0379440),
            (0xC030F380, 0xC030F3B8), (0xC030FCD8, 0xC030FD08)]
        # Enter after earlier work, with the function's saved-register frame.
        put(sp+0x26C+24, end)
        reg(UC_ARM_REG_R6, owner)
        reg(UC_ARM_REG_R4, req)
        reg(UC_ARM_REG_R11, settings)
    elif phase == 'stop':
        start, bounds = 0xC038C5D8, [(0xC038C5D8, 0xC038C810)]
        reg(UC_ARM_REG_R0, owner)
        reg(UC_ARM_REG_R1, 0xFFFFFFFF)
        reg(UC_ARM_REG_R2, req)
    elif phase in ('fail_acquire', 'fail_setup', 'cancel'):
        start, last = {'fail_acquire': (0xC0378D34, 0xC0378D4C),
                       'fail_setup': (0xC0378FA0, 0xC0378FC0),
                       'cancel': (0xC037918C, 0xC03791DC)}[phase]
        bounds = [(start, last), (0xC0379434, 0xC0379440)]
        put(sp+0x26C+24, end)
        reg(UC_ARM_REG_R6, owner)
        u.mem_write(owner+0x78, b'\1')
    elif phase == 'worker_negative':
        start, bounds = 0xC0398FA0, [(0xC0398FA0, 0xC0399330),
                                    (0xC03A53A8, 0xC03A5460)]
        reg(UC_ARM_REG_R0, 1)
        reg(UC_ARM_REG_R1, 0xFFFFFFFF)
    else:
        start, bounds = 0xC0378734, [(0xC0378734, 0xC0378770),
                                    (0xC0377428, 0xC0377470),
                                    (0xC0385978, 0xC0385A98)]
        put(sp+0x27C+28, end)
        put(req+0x10FC, 42)
        reg(UC_ARM_REG_R4, req)
        reg(UC_ARM_REG_R5, result)
        reg(UC_ARM_REG_R7, owner)
    reg(UC_ARM_REG_SP, sp)
    reg(UC_ARM_REG_LR, end)

    def code(uc, address, size, _):
        visited.add(address)
        if address == 0xC0385978:
            check([uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                UC_ARM_REG_R2, UC_ARM_REG_R3)] == [obj, 42, 0, result], 'callback arguments')
        if any(a <= address < b for a, b in bounds):
            return
        events.append(hex(address))
        value = 0
        if address in pointers:
            value = pointers[address]
        elif address in returns:
            value = returns[address]
        elif address == 0xC030D390:
            check(get(uc.reg_read(UC_ARM_REG_R0)) == 1, 'Cinema selector input')
            check(uc.reg_read(UC_ARM_REG_R1) == dummy+0x100, 'volume string input')
            value = manager  # assumed initialized SD/SSD Cinema manager
        elif address == 0xC030F100:
            put(uc.reg_read(UC_ARM_REG_R1), path)  # assumed valid path object
        elif address == 0xC030ED38:
            value = dummy  # assumed extension succeeds; no file opened
        elif address == 0xC0015058:
            dest, val, count = [uc.reg_read(r) for r in
                               (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
            check(ram <= dest and dest+count <= ram+0x20000, 'memset bounds')
            uc.mem_write(dest, bytes([val & 255])*count)
            value = dest
        elif address == 0xC03A9798:
            event = uc.reg_read(UC_ARM_REG_R1)
            fields = [get(event+o) for o in (4, 0xC, 0xE8, 0xE4)]
            check(fields == [0x2B, 5, 42, result], 'failure event fields')
            submitted.append(fields)  # queue delivery/consumer is not executed
        else:
            check(address in noop, f'unexpected execution {address:08x}')
        reg(UC_ARM_REG_R0, value)
        reg(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def write(uc, access, address, size, value, _):
        check(ram <= address and address+size <= ram+0x20000, 'write outside synthetic RAM')
    u.hook_add(UC_HOOK_CODE, code)
    u.hook_add(UC_HOOK_MEM_WRITE, write)
    u.emu_start(start, end, count=5000)
    check(u.reg_read(UC_ARM_REG_PC) == end, 'bounded execution did not return')
    actual = u.reg_read(UC_ARM_REG_R0)
    if phase == 'start':
        check(actual == (0 if result else 2), 'start result')
        check(get(owner+0xA0) == 1, 'provisional selector publication')
        check((0xC03792D0 in visited) == bool(audio), 'audio-only START')
        check((0xC0379430 in visited) == bool(result), 'common local success tail')
        check(get(manager+0x14) == int(bool(result)), 'successful frame increment')
        check(get(manager+0x10) == 7, 'tail did not advance take')
    elif phase == 'stop':
        check((0xC038C69C in visited) == (not retry), 'STOP bypass on retry')
        check((0xC038C778 in visited) == bool(result), 'stop_fin branch')
        check(u.mem_read(owner+0x20, 1)[0] == (retry if result else 1), 'stop retry flag')
        check(actual == (23 if result and fmt != 2 else 17), 'stop state return')
    elif phase in ('fail_acquire', 'fail_setup', 'cancel'):
        check(actual == (3 if phase == 'fail_setup' else 1), 'early failure status')
        check(get(owner+0xA0) == 13, 'early failure must precede selector publication')
        check((hex(0xC01F7D88) in events) == (phase == 'cancel'), 'cancel audio unwind')
    elif phase == 'worker_negative':
        check(actual == int(fmt == 3), 'worker finalizer-zero path can return nonzero')
        check((hex(0xC0397098) in events) == (fmt == 3), 'worker notification')
        check(0xC03991A8 not in visited, 'worker bypasses later finalization')
    else:
        check(actual == result, 'caller propagates start status')
        check((0xC0385978 in visited) == bool(result and callback), 'failure callback only')
        check(len(submitted) == int(bool(result and callback)), 'failure event submission')
    return dict(phase=phase, audio=audio, media=media, assumed_result=result,
                retry=retry, raw_format=fmt, callback=callback, returned=actual,
                external_stub_trace=events, submitted_events=submitted)


def execution_tests(data):
    rows = []
    for audio in (0, 1):
        for media in ('SD', 'SSD'):
            for result in (0, 1):
                rows.append(execute_case(data, 'start', audio, media, result))
        for retry in (0, 1):
            for result in (0, 1):
                for fmt in (0, 2):
                    rows.append(execute_case(data, 'stop', audio=audio, retry=retry,
                                             result=result, fmt=fmt))
    for result in (0, 1, 2, 3):
        for callback in (False, True):
            rows.append(execute_case(data, 'caller', result=result, callback=callback))
    for phase in ('fail_acquire', 'fail_setup', 'cancel'):
        rows.append(execute_case(data, phase))
    for state in (0, 1, 2, 3):
        rows.append(execute_case(data, 'worker_negative', fmt=state))
    return rows


def negatives(fp, fpl):
    passed = []
    for kind, data in [('fp', fp), ('fpl', fpl)]:
        for at in (0, 0x37936C, len(data)-1, None):
            changed = bytearray(data)
            if at is None:
                changed.pop()
            else:
                changed[at] ^= 1
            try:
                fingerprint(changed, kind)
            except ValueError:
                passed.append(f'{kind}:fingerprint:{at}')
            else:
                raise AssertionError('fingerprint mutation accepted')
    # Bypass fingerprint and structural comparison: execution oracles alone.
    cases = [
        ('start', 0xC0379368, 0xE3A02000, dict()),  # selector publication 1 -> 0
        ('start', 0xC03793A4, 0x0A000001, dict(result=0)),  # BNE -> BEQ
        ('start', 0xC0379220, 0x1A000046, dict(audio=0)),  # audio gate reversed
        ('stop', 0xC038C774, 0x1A00001F, dict(result=0)),  # retry test reversed
        ('stop', 0xC038C7F8, 0xE3A03000, dict(result=0)),  # lose retry latch
        ('caller', 0xC0378738, 0x1A000008, dict(result=2)),  # lose failure callback
    ]
    for phase, address, value, kwargs in cases:
        try:
            execute_case(fpl, phase, mutation=(address, value), **kwargs)
        except ValueError:
            passed.append(f'execution:{address:08x}')
        else:
            raise AssertionError(f'execution mutation accepted: {address:08x}')
    return passed


def main():
    root = Path.home()/'.local/share/fpsup/firmware'
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp', type=Path, default=root/'FP__V502/MAIN.bin')
    p.add_argument('--fpl', type=Path, default=root/'FPL_V302/MAIN.bin')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    result = static_checks(fp, fpl)
    result.update(hardware_tested=False, cfg='incompleteCFG',
        hashes={k: hashlib.sha256(v).hexdigest() for k, v in [('fp', fp), ('fpl', fpl)]},
        assumptions=['start enters at audio gate with earlier initialization assumed',
            'explicit service stubs; no RTOS, sensor, media I/O or asynchronous completion',
            'stubs preserve registers except r0/pc; zero return unless explicitly overridden',
            'initialized Cinema manager and path-object stubs for both volume strings',
            'stock frame increment and bounds helper execute; take number remains unchanged',
            'stop worker result is injected, not a durability or quiescence result',
            'worker negatives inject state 0/1/2/3; real finalizer sees synthetic owner+C=0',
            'real installed callback constructs event; queue delivery/consumer unwind unresolved'],
        execution=execution_tests(fpl) if args.self_test else [],
        negatives=negatives(fp, fpl) if args.self_test else [])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
