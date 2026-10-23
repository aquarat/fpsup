#!/usr/bin/env python3
"""Offline fp L completion/query audit. No camera/transport imports or outputs.

Reads only the exact official MAIN supplied by --main. Executes native query
stubs and kernel bodies in Unicorn with synthetic BSS/objects. The exception
dispatcher is bridged explicitly; scheduler effects are mocked, not certified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
import unicorn as uc
from unicorn import arm_const as ar

BASE = 0xC0000000
SIZE = 49310208
SHA = 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'
REF_TASK, REF_FLAG, WAIT_FLAG = 0xC01F54CC, 0xC01F5460, 0xC0016C08
SERVICES = {0x800F0200: 0xC000B328, 0x80250200: 0xC00040A0,
            0x80240500: 0xC0003E78, 0x80220200: 0xC0003C58}
CURRENT, NEXT, DISABLED, CONTEXT = 0xC3000098, 0xC30000A0, 0xC3000094, 0xC3033268
TASK_BASE, FLAG_BASE = 0xC3000838, 0xC3011428
RAM, OUT, STOP, BRIDGE, SP = 0x45000000, 0x45000100, 0x46000000, 0x46000004, 0x45010000
TID, FID = 7, 11
TASK, CALLER, FLAG = TASK_BASE+132*TID, TASK_BASE+132*2, FLAG_BASE+32*FID
OWNER, HOLDER, WAITSPEC = RAM+0x400, RAM+0x440, RAM+0x480

BOUNDS = {
    'ref_task_stub': (REF_TASK, REF_TASK+0x24),
    'ref_flag_stub': (REF_FLAG, REF_FLAG+0x24),
    'wait_flag_stub': (WAIT_FLAG, WAIT_FLAG+0x24),
    'set_flag_stub': (0xC0016B9C, 0xC0016BC0),
    'ref_task_kernel': (0xC000B328, 0xC000B4CC),
    'ref_flag_kernel': (0xC00040A0, 0xC0004168),
    'wait_flag_kernel': (0xC0003E78, 0xC00040A0),
    'queue_first_id': (0xC000E040, 0xC000E054),
    'wait_zero_timeout_prefix': (0xC000E058, 0xC000E080),
    'zero_words': (0xC0015808, 0xC0015898),
    'irq_guards': (0xC000EC14, 0xC000EC3C),
    'context_psr': (0xC0003A00, 0xC0003A08),
    'pool_flag_boolean': (0xC036F1B0, 0xC036F200),
    'pool_holder_boolean': (0xC036E3F0, 0xC036E410),
    'pool_worker': (0xC036F200, 0xC036F2D0),
    'pool_attach': (0xC036F0B0, 0xC036F1AC),
    'pool_ctor': (0xC036E0D0, 0xC036E240),
    'pool_join': (0xC036E410, 0xC036E450),
    'start_task_kernel': (0xC000ACE8, 0xC000AE04),
    'dormant_init': (0xC000A4C8, 0xC000A548),
    'ready_enqueue': (0xC000A548, 0xC000A5B8),
    'sleep_kernel': (0xC000BD90, 0xC000BED0),
    'wait_transition': (0xC000DE70, 0xC000DF04),
    'set_flag_kernel': (0xC0003C58, 0xC0003DB0),
    'dispatcher_prefix': (0xC00011D0, 0xC0001258),
}

# Pin meaning-bearing instructions as well as the whole-image fingerprint.
# The executable scenarios below also reject intentional mutations with the
# fingerprint/these pins deliberately bypassed.
PINS = {
    0xC0001248: ('ldr', 'pc, [ip, sl, lsl #2]'),
    0xC000B368: ('cmp', 'r1, #0x1f4'),
    0xC000B438: ('str', 'r1, [r6, #0xc]'),
    0xC000B43C: ('strne', 'r0, [r6, #0x10]'),
    0xC000B444: ('strne', 'r0, [r6, #0x14]'),
    0xC000B46C: ('str', 'r0, [r6, #0x18]'),
    0xC000B478: ('str', 'r0, [r6, #0x1c]'),
    0xC00040AC: ('cmp', 'r1, #0x12c'),
    0xC000410C: ('str', 'r0, [r6, #8]'),
    0xC000E078: ('str', 'r3, [r1]'),
    0xC000E07C: ('popeq', '{r4, r5, pc}'),
    0xC0003FF0: ('tst', 'r6, #0x20'),
    0xC0004000: ('tst', 'r6, #0x10'),
    0xC036F23C: ('blx', 'r1'),
    0xC036F2AC: ('str', 'r1, [r4, #8]'),
    0xC036F2B8: ('bl', '#0xc0016b9c'),
    0xC036F2CC: ('b', '#0xc036f218'),
    0xC036F21C: ('bl', '#0xc01f5580'),
    0xC036F134: ('str', 'r5, [r4, #8]'),
    0xC036F138: ('str', 'r5, [r4, #4]'),
    0xC036F0E0: ('mvn', 'r1, #1'),
    0xC036F0E4: ('bl', '#0xc00169c8'),
    0xC036E188: ('add', 'ip, r4, #4'),
    0xC036E18C: ('str', 'ip, [sp]'),
    0xC036E1F4: ('bl', '#0xc0016a58'),
    0xC036E22C: ('bl', '#0xc0016bc0'),
    0xC036E230: ('mov', 'ip, r4'),
    0xC000AD74: ('cmp', 'r1, #8'),
    0xC000A4CC: ('strb', 'r1, [r0, #0x23]'),
    0xC000A560: ('strb', 'r0, [r4, #0x23]'),
    0xC000BE50: ('str', 'r1, [r0, #0x28]'),
}


def fingerprint(data):
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA:
        raise ValueError('not the audited official fp L 3.02 MAIN')


def word(data, address):
    return struct.unpack_from('<I', data, address-BASE)[0]


def structure(data):
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    for address, expected in PINS.items():
        insns = list(md.disasm(data[address-BASE:address-BASE+4], address))
        if len(insns) != 1 or (insns[0].mnemonic, insns[0].op_str) != expected:
            raise ValueError(f'changed semantic instruction at {address:08x}')
    table = word(data, 0xC0001568)
    if table != 0xC0021040:
        raise ValueError('changed dispatcher table')
    for stub, service in ((REF_TASK, 0x800F0200), (REF_FLAG, 0x80250200),
                          (WAIT_FLAG, 0x80240500), (0xC0016B9C, 0x80220200)):
        signed_index = (service >> 16)-0x10000
        if word(data, stub+0x20) != service or word(data, table+signed_index*4) != SERVICES[service]:
            raise ValueError('changed syscall binding')
    if [word(data, 0xC0BBEA7C+i) for i in (0, 4, 8)] != [0, 0x49, 1]:
        raise ValueError('changed native completion flag initial descriptor')
    return [dict(name=name, address=hex(lo), bytes=hi-lo,
                 sha256=hashlib.sha256(data[lo-BASE:hi-BASE]).hexdigest())
            for name, (lo, hi) in BOUNDS.items()]


class NonPollingPath(RuntimeError):
    pass


class NextSleep(RuntimeError):
    pass


class Harness:
    """Real stub/kernel, simulated exception entry/return, synthetic kernel state.

    IRQ save/restore instructions and the output-zero helper execute for real.
    The scheduler call is counted and returned immediately; no timing guarantee.
    """
    def __init__(self, image):
        self.m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
        for address, size in ((BASE, (len(image)+4095)&~4095), (0xC2F06000, 0x2000),
                              (0xC3000000, 0x40000), (RAM, 0x10000), (STOP, 4096)):
            # The last MAIN page overlaps the auxiliary runtime-descriptor area.
            if address == 0xC2F06000:
                self.m.mem_map(0xC2F07000, 4096)
            else:
                self.m.mem_map(address, size)
        self.m.mem_write(BASE, bytes(image))
        self.w(CURRENT, CALLER)
        self.w(NEXT, CALLER)
        self.w(CALLER+8, 2)
        self.w(TASK+8, TID)
        self.w(TASK+0xC, OWNER+4)
        self.m.mem_write(TASK+0x21, bytes([5, 6, 1]))
        self.w(TASK+0x28, WAITSPEC)
        self.w(WAITSPEC, 0x12345678)   # deliberately synthetic wait-reason value
        self.w(TASK+0x2C, 55)
        self.w(TASK+0x30, 3)
        self.w(TASK+0x34, 2)
        self.w(FLAG, FLAG)
        self.w(FLAG+4, FLAG)
        self.w(FLAG+8, FID)
        self.w(FLAG+0xC, 0x76543210)
        self.w(FLAG+0x10, 0x49)
        self.w(FLAG+0x14, 1)
        self.w(OWNER+0xC, FID)
        self.w(HOLDER, OWNER)
        self.m.mem_write(OUT-16, b'\xA5'*96)
        self.executed = set()
        self.schedules = 0
        self.bridges = []
        self.worker_trace = None
        self.m.hook_add(uc.UC_HOOK_CODE, self.execute)
        self.m.hook_add(uc.UC_HOOK_MEM_WRITE, self.store)

    def w(self, at, value=None):
        if value is None:
            return struct.unpack('<I', self.m.mem_read(at, 4))[0]
        self.m.mem_write(at, struct.pack('<I', value & 0xffffffff))

    def store(self, m, access, at, size, value, unused):
        assert ((RAM <= at and at+size <= RAM+0x10000) or
                (CALLER+0x28 <= at and at+size <= CALLER+0x48) or
                (FLAG+0x14 <= at and at+size <= FLAG+0x18)), f'unexpected store {at:x}'

    def execute(self, m, pc, size, unused):
        self.executed.add(pc)
        if self.worker_trace is not None and pc in (0xC01F5580, STOP+0x10, 0xC001CCE0, 0xC001CD18):
            if pc == 0xC01F5580:
                self.worker_trace.append('sleep')
                if self.worker_trace.count('sleep') == 2:
                    raise NextSleep('next native sleep call reached, not executed')
            elif pc == STOP+0x10:
                assert m.reg_read(ar.UC_ARM_REG_R0) == RAM+0x500
                self.worker_trace.append('body_return_boundary')
            elif pc == 0xC001CCE0:
                self.w(m.reg_read(ar.UC_ARM_REG_R0), 0)
            m.reg_write(ar.UC_ARM_REG_R0, 0)
            m.reg_write(ar.UC_ARM_REG_PC, m.reg_read(ar.UC_ARM_REG_LR))
        elif pc == 0xC00011D0:
            service = m.reg_read(ar.UC_ARM_REG_R12)
            assert service in SERVICES, f'unexpected service {service:x}'
            if self.worker_trace is not None and service == 0x80220200:
                assert self.w(OWNER+8) == 0, 'flag set before callback cleared'
                assert 'body_return_boundary' in self.worker_trace
                self.worker_trace.append('set_completion_after_return')
            old_sp, old_lr = m.reg_read(ar.UC_ARM_REG_SP), m.reg_read(ar.UC_ARM_REG_LR)
            # Real stub r4 holds its original caller SP. Forward fifth argument
            # like the inspected dispatcher, without emulating exception modes.
            bridge_sp = old_sp-8
            self.w(bridge_sp, self.w(m.reg_read(ar.UC_ARM_REG_R4)))
            self.bridges.append((old_sp, old_lr))
            m.reg_write(ar.UC_ARM_REG_SP, bridge_sp)
            m.reg_write(ar.UC_ARM_REG_LR, BRIDGE)
            m.reg_write(ar.UC_ARM_REG_PC, SERVICES[service])
        elif pc == BRIDGE:
            old_sp, old_lr = self.bridges.pop()
            m.reg_write(ar.UC_ARM_REG_SP, old_sp)
            m.reg_write(ar.UC_ARM_REG_PC, old_lr)
        elif pc == 0xC0000CFC:
            self.schedules += 1
            m.reg_write(ar.UC_ARM_REG_PC, m.reg_read(ar.UC_ARM_REG_LR))
        elif pc == 0xC000E080:
            raise NonPollingPath('positive/infinite timeout would enter blocking path')
        else:
            assert any(lo <= pc < hi for lo, hi in BOUNDS.values()), f'escaped audit {pc:x}'

    def run(self, address, args, size=32, *, masked=False):
        m = self.m
        m.reg_write(ar.UC_ARM_REG_CPSR, 0x13 | (0xC0 if masked else 0))
        m.reg_write(ar.UC_ARM_REG_SP, SP-16)
        m.reg_write(ar.UC_ARM_REG_LR, STOP)
        saved = {r: 0xABC00000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
        for r, v in saved.items():
            m.reg_write(r, v)
        for i, v in enumerate(args[:4]):
            m.reg_write(getattr(ar, 'UC_ARM_REG_R'+str(i)), v & 0xffffffff)
        self.w(SP-16, args[4] if len(args) > 4 else 0)
        m.emu_start(address, STOP, count=10000)
        assert m.reg_read(ar.UC_ARM_REG_PC) == STOP, 'instruction bound exceeded'
        assert m.reg_read(ar.UC_ARM_REG_SP) == SP-16
        assert all(m.reg_read(r) == v for r, v in saved.items()), 'callee ABI'
        assert m.reg_read(ar.UC_ARM_REG_CPSR) & 0xC0 == (0xC0 if masked else 0)
        assert m.mem_read(OUT-16, 16) == b'\xA5'*16
        assert m.mem_read(OUT+size, 64-size) == b'\xA5'*(64-size)
        rc = m.reg_read(ar.UC_ARM_REG_R0)
        return (rc if rc < 2**31 else rc-2**32,
                list(struct.unpack('<'+'I'*(size//4), m.mem_read(OUT, size))))


def task_case(image, state=1, current=False, task_id=TID, schedule=False):
    h = Harness(image)
    h.m.mem_write(TASK+0x23, bytes([state]))
    if current:
        h.w(CURRENT, TASK)
        h.w(NEXT, TASK)
    if schedule:
        h.w(NEXT, TASK)
    rc, out = h.run(REF_TASK, [task_id, OUT])
    if task_id not in (0, *range(1, 501)):
        assert rc == -18 and out == [0xA5A5A5A5]*8
    elif state == 0:
        assert rc == -42 and out == [0]*8
    else:
        expected_state = 1 if state == 1 and current else state*2
        assert rc == 0 and out == [OWNER+4, 7, 6, expected_state,
                                  0x12345678 if state & 2 else 0,
                                  55 if state & 2 else 0, 3, 2], (rc, out)
    if schedule:
        assert h.schedules == 1
    return dict(kind='ref_task', internal_state=state, current=current, id=task_id,
                rc=rc, words=out, scheduler_calls=h.schedules)


def flag_case(image, pattern=1, flag_id=FID, exists=True, waiter=False):
    h = Harness(image)
    h.w(FLAG+0x14, pattern)
    h.w(FLAG+8, FID if exists else 0)
    if waiter:
        h.w(FLAG, TASK)
    rc, out = h.run(REF_FLAG, [flag_id, OUT], 12)
    if not 1 <= flag_id <= 300:
        assert rc == -18 and out == [0xA5A5A5A5]*3
    elif not exists:
        assert rc == -42 and out == [0xA5A5A5A5]*3
    else:
        assert rc == 0 and out == [0x76543210, TID if waiter else 0, pattern]
    assert h.w(FLAG+0x14) == pattern
    return dict(kind='ref_flag', id=flag_id, exists=exists, waiter=waiter, rc=rc, words=out)


def wait_case(image, pattern=1, wanted=1, mode=0, timeout=0, flag_id=FID,
              exists=True, blocked_context=False, masked=False, waiter=False, attr=0x49):
    h = Harness(image)
    h.w(FLAG+0x14, pattern)
    h.w(FLAG+8, FID if exists else 0)
    h.w(FLAG+0x10, attr)
    if waiter:
        h.w(FLAG, TASK)
    if blocked_context:
        h.w(DISABLED, 1)
    rc, out = h.run(WAIT_FLAG, [flag_id, wanted, mode, OUT, timeout], 4, masked=masked)
    match = bool(pattern & wanted) if mode & 1 else (pattern & wanted) == wanted
    expected = (-18 if not 1 <= flag_id <= 300 else
                -17 if not wanted or mode & ~0x31 or timeout < -1 else
                -25 if blocked_context or masked else
                -42 if not exists else
                -41 if waiter and not attr & 8 else 0 if match else -50)
    assert rc == expected, (rc, expected)
    assert out == [pattern if expected == 0 else 0xA5A5A5A5]
    after = pattern
    if expected == 0:
        if mode & 0x20:
            after &= ~wanted
        if mode & 0x10:
            after = 0
    assert h.w(FLAG+0x14) == after
    assert 0xC000DE70 not in h.executed, 'poll enqueued a wait'
    if expected == -50:
        assert h.w(CALLER+0x28) in (0xC2F06A58, 0xC2F06A64)
    return dict(kind='wait_flag_poll', rc=rc, mode=mode, before=pattern, after=after,
                output=out, wait_scratch_written=expected == -50)


def scenarios(image):
    results = [task_case(image, state=s) for s in (0, 1, 2, 4, 6, 8)]
    results += [task_case(image, current=True), task_case(image, current=True, task_id=0),
                task_case(image, schedule=True)]
    results += [task_case(image, task_id=x) for x in (-1, 501)]
    # Positive upper limit, absent object => buffer zeroed, not invalid-ID path.
    h = Harness(image)
    assert h.run(REF_TASK, [500, OUT]) == (-42, [0]*8)
    results.append(dict(kind='ref_task_upper_limit', rc=-42))
    results += [flag_case(image, **kw) for kw in ({}, {'pattern': 0}, {'pattern': 5},
        {'exists': False}, {'waiter': True}, {'flag_id': 0}, {'flag_id': 301})]
    h = Harness(image)
    assert h.run(REF_FLAG, [300, OUT], 12) == (-42, [0xA5A5A5A5]*3)
    results.append(dict(kind='ref_flag_upper_limit', rc=-42))
    results += [wait_case(image, **kw) for kw in ({}, {'pattern': 0},
        {'pattern': 5, 'wanted': 3, 'mode': 1}, {'pattern': 5, 'wanted': 3},
        {'pattern': 5, 'mode': 0x20}, {'pattern': 5, 'mode': 0x10},
        {'pattern': 5, 'mode': 0x30}, {'wanted': 0}, {'mode': 2}, {'timeout': -2},
        {'flag_id': 0}, {'exists': False}, {'blocked_context': True}, {'masked': True},
        {'attr': 0x41, 'waiter': True}, {'attr': 0x48, 'pattern': 0})]
    for exists, pattern, expected in ((True, 1, 1), (True, 0, 0), (False, 1, 0)):
        h = Harness(image)
        h.w(FLAG+8, FID if exists else 0)
        h.w(FLAG+0x14, pattern)
        rc, _ = h.run(0xC036E3F0, [HOLDER], 0)
        assert rc == expected
        results.append(dict(kind='native_boolean_wrapper', exists=exists, pattern=pattern, result=rc))
    for timeout in (1, -1):
        h = Harness(image)
        h.w(FLAG+0x14, 0)
        try:
            h.run(WAIT_FLAG, [FID, 1, 0, OUT, timeout], 4)
        except NonPollingPath:
            results.append(dict(kind='nonpolling_path_refused', timeout=timeout))
        else:
            raise AssertionError('nonzero timeout unexpectedly stayed polling')
    results += [completion_case(image, queued_wakes=n) for n in (0, 1)]
    results.append(completion_case(image, query_error=True))
    return results


def completion_case(image, queued_wakes=0, query_error=False):
    """Run native pool instructions through real ref-task/set-flag kernels.

    Mock body returns immediately; sleep and IRQ wrapper boundaries are explicit.
    Stop at the NEXT sleep call: completion precedes parking, not vice versa.
    """
    h = Harness(image)
    h.worker_trace = []
    h.w(CURRENT, TASK)
    h.w(NEXT, TASK)
    h.w(TASK+0x30, queued_wakes)
    if query_error:
        h.w(CONTEXT, 1)               # real ref_tsk(0) returns E_ID here
    h.w(FLAG+0x14, 0)
    h.w(OWNER+8, RAM+0x500)
    h.w(OWNER+4, RAM+0x500)
    h.w(RAM+0x500, RAM+0x520)
    h.w(RAM+0x52C, STOP+0x10)
    h.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
    h.m.reg_write(ar.UC_ARM_REG_SP, SP-16)
    h.m.reg_write(ar.UC_ARM_REG_R0, OWNER)
    h.m.reg_write(ar.UC_ARM_REG_LR, STOP)
    try:
        h.m.emu_start(0xC036F200, STOP, count=10000)
    except NextSleep:
        pass
    else:
        raise AssertionError('native pool never reached next sleep')
    expected = ['sleep', 'body_return_boundary']
    if not queued_wakes:
        expected += ['set_completion_after_return']
    expected += ['sleep']
    assert h.worker_trace == expected
    assert h.w(OWNER+8) == (RAM+0x500 if queued_wakes else 0)
    assert h.w(OWNER+4) == RAM+0x500  # retained historical pointer, NOT detached
    assert h.w(FLAG+0x14) == (0 if queued_wakes else 1)
    query_rc = h.m.reg_read(ar.UC_ARM_REG_R5)
    assert query_rc == (0xffffffee if query_error else 0)
    return dict(kind='native_completion_order', queued_wakes=queued_wakes,
                query_error=query_error, query_rc=-18 if query_error else 0,
                trace=h.worker_trace, body_slot=hex(h.w(OWNER+8)),
                historical_body_slot=hex(h.w(OWNER+4)),
                flag_pattern=h.w(FLAG+0x14), parked_proven=False)


def negative_tests(image):
    count = 0
    for at in (0, 0xB438, len(image)-1, None):
        changed = bytearray(image)
        if at is None:
            changed.pop()
        else:
            changed[at] ^= 1
        try:
            fingerprint(changed)
        except ValueError:
            count += 1
        else:
            raise AssertionError('fingerprint mutation accepted')
    for at in (0x107C, 0x1F5480, 0xB438, 0x36F2AC):
        changed = bytearray(image)
        changed[at] ^= 4
        try:
            structure(changed)        # fingerprint deliberately bypassed
        except ValueError:
            count += 1
        else:
            raise AssertionError('semantic/dispatch mutation accepted')
    # Execute wrong field offsets, wrong poll timeout result, and missing guard.
    for at, delta, oracle in (
        (0xB438, 4, lambda b: task_case(b)),
        (0x410C, 4, lambda b: flag_case(b)),
        (0xE074, 1, lambda b: wait_case(b, pattern=0)),
        (0x3FF0, 0x30, lambda b: wait_case(b, pattern=5, mode=0x20)),
        (0x36F2AC, 0xC, lambda b: completion_case(b)),
    ):
        changed = bytearray(image)
        changed[at] ^= delta
        try:
            oracle(changed)           # bypass ALL static guards on purpose
        except AssertionError:
            count += 1
        else:
            raise AssertionError(f'execution mutation accepted at {at:x}')
    return count


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--main', type=Path, required=True)
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args(argv)
    image = args.main.read_bytes()
    fingerprint(image)
    report = dict(firmware='fp L 3.02', main_sha256=SHA, hardware_tested=False,
                  bounds=structure(image), scenarios=scenarios(image),
                  dispatcher='explicit stub-to-kernel bridge; exception-mode paths not executed',
                  scheduler='C0000CFC effects mocked; no wall-time bound',
                  completion_trace_mocks=['body return', 'sleep entry', 'IRQ wrapper boundaries'],
                  release_authorized=False)
    if args.self_test:
        report['negative_cases'] = negative_tests(image)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
