"""Execute stock fp L mem-save parsing and file-write adapter under Unicorn.

Requires the private official MAIN image via FPSUP_FPL_MAIN. Firmware file
services are stubbed; this does not emulate an SD card or prove AutoRun boot.
"""
import os
from pathlib import Path
import struct
import tempfile
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_SP,
                               UC_CPU_ARM_CORTEX_A15)

from fpl_probe import BASE, CAMERA, REGIONS, autorun, build, inspect


class NativeProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('FPSUP_FPL_MAIN'):
            raise unittest.SkipTest('set FPSUP_FPL_MAIN to the inspected official MAIN image')
        cls.main = Path(os.environ['FPSUP_FPL_MAIN'])
        cls.image = CAMERA.verify_main(cls.main)

    def execute(self, line, expected):
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A15)
        mu.mem_map(BASE, 0x4000000)
        mu.mem_write(BASE, self.image)
        mu.mem_map(0x10000000, 0x20000)
        done, printer = 0x10000100, 0x10000200
        ctx, argv, strings = 0x10001000, 0x10001100, 0x10002000
        mu.mem_write(ctx, struct.pack('<I', printer))
        fields = line.split()
        self.assertEqual(fields[0], 'mem')
        pointers = []
        for text in fields[1:]:
            pointers.append(strings)
            raw = text.encode('ascii') + b'\0'
            mu.mem_write(strings, raw)
            strings += len(raw)
        mu.mem_write(argv, struct.pack(f'<{len(pointers)}I', *pointers))
        mu.reg_write(UC_ARM_REG_R0, ctx)
        mu.reg_write(UC_ARM_REG_R1, len(pointers))
        mu.reg_write(UC_ARM_REG_R2, argv)
        mu.reg_write(UC_ARM_REG_SP, 0x1001FFF0)
        mu.reg_write(UC_ARM_REG_LR, done)
        calls = []
        saved = []

        def text(at):
            return bytes(mu.mem_read(at, 256)).split(b'\0')[0].decode('ascii')

        def hook(uc, address, size, _):
            r0, r1, r2 = [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
            value = 1
            if address == printer:
                value = 0
            elif address == 0xC04408B8:
                calls.append('manager')
                value = 0x12340000
            elif address == 0xC04408F8:
                self.assertEqual((r0, r1), (0x12340000, 0))
                calls.append('volume')
            elif address == 0xC03660A8:
                self.assertEqual(r1, 1)
                calls.append('construct')
            elif address == 0xC03661C8:
                self.assertEqual(text(r1), f'\\FPLPROBE\\{expected[0]}.BIN')
                self.assertEqual(r2, 0x402)
                calls.append('open')
            elif address == 0xC0366300:
                # Independent oracle: compare the real parser's file-write
                # arguments to the intended region, not back to parsed text.
                self.assertEqual((r1, r2), (expected[1], expected[2]))
                saved.append(bytes(uc.mem_read(r1, r2)))
                calls.append('write')
                value = 1  # XC_File write returns a boolean, not byte count.
            elif address == 0xC0366238:
                calls.append('close')
            elif address == 0xC03660E8:
                self.assertEqual(r1, 2)
                calls.append('destroy')
            else:
                return
            uc.reg_write(UC_ARM_REG_R0, value)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        def writes(uc, access, address, size, value, _):
            # Stock parser owns two BSS cursor words; everything else it
            # writes must be in this test's arguments or stack, never a probe
            # target, a firmware patch, settings or MMIO.
            self.assertTrue(0x10000000 <= address < 0x10020000 or
                            0xC37588B4 <= address and address + size <= 0xC37588BC,
                            f'unexpected native memory write at {address:#x}')

        mu.hook_add(UC_HOOK_CODE, hook)
        mu.hook_add(UC_HOOK_MEM_WRITE, writes)
        mu.emu_start(0xC03FA4C0, done, count=200000)
        self.assertEqual(mu.reg_read(UC_ARM_REG_PC), done)
        self.assertEqual(calls, ['manager', 'volume', 'construct', 'open', 'write', 'close', 'destroy'])
        self.assertEqual(len(saved), 1)
        return saved[0]

    def test_generated_commands_through_native_handler(self):
        for line, region in zip(autorun().decode().splitlines(), REGIONS, strict=True):
            with self.subTest(region=region[0]):
                data = self.execute(line, region)
                if region[3]:
                    self.assertEqual(data, self.image[region[1]-BASE:region[1]-BASE+region[2]])

    def test_changed_range_is_detected_by_execution_oracle(self):
        line = autorun().decode().splitlines()[0].replace('0x200', '0x204')
        with self.assertRaises(AssertionError):
            self.execute(line, REGIONS[0])

    def test_result_check_rejects_missing_truncated_and_changed_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = Path(tmp)
            self.assertFalse(inspect(self.main, results)['complete'])
            for name, addr, size, immutable, _ in REGIONS:
                data = self.image[addr-BASE:addr-BASE+size] if immutable else bytes(size)
                (results / (name + '.BIN')).write_bytes(data)
            self.assertTrue(inspect(self.main, results)['complete'])
            (results / 'DONE.BIN').write_bytes(b'old')
            self.assertFalse(inspect(self.main, results)['complete'])
            addr, size = REGIONS[-1][1:3]
            (results / 'DONE.BIN').write_bytes(self.image[addr-BASE:addr-BASE+size])
            (results / 'ARUN.BIN').write_bytes(bytes(REGIONS[0][2]))
            self.assertFalse(inspect(self.main, results)['complete'])

    def test_build_refuses_wrong_image_or_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / 'bad.bin'
            bad.write_bytes(b'not firmware')
            with self.assertRaises(ValueError):
                build(bad, root / 'absent')
            self.assertFalse((root / 'absent').exists())
            out = root / 'probe'
            build(self.main, out)
            before = (out / 'card/AutoRun.txt').read_bytes()
            with self.assertRaises(FileExistsError):
                build(self.main, out)
            self.assertEqual((out / 'card/AutoRun.txt').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
