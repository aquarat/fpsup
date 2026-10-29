"""Execute emitted probe and real fp L Thumb IRQ dispatcher; no USB IO."""
import os
from pathlib import Path
import struct
import unittest

import armasm
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *

CODE, PARAM, BUFFER = 0x45000000, 0x45001000, 0x45002000
SLOT, RET = 0xC31D6DD8, 0x100000
SOURCE = Path(__file__).parent / 'asm/fpl_vd_probe.S'
DEFINES = [f'PARAM={PARAM}', f'BUFFER={BUFFER}']


class Probe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = armasm.assemble(SOURCE, DEFINES)
        cls.sym = armasm.symbols(SOURCE, DEFINES)
        path = os.environ.get('FPL_MAIN')
        if not path:
            raise RuntimeError('FPL_MAIN required; this test must execute native IRQ instructions')
        cls.image = Path(path).read_bytes()
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        from fpl_sensor_timing_audit import validate
        validate(cls.image)

    def machine(self, capacity=3):
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a, n in [(CODE, 0x10000), (0xC0000000, 0x4000000),
                     (0x100000, 0x10000), (0x30100000, 0x1000), (0x2D810000, 0x1000)]:
            u.mem_map(a, n)
        u.mem_write(0xC0000000, self.image)
        u.mem_write(CODE, self.code)
        u.mem_write(PARAM, struct.pack('<8I', 0, 0, 0, capacity, 0, 0, 0x0243049B, 0x08150000))
        u.mem_write(BUFFER, b'\xa5' * 0x9000)
        for a, v in [(SLOT + 4, 1), (0x30100004, 0x0243049B), (0x30100020, 0x08150000)]:
            self.write(u, a, v)
        # Only unrelated IRQ side effects are stubbed. The callback loads,
        # flag check, BLX interworking and return execute native instructions.
        stubs = {0xC01256D0, 0xC0121FC8, 0xC0125DF0, 0xC0123DA8,
                 0xC01F555C, 0xC0016B9C}
        def hook(mu, pc, size, _):
            if pc in stubs:
                mu.reg_write(UC_ARM_REG_R0, 0)
                mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    @staticmethod
    def word(u, a):
        return struct.unpack('<I', u.mem_read(a, 4))[0]

    @staticmethod
    def write(u, a, v):
        u.mem_write(a, struct.pack('<I', v))

    def call(self, u, pc, irq=False):
        u.reg_write(UC_ARM_REG_CPSR, 0xD2 if irq else 0x13)
        u.reg_write(UC_ARM_REG_SP, 0x10F000)
        u.reg_write(UC_ARM_REG_LR, RET)
        regs = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
        for k, r in enumerate(regs):
            u.reg_write(r, 0x12340000 + k)
        u.emu_start(pc, RET, count=10000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), RET)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), 0x10F000)
        self.assertEqual([u.reg_read(r) for r in regs], [0x12340000 + k for k in range(8)])
        self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, 0xD2 if irq else 0x13)

    def test_native_dispatch_capture_and_self_detach(self):
        u = self.machine()
        self.call(u, CODE)
        self.assertEqual(self.word(u, SLOT), CODE + self.sym['callback'])
        for k in range(4):
            self.write(u, 0xC3076D98, 42)
            self.write(u, 0x2D810054, k * 200000)
            self.call(u, 0xC0121D19, irq=True)
        self.assertEqual(self.word(u, PARAM + 8), 3)
        self.assertEqual(self.word(u, PARAM + 4), 2)
        self.assertEqual(self.word(u, SLOT), 0)
        for k in range(3):
            rec = struct.unpack('<8I', u.mem_read(BUFFER + 32*k, 32))
            self.assertEqual(rec[:5], (42, k*200000, 42, 0x0243049B, 0x08150000))
            self.assertEqual(rec[6] & 0x1F, 0x12)
        self.assertEqual(u.mem_read(BUFFER + 96, 32), b'\xa5' * 32)

    def test_foreign_slot_and_disabled_dispatch_refused(self):
        for a, v in [(SLOT, 0x1234), (SLOT + 4, 0), (PARAM + 12, 1025),
                     (0x30100004, 0x1234), (0x30100020, 0x1234)]:
            u = self.machine()
            self.write(u, a, v)
            before = self.word(u, SLOT)
            self.call(u, CODE)
            self.assertEqual(self.word(u, PARAM + 4), 4)
            self.assertEqual(self.word(u, SLOT), before)

    def test_early_detach_keeps_foreign_pointer(self):
        u = self.machine()
        self.call(u, CODE)
        self.write(u, PARAM, 1)
        self.call(u, CODE)
        self.assertEqual(self.word(u, SLOT), 0)
        self.assertEqual(self.word(u, PARAM + 4), 3)
        self.write(u, SLOT, 0x1234)
        self.call(u, CODE)
        self.assertEqual(self.word(u, SLOT), 0x1234)
        self.assertEqual(self.word(u, PARAM + 4), 4)

    def test_mutation_missing_detach_is_detected(self):
        u = self.machine(capacity=1)
        # Remove the conditional slot clear in a private emulator image.
        start = self.sym['complete']
        needle = bytes.fromhex('00108005')  # streq r1,[r0]
        off = self.code.index(needle, start)
        u.mem_write(CODE + off, bytes.fromhex('00f020e3'))
        self.call(u, CODE)
        self.call(u, 0xC0121D19, irq=True)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.word(u, SLOT), 0)

    def timing_machine(self):
        u = self.machine(capacity=120)
        body = armasm.assemble(SOURCE, DEFINES + ['TIMING_TEST=1'])
        self.assertLessEqual(len(body), 0x400)
        u.mem_write(CODE, body)
        self.write(u, PARAM + 36, 0x024904A7)
        return u

    def test_timing_trial_restores_at_boundary_and_early_detach(self):
        for early in (False, True):
            u = self.timing_machine()
            self.call(u, CODE)
            for _ in range(8):
                self.call(u, 0xC0121D19, irq=True)
            self.assertEqual(self.word(u, 0x30100004), 0x024904A7)
            if early:
                self.write(u, PARAM, 1)
                self.call(u, CODE)
            else:
                for _ in range(80):
                    self.call(u, 0xC0121D19, irq=True)
            self.assertEqual(self.word(u, 0x30100004), 0x0243049B)
            self.assertEqual(self.word(u, PARAM + 40), 0)
            self.assertEqual(self.word(u, PARAM + 44), 1)

    def test_timing_restore_never_overwrites_a_foreign_mode(self):
        for address in (0x30100004, 0x30100020):
            u = self.timing_machine()
            self.call(u, CODE)
            for _ in range(8):
                self.call(u, 0xC0121D19, irq=True)
            self.write(u, address, 0x1234)
            self.write(u, PARAM, 1)
            self.call(u, CODE)
            self.assertEqual(self.word(u, address), 0x1234)
            self.assertEqual(self.word(u, PARAM + 44), 2)

    def test_timer_wrap_analysis(self):
        from fpl_vd_probe import analyse
        raw = b''.join(struct.pack('<8I', 42, t, 42, 1, 2, 3, 0x12, 0)
                       for t in (11800000, 0, 200000))
        self.assertAlmostEqual(analyse(raw, 12000000)['measured_hz'], 60)

    def test_mutation_missing_timing_restore_is_detected(self):
        u = self.timing_machine()
        defines = DEFINES + ['TIMING_TEST=1']
        body = armasm.assemble(SOURCE, defines)
        symbols = armasm.symbols(SOURCE, defines)
        off = body.index(bytes.fromhex('042080e5'), symbols['restore_timing'])
        u.mem_write(CODE + off, bytes.fromhex('00f020e3'))
        self.call(u, CODE)
        for _ in range(88):
            self.call(u, 0xC0121D19, irq=True)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.word(u, 0x30100004), 0x0243049B)

    def test_slit_scan_packaged_payload_duration_identity_and_mode_exit(self):
        import fpl_slit_scan as slit
        import fpl_getfile as gf
        plan = gf.Layout(CODE, PARAM, PARAM+0x400, BUFFER, 0)
        for frames, change_mode, mutate in ((1, False, False), (24, False, False),
                                            (480, False, False), (24, True, False),
                                            (1, False, True)):
            capture = slit.Capture(frames=frames)
            code, param, addresses = slit.build(plan, capture)
            u = self.machine()
            u.mem_write(CODE, code)
            u.mem_write(PARAM, param)
            self.write(u, 0x30100004, slit.T04)
            self.write(u, 0x30100020, slit.T20)
            if mutate:
                # Remove the actual packaged restore MMIO store.
                off = code.rindex(bytes.fromhex('042080e5'), 0x800)
                u.mem_write(CODE+off, bytes.fromhex('00f020e3'))
            self.call(u, addresses['vcode'])
            self.assertEqual(self.word(u, SLOT), addresses['callback'])
            for index in range(capture.count):
                self.write(u, PARAM+0xF0, 100+index)
                if change_mode and index == 12:
                    self.write(u, 0x30100004, 0x1234)
                self.call(u, 0xC0121D19, irq=True)
                if index == 7:
                    self.assertEqual(self.word(u, 0x30100004), capture.trial)
            self.assertEqual(self.word(u, SLOT), 0)
            if change_mode:
                self.assertEqual(self.word(u, 0x30100004), 0x1234)
                self.assertEqual(self.word(u, addresses['vparam']+44), 2)
                self.assertEqual(self.word(u, addresses['vparam']+8), 12)
            elif mutate:
                with self.assertRaises(AssertionError):
                    self.assertEqual(self.word(u, 0x30100004), slit.T04)
            else:
                self.assertEqual(self.word(u, 0x30100004), slit.T04)
                raw = bytes(u.mem_read(addresses['buffer'], capture.count*32))
                selected = slit.select_frames(raw, capture)
                self.assertEqual(selected, list(range(121, 121+frames)))
                self.assertEqual(u.mem_read(addresses['buffer']+capture.count*32, 32), b'\xa5'*32)


if __name__ == '__main__':
    unittest.main()
