"""Offline retained-task integration; real capture, native wrappers and queries.

Reuse the stable fixture's allocator/RTOS scheduling boundary, replacing its
query mocks with actual stubs/kernels. No transport/backend is instantiated.
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
import test_fpl_gyro_task as base

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import fpl_thread_completion_audit as audit

SOURCE = Path(__file__).parent/'asm/fpl_gyro_task_retained.S'
OWNED, SYS, STOP = base.OWNED, base.SYS, base.STOP
OBS, BRIDGE = OWNED+0x100, STOP+0x200
TASK, FLAG = audit.TASK, audit.FLAG
SKIPPED = 0x80000000


def mutation_source():
    """Expand adapter for source mutations of the actual shared algorithm."""
    root = SOURCE.resolve().parents[2]
    return SOURCE.read_text().replace('"../firmware/fpl_302.h"',
        f'"{root}/fp_usb_shell/firmware/fpl_302.h"').replace(
        '#include "../../gyro/retained_task.inc.S"',
        (root/'gyro/retained_task.inc.S').read_text())


def build(source=SOURCE, sleep_reason=0):
    with tempfile.TemporaryDirectory() as directory:
        src = Path(directory)/'retained.S'
        text = mutation_source() if Path(source) == SOURCE else Path(source).read_text()
        src.write_text(f'#define SLEEP_REASON {sleep_reason}\n'+text)
        artifact = base.build(src)
    code, syms, plan, cs = artifact
    assert syms['image_end'] == 0x3000 and syms['capture_image'] == 0x2000
    assert syms['observe_finish'] < 0x2000
    assert not {'join', 'retire'} & syms.keys()
    extents = [(0, 0x3C), (0x100, 0x100), (0x1000, 0x2000),
               (0x4000, base.lat.STATE_ROOM), (0x5000, plan.output_room)]
    for (start, size), (next_start, _) in zip(extents, extents[1:]):
        assert start+size <= next_start
    assert extents[-1][0]+extents[-1][1] <= 0x10000
    return artifact


class Machine(base.Machine):
    def __init__(self, image, artifact, **faults):
        super().__init__(image, artifact, **faults)
        self.m.mem_map(0xC3000000, 0x40000)
        self.word(audit.CALLER+8, 2)
        self.m.mem_write(audit.CALLER+0x23, b'\x01')
        self.word(TASK+8, base.TID)
        self.word(TASK+0xC, SYS+4)
        self.m.mem_write(TASK+0x21, bytes([5, 5, 0]))
        self.word(TASK+0x28, 0xC2F06B48)
        self.word(0xC2F06B48, 1)  # known-once diagnostic fixture, not image bytes
        self.word(FLAG, FLAG)
        self.word(FLAG+4, FLAG)
        self.word(FLAG+0x10, 0x49)
        self.bridges = []
        self.query_calls = []
        self.active_output = None
        self.schedules = 0
        self.capture_calls = 0
        self.native_exit = False
        self.worker_context = None
        self.mutate_on_flag = None
        self.stop_at = None
        self.paused = False
        self.mutable_code = {self.plan.code+self.capture_syms[n]
                             for n in (*base.lat.strict.MUTABLE, 'g_latched_head')}

    def memory(self, m, access, address, size, value, unused):
        if access == uc.UC_MEM_WRITE and self.active_output and OWNED <= address < OWNED+0x10000:
            lo, length = self.active_output
            assert lo <= address and address+size <= lo+length, 'query output extent'
        if access == uc.UC_MEM_WRITE and self.entry_returned:
            if OWNED+0x1000 <= address < OWNED+0x2000:
                raise AssertionError('immutable retained code changed')
            if self.plan.code <= address < self.plan.code+4096:
                assert address in self.mutable_code and size == 4, 'immutable capture bytes changed'
        if access == uc.UC_MEM_WRITE and FLAG+0x14 <= address < FLAG+0x18:
            assert address+size <= FLAG+0x18
            return
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        self.executed.add(pc)
        assert pc not in (base.JOIN, base.DESTROY, base.FREE, audit.WAIT_FLAG,
                          0xC01F56C4, 0xC01F51FC, 0xC0016AA0), 'forbidden lifecycle call'
        if self.context == 'task' and pc == self.stop_at:
            self.paused = True
            self.worker_context = m.context_save()
            m.emu_stop()
            return
        if pc == self.plan.code:
            self.capture_calls += 1
        if pc in (audit.REF_TASK, audit.REF_FLAG, 0xC0016B9C):
            if self.context == 'external':
                assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0, 'query call ABI'
            self.query_calls.append((self.context, pc, self.reg(0)))
            self.active_output = (self.reg(1), 32 if pc == audit.REF_TASK else 12) \
                if pc != 0xC0016B9C else None
            if pc == audit.REF_TASK and self.context == 'task':
                self.word(TASK+0x30, self.wakes)
                self.word(audit.CONTEXT, int(bool(self.faults.get('self_ref_error'))))
            if pc == audit.REF_FLAG and self.mutate_on_flag:
                mutation, self.mutate_on_flag = self.mutate_on_flag, None
                mutation(self)
            if pc == 0xC0016B9C:
                assert self.word(SYS+8) == 0 and self.word(OWNED+0x24) == 1
            return  # execute actual stub, not stable fixture's RTOS mock
        if pc == 0xC00011D0:
            service = self.reg(12)
            assert service in (0x800F0200, 0x80250200, 0x80220200)
            sp, lr = m.reg_read(ar.UC_ARM_REG_SP), m.reg_read(ar.UC_ARM_REG_LR)
            self.bridges.append((sp, lr))
            self.word(sp-8, self.word(self.reg(4)))
            m.reg_write(ar.UC_ARM_REG_SP, sp-8)
            m.reg_write(ar.UC_ARM_REG_LR, BRIDGE)
            m.reg_write(ar.UC_ARM_REG_PC, audit.SERVICES[service])
            return
        if pc == BRIDGE:
            self.active_output = None
            sp, lr = self.bridges.pop()
            m.reg_write(ar.UC_ARM_REG_SP, sp)
            m.reg_write(ar.UC_ARM_REG_PC, lr)
            return
        if pc == 0xC0000CFC:
            self.schedules += 1
            m.reg_write(ar.UC_ARM_REG_PC, m.reg_read(ar.UC_ARM_REG_LR))
            return
        if pc == 0xC036F288:
            self.word(audit.CONTEXT, 0)
        if pc == 0xC01F5580:
            assert self.context == 'task' and self.reg(0) == 0xFFFFFFFF
            if self.wakes:
                self.wakes -= 1
                self.word(TASK+0x30, self.wakes)
                self.m.mem_write(TASK+0x23, b'\x01')
                self.ret()
            else:
                self.m.mem_write(TASK+0x23, b'\x02')
                self.word(TASK+0x2C, 0)
                self.word(TASK+0x30, 0)
                self.parked = True
                self.worker_context = m.context_save()
                m.emu_stop()
            return
        if pc == 0xC01F52D4:
            # Native no-body path after a post-completion wake. Do not emulate
            # self-exit as a returning success, or infer any reclamation.
            self.native_exit = True
            m.emu_stop()
            return
        real = ('ref_task_stub', 'ref_flag_stub', 'set_flag_stub',
                'ref_task_kernel', 'ref_flag_kernel', 'set_flag_kernel',
                'queue_first_id', 'zero_words', 'irq_guards')
        if any(audit.BOUNDS[n][0] <= pc < audit.BOUNDS[n][1] for n in real):
            return
        super().execute(m, pc, size, unused)
        if pc == 0xC00169EC:
            self.word(FLAG+8, base.FLAG if not self.faults.get('flag_create') else 0)
            self.word(FLAG+0x14, self.flag)
        elif pc == 0xC0016A58 and self.task:
            self.m.mem_write(TASK+0x23, b'\x08')
        elif pc == 0xC0016BC0 and self.started:
            self.m.mem_write(TASK+0x23, b'\x01')
        elif pc == 0xC00169C8:
            self.word(FLAG+0x14, self.flag)
        elif pc == 0xC01F5754:
            self.word(TASK+0x30, self.wakes)

    def call(self, name, r0=None):
        self.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
        self.word(audit.CURRENT, audit.CALLER)
        self.word(audit.NEXT, audit.CALLER)
        super().call(name, r0)

    def run_task(self, initial_alignment=0):
        assert self.started and self.task and not self.native_exit
        self.context, self.parked, self.paused = 'task', False, False
        if self.worker_context is None:
            self.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
            self.m.reg_write(ar.UC_ARM_REG_SP, base.TASK_STACK-initial_alignment)
            self.m.reg_write(ar.UC_ARM_REG_R0, SYS)
            self.m.reg_write(ar.UC_ARM_REG_LR, STOP)
            pc = base.WORKER
        else:
            self.m.context_restore(self.worker_context)
            pc = self.m.reg_read(ar.UC_ARM_REG_PC)
        self.word(audit.CURRENT, TASK)
        self.word(audit.NEXT, TASK)
        self.m.emu_start(pc, STOP, count=1000000)
        assert self.parked or self.native_exit or self.paused, 'unbounded worker fixture'

    def observe(self):
        before = len(self.query_calls)
        self.call('observe')
        assert len(self.query_calls)-before <= 4
        assert self.word(OBS+4) == 1
        return self.word(OBS+0xE0)

    def retained_readback(self):
        assert self.word(OWNED+0x24) == 1
        assert self.word(OWNED+8) == OWNED+0x10
        assert self.word(OWNED+0x1C) == OWNED+self.syms['body_entry']
        assert self.word(OWNED+0x20) == self.plan.code
        assert [self.word(OWNED+off) for off in (4, 0x30, 0x34, 0x38)] == \
            [SYS, SYS, base.TID, base.FLAG]
        assert bytes(self.m.mem_read(OWNED+0x1000, 4096)) == self.code[0x1000:0x2000]
        base.lat.verify_code(self.code[0x2000:], bytes(self.m.mem_read(self.plan.code, 4096)),
                             self.capture_syms)
        state = bytes(self.m.mem_read(self.plan.state, base.lat.STATE_ROOM))
        output = bytes(self.m.mem_read(self.plan.output, self.plan.output_room))
        report = base.lat.decode(state, output, 1200)
        assert report['appended_records'] == 950 and report['delay_calls'] == 20
        assert report['proven_valid_records'] == 0
        assert report['records_copy_order'] == [[v, -v, 0, v+1] for v in range(1, 951)]
        assert self.task and self.allocated and not self.deleted and not self.released
        return state, output


class Retained(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = base.MAIN.read_bytes()
        audit.fingerprint(cls.image)
        audit.structure(cls.image)
        cls.artifact = build()

    def machine(self, artifact=None, **faults):
        return Machine(self.image, artifact or self.artifact, **faults)

    def launch(self, m):
        m.call('entry')
        m.poison_staging()
        m.call('activate')

    def test_real_capture_queries_retained_and_initial_flag_not_completion(self):
        for alignment in (0, 4):
            m = self.machine()
            m.call('entry')
            self.assertEqual(m.body_calls, 0)
            m.run_task(alignment)  # park unattached
            self.assertEqual(m.observe(), 7)
            self.assertEqual(m.word(OBS+0x64), 1)  # initial flag trap
            self.assertEqual(m.word(OBS+0x48), 4)
            m.poison_staging()
            m.call('activate')
            self.assertEqual(m.observe(), 7)
            self.assertEqual(m.word(OBS+0x64), 0)
            m.run_task(alignment)
            self.assertEqual(m.observe(), 15)
            for sample in (OBS+0x20, OBS+0x80):
                identity = [SYS, base.TID, OWNED+8, 0, base.FLAG]
                self.assertEqual([m.word(sample+i*4) for i in range(5)], identity)
                self.assertEqual([m.word(sample+0x48+i*4) for i in range(5)], identity)
                self.assertEqual([m.word(sample+0x1C+i*4) for i in range(8)],
                                 [SYS+4, 6, 6, 4, 1, 0, 0, 0])
                self.assertEqual([m.word(sample+0x3C+i*4) for i in range(3)], [0, 0, 1])
            self.assertEqual([pc for context, pc, _ in m.query_calls[-4:]],
                             [audit.REF_TASK, audit.REF_FLAG]*2)
            m.retained_readback()
            self.assertEqual(m.capture_calls, 1)
            self.assertEqual(m.word(SYS+4), OWNED+8)
            for address in (base.CREATE, base.ATTACH, base.WORKER,
                            audit.REF_TASK, audit.REF_FLAG, 0xC000B328, 0xC00040A0,
                            0xC0003C58, 0xC0015808):
                self.assertIn(address, m.executed)

    def test_queued_wakes_repeat_body_but_never_capture_or_results(self):
        m = self.machine()
        self.launch(m)
        m.wakes += 2
        m.run_task()
        self.assertEqual(m.body_calls, 3)
        self.assertEqual(m.capture_calls, 1)
        self.assertEqual(m.word(OWNED+0x2C), 2)
        self.assertEqual(m.observe(), 15)
        before = m.retained_readback()
        m.wakes += 1   # after completion active body is detached: native exit path
        m.run_task()
        self.assertTrue(m.native_exit)
        self.assertEqual(m.capture_calls, 1)
        self.assertEqual(before, m.retained_readback())

    def test_cancelled_core_retains_once_and_native_completion_order(self):
        code_for = base.lat.code_for
        with patch.object(base.lat, 'code_for', side_effect=lambda *a, **kw: code_for(*a, **kw, cancel=True)):
            artifact = build()
        m = self.machine(artifact)
        self.launch(m)
        m.word(m.plan.code+m.capture_syms['g_cancel_request'], 1)
        m.wakes += 2
        m.stop_at = OWNED+m.syms['body_return']
        m.run_task()
        self.assertEqual(m.word(OWNED+0x24), 1)
        self.assertEqual(m.observe(), 7)  # capture DONE is not native completion
        m.stop_at = None
        m.run_task()
        self.assertEqual(m.capture_calls, 1)
        self.assertEqual(m.body_calls, 3)
        self.assertEqual(m.observe(), 15)
        state = bytes(m.m.mem_read(m.plan.state, base.lat.STATE_ROOM))
        output = bytes(m.m.mem_read(m.plan.output, m.plan.output_room))
        report = base.lat.decode(state, output, 1200, cancel=True)
        self.assertEqual((report['status_code'], report['batches']), (101, []))
        actual = bytes(m.m.mem_read(m.plan.code, 4096))
        base.lat.verify_code(artifact[0][0x2000:], actual, m.capture_syms, cancel=True)
        self.assertTrue(m.task and m.allocated and not m.deleted and not m.released)
        m.wakes += 1
        m.run_task()
        self.assertTrue(m.native_exit)
        self.assertEqual(m.capture_calls, 1)
        self.assertEqual(bytes(m.m.mem_read(m.plan.state, base.lat.STATE_ROOM)), state)

    def test_done_before_native_return_and_publication_before_sleep(self):
        m = self.machine()
        self.launch(m)
        m.stop_at = OWNED+m.syms['body_return']
        m.run_task()
        self.assertTrue(m.paused)
        self.assertEqual(m.word(OWNED+0x24), 1)
        self.assertEqual(m.observe(), 7)  # DONE != native completion
        m.stop_at = 0xC036F2C0           # after real set, before next sleep
        m.run_task()
        self.assertEqual(m.observe(), 15)
        self.assertEqual(m.word(OBS+0x48), 2)  # ready, not sleeping
        m.stop_at = None
        m.run_task()
        m.retained_readback()

    def test_self_reference_error_publishes_but_retains(self):
        m = self.machine(self_ref_error=True)
        self.launch(m)
        m.wakes += 1
        m.run_task()
        self.assertTrue(m.native_exit)  # pending wake after error publication
        self.assertEqual(m.word(FLAG+0x14), 1)
        self.assertEqual(m.word(SYS+8), 0)
        self.assertEqual(m.observe(), 15)
        self.assertEqual(m.capture_calls, 1)
        m.retained_readback()

    def test_optional_known_once_sleep_reason(self):
        m = self.machine(build(sleep_reason=1))
        self.launch(m)
        m.run_task()
        self.assertEqual(m.observe(), 31)
        m.word(0xC2F06B48, 99)
        self.assertEqual(m.observe(), 15)
        m.word(0xC2F06B48, 1)
        m.m.mem_write(TASK+0x23, b'\x06')
        self.assertEqual(m.observe(), 15)

    def test_missing_invalid_ids_and_stale_outputs_preserve_signed_status(self):
        for target, value, rc in (('task', 501, -18), ('task', -1, -18),
                                  ('task', 500, -42), ('flag', 301, -18),
                                  ('flag', 300, -42), ('flag', 0, -18)):
            with self.subTest(target=target, value=value):
                m = self.machine()
                self.launch(m)
                m.run_task()
                m.observe()  # stale successful record must be overwritten
                m.word(SYS+(0 if target == 'task' else 12), value)
                self.assertFalse(m.observe() & 8)
                for sample in (OBS+0x20, OBS+0x80):
                    off = 0x14 if target == 'task' else 0x18
                    self.assertEqual(m.word(sample+off), rc & 0xFFFFFFFF)
                    size, off = (32, 0x1C) if target == 'task' else (12, 0x3C)
                    expected = b'\0'*size if target == 'task' and rc == -42 else b'\xA5'*size
                    self.assertEqual(bytes(m.m.mem_read(sample+off, size)), expected)
        m = self.machine()
        self.launch(m)
        m.word(SYS, 0)
        m.observe()
        self.assertEqual(m.word(OBS+0x34), SKIPPED)  # must not query caller id0

    def test_exinf_and_identity_races_are_inconclusive(self):
        for mutation in (lambda m: m.word(TASK+0xC, SYS+8),
                         lambda m: m.word(OWNED+4, 0xDEAD0000),
                         lambda m: m.word(SYS, 8),
                         lambda m: m.word(SYS+12, 12),
                         lambda m: m.word(SYS+8, OWNED+8),
                         lambda m: m.word(SYS+4, OWNED+12)):
            m = self.machine()
            self.launch(m)
            m.run_task()
            m.mutate_on_flag = mutation
            self.assertFalse(m.observe() & 8)
            self.assertTrue(m.allocated and m.task)

    def test_create_attach_assertions_and_start_failure_are_retained(self):
        for fault in ('allocation', 'flag_create', 'task_create'):
            m = self.machine(**{fault: True})
            with self.assertRaises(base.NativeAssertion):
                m.call('entry')
            self.assertEqual(m.word(OWNED), 1)
            m.call('entry')
            self.assertEqual(m.events.count(base.CREATE), 1)
            self.assertEqual(m.observe(), 0)
            self.assertEqual(m.word(OBS+0x34), SKIPPED)
        for fault in ('attach', 'task_start'):
            m = self.machine(**{fault: True})
            m.call('entry')
            if fault == 'task_start':
                self.assertEqual(m.observe(), 7)
                self.assertEqual(m.word(OBS+0x48), 16)
            with self.assertRaises(base.NativeAssertion):
                m.call('activate')
            self.assertEqual(m.word(OWNED), 3)
            m.call('activate')
            self.assertEqual(m.events.count(base.ATTACH), 1)
            self.assertFalse(m.observe() & 8)

    def test_duplicate_commands_leave_results_and_immutable_extent_intact(self):
        m = self.machine()
        m.call('entry')
        m.call('entry')
        m.poison_staging()
        m.call('activate')
        m.call('activate')
        m.run_task()
        before = m.retained_readback()
        for _ in range(3):
            m.call('activate')
            self.assertEqual(m.observe(), 15)
        self.assertEqual(before, m.retained_readback())
        self.assertEqual(m.events.count(base.CREATE), 1)
        self.assertEqual(m.events.count(base.ATTACH), 1)
        self.assertEqual(m.word(OBS), 3)

    def test_changed_holder_before_activation_blocks_permanently(self):
        m = self.machine()
        m.call('entry')
        m.poison_staging()
        m.word(OWNED+4, 0xDEAD0000)
        m.call('activate')
        self.assertEqual(m.word(OWNED), 3)
        self.assertEqual(m.observe(), 0)
        self.assertEqual(m.word(OBS+0x34), SKIPPED)
        m.word(OWNED+4, SYS)
        m.call('activate')
        self.assertNotIn(base.ATTACH, m.events)
        self.assertTrue(m.allocated and m.task)

    def test_scheduler_boundary_is_not_a_deadline(self):
        m = self.machine()
        self.launch(m)
        m.run_task()
        m.mutate_on_flag = lambda m: m.word(audit.NEXT, TASK)
        self.assertEqual(m.observe(), 15)
        self.assertGreater(m.schedules, 0)

    def test_mutations_staging_object_stack_oneshot_and_exinf(self):
        mutations = (
            ('add r1, r4, #BODY', 'ldr r1, [r4, #BODY]', 'object'),
            ('ldr r0, =OWNED + body_entry', 'ldr r0, =0x45000000 + body_entry', 'staging'),
            ('bic sp, sp, #7', 'nop', 'stack'),
            ('bne body_repeat', 'nop', 'oneshot'),
            ('add r0, r0, #4\n    ldr r1, [r5, #0x3C]',
             'add r0, r0, #8\n    ldr r1, [r5, #0x3C]', 'exinf'),
        )
        with tempfile.TemporaryDirectory() as directory:
            for old, new, kind in mutations:
                with self.subTest(kind=kind):
                    text = mutation_source()
                    assert old in text
                    src = Path(directory)/'mutant.S'
                    src.write_text(text.replace(old, new))
                    m = self.machine(build(src))
                    expected = {'object': 'body object address', 'staging': 'staging',
                                'stack': 'capture call ABI', 'oneshot': 'one-shot guard failed',
                                'exinf': 'identity oracle failed'}[kind]
                    with self.assertRaisesRegex(AssertionError, expected):
                        self.launch(m)
                        m.wakes += 1
                        m.run_task()
                        assert m.capture_calls == 1, 'one-shot guard failed'
                        assert m.observe() == 15, 'identity oracle failed'

    def test_readback_rejects_changed_static_bytes_and_runtime_references(self):
        for offset in (8, 0x1C, 0x20, 0x1000, 0x2000,
                       0x2000+self.artifact[3]['runtime_refs']):
            m = self.machine()
            self.launch(m)
            m.run_task()
            m.word(OWNED+offset, m.word(OWNED+offset)^4)
            with self.assertRaises((AssertionError, RuntimeError)):
                m.retained_readback()

    def test_native_lifecycle_mutations_are_trapped(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'forbidden.S'
            text = mutation_source()
            for address in (base.JOIN, base.DESTROY, base.FREE):
                source.write_text(text.replace('ldr ip, [r0, #CAPTURE]', f'ldr ip, ={address}'))
                m = self.machine(build(source))
                with self.assertRaisesRegex(AssertionError, 'forbidden lifecycle'):
                    self.launch(m)
                    m.run_task()


if __name__ == '__main__':
    unittest.main()
