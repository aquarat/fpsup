"""Disposable offline task-lifetime experiment, actual fp L wrapper instructions.

FPL_MAIN may name the official decompressed MAIN. Missing/wrong firmware fails
the tests, never silently substitutes a modeled wrapper. Only RTOS, allocator
backend, assertion and libc/cache boundaries listed in Machine are mocked.
"""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest

import unicorn as uc
from unicorn import arm_const as ar
import fpl_gyro_latched as lat

SOURCE = Path(__file__).parent/'asm/fpl_gyro_task_prototype.S'
MAIN = Path(os.environ.get('FPL_MAIN', Path.home()/
    '.local/share/fpsup/firmware/FPL_V302/MAIN.bin'))
OWNED, STAGING, STOP, SYS = 0x46000000, 0x45000000, 0x48000000, 0x49000000
HOST_STACK, TASK_STACK = 0x4B010000, 0x4C010000
ALLOC, FREE = STOP+0x100, STOP+0x104
P, R, GLOBAL = lat.P, lat.R, 0xC31E23CC
TID, FLAG = 7, 11
CREATE, ATTACH, JOIN, DESTROY = 0xC036E320, 0xC036E3D0, 0xC036E410, 0xC036E380
WORKER = 0xC036F200
# Audited executable bodies, including full join (the old audit bound was a prefix).
NATIVE = [(0xC036E0D0, 0xC036E450), (0xC036E5A8, 0xC036E660),
          (0xC036E6A0, 0xC036E6F0), (0xC036F0B0, 0xC036F1AC),
          (0xC036F200, 0xC036F2D0)]


class NativeAssertion(RuntimeError):
    pass


class WaitBlocked(RuntimeError):
    pass


def build(source=SOURCE):
    plan = lat.strict.Layout(OWNED+0x2000, OWNED+0x4000, OWNED+0x5000, 11264)
    capture, capture_syms = lat.code_for(plan, 1200, runtime=True)
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory)/'capture.bin'
        binary.write_bytes(capture)
        defs = [f'OWNED={OWNED}', f'CAPTURE_FILE="{binary}"']
        code = lat.armasm.assemble(source, defs)
        syms = lat.armasm.symbols(source, defs)
    assert len(code) == 0x3000 and syms['resident_image'] == 0x1000
    assert code[0x2000:] == capture
    return code, syms, plan, capture_syms


