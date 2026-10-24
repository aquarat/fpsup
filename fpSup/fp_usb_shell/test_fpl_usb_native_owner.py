"""Bounded native queued-transfer task evidence; no candidate hooks or tickets.

FIRMWARE_ROOT must contain FPL_V302/MAIN.bin and FP__V502/MAIN.bin.
Runs actual task/StartTransfer/unwind instructions with synthetic RTOS/MMIO.
"""
import hashlib
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fpl_usb_generation_audit as g
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_PC


class QueuedTransfer(g.Machine):
    def __init__(self, image, profile, *, nested=False, replace=False):
        super().__init__(image, profile, nested=nested)
        self.replace = replace
        self.replacement = self.trb + 0x3500
        self.reached = []
        self.response = None

    def hook(self, u, pc, size, user):
        site = pc - self.delta
        self.reached.append(site)
        if site == 0xC01F53D0:  # synthetic successful message receive
            target = u.reg_read(UC_ARM_REG_R1)
            for offset, value in ((0, 0), (4, 0x45004000), (8, 1024)):
                self.put(target + offset, value)
            self.ret(12)
        elif site == 0xC01F54CC:  # synthetic current-task info / priority
            self.put(u.reg_read(UC_ARM_REG_R1) + 4, 28)
            self.ret()
        elif site == 0xC01F5094:  # priority change, not a lock
            self.ret()
        elif site == 0xC01E2918:  # synthetic configured bulk packet length
            self.ret(1024)
        elif site == 0xC01E4502 and self.replace:
            # Explicit schedule injection, not an assertion that hardware did it.
            # CPU already loaded A; subsequent descriptor fields reload the table.
            self.put(self.drv + 0x58, self.replacement)
        elif site == 0xC01E3400 and not self.nested:
            u.emu_stop()  # inspect all real TRB stores before native StartTransfer
        elif site == 0xC01F55A4:
            self.response = self.get(u.reg_read(UC_ARM_REG_R1))
            u.emu_stop()  # task is an infinite loop; stop at response send
        else:
            super().hook(u, pc, size, user)

    def task(self):
        self.u.reg_write(UC_ARM_REG_SP, self.stack)
        self.u.emu_start((0xC01E4450 + self.delta) | 1, self.stop, count=200000)
        expected = 0xC01F55A4 if self.nested else 0xC01E3400
        assert self.u.reg_read(UC_ARM_REG_PC) == expected + self.delta
        assert self.u.reg_read(UC_ARM_REG_SP) == self.stack - 0x88
        return self


@unittest.skipUnless(os.environ.get('FIRMWARE_ROOT'), 'set FIRMWARE_ROOT to official MAIN inputs')
class NativeOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = {}
        for profile, (directory, length, digest, _, _) in g.wait.PROFILES.items():
            image = (Path(os.environ['FIRMWARE_ROOT']) / directory / 'MAIN.bin').read_bytes()
            assert len(image) == length and hashlib.sha256(image).hexdigest() == digest
            cls.images[profile] = image

    def test_native_queue_reaches_descriptor_write_without_controller_semaphore(self):
        for profile, image in self.images.items():
            with self.subTest(profile=profile):
                m = QueuedTransfer(image, profile).task()
                self.assertEqual(m.get(m.trb + 0x100), 0x05004000)
                self.assertEqual(m.get(m.trb + 0x10C), 0x813)
                self.assertIn(0xC01E4502, m.reached)
                self.assertNotIn(0xC01F570C, m.reached)
                self.assertNotIn(0xC000EC14, m.reached)

    def test_replacement_between_native_table_load_and_first_store_splits_descriptor(self):
        for profile, image in self.images.items():
            with self.subTest(profile=profile):
                m = QueuedTransfer(image, profile, replace=True).task()
                self.assertEqual(m.get(m.trb + 0x100), 0x05004000)
                self.assertEqual(m.get(m.trb + 0x10C), 1)  # old descriptor not armed
                self.assertEqual(m.get(m.replacement), 0)  # new has no buffer
                self.assertEqual(m.get(m.replacement + 8), 1024)
                self.assertEqual(m.get(m.replacement + 12), 0x813)

    def test_native_queued_start_retains_old_unwind_after_nested_teardown(self):
        for profile, image in self.images.items():
            with self.subTest(profile=profile):
                m = QueuedTransfer(image, profile, nested=True).task()
                self.assertEqual(g.wait.signed(m.response), -4)
                self.assertLess(m.reached.index(0xC01E3778), m.reached.index(0xC01E3512))
                self.assertLess(m.reached.index(0xC01E3512), m.reached.index(0xC01F55A4))
                self.assertEqual(m.get(m.drv + 0x704), 0)

    def test_store_mutations_change_native_effects(self):
        for profile, image in self.images.items():
            with self.subTest(profile=profile, site='descriptor'):
                m = QueuedTransfer(image, profile)
                site = 0xC01E4502 + m.delta
                self.assertEqual(bytes(m.u.mem_read(site, 2)), bytes.fromhex('0160'))
                m.u.mem_write(site, bytes.fromhex('00bf'))
                m.task()
                self.assertNotEqual(m.get(m.trb + 0x100), 0x05004000)
            with self.subTest(profile=profile, site='old-unwind'):
                m = QueuedTransfer(image, profile, nested=True)
                site = 0xC01E3512 + m.delta
                self.assertEqual(bytes(m.u.mem_read(site, 2)), bytes.fromhex('0860'))
                m.u.mem_write(site, bytes.fromhex('00bf'))
                m.task()
                self.assertEqual(g.wait.signed(m.response), -4)
                self.assertNotEqual(m.get(m.drv + 0x704), 0)


if __name__ == '__main__':
    unittest.main()
