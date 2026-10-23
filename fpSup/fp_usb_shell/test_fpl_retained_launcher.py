"""Offline camera-side launcher: actual USER allocator and native task kernels.

The synthetic USER list first reserves loader staging using real H_GET. Only
telemetry/static guards, native task backend/scheduling and cache effects are
mocked. No transport or physical camera is opened.
"""
from contextlib import contextmanager
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
import fpl_retained_launcher as launch
import test_fpl_gyro_task_retained as retained
import fpl_allocator_audit as allocator

base = retained.base
GET, ADDR = 0xC001D740, 0xC001D7F0
STAGE_SIZE = 0x8000
OWNERS = (0x44500000, 0x45A00000)


class LostExecution(RuntimeError):
    pass


class Machine(retained.Machine):
    def __init__(self, image, built, heap, stage, owner, *, malformed=None, lost=None, **faults):
        self.launcher, self.ls, self.artifact = built
        self.stage, self.owner = stage, owner
        self.fullcache, self.get_calls, self.launch_writes = [], 0, []
        self.malformed, self.lost = malformed, lost
        self.heap_start = owner-0x10000
        self.wrapper_stage = stage+self.ls['embedded_image']
        initialized = launch.runtime.initialize(self.artifact, self.wrapper_stage, owner)
        _, ws, cs = self.artifact
        plan = base.lat.strict.Layout(owner+0x2000, owner+0x4000, owner+0x5000, 11264)
        constructor = uc.Uc
        def cortex(*args, **kwargs):
            machine = constructor(*args, **kwargs)
            machine.ctl_set_cpu_model(ar.UC_CPU_ARM_CORTEX_A15)
            return machine
        with patch.object(uc, 'Uc', side_effect=cortex):
            super().__init__(image, (initialized, ws, plan, cs), **faults)
        self.m.mem_map(owner+0x10000, 0x10000)
        self.m.mem_map(0xC3070000, 0x10000)
        self.m.mem_write(self.heap_start, bytes(heap.mu.mem_read(self.heap_start, 0x30000)))
        self.m.mem_write(0xC3070000, bytes(heap.mu.mem_read(0xC3070000, 0x10000)))
        self.m.mem_write(owner, b'\xCD'*0x10000)  # allocator does NOT zero payload
        self.m.mem_write(stage, self.launcher)
        self.m.mem_write(stage+len(self.launcher), b'\xD3'*(STAGE_SIZE-len(self.launcher)))

    def allocator_pc(self, pc):
        return (0xC0010310 <= pc < 0xC0010D68 or
                0xC001CCE0 <= pc < 0xC001D800 or 0xC000EC14 <= pc < 0xC000EC3C)

    def memory(self, m, access, address, size, value, unused):
        if self.staging_poisoned:
            assert not self.stage <= address < self.stage+STAGE_SIZE, 'full staging reference survived'
        pc = m.reg_read(ar.UC_ARM_REG_PC)
        if self.allocator_pc(pc):
            if access == uc.UC_MEM_WRITE:
                ranges = ((self.heap_start, self.owner+0x20000), (0xC3070000, 0xC3080000),
                          (base.HOST_STACK-0x10000, base.HOST_STACK),
                          (base.TASK_STACK-0x10000, base.TASK_STACK))
                assert any(lo <= address and address+size <= hi for lo, hi in ranges), f'allocator write extent {address:x} at {pc:x}'
            return
        if access == uc.UC_MEM_WRITE:
            if self.stage <= address < self.stage+STAGE_SIZE:
                allowed = [(self.stage+self.ls['result'], 32)]
                allowed += [(self.wrapper_stage+off, 4)
                            for off in launch.runtime.reference_offsets(*self.artifact[1:])]
                assert any(lo <= address and address+size <= lo+n for lo, n in allowed), 'staging immutable write'
                return
            if self.owner <= address < self.owner+0x10000:
                self.launch_writes.append((address, size))
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        assert pc != 0xC001D7A0, 'USER free forbidden'
        if pc in (0xC000E91C, 0xC000EABC):
            self.fullcache.append(pc)
        if pc == GET:
            self.get_calls += 1
            assert self.reg(1) == 0 and self.reg(2) == self.reg(3) == 0x10000
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            assert self.word(self.stage+self.ls['result']) == 1, 'allocation before intent'
        if pc == ADDR:
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
        if pc == self.stage+self.ls['validate_descriptor'] and self.malformed:
            values = self.malformed
            for i, v in enumerate(values):
                self.word(self.stage+self.ls['result']+4+4*i, v)
        if self.lost == pc:
            raise LostExecution('lost execution')
        if self.stage <= pc < self.wrapper_stage:
            assert not self.staging_poisoned
            return
        if self.wrapper_stage <= pc < self.wrapper_stage+0x1000:
            assert not self.staging_poisoned
            if pc == self.wrapper_stage:
                assert self.reg(0) == pc, 'runtime entry ABI'
                assert self.fullcache == [0xC000E91C, 0xC000EABC], 'unpublished runtime references'
                assert bytes(m.mem_read(self.owner+0x400, 32)) == bytes(m.mem_read(self.stage+self.ls['result'], 32))
                assert self.word(self.owner+0x400) == 5, 'native entry before retained intent'
                self.cache = []  # existing native oracle checks resident D/I pair
            return
        if pc in (0xC0013090, 0xC00131E4, 0xC001E328, 0xC001E3C8):
            self.ret(1 if pc == 0xC0013090 else 0)
            return
        if self.allocator_pc(pc):
            return  # actual firmware allocator/IRQ guard instructions execute
        super().execute(m, pc, size, unused)

    def run_launcher(self, *, alignment=0, r0=None):
        self.context = 'external'
        saved = {r: 0xABC00000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
        for r, v in saved.items():
            self.m.reg_write(r, v)
        sp = base.HOST_STACK-alignment
        self.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
        self.m.reg_write(ar.UC_ARM_REG_SP, sp)
        self.m.reg_write(ar.UC_ARM_REG_LR, base.STOP)
        self.m.reg_write(ar.UC_ARM_REG_R0, self.stage if r0 is None else r0)
        self.m.emu_start(self.stage, base.STOP, count=2000000)
        assert self.m.reg_read(ar.UC_ARM_REG_PC) == base.STOP
        assert self.m.reg_read(ar.UC_ARM_REG_SP) == sp
        assert all(self.m.reg_read(r) == v for r, v in saved.items()), 'callee saves'
        self.entry_returned = True

    def poison_staging(self):
        assert self.entry_returned
        self.m.mem_write(self.stage, b'\xFE'*STAGE_SIZE)
        self.staging_poisoned = True


class Launcher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = base.MAIN.read_bytes()
        retained.audit.fingerprint(cls.image)
        cls.built = launch.build()

    @contextmanager
    def machine(self, owner=OWNERS[0], *, refusal=False, built=None, **faults):
        a = allocator.Machine(self.image)
        heap_start, heap_size = owner-0x10000, 0x30000
        a.mu.mem_map(heap_start, heap_size)
        a.stubs.update({0xC0013090: 1, 0xC00131E4: 0, 0xC001E328: 0, 0xC001E3C8: 0})
        a.put(0xC30739D8, allocator.CHANNEL)
        a.put(0xC3073A10, allocator.CHANNEL)
        a.put(allocator.CHANNEL, 0, 0)
        a.call(0xC0010310, allocator.CHANNEL+8)
        a.call(0xC00103A8, allocator.CHANNEL+8, heap_start)
        for address in (heap_start, heap_start+(0x10000 if refusal else heap_size)-0x40):
            a.put(allocator.DESC+0x100, address, 0x40)
            a.call(0xC00103E8, allocator.CHANNEL+8, allocator.DESC+0x100)
        # Model the loader's still-live staging allocation on this SAME list.
        a.call(GET, allocator.DESC, 0, STAGE_SIZE, 0)
        stage = a.call(ADDR, allocator.DESC)
        assert stage == heap_start+0x80
        with patch.multiple(base, STAGING=heap_start, OWNED=owner), \
                patch.multiple(retained, OWNED=owner, OBS=owner+0x100):
            yield Machine(self.image, built or self.built, a, stage, owner, **faults)

    def test_same_blob_real_allocator_two_placements_unattached_then_poison_and_capture(self):
        for owner in OWNERS:
            for alignment in (0, 4):
                with self.subTest(owner=hex(owner), alignment=alignment), self.machine(owner) as m:
                    m.run_launcher(alignment=alignment)
                    self.assertEqual(m.get_calls, 1)
                    self.assertEqual(m.events.count(base.CREATE), 1)
                    self.assertNotIn(base.ATTACH, m.events)
                    self.assertEqual(m.capture_calls, 0)
                    self.assertEqual(m.fullcache, [0xC000E91C, 0xC000EABC]*2)
                    expected = [6, owner, owner, 0, owner, 0x10000, 2, 0]
                    self.assertEqual([m.word(owner+0x400+i*4) for i in range(8)], expected)
                    actual = bytes(m.m.mem_read(m.stage, len(m.launcher)))
                    launch.verify_staging(m.launcher, actual, m.ls, m.artifact)
                    self.assertEqual(actual[m.ls['embedded_image']:], m.code)
                    self.assertEqual(bytes(m.m.mem_read(m.stage+len(m.launcher), STAGE_SIZE-len(m.launcher))),
                                     b'\xD3'*(STAGE_SIZE-len(m.launcher)))
                    self.assertEqual(bytes(m.m.mem_read(owner+0x5000, 11264)), b'\xA5'*11264)
                    for lo, hi in ((0x3C, 0x100), (0x200, 0x400), (0x420, 0x1000),
                                   (0x3000, 0x5000), (0x7C00, 0x10000)):
                        self.assertEqual(bytes(m.m.mem_read(owner+lo, hi-lo)), bytes(hi-lo))
                    m.poison_staging()
                    self.assertEqual(m.observe(), 7)
                    m.call('activate'); m.run_task()
                    self.assertEqual(m.observe(), 15)
                    m.retained_readback()

    def test_real_allocation_refusal_returns_without_owned_writes_or_native_create(self):
        with self.machine(refusal=True) as m:
            m.run_launcher()
            self.assertEqual(m.word(m.stage+m.ls['result']), 3)
            self.assertEqual(m.get_calls, 1)
            self.assertFalse(m.launch_writes or m.events or m.cache)

    def test_malformed_descriptors_bounds_overflow_and_overlap_refuse(self):
        owner = OWNERS[0]
        cases = [(owner, owner, 1, owner, 0x10000), (owner, owner, 0, owner+4, 0x10000),
                 (owner, owner, 0, owner, 0xFFFF), (0, owner, 0, owner, 0x10000)]
        for address in (owner+64, 0x443F0000, 0x46400000, 0xFFFF0000, owner-0x10000):
            cases.append((address, address, 0, address, 0x10000))
        for values in cases:
            with self.subTest(values=values), self.machine(malformed=values) as m:
                m.run_launcher()
                self.assertEqual(m.word(m.stage+m.ls['result']), 4)
                self.assertFalse(m.launch_writes or m.events or m.cache)

    def test_input_references_must_be_zero_and_bad_argv_cannot_allocate(self):
        for offset in launch.runtime.reference_offsets(*self.built[2][1:]):
            with self.machine() as m:
                m.word(m.wrapper_stage+offset, 1)
                m.run_launcher()
                self.assertEqual(m.word(m.stage+m.ls['result']), 4)
                self.assertEqual(m.get_calls, 0)
                self.assertFalse(m.launch_writes or m.events)
        with self.machine() as m:
            m.run_launcher(r0=0xDEAD0000)
            self.assertEqual(m.get_calls, 0)
            self.assertEqual(m.word(m.stage+m.ls['result']), 0)

    def test_duplicate_and_lost_attempts_never_allocate_twice(self):
        for label in ('after_get', 'validate_descriptor', 'invoke', 'after_entry', None):
            with self.subTest(label=label), self.machine() as m:
                if label:
                    m.lost = m.stage+(m.ls['invoke']+8 if label == 'after_entry' else m.ls[label])
                    with self.assertRaises(LostExecution):
                        m.run_launcher()
                else:
                    m.run_launcher()
                m.lost = None
                count = len(m.events)
                m.run_launcher()
                self.assertEqual(m.get_calls, 1)
                self.assertEqual(len(m.events), count)
                self.assertFalse(m.deleted or m.released)

    def test_native_assertion_retains_owned_descriptor_and_entry_intent(self):
        for fault in ('allocation', 'flag_create', 'task_create'):
            with self.subTest(fault=fault), self.machine(**{fault: True}) as m:
                with self.assertRaises(base.NativeAssertion):
                    m.run_launcher()
                self.assertEqual([m.word(m.owner+0x400+i*4) for i in range(8)],
                                 [5, m.owner, m.owner, 0, m.owner, 0x10000, 0, 0])
                self.assertEqual(m.word(m.owner), 1)
                m.run_launcher()
                self.assertEqual(m.get_calls, 1)
                self.assertEqual(m.events.count(base.CREATE), 1)

    def test_start_failure_is_unattached_not_falsely_runnable(self):
        with self.machine(task_start=True) as m:
            m.run_launcher()
            self.assertEqual(m.word(m.owner+0x418), 2)
            self.assertFalse(m.started)
            self.assertNotIn(base.ATTACH, m.events)
            m.poison_staging()
            self.assertEqual(m.observe(), 7)
            self.assertEqual(m.word(m.owner+0x148), 16)  # dormant, not admitted

    def test_cancellable_template_is_embedded_unchanged_and_retained(self):
        built = launch.build(cancel=True)
        with self.machine(OWNERS[1], built=built) as m:
            m.run_launcher(); m.poison_staging()
            m.word(m.plan.code+m.capture_syms['g_cancel_request'], 1)
            m.call('activate'); m.wakes += 1; m.run_task()
            self.assertEqual(m.capture_calls, 1)
            self.assertEqual(m.observe(), 15)
            report = base.lat.decode(bytes(m.m.mem_read(m.plan.state, 2048)),
                                     bytes(m.m.mem_read(m.plan.output, 11264)), 1200, cancel=True)
            self.assertEqual((report['status_code'], report['batches']), (101, []))

    def test_entire_launcher_extent_checked_before_intent_or_allocation(self):
        blob, syms, _ = self.built
        # Head is below the domain boundary, embedded tail crosses it. Also
        # exercise arithmetic carry with just the executable head at top of VA.
        for stage in (0x7FFFF000, 0xFFFFF000):
            m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
            m.mem_map(stage, 4096)
            m.mem_write(stage, blob[:4096])
            m.mem_map(base.HOST_STACK-4096, 4096)
            m.mem_map(base.STOP, 4096)
            m.reg_write(ar.UC_ARM_REG_SP, base.HOST_STACK)
            m.reg_write(ar.UC_ARM_REG_LR, base.STOP)
            m.reg_write(ar.UC_ARM_REG_R0, stage)
            def execute(mu, pc, size, unused):
                assert stage <= pc < stage+syms['result'], 'native call before bounds check'
            m.hook_add(uc.UC_HOOK_CODE, execute)
            m.emu_start(stage, base.STOP, count=1000)
            self.assertEqual(m.reg_read(ar.UC_ARM_REG_PC), base.STOP)
            self.assertEqual(bytes(m.mem_read(stage+syms['result'], 32)), bytes(32))

    def test_staging_readback_mask_is_exact(self):
        blob, syms, artifact = self.built
        allowed = set(range(syms['result'], syms['result']+32))
        allowed.update(syms['embedded_image']+off+i for off in
                       launch.runtime.reference_offsets(*artifact[1:]) for i in range(4))
        for offset in range(len(blob)):
            bad = bytearray(blob); bad[offset] ^= 1
            if offset in allowed:
                launch.verify_staging(blob, bad, syms, artifact)
            else:
                with self.assertRaises(ValueError):
                    launch.verify_staging(blob, bad, syms, artifact)

    def test_source_mutations_fail_independent_order_and_initialization_oracles(self):
        root = Path(__file__).resolve().parents[1]
        text = launch.SOURCE.read_text().replace('"../firmware/fpl_302.h"',
            f'"{root}/fp_usb_shell/firmware/fpl_302.h"').replace(
            '#include "../../gyro/retained_launch.inc.S"', (root/'gyro/retained_launch.inc.S').read_text())
        mutations = [
            ('ldr ip, =RL_DCACHE\n    blx ip', 'nop\n    nop', 'cache'),
            ('mov r0, r6                       @ ordinary', 'mov r0, #0                       @ ordinary', 'abi'),
            ('zero_owner:\n    str r1, [r0], #4', 'zero_owner:\n    add r0, r0, #4', 'zero'),
            ('ldr r1, =0xA5A5A5A5', 'mov r1, #0', 'sentinel'),
            ('ldr r0, [r4, #12]\n    cmp r0, #0', 'ldr r0, [r4, #12]\n    cmp r0, r0', 'descriptor'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'mutant.S'
            for old, new, kind in mutations:
                with self.subTest(kind=kind):
                    self.assertIn(old, text)
                    source.write_text(text.replace(old, new))
                    with patch.object(launch, 'SOURCE', source):
                        built = launch.build()
                    malformed = (OWNERS[0], OWNERS[0], 1, OWNERS[0], 0x10000) if kind == 'descriptor' else None
                    with self.machine(built=built, malformed=malformed) as m:
                        with self.assertRaises(AssertionError):
                            m.run_launcher()
                            if kind == 'descriptor':
                                self.assertFalse(m.launch_writes)
                            else:
                                self.assertEqual(m.events.count(base.CREATE), 1)
                                self.assertEqual(bytes(m.m.mem_read(m.owner+0x5000, 11264)), b'\xA5'*11264)


if __name__ == '__main__':
    unittest.main()
