#!/usr/bin/env python3
"""Offline failed-start delivery/unwind audit; no camera or deployment imports.

The reported live descriptor and the earlier hypothetical descriptor are replayed
separately. Kernel/media effects remain explicit synthetic assumptions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint
from fpl_gyro_recording_audit import compare
from fpl_gyro_path_audit import materialized

BINDINGS = [
    ('callback_dispatch', 0xC0377210, 0xC0377428, 0x48),
    ('event_callback', 0xC0385760, 0xC0385978, 0x120),
    ('movie_owner_ctor', 0xC03887F8, 0xC0388A10, 0x198),
    ('movie_owner_get', 0xC0388990, 0xC0388BA8, 0x50),
    ('submit', 0xC03A9580, 0xC03A9798, 0x110),
    ('consumer_loop', 0xC03889E0, 0xC0388BF8, 0x2D0),
    ('state_dispatch', 0xC038ACA8, 0xC038AEC0, 0xB0),
    ('common_result_handler', 0xC0383E90, 0xC03840A8, 0x838),
    ('common_start_result', 0xC03846C8, 0xC03848E0, 0x480),
    ('dng_event_handler', 0xC038BC50, 0xC038BE68, 0x128),
    ('dng_start_result', 0xC038BD98, 0xC038BFB0, 0x2C0),
    ('dng_stopping_test', 0xC038C800, 0xC038CA18, 0x38),
    ('state_return_filter', 0xC038C858, 0xC038CA70, 0x20),
    ('event_release', 0xC03A9740, 0xC03A9958, 0x38),
    ('cont_ctor_prefix', 0xC038CA18, 0xC038CC30, 0x28),
    ('interval_ctor', 0xC03905E8, 0xC0390800, 0x40),
    ('generic_event_route', 0xC0381A50, 0xC0381C68, 0xD0),
    ('clear_control_byte', 0xC03A92F0, 0xC03A9508, 0x20),
    ('event_2b_direct_thunk', 0xC03ABB08, 0xC03ABD20, 0x38),
    ('recstart_state_get', 0xC038AFE0, 0xC038B1F8, 0x58),
    ('rec_state_get', 0xC038B038, 0xC038B250, 0x58),
]
LIVE_ROW = (0x2B, 0, 0xFFFFFFFF, 0xC03ABD20)
HYPOTHETICAL_ROW = (0, 0, 0x28, 0x10)


def check(ok, message):
    if not ok:
        raise ValueError(message)


def word(data, address):
    check(BASE <= address <= BASE+len(data)-4, 'not file backed')
    return struct.unpack_from('<I', data, address-BASE)[0]


def static_checks(fp, fpl):
    rows = [compare(fp, fpl, row) for row in BINDINGS]
    check(materialized(fpl, 0xC0388BA8, 4, 8) == 0xC358D990, 'owner base')
    check(materialized(fpl, 0xC038AEC0, 0xC, 0x14) == 0xC2F2F508, 'runtime descriptor')
    check(0xC2F2F508 >= BASE+len(fpl), 'descriptor must not be decoded from MAIN')
    for address, target in ((0xC0BC2050, 0xC0388BF8),
                            (0xC0BC254C, 0xC038BE68),
                            (0xC0BC2564, 0xC038CA70),
                            (0xC0BC1A68, 0xC0385978)):
        check(word(fpl, address) == target, 'installed vtable slot')
    for a, text in ((0xBC2484, b'MovRecFuncStateCinemaDng'),
                    (0xBC27C4, b'MovRecFuncStateCONT'),
                    (0xBC2AC0, b'MovRecFuncStateINTERVAL'),
                    (0xBC2E90, b'MovRecFuncStateRECSTART'),
                    (0xBC2CA4, b'MovRecFuncStateREC')):
        check(fpl[a:a+len(text)+1] == text+b'\0', 'state RTTI')
    return rows


def live_evidence(path):
    """Validate a saved observation, never connect to a camera."""
    data = path.read_bytes()
    record = json.loads(data)
    check(record['address'] == 0xC2F2F7B8, 'live descriptor address')
    check(tuple(record['words']) == LIVE_ROW, 'live descriptor words')
    version = dict(line.split('=', 1) for line in record['version'].splitlines() if '=' in line)
    version = {k.strip(): v.strip() for k, v in version.items()}
    check(version == {'model': 'w91c1', 'xc version': 'V90',
          'rel version': '3.02.0.V90', 'git hash': '13aa621060efff11aaba9b21ad925005302605cf'},
          'live version identity')
    check(record['ping'] == 'OK pong seq=89 proof=PONG', 'saved post-read liveness')
    return dict(sha256=hashlib.sha256(data).hexdigest(), address=hex(record['address']),
                words=[hex(w) for w in record['words']], version=version,
                scope='one sequential passive observation; no all-boot stability claim')


def run(data, phase, error=2, request_present=True, callback=True, resources=1,
        allocation=True, send_ok=True, state=15, active=True, deferred=False,
        received_null=False, mutation=None, descriptor_kind='hypothetical', row_mutation=None):
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE,
                         UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC)
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, (len(data)+0xFFF) & ~0xFFF, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, bytes(data))
    if mutation:
        u.mem_write(mutation[0], struct.pack('<I', mutation[1]))
    ram = 0x10000000
    u.mem_map(ram, 0x30000)
    u.mem_map(0xC2F20000, 0x10000)  # synthetic runtime globals, NOT image bytes
    u.mem_map(0xC3580000, 0x30000)
    owner, event, req, raw, stateobj, pool, allocated = [ram+n for n in
        (0x1000, 0x3000, 0x5000, 0x8000, 0xA000, 0xB000, 0xC000)]
    end, callback_obj, request_id = ram+0x2F000, ram+0xD000, 42
    def put(a, v):
        u.mem_write(a, struct.pack('<I', v))
    def get(a):
        return struct.unpack('<I', u.mem_read(a, 4))[0]
    def rr(r):
        return u.reg_read(r)
    def wr(r, v):
        u.reg_write(r, v)
    put(event+4, 0x2B)
    put(event+0xC, 5)
    put(event+0xE4, error)
    put(event+0xE8, request_id)
    put(req+0x10FC, request_id)
    put(req+0x1100, 77)
    put(owner+0x144, state)
    put(owner+0x148, state)
    put(owner+0xF8+4*state, stateobj)
    put(stateobj+0xC, state)
    put(stateobj, ram+0xE000)
    u.mem_write(ram+0xE002, b'\1\1')
    put(stateobj+0x10, 0xC0BC24AC)
    put(stateobj+0x14, 0 if active else 0x80000000)
    u.mem_write(raw+0x78, bytes([int(not active)]))
    # Both rows are synthetic RAM during emulation. Only LIVE_ROW was reported
    # observed on hardware; HYPOTHETICAL_ROW preserves the original test model.
    descriptor = 0xC2F2F508+0x2B*16
    row = list(LIVE_ROW if descriptor_kind == 'live' else HYPOTHETICAL_ROW)
    if row_mutation:
        row[row_mutation[0]] = row_mutation[1]
    for index, value in enumerate(row):
        put(descriptor+4*index, value)
    put(raw+0xC, callback_obj if callback else 0)
    put(callback_obj, 0xC0BC1A5C)
    put(0xC2F2F838, pool)
    put(pool, pool+0x100)
    put(pool+0x114, ram+0x20000)
    put(pool+0x110, ram+0x20004)
    trace, visited, sends, notifications, cleanups = [], set(), [], [], []
    returned_event = False
    if phase == 'submit':
        start = 0xC0377428
        bounds = [(0xC0377428, 0xC0377470), (0xC0385978, 0xC0385A98),
                  (0xC0388BA8, 0xC0388BF8), (0xC03A9798, 0xC03A98A8)]
        wr(UC_ARM_REG_R0, raw)
        wr(UC_ARM_REG_R1, request_id)
        wr(UC_ARM_REG_R2, 0)
        wr(UC_ARM_REG_R3, error)
    else:
        start = 0xC0388BF8
        bounds = [(0xC0388BF8, 0xC0388EC8), (0xC038AEC0, 0xC038AF70),
                  (0xC038BE68, 0xC038BF90), (0xC038BFB0, 0xC038C270),
                  (0xC038CA18, 0xC038CA50), (0xC038CA70, 0xC038CA90),
                  (0xC0381C68, 0xC0381D38),
                  (0xC03A9508, 0xC03A9528),
                  (0xC03ABD20, 0xC03ABD58),
                  (0xC03840A8, 0xC03848E0), (0xC03848E0, 0xC0384D60)]
        wr(UC_ARM_REG_R0, owner)
    wr(UC_ARM_REG_SP, ram+0x2E000)
    wr(UC_ARM_REG_LR, end)
    noops = {0xC0013090, 0xC001CCE0, 0xC001CD18, 0xC0019DC0, 0xC001A450,
             0xC001A048, 0xC001A288, 0xC0388EC8, 0xC0389140, 0xC03A9958,
             0xC0374438, 0xC0396030, 0xC0396218, 0xC03A9508,
             0xC037DF20, 0xC037E0F8, 0xC03A5B50, 0xC0381940,
             0xC03A65B0, 0xC03A66E0, 0xC0396CD8}
    cleanup_targets = {0xC0377838, 0xC0375390, 0xC0377948, 0xC0375248}

    def code(uc, address, size, _):
        nonlocal returned_event
        if phase == 'consume' and address == 0xC0388C08 and returned_event:
            uc.emu_stop()  # exactly one iteration, not an invented function return
            return
        visited.add(address)
        if any(a <= address < b for a, b in bounds):
            return
        trace.append(hex(address))
        value = 0
        if address == ram+0x20000:
            value = resources
        elif address == 0xC03AC518:
            check(rr(UC_ARM_REG_R0) == 0x168, 'event allocation size')
            value = allocated if allocation else 0
        elif address in (0xC0015058, 0xC0014DAC):
            dest, source, count = [rr(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
            check(ram <= dest and dest+count <= ram+0x30000, 'copy destination')
            uc.mem_write(dest, bytes([source & 255])*count if address == 0xC0015058
                         else bytes(uc.mem_read(source, count)))
            value = dest
        elif address == 0xC036DB60:
            ptr = rr(UC_ARM_REG_R2)
            sends.append(ptr)
            if ptr:
                check([get(ptr+o) for o in (4, 0xC, 0xE4, 0xE8)] ==
                      [0x2B, 5, error, request_id], 'submitted event correlation')
            value = 0 if send_ok else 1
        elif address == 0xC03896A0:
            value = int(deferred)
        elif address == 0xC036DBD8:
            check(not returned_event, 'unexpected second receive')
            put(rr(UC_ARM_REG_R2), 0 if received_null else event)
            returned_event = True
        elif address == 0xC03755D8:
            check(rr(UC_ARM_REG_R1) == request_id, 'request-id lookup')
            value = req if request_present else 0
        elif address == 0xC0377560:
            value = raw
        elif address in cleanup_targets:
            if address != 0xC0377838:
                check(rr(UC_ARM_REG_R1) == request_id, 'cleanup request correlation')
            cleanups.append(hex(address))
        elif address == 0xC0397250:
            notifications.append(rr(UC_ARM_REG_R1))
        elif address == 0xC0396CD8:
            value = state  # returned state from late-error processing is assumed
        elif address == 0xC038C5D8:
            check(rr(UC_ARM_REG_R1) == (77 if request_present else 0xFFFFFFFF), 'stop request token')
            value = 15  # stop result injected, NOT IO completion
        else:
            check(address in noops, f'unexpected execution {address:08x}')
        wr(UC_ARM_REG_R0, value)
        wr(UC_ARM_REG_PC, rr(UC_ARM_REG_LR))

    def on_write(uc, access, address, size, value, _):
        check(ram <= address and address+size <= ram+0x30000 or
              0xC35A9D78 <= address and address+size <= 0xC35A9D7C,
              'write outside modeled RAM/counter')
    u.hook_add(UC_HOOK_CODE, code)
    u.hook_add(UC_HOOK_MEM_WRITE, on_write)
    u.emu_start(start, end, count=10000)
    if phase == 'submit':
        check(rr(UC_ARM_REG_PC) == end, 'submit did not return')
        if not callback:
            check(not sends and not trace, 'null callback must bypass submit')
        else:
            check(rr(UC_ARM_REG_R0) == int(resources > 0), 'submit result')
            check(len(sends) == int(resources > 0), 'queue call despite allocation/send failure')
            check(get(0xC35A9D78) == int(resources == 0), 'rejection counter')
            if sends:
                check(sends == [allocated if allocation else 0], 'queued pointer')
    else:
        check(rr(UC_ARM_REG_PC) == 0xC0388C08, 'consumer iteration bound')
        check(get(owner+0x144) == state, 'no terminal state change in modeled failures')
        if received_null:
            check(not cleanups and 0xC0388C58 not in visited, 'null queue item skipped')
        elif deferred:
            check(not cleanups and hex(0xC03A9958) in trace, 'deferred event release')
        elif state in (4, 5, 8, 14, 16):
            check(0xC038AEC0 not in visited, 'prefilter bypasses state dispatch')
            expected = [hex(a) for a in (0xC0377838, 0xC0375390, 0xC0377948, 0xC0375248)]
            check(cleanups == (expected if request_present else []), 'common cleanup order')
            check(notifications == ([5 if error == 3 else 6] if request_present else []), 'error class')
            check((hex(0xC03A9958) in trace) == (state in (4, 5, 8)), 'route-specific event release')
            check((hex(0xC0396CD8) in trace) == (request_present and error == 2), 'late error extra processing')
        else:
            check(0xC038BE68 in visited and 0xC038BFB0 in visited, 'conditional DNG route')
            check((0xC03ABD20 in visited) == (descriptor_kind == 'live'), 'direct thunk route')
            check((0xC038AF0C in visited) == (descriptor_kind == 'live'), 'signed negative selector')
            check((0xC038AF18 in visited) == (descriptor_kind != 'live'), 'hypothetical virtual route')
            check(cleanups == ([hex(0xC0377948), hex(0xC0375248)] if request_present else []), 'DNG cleanup')
            check((hex(0xC038C5D8) in trace) == active, 'DNG conditional stop')
            check(hex(0xC03A9958) in trace, 'DNG normal event release')
            check(bytes(u.mem_read(ram+0xE002, 2)) == b'\0\0', 'DNG control bytes cleared')
    return dict(phase=phase, error=error, request_present=request_present,
                callback=callback, resources=resources, allocation=allocation,
                send_ok=send_ok, state=state, active=active, deferred=deferred,
                received_null=received_null,
                descriptor_kind=descriptor_kind,
                replayed_descriptor_words=[hex(w) for w in row],
                trace=trace, cleanup_calls=cleanups, notification_classes=notifications,
                queued_null=bool(sends and sends[0] == 0))


def execution_tests(data):
    cases = []
    for error in (1, 2, 3):
        for kwargs in ({}, {'resources': 0}, {'allocation': False},
                       {'send_ok': False}, {'callback': False}):
            cases.append(run(data, 'submit', error=error, **kwargs))
        for state in (8, 14, 16):
            for present in (False, True):
                cases.append(run(data, 'consume', error=error, state=state,
                                 request_present=present))
        for present in (False, True):
            for active in (False, True):
                cases.append(run(data, 'consume', error=error,
                                 request_present=present, active=active))
    cases.append(run(data, 'consume', deferred=True))
    cases.append(run(data, 'consume', received_null=True))
    for error in (1, 2, 3):
        for present in (False, True):
            for active in (False, True):
                cases.append(run(data, 'consume', error=error, request_present=present,
                                 active=active, descriptor_kind='live'))
    # Dispatcher never reads row[0]; it indexes using event+4. This neutral
    # mutation is deliberately accepted by execution, not called a negative.
    cases.append(run(data, 'consume', descriptor_kind='live', row_mutation=(0, 0)))
    for state in (4, 5):
        for error in (1, 2, 3):
            cases.append(run(data, 'consume', descriptor_kind='live', state=state, error=error))
    return cases


def negatives(fp, fpl):
    passed = []
    for kind, data in [('fp', fp), ('fpl', fpl)]:
        for at in (0, 0x3A9898, len(data)-1, None):
            m = bytearray(data)
            if at is None:
                m.pop()
            else:
                m[at] ^= 1
            try:
                fingerprint(m, kind)
            except ValueError:
                passed.append(f'{kind}:fingerprint:{at}')
            else:
                raise AssertionError('fingerprint mutation accepted')
    for phase, addr, value, kwargs in [
        ('submit', 0xC03859C8, 0xE3A0C006, {}),  # subtype 5 -> 6
        ('submit', 0xC0385A74, 0xE58D40FC, {}),  # request correlation offset
        ('submit', 0xC03A9898, 0xE3A00000, {}),  # submit return 1 -> 0
        ('consume', 0xC038BF24, 0xE3530006, {}),  # DNG subtype 5 -> 6
        ('consume', 0xC0384CA0, 0xE3520002, dict(error=3, state=14)),
        ('consume', 0xC0384204, 0xE3530001, dict(state=14, error=2)),
    ]:
        try:
            run(fpl, phase, mutation=(addr, value), **kwargs)
        except ValueError:
            passed.append(f'execution:{addr:08x}')
        else:
            raise AssertionError(f'mutation accepted {addr:08x}')
    for address in (0xC038AECC, 0xC0BC254C):
        changed = bytearray(fpl)
        changed[address-BASE] ^= 4
        try:
            static_checks(fp, changed)
        except ValueError:
            passed.append(f'static:{address:08x}')
        else:
            raise AssertionError('static mutation accepted')
    for kwargs in ({'row_mutation': (2, 0)},
                   {'row_mutation': (3, 0xC03ABD58)},
                   {'mutation': (0xC03ABD38, 0xE28330A4)}):
        try:
            run(fpl, 'consume', descriptor_kind='live', **kwargs)
        except ValueError:
            passed.append('live_direct_route:'+str(kwargs))
        else:
            raise AssertionError('direct-route mutation accepted')
    return passed


def main():
    root = Path.home()/'.local/share/fpsup/firmware'
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp', type=Path, default=root/'FP__V502/MAIN.bin')
    p.add_argument('--fpl', type=Path, default=root/'FPL_V302/MAIN.bin')
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--live-descriptor', type=Path,
                   help='optional saved passive observation to validate (never device access)')
    args = p.parse_args()
    fp, fpl = args.fp.read_bytes(), args.fpl.read_bytes()
    fingerprint(fp, 'fp')
    fingerprint(fpl, 'fpl')
    result = dict(hardware_tested=False, cfg='incompleteCFG',
                  hashes={k: hashlib.sha256(v).hexdigest() for k, v in [('fp', fp), ('fpl', fpl)]},
                  bindings=static_checks(fp, fpl),
                  saved_live_observation=live_evidence(args.live_descriptor) if args.live_descriptor else None,
                  reported_live_row=[hex(w) for w in LIVE_ROW],
                  initializer_search={k: dict(
                      exact_row_present=struct.pack('<4I', 0x2B, 0, 0xFFFFFFFF, target) in data,
                      packed_target_word_present=struct.pack('<I', target) in data,
                      limit='byte-pattern search only; encoded/relocated initialization unresolved')
                      for k, data, target in [('fp', fp, 0xC03ABB08), ('fpl', fpl, 0xC03ABD20)]},
                  assumptions=['initialized getter guard', 'synthetic pool count/allocation/queue',
                    'hypothetical virtual row preserved separately from reported live direct row',
                    'reported live row -> real C03ABD20 -> state vtable +A0; one observation only',
                    'state14=CONT,16=INTERVAL; neither renamed MOV',
                    'lookup correlates event E8 to synthetic request; cleanup services stubbed',
                    'stop returns injected state15; no IO/RTOS/task completion tested',
                    'stubs preserve all registers except r0/pc; unlisted execution fails'],
                  execution=execution_tests(fpl) if args.self_test else [],
                  negatives=negatives(fp, fpl) if args.self_test else [])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
