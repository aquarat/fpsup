"""Actual opt-in ARM admission with a deliberately modelled ownership provider.

The provider owns a separate synthetic allocation and reserves its first 64
bytes exclusively. This is not a claimed fp L firmware publication binding.
"""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from unicorn import UC_MEM_WRITE
from unicorn import arm_const as ar
import fpl_retained_admission as admission
import test_fpl_retained_launcher as prior

SLOT, PROVIDER, EPOCH = 0x46200000, 0x47000000, 19


class Machine(prior.Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.m.mem_map(SLOT, 0x10000)
        self.m.mem_map(PROVIDER, 4096)
        self.authority, self.epoch, self.slot = True, EPOCH, SLOT
        self.provider_calls = 0
        self.old_staging = []
        self.m.mem_write(SLOT, struct.pack('<16I', admission.MAGIC, 1, EPOCH, *([0]*13)))

    def memory(self, m, access, address, size, value, unused):
        assert not any(lo <= address < hi for lo, hi in self.old_staging), 'old staging read/write'
        if SLOT <= address < SLOT+64:
            if access == UC_MEM_WRITE:
                assert address+size <= SLOT+64
            return
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        assert not any(lo <= pc < hi for lo, hi in self.old_staging), 'old staging execution'
        if pc == PROVIDER:
            self.provider_calls += 1
            assert (self.reg(0), self.reg(1)) == (self.stage, self.stage+len(self.launcher))
            assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            self.ret(self.slot)
            m.reg_write(ar.UC_ARM_REG_R1, self.epoch)
            m.reg_write(ar.UC_ARM_REG_R2, int(self.authority))
            return
        if pc == prior.GET:
            assert self.word(SLOT+12) == 1, 'allocation before exclusive intent'
        if pc == self.wrapper_stage:
            assert self.word(SLOT+12) == 2, 'runtime before owned intent'
            assert bytes(m.mem_read(SLOT+16, 32)) == bytes(m.mem_read(self.owner+0x400, 32))
            assert bytes(m.mem_read(self.owner+0x440, 16)) == struct.pack(
                '<4I', admission.MAGIC, 1, SLOT, EPOCH)
        super().execute(m, pc, size, unused)

    def fresh_staging(self):
        old = self.stage
        self.m.mem_write(old, b'\xFE'*prior.STAGE_SIZE)
        self.old_staging.append((old, old+prior.STAGE_SIZE))
        self.stage = 0x45200000 + len(self.old_staging)*0x10000
        self.m.mem_map(self.stage, 0x10000)
        self.m.mem_write(self.stage, self.launcher)
        self.wrapper_stage = self.stage+self.ls['embedded_image']
        self.entry_returned = False

    def snapshot(self):
        return bytes(self.m.mem_read(SLOT, 64))

    def discover(self, **kwargs):
        b = self.snapshot()
        return admission.discover(b, b, slot=SLOT, epoch=self.epoch,
            owned_result=bytes(self.m.mem_read(self.owner+0x400, 32)),
            owned_identity=bytes(self.m.mem_read(self.owner+0x440, 16)), **kwargs)


class Admission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prior.Launcher.setUpClass()
        cls.built = prior.launch.build(admission_provider=PROVIDER)

    @contextmanager
    def machine(self, **kwargs):
        with patch.object(prior, 'Machine', Machine), prior.Launcher().machine(
                built=kwargs.pop('built', self.built), **kwargs) as m:
            yield m

    def test_default_bytes_and_runtime_template_unchanged(self):
        self.assertEqual(hashlib.sha256(prior.Launcher.built[0]).hexdigest(),
                         '081b3a58e806a5081798e309aa4f1790e094102d950a8d9e6380fa61b6c070d5')
        self.assertEqual(self.built[2], prior.Launcher.built[2])

    def test_discovery_and_fresh_staging_duplicate_after_poison(self):
        for alignment in (0, 4):
            with self.machine() as m:
                m.run_launcher(alignment=alignment)
                self.assertEqual(m.word(SLOT+12), 3)
                before = m.snapshot()
                with self.assertRaises(ValueError):
                    m.discover()  # even perfectly matching pointers/epoch are insufficient
                report = m.discover(current_boot_verified=True)
                self.assertFalse(report['activation_authorized'])
                m.fresh_staging()
                m.run_launcher()
                self.assertEqual(m.word(m.stage+m.ls['result']), 7)
                self.assertEqual(m.snapshot(), before)
                self.assertEqual(m.get_calls, 1)
                self.assertEqual(m.events.count(prior.base.CREATE), 1)
                self.assertNotIn(prior.base.ATTACH, m.events)
                self.assertEqual(m.capture_calls, 0)
                self.assertEqual(m.observe(), 7)
                m.call('activate'); m.run_task()
                self.assertEqual(m.observe(), 15)
                m.retained_readback()

    def test_absent_authority_never_dereferences_even_matching_or_invalid_pointer(self):
        for pointer in (SLOT, 0xDEAD0000):
            with self.machine() as m:
                m.authority, m.slot = False, pointer
                before = m.snapshot()
                m.run_launcher()
                self.assertEqual(m.word(m.stage+m.ls['result']), 8)
                self.assertEqual(m.snapshot(), before)
                self.assertEqual(m.get_calls, 0)

    def test_corrupt_stale_and_premature_publication_refuse_without_owner_dereference(self):
        for offset, value in ((0, 0), (4, 2), (8, EPOCH-1), (12, 1), (12, 2),
                              (12, 3), (12, 0xffffffff), (20, 0xDEAD0000), (60, 1)):
            with self.subTest(offset=offset, value=value), self.machine() as m:
                m.word(SLOT+offset, value)
                before = m.snapshot()
                m.run_launcher()
                self.assertIn(m.word(m.stage+m.ls['result']), (7, 8))
                self.assertEqual(m.snapshot(), before)
                self.assertEqual(m.get_calls, 0)
                self.assertFalse(m.events)

    def test_invalid_provider_extent_and_epoch_refuse(self):
        for pointer, epoch in ((0, EPOCH), (SLOT+4, EPOCH), (0xffffffc0, EPOCH),
                               (0x464000e0, EPOCH), (SLOT, 0)):
            with self.machine() as m:
                m.slot, m.epoch = pointer, epoch
                m.run_launcher()
                self.assertEqual(m.get_calls, 0)
                self.assertEqual(m.word(m.stage+m.ls['result']), 8)

    def test_refusal_and_native_failures_retain_and_block_fresh_attempt(self):
        for fault in ('refusal', 'allocation', 'flag_create', 'task_create', 'task_start'):
            with self.subTest(fault=fault), self.machine(**{fault: True}) as m:
                if fault in ('allocation', 'flag_create', 'task_create'):
                    with self.assertRaises(prior.base.NativeAssertion):
                        m.run_launcher()
                    self.assertEqual(m.word(SLOT+12), 2)
                else:
                    m.run_launcher()
                    self.assertEqual(m.word(SLOT+12), 4 if fault == 'refusal' else 3)
                if fault == 'task_start':
                    self.assertFalse(m.started)
                    self.assertFalse(m.discover(current_boot_verified=True)['native_start_verified'])
                before = m.snapshot()
                m.fresh_staging(); m.run_launcher()
                self.assertEqual(m.snapshot(), before)
                self.assertEqual(m.get_calls, 1)
                self.assertFalse(m.deleted or m.released)

    def test_malformed_descriptor_and_reservation_overlap_are_retained_failures(self):
        for values in ((prior.OWNERS[0], prior.OWNERS[0], 1, prior.OWNERS[0], 0x10000),
                       (SLOT, SLOT, 0, SLOT, 0x10000)):
            with self.machine(malformed=values) as m:
                m.run_launcher()
                self.assertEqual(m.word(SLOT+12), 5)
                self.assertFalse(m.launch_writes or m.events)
                before = m.snapshot()
                m.fresh_staging(); m.run_launcher()
                self.assertEqual(m.get_calls, 1)
                self.assertEqual(m.snapshot(), before)

    def test_lost_outcomes_block_fresh_staging_and_incomplete_discovery(self):
        for label in ('after_get', 'validate_descriptor', 'invoke'):
            with self.subTest(label=label), self.machine() as m:
                m.lost = m.stage+m.ls[label]
                with self.assertRaises(prior.LostExecution):
                    m.run_launcher()
                before = m.snapshot()
                with self.assertRaises(ValueError):
                    m.discover(current_boot_verified=True)
                m.lost = None
                m.fresh_staging(); m.run_launcher()
                self.assertEqual(m.get_calls, 1)
                self.assertEqual(m.snapshot(), before)

    def test_boot_reset_is_provider_model_not_epoch_comparison(self):
        with self.machine() as m:
            m.run_launcher()
            stale = m.snapshot()
            m.epoch += 1
            m.fresh_staging(); m.run_launcher()
            self.assertEqual(m.get_calls, 1)
            self.assertEqual(m.snapshot(), stale)
        # A NEW emulator/allocator/provider owns the reset; same numeric epoch
        # is intentionally legal and illustrates why equality proves no reboot.
        with self.machine() as m:
            m.authority = False
            m.run_launcher()
            self.assertEqual(m.get_calls, 0)
            m.authority = True
            m.fresh_staging(); m.run_launcher()
            self.assertEqual(m.get_calls, 1)

    def test_parser_rejects_torn_result_and_owned_identity(self):
        with self.machine() as m:
            m.run_launcher()
            b = m.snapshot()
            kwargs = dict(slot=SLOT, epoch=EPOCH, current_boot_verified=True,
                          owned_result=b[16:48], owned_identity=bytes(m.m.mem_read(m.owner+0x440, 16)))
            for offset in range(64):
                changed = bytearray(b); changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    admission.discover(b, changed, **kwargs)
            for field in ('owned_result', 'owned_identity'):
                bad = dict(kwargs); bad[field] = b''
                with self.assertRaises(ValueError):
                    admission.discover(b, b, **bad)
            # An internally stable but corrupt descriptor is rejected before a
            # caller is given an address to read. State=returned alone is false.
            for offset in (16, 20, 24, 28, 32, 36, 40, 44, 48):
                changed = bytearray(b); changed[offset] ^= 1
                with self.assertRaises(ValueError):
                    admission.candidate(changed, changed, slot=SLOT, epoch=EPOCH,
                                        current_boot_verified=True)

    def test_mutation_missing_exclusive_intent_is_detected(self):
        root = Path(__file__).resolve().parents[1]
        source = prior.launch.SOURCE.read_text().replace('"../firmware/fpl_302.h"',
            f'"{root}/fp_usb_shell/firmware/fpl_302.h"').replace(
            '#include "../../gyro/retained_launch.inc.S"',
            (root/'gyro/retained_launch.inc.S').read_text().replace(
                '#include "retained_admission.inc.S"',
                (root/'gyro/retained_admission.inc.S').read_text()))
        self.assertIn('strex ip, r2, [r3]', source)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/'mutant.S'
            p.write_text(source.replace('strex ip, r2, [r3]', 'mov ip, #0'))
            with patch.object(prior.launch, 'SOURCE', p):
                built = prior.launch.build(admission_provider=PROVIDER)
            with self.machine(built=built) as m:
                with self.assertRaisesRegex(AssertionError, 'exclusive intent'):
                    m.run_launcher()


if __name__ == '__main__':
    unittest.main()