class Machine:
    def __init__(self, image, artifact, **faults):
        self.code, self.syms, self.plan, self.capture_syms = artifact
        self.faults = faults
        self.m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
        for address, size in ((0xC0000000, (len(image)+4095)&~4095),
                              (0xC2F2F000, 4096), (GLOBAL & ~4095, 4096),
                              (STAGING, 0x10000), (OWNED, 0x10000), (SYS, 0x10000),
                              (STOP, 4096), (HOST_STACK-0x10000, 0x10000),
                              (TASK_STACK-0x10000, 0x10000), (0x2E000000, 0x10000)):
            self.m.mem_map(address, size)
        self.m.mem_write(0xC0000000, image)
        self.m.mem_write(STAGING, self.code)
        self.m.mem_write(self.plan.output, lat.strict.SENTINEL*self.plan.output_room)
        # Synthetic native allocator singleton and vtable; real allocation wrapper
        # calls these mocked allocation/free backend slots, not a fake XT_CREATE.
        self.word(0xC2F2F298, SYS+0x100)
        self.word(SYS+0x100, SYS+0x200)
        self.word(SYS+0x20C, ALLOC)
        self.word(SYS+0x210, FREE)
        self.word(GLOBAL, P)
        self.word(P+0x60, R)
        self.word(R, R+8)
        self.current = 0
        self.generation = 0
        self.events = []
        self.flag = 0
        self.task = False
        self.started = False
        self.terminated = False
        self.deleted = False
        self.allocated = False
        self.wakes = 0
        self.body_calls = 0
        self.context = 'external'
        self.entry_returned = False
        self.staging_poisoned = False
        self.released = False
        self.parked = False
        self.cache = []
        self.executed = set()
        self.m.hook_add(uc.UC_HOOK_CODE, self.execute)
        self.m.hook_add(uc.UC_HOOK_MEM_WRITE | uc.UC_HOOK_MEM_READ, self.memory)

    def word(self, address, value=None):
        if value is None:
            return struct.unpack('<I', self.m.mem_read(address, 4))[0]
        self.m.mem_write(address, struct.pack('<I', value & 0xffffffff))

    def reg(self, n):
        return self.m.reg_read(getattr(ar, 'UC_ARM_REG_R'+str(n)))

    def ret(self, value=0):
        for n in (0, 1, 2, 3, 12):
            self.m.reg_write(getattr(ar, 'UC_ARM_REG_R'+str(n)), 0xBAD00000+n)
        self.m.reg_write(ar.UC_ARM_REG_R0, value & 0xffffffff)
        self.m.reg_write(ar.UC_ARM_REG_PC, self.m.reg_read(ar.UC_ARM_REG_LR))

    def memory(self, m, access, address, size, value, unused):
        if self.staging_poisoned:
            assert not STAGING <= address < STAGING+0x10000, 'staging reference survived'
        if self.released:
            assert not OWNED <= address < OWNED+0x10000, 'released reference survived'
        if access == uc.UC_MEM_WRITE:
            ranges = [(OWNED, OWNED+0x10000), (SYS, SYS+0x10000),
                      (HOST_STACK-0x10000, HOST_STACK), (TASK_STACK-0x10000, TASK_STACK)]
            assert any(lo <= address and address+size <= hi for lo, hi in ranges), 'unowned store'

    def execute(self, m, pc, size, unused):
        self.executed.add(pc)
        if self.staging_poisoned:
            assert not STAGING <= pc < STAGING+0x10000, 'executed freed staging'
        if self.released:
            assert not OWNED <= pc < OWNED+0x10000, 'executed released payload'
        if pc in (CREATE, ATTACH, JOIN, DESTROY):
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0, 'prototype call ABI'
            assert self.context == 'external', 'lifecycle called by worker'
            self.events.append(pc)
            if pc == ATTACH:
                assert self.entry_returned, 'attached before launcher returned'
                assert self.reg(1) == OWNED+8, 'body object address, not vtable value'
            if pc == DESTROY:
                assert self.word(OWNED) == 6 and self.word(OWNED+0x2C) == 1
        if pc == OWNED+self.syms['body_entry']:
            assert self.context == 'task' and self.entry_returned
            assert self.reg(0) == OWNED+8
            self.body_calls += 1
        if pc == self.plan.code:
            assert self.context == 'task' and self.entry_returned
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0, 'capture call ABI'
        if pc in (0xC000E91C, 0xC000EABC):
            self.cache.append(pc)
            self.ret()
        elif pc == ALLOC:
            assert self.reg(1) == 0x14
            assert self.cache == [0xC000E91C, 0xC000EABC]
            self.allocated = not self.faults.get('allocation')
            self.ret(SYS if self.allocated else 0)
        elif pc == FREE:
            assert self.reg(1) == SYS and self.deleted and not self.task
            self.allocated = False
            self.ret()
        elif pc in (0xC0011100, 0xC0011130):
            raise NativeAssertion(f'native assertion at {pc:08x}, line {self.reg(1):x}')
        elif pc == 0xC0015058:         # memset
            self.m.mem_write(self.reg(0), bytes([self.reg(1)&255])*self.reg(2))
            self.ret(self.reg(0))
        elif pc == 0xC0013CF8:         # bounded name copy
            assert OWNED <= self.reg(1) < OWNED+0x3000
            self.m.mem_write(self.reg(0), bytes(self.m.mem_read(self.reg(1), self.reg(2))))
            self.ret(self.reg(0))
        elif pc == 0xC01F204C:         # special-name comparison: ordinary name
            self.ret(1)
        elif pc == 0xC00169EC:         # create completion flag, real descriptor
            assert self.word(self.reg(0)+4) == 0x49
            self.flag = self.word(self.reg(0)+8)
            self.ret(-17 if self.faults.get('flag_create') else FLAG)
        elif pc == 0xC0016A58:         # create task, real native descriptor
            at = self.reg(0)
            assert [self.word(at+i) for i in (0, 4, 8, 12, 16)] == [SYS+4, 0x41, WORKER, 6, 0x2000]
            self.task = not self.faults.get('task_create')
            self.ret(TID if self.task else -17)
        elif pc == 0xC0016BC0:         # start task
            assert self.reg(0) == TID and self.reg(1) == SYS
            assert self.word(SYS+8) == 0, 'new worker already has a body'
            self.started = not self.faults.get('task_start')
            self.ret(0 if self.started else -18)
        elif pc == 0xC00169C8:         # clear flag: AND, not complement
            assert self.reg(0) == FLAG and self.reg(1) == 0xfffffffe
            self.flag &= self.reg(1)
            self.ret()
        elif pc == 0xC01F5754:         # wake
            assert self.reg(0) == TID
            rc = -18 if self.faults.get('attach') or not self.started else 0
            if rc == 0:
                self.wakes += 1
            self.ret(rc)
        elif pc == 0xC01F5580:         # sleep forever; mocked scheduling boundary
            assert self.reg(0) == 0xffffffff and self.context == 'task'
            if self.wakes:
                self.wakes -= 1
                self.ret()
            else:
                self.parked = True
                self.m.emu_stop()
        elif pc == 0xC0016C08:         # wait completion flag: native fifth argument
            assert self.reg(0) == FLAG and self.reg(1) == 1 and self.reg(2) == 0
            assert self.word(m.reg_read(ar.UC_ARM_REG_SP)) == 0xffffffff
            if 'join_rc' in self.faults:
                self.ret(self.faults['join_rc'])
            elif self.flag & 1:
                self.word(self.reg(3), self.flag)
                self.ret()
            else:
                raise WaitBlocked('native join waits forever; retain all storage')
        elif pc == 0xC0016B9C:         # pool signals completion only AFTER body
            assert self.context == 'task' and self.word(OWNED+0x24) == 1
            assert self.word(SYS+8) == 0
            self.flag |= self.reg(1)
            self.ret()
        elif pc == 0xC01F54CC:         # ref_tsk: no queued wake after single body
            self.word(self.reg(1)+0x18, 0)
            self.ret()
        elif pc in (0xC001CCE0, 0xC001CD18):  # interrupt guard boundaries mocked
            if pc == 0xC001CCE0:
                self.word(self.reg(0), 0)
            self.ret()
        elif pc == 0xC01F56C4:         # terminate task
            assert self.context == 'external'
            self.terminated = not self.faults.get('terminate')
            self.ret(0 if self.terminated else -18)
        elif pc == 0xC01F51FC:         # delete task: refuse a still-live task
            assert self.context == 'external'
            if self.terminated and not self.faults.get('delete'):
                self.task = False
                self.deleted = True
                self.wakes = 0
                self.ret()
            else:
                self.ret(-41)
        elif pc == 0xC0016AA0:         # delete flag
            assert self.deleted
            self.ret(-18 if self.faults.get('flag_delete') else 0)
        elif pc == 0xC01F5244:         # actual capture's finite delay, produce data
            assert self.context == 'task' and self.reg(0) == 20
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            for _ in range(50):
                self.current = (self.current+1) % 600
                self.generation += 1
                v = self.generation
                self.m.mem_write(R+4+self.current*8, struct.pack('<hhhh', v, -v, 0, v+1))
                self.word(R, R+8*(self.current+1))
            self.ret()
        elif pc == 0xC01F52D4:
            raise AssertionError('unexpected native self-exit')
        else:
            assert (any(lo <= pc < hi for lo, hi in NATIVE) or
                    STAGING <= pc < STAGING+0x1000 or
                    OWNED+0x1000 <= pc < OWNED+0x3000), f'unmocked call {pc:08x}'

    def call(self, name, r0=None):
        self.context = 'external'
        address = (STAGING if name == 'entry' else OWNED)+self.syms[name]
        saved = {r: 0xABC00000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
        for r, value in saved.items():
            self.m.reg_write(r, value)
        self.m.reg_write(ar.UC_ARM_REG_SP, HOST_STACK)
        self.m.reg_write(ar.UC_ARM_REG_LR, STOP)
        self.m.reg_write(ar.UC_ARM_REG_R0, address if r0 is None else r0)
        self.m.emu_start(address, STOP, count=1000000)
        assert self.m.reg_read(ar.UC_ARM_REG_PC) == STOP
        assert self.m.reg_read(ar.UC_ARM_REG_SP) == HOST_STACK
        assert all(self.m.reg_read(r) == v for r, v in saved.items()), 'callee saved ABI'
        if name == 'entry':
            self.entry_returned = True

    def poison_staging(self):
        assert self.entry_returned
        self.m.mem_write(STAGING, b'\xFE'*0x10000)
        self.staging_poisoned = True

    def run_task(self, initial_alignment=0):
        assert self.started and self.task
        self.context = 'task'
        self.parked = False
        self.m.reg_write(ar.UC_ARM_REG_SP, TASK_STACK-initial_alignment)
        self.m.reg_write(ar.UC_ARM_REG_R0, SYS)
        self.m.reg_write(ar.UC_ARM_REG_LR, STOP)
        self.m.emu_start(WORKER, STOP, count=1000000)
        assert self.parked, 'pool did not park after finite body'

    def readback(self):
        assert self.word(OWNED) == 4
        code = bytes(self.m.mem_read(self.plan.code, lat.CODE_ROOM))
        expected = self.code[0x2000:0x3000]
        lat.verify_code(expected, code, self.capture_syms)
        state = bytes(self.m.mem_read(self.plan.state, lat.STATE_ROOM))
        output = bytes(self.m.mem_read(self.plan.output, self.plan.output_room))
        report = lat.decode(state, output, 1200)
        assert report['proven_valid_records'] == 0
        assert report['appended_records'] == 950
        assert report['records_copy_order'] == [[v, -v, 0, v+1] for v in range(1, 951)]
        return report

    def release(self):
        assert self.context == 'external' and self.m.reg_read(ar.UC_ARM_REG_PC) == STOP
        assert self.word(OWNED+0x30) == 1 and self.deleted and not self.allocated
        assert self.word(OWNED+4) == 0 and self.word(OWNED+8) == 0
        assert self.word(OWNED+0x1C) == 0 and self.word(OWNED+0x20) == 0
        self.m.mem_unmap(OWNED, 0x10000)
        self.released = True


class Lifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not MAIN.is_file():
            raise FileNotFoundError('Set FPL_MAIN to the external official fp L 3.02 MAIN image')
        cls.image = MAIN.read_bytes()
        if len(cls.image) != 49310208 or hashlib.sha256(cls.image).hexdigest() != \
                'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9':
            raise ValueError('not the audited official fp L 3.02 MAIN')
        cls.artifact = build()

    def machine(self, **faults):
        return Machine(self.image, self.artifact, **faults)

    def completed(self, **faults):
        m = self.machine(**faults)
        m.call('entry')
        m.poison_staging()
        m.call('activate')
        m.run_task()
        return m

    def test_launcher_returns_parked_then_finite_body_join_readback_retire(self):
        for alignment in (0, 4):
            m = self.machine()
            m.call('entry')
            self.assertEqual(m.word(OWNED), 2)
            self.assertEqual(m.body_calls, 0)
            m.run_task(alignment)     # native worker sleeps, no callback attached
            self.assertEqual(m.body_calls, 0)
            m.poison_staging()
            m.call('activate')
            m.run_task(alignment)
            self.assertEqual(m.body_calls, 1)
            self.assertEqual(m.word(OWNED), 3)  # body done is not joined
            m.call('retire', 1)
            self.assertEqual(m.word(OWNED+0x30), 0)
            m.call('join')
            self.assertEqual(m.word(OWNED), 4)
            report = m.readback()
            self.assertEqual(report['delay_calls'], 20)
            m.call('retire', 0)       # no readback acknowledgement
            self.assertTrue(m.task)
            m.call('retire', 1)
            m.call('retire', 1)       # no second destructor/free
            m.release()
            for address in (CREATE, ATTACH, JOIN, DESTROY, 0xC036E0D0,
                            0xC036E6A0, 0xC036F0B0, WORKER, 0xC036E620, 0xC036E240):
                self.assertIn(address, m.executed)

    def test_duplicate_launch_and_attach_do_not_reinitialize_running_state(self):
        m = self.machine()
        m.call('entry')
        before = bytes(m.m.mem_read(OWNED, 0x10000))
        m.call('entry')
        self.assertEqual(m.events.count(CREATE), 1)
        self.assertEqual(bytes(m.m.mem_read(OWNED, 0x10000)), before)
        m.poison_staging()
        m.call('activate')
        m.call('activate')
        self.assertEqual(m.events.count(ATTACH), 1)
        m.run_task()
        m.call('join')
        m.readback()

    def test_native_allocation_and_create_failures_are_not_success_statuses(self):
        for fault in ('allocation', 'flag_create', 'task_create'):
            m = self.machine(**{fault: True})
            with self.subTest(fault=fault), self.assertRaises(NativeAssertion):
                m.call('entry')
            self.assertEqual(m.word(OWNED), 1)
            self.assertEqual(m.word(OWNED+0x30), 0)
            self.assertEqual(m.body_calls, 0)
            m.call('entry')           # uncertain prior native call: no retry
            self.assertEqual(m.events.count(CREATE), 1)

    def test_attach_refusal_and_ignored_start_error_retain_everything(self):
        for fault in ('attach', 'task_start'):
            m = self.machine(**{fault: True})
            m.call('entry')
            m.poison_staging()
            with self.subTest(fault=fault), self.assertRaises(NativeAssertion):
                m.call('activate')
            self.assertEqual(m.word(OWNED), 3)
            self.assertTrue(m.allocated)
            m.call('retire', 1)
            self.assertEqual(m.word(OWNED+0x30), 0)

    def test_join_wait_and_uncertain_error_never_release(self):
        m = self.machine()
        m.call('entry')
        m.poison_staging()
        m.call('activate')
        with self.assertRaises(WaitBlocked):
            m.call('join')
        self.assertEqual(m.word(OWNED+0x30), 0)
        m = self.completed(join_rc=-50)
        m.call('join')
        self.assertEqual(m.word(OWNED), 3)
        self.assertEqual(m.word(OWNED+0x28), 0xffffffce)
        m.call('retire', 1)
        self.assertTrue(m.allocated)
        self.assertNotIn(DESTROY, m.events)
        m = self.machine(join_rc=0)   # even a reported success is insufficient
        m.call('entry')
        m.poison_staging()
        m.call('activate')
        m.call('join')               # body has not run/returned
        m.call('retire', 1)
        self.assertEqual(m.word(OWNED), 3)
        self.assertNotIn(DESTROY, m.events)

    def test_destroy_failure_retains_result_allocation(self):
        for fault in ('terminate', 'delete', 'flag_delete'):
            m = self.completed(**{fault: True})
            m.call('join')
            m.readback()
            with self.subTest(fault=fault), self.assertRaises(NativeAssertion):
                m.call('retire', 1)
            self.assertEqual(m.word(OWNED+0x30), 0)
            self.assertTrue(m.allocated)
            self.assertEqual(m.word(OWNED), 6)
            m.call('retire', 1)
            self.assertEqual(m.events.count(DESTROY), 1)

    def test_failed_readback_retains_joined_result_and_worker(self):
        m = self.completed()
        m.call('join')
        m.word(m.plan.state+36, 1)    # forbidden proven-valid claim
        with self.assertRaises(RuntimeError):
            m.readback()
        self.assertEqual(m.word(OWNED), 4)
        self.assertEqual(m.word(OWNED+0x2C), 0)
        self.assertTrue(m.task and m.allocated)
        self.assertNotIn(DESTROY, m.events)

    def test_mutations_expose_staging_object_and_stack_ownership_errors(self):
        original = SOURCE.read_text()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'broken.S'
            for old, new, expected in (
                ('add r1, r4, #BODY', 'ldr r1, [r4, #BODY]', 'body object address'),
                ('ldr r0, =OWNED + body_entry', 'ldr r0, =STAGING + body_entry', 'staging'),
                ('bic sp, sp, #7', 'nop', 'capture call ABI')):
                text = original.replace(old, new)
                if 'STAGING' in new:
                    text = '#define STAGING 0x45000000\n'+text
                source.write_text(text)
                m = Machine(self.image, build(source))
                m.call('entry')
                m.poison_staging()
                with self.subTest(mutation=old), self.assertRaisesRegex(AssertionError, expected):
                    m.call('activate')
                    m.run_task()


if __name__ == '__main__':
    unittest.main()
