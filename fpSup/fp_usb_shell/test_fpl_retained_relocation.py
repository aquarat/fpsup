"""Offline relocation through the actual fp L native wrapper/query kernels."""
from contextlib import contextmanager
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
import fpl_retained_relocation as runtime
import test_fpl_gyro_task_retained as retained

base = retained.base
PLACEMENTS = ((0x48010000, 0x44500000), (0x51030000, 0x45A00000))


class Machine(retained.Machine):
    def __init__(self, *args, **kwargs):
        self.owner_writes = []
        self.old_ranges = []
        super().__init__(*args, **kwargs)

    def memory(self, m, access, address, size, value, unused):
        assert not any(lo <= address < hi for lo, hi in self.old_ranges), 'old placement reference'
        if access == uc.UC_MEM_WRITE and base.OWNED <= address < base.OWNED+0x10000:
            self.owner_writes.append((address, size))
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        assert not any(lo <= pc < hi for lo, hi in self.old_ranges), 'old placement execution'
        super().execute(m, pc, size, unused)


class Relocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = base.MAIN.read_bytes()
        retained.audit.fingerprint(cls.image)
        cls.artifact = runtime.template()

    @contextmanager
    def machine(self, stage, owner, artifact=None, data=None, **faults):
        artifact = artifact or self.artifact
        image, syms, cs = artifact
        initialized = runtime.initialize(artifact, stage, owner) if data is None else data
        plan = base.lat.strict.Layout(owner+0x2000, owner+0x4000, owner+0x5000, 11264)
        with patch.multiple(base, STAGING=stage, OWNED=owner), \
                patch.multiple(retained, OWNED=owner, OBS=owner+0x100):
            m = Machine(self.image, (initialized, syms, plan, cs), **faults)
            # Map and poison unrelated former storage. Reads/execution are trapped.
            prior = PLACEMENTS[0] if (stage, owner) == PLACEMENTS[1] else ()
            for lo in (0x45000000, 0x46000000, *prior):
                m.m.mem_map(lo, 0x10000)
                m.m.mem_write(lo, b'\xFE'*0x10000)
                m.old_ranges.append((lo, lo+0x10000))
            yield m, initialized

    def test_identical_template_two_placements_full_native_capture_and_queries(self):
        canonical, syms, cs = self.artifact
        results = []
        for stage, owner in PLACEMENTS:
            with self.subTest(stage=hex(stage), owner=hex(owner)), self.machine(stage, owner) as (m, data):
                uninitialized = bytearray(data)
                for offset in runtime.reference_offsets(syms, cs):
                    struct.pack_into('<I', uninitialized, offset, 0)
                self.assertEqual(bytes(uninitialized), canonical)  # no instruction fixups
                guards = ((0x400, 0x1000), (0x3000, 0x4000), (0x4800, 0x5000), (0x7C00, 0x10000))
                for lo, hi in guards:
                    m.m.mem_write(owner+lo, b'\xD3'*(hi-lo))
                m.call('entry')
                self.assertEqual(m.word(owner), 2)
                self.assertEqual(m.word(owner+syms['runtime_owner']), owner)
                m.poison_staging()
                self.assertEqual(m.observe(), 7)
                m.call('activate')
                m.wakes += 2
                m.run_task(4)
                self.assertEqual(m.capture_calls, 1)
                self.assertEqual(m.body_calls, 3)
                self.assertEqual(m.observe(), 15)
                results.append(m.retained_readback())
                runtime.verify_resident(data, bytes(m.m.mem_read(owner+0x1000, 4096)),
                    bytes(m.m.mem_read(owner+0x2000, 4096)), syms, cs)
                self.assertTrue(m.task and m.allocated and not m.deleted and not m.released)
                for lo, hi in guards:
                    self.assertEqual(bytes(m.m.mem_read(owner+lo, hi-lo)), b'\xD3'*(hi-lo))
        self.assertEqual(results[0], results[1])

    def test_invalid_owner_and_capture_references_refuse_before_any_owned_write_or_create(self):
        stage, owner = PLACEMENTS[0]
        good = runtime.initialize(self.artifact, stage, owner)
        syms, cs = self.artifact[1:]
        offsets = runtime.reference_offsets(syms, cs)
        changes = [(offsets[0], v) for v in (0, 0x443F0000, owner+64, 0x46400000,
                                            0xFFFF0000, 0xC3000000, 0x50000000)]
        changes += [(offset, value) for offset in offsets[1:]
                    for value in (0, stage, owner, 0xFFFFFFFF)]
        for offset, value in changes:
            with self.subTest(offset=offset, value=hex(value)):
                bad = bytearray(good); struct.pack_into('<I', bad, offset, value)
                with self.machine(stage, owner, data=bytes(bad)) as (m, _):
                    m.call('entry')
                    self.assertFalse(m.owner_writes or m.cache or m.events or m.allocated)

    def test_staging_overlap_domain_and_wrong_entry_abi_refused(self):
        owner = 0x45A00000
        for stage, candidate in ((0x44500000, 0x44500000), (0x444FF000, 0x44500000),
                                 (0x7FFFF000, owner), (0xFFFF0000, owner)):
            data = bytearray(runtime.initialize(self.artifact, PLACEMENTS[0][0], owner))
            for offset, value in zip(runtime.reference_offsets(*self.artifact[1:]),
                                     (candidate, candidate+0x4000, 2048, candidate+0x5000, 11264, 1200)):
                struct.pack_into('<I', data, offset, value)
            with self.subTest(stage=hex(stage)), self.machine(stage, owner, data=bytes(data)) as (m, _):
                m.call('entry')
                self.assertFalse(m.owner_writes or m.events or m.cache)
        with self.machine(*PLACEMENTS[0]) as (m, _):
            m.call('entry', r0=0xDEAD0000)
            self.assertFalse(m.owner_writes or m.events or m.cache)

    def test_corrupt_resident_owner_cannot_redirect_commands_or_callback(self):
        stage, owner = PLACEMENTS[0]
        for command in ('activate', 'observe', 'body_entry'):
            with self.subTest(command=command), self.machine(stage, owner) as (m, data):
                m.call('entry'); m.poison_staging()
                m.word(owner+m.syms['runtime_owner'], 0x46000000)
                before, events = len(m.owner_writes), len(m.events)
                if command == 'body_entry':
                    m.context = 'task'
                    m.m.reg_write(ar.UC_ARM_REG_SP, base.TASK_STACK)
                    m.m.reg_write(ar.UC_ARM_REG_LR, base.STOP)
                    m.m.reg_write(ar.UC_ARM_REG_R0, owner+8)
                    m.m.emu_start(owner+m.syms[command], base.STOP, count=10000)
                    self.assertEqual(m.m.reg_read(ar.UC_ARM_REG_PC), base.STOP)
                    self.assertEqual(m.capture_calls, 0)
                else:
                    m.call(command)
                self.assertEqual(len(m.owner_writes), before)
                self.assertEqual(len(m.events), events)
                with self.assertRaisesRegex(RuntimeError, 'owner reference'):
                    runtime.verify_resident(data, bytes(m.m.mem_read(owner+0x1000, 4096)),
                        bytes(m.m.mem_read(owner+0x2000, 4096)), m.syms, m.capture_syms)

    def test_cancel_and_done_before_native_completion_at_second_placement(self):
        artifact = runtime.template(cancel=True)
        stage, owner = PLACEMENTS[1]
        with self.machine(stage, owner, artifact) as (m, data):
            m.call('entry'); m.poison_staging(); m.call('activate')
            m.word(m.plan.code+m.capture_syms['g_cancel_request'], 1)
            m.wakes += 1
            m.stop_at = owner+m.syms['body_return']
            m.run_task()
            self.assertEqual(m.word(owner+0x24), 1)
            self.assertEqual(m.observe(), 7)
            m.stop_at = None
            m.run_task()
            self.assertEqual(m.observe(), 15)
            self.assertEqual(m.capture_calls, 1)
            state = bytes(m.m.mem_read(m.plan.state, 2048))
            output = bytes(m.m.mem_read(m.plan.output, m.plan.output_room))
            self.assertEqual(base.lat.decode(state, output, 1200, cancel=True)['status_code'], 101)
            runtime.verify_resident(data, bytes(m.m.mem_read(owner+0x1000, 4096)),
                bytes(m.m.mem_read(owner+0x2000, 4096)), m.syms, m.capture_syms, cancel=True)

    def test_reference_words_are_not_postexecution_mutable(self):
        data = runtime.initialize(self.artifact, *PLACEMENTS[0])
        syms, cs = self.artifact[1:]
        for offset in runtime.reference_offsets(syms, cs):
            changed = bytearray(data); changed[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                runtime.verify_resident(data, changed[0x1000:0x2000], changed[0x2000:], syms, cs)
        with self.assertRaises(ValueError):
            runtime.initialize((data, syms, cs), *PLACEMENTS[1])

    def test_exact_symbol_derived_readback_mask(self):
        data = runtime.initialize(self.artifact, *PLACEMENTS[0])
        syms, cs = self.artifact[1:]
        mutable = {0x2000+cs[name]+i for name in base.lat.MUTABLE for i in range(4)}
        for offset in range(0x1000, 0x3000):
            changed = bytearray(data); changed[offset] ^= 1
            if offset in mutable:
                runtime.verify_resident(data, changed[0x1000:0x2000], changed[0x2000:], syms, cs)
            else:
                with self.assertRaises(RuntimeError):
                    runtime.verify_resident(data, changed[0x1000:0x2000], changed[0x2000:], syms, cs)

    def test_native_signed_query_errors_and_identity_changes_after_relocation(self):
        stage, owner = PLACEMENTS[1]
        for field, value, rc in ((0, 501, -18), (0, 500, -42), (12, 301, -18), (12, 300, -42)):
            with self.subTest(field=field, value=value), self.machine(stage, owner) as (m, _):
                m.call('entry'); m.poison_staging(); m.call('activate'); m.run_task()
                self.assertEqual(m.observe(), 15)
                m.word(base.SYS+field, value)
                self.assertFalse(m.observe() & 8)
                for sample in (owner+0x120, owner+0x180):
                    self.assertEqual(m.word(sample+(0x14 if field == 0 else 0x18)), rc & 0xFFFFFFFF)
                self.assertTrue(m.task and m.allocated and not m.deleted)
        with self.machine(stage, owner) as (m, _):
            m.call('entry'); m.poison_staging(); m.call('activate'); m.run_task()
            m.mutate_on_flag = lambda mm: mm.word(base.SYS+8, owner+8)
            self.assertFalse(m.observe() & 8)

    def test_runtime_constructor_failure_retains_attempt_without_recreate(self):
        with self.machine(*PLACEMENTS[0], flag_create=True) as (m, _):
            with self.assertRaises(base.NativeAssertion):
                m.call('entry')
            self.assertEqual(m.word(PLACEMENTS[0][1]), 1)
            m.call('entry')
            self.assertEqual(m.events.count(base.CREATE), 1)
            self.assertFalse(m.deleted or m.released)

    def test_copied_owner_checked_before_native_create(self):
        stage, owner = PLACEMENTS[0]
        with self.machine(stage, owner) as (m, _):
            def corrupt(mu, pc, size, unused):
                if pc == stage+m.syms['copy']:
                    mu.mem_write(stage+m.syms['runtime_owner'], struct.pack('<I', 0x46000000))
            m.m.hook_add(uc.UC_HOOK_CODE, corrupt)
            m.call('entry')
            self.assertEqual(m.word(owner), 1)
            self.assertFalse(m.events or m.cache or m.allocated)

    def test_mutated_validation_and_resident_owner_check_fail_independent_oracles(self):
        text = retained.mutation_source()
        mutations = [
            ('cmp r7, r8\n    bne entry_return', 'cmp r7, r8\n    nop', 'capture'),
            ('bne \\failure', 'nop', 'owner'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'mutant.S'
            for old, new, kind in mutations:
                self.assertIn(old, text)
                source.write_text(text.replace(old, new))
                with patch.object(runtime, 'SOURCE', source):
                    artifact = runtime.template()
                stage, owner = PLACEMENTS[0]
                data = bytearray(runtime.initialize(artifact, stage, owner))
                if kind == 'capture':
                    struct.pack_into('<I', data, runtime.reference_offsets(*artifact[1:])[1], 0)
                with self.machine(stage, owner, artifact, data=bytes(data)) as (m, _):
                    if kind == 'capture':
                        m.call('entry')
                        with self.assertRaises(AssertionError):
                            self.assertFalse(m.owner_writes or m.events)
                    else:
                        m.call('entry'); m.poison_staging()
                        m.word(owner+m.syms['runtime_owner'], 0x46000000)
                        with self.assertRaisesRegex(AssertionError, 'old placement reference'):
                            m.call('activate')


if __name__ == '__main__':
    unittest.main()
