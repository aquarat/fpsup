"""Offline stage0 ABI tests: the SAME loader.S, independent firmware oracles.

Run: python3 -B -m unittest -v test_firmware_profiles
Optional inspected, declared-length MAIN images: FPSUP_FP_MAIN / FPSUP_FPL_MAIN.
All placement below is synthetic, NOT evidence of an fp L cave or a working
card. Firmware routines are stubbed; stage2 is only an ARM `bx lr` fixture.
"""
import hashlib
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

from armasm import assemble
from firmware import get_camera

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
                                   UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                                   UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
                                   UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC, UC_ARM_REG_CPSR)
except ImportError:
    Uc = None

HERE = pathlib.Path(__file__).resolve().parent
# Literal oracles: deliberately do not parse firmware/*.h or derive one model
# from the other. A wrong selected address must fail, not move its stub with it.
EXPECTED = {
    'fp-5.02': dict(H_GET=0xC001D740, H_ADDR=0xC001D7F0, H_FREE=0xC001D7A0,
                   F_MGR=0xC0444658, F_VOL=0xC0444698, F_CTOR=0xC0365E90,
                   F_OPEN=0xC0365FB0, F_READ=0xC0366060, F_CLOSE=0xC0366020,
                   F_DTOR=0xC0365ED0, DCACHE=0xC000E91C, ICACHE=0xC000EABC,
                   TICK_US=0xC002B6E0, AR_START=0xC03DA758),
    'fp-l-3.02': dict(H_GET=0xC001D740, H_ADDR=0xC001D7F0, H_FREE=0xC001D7A0,
                     F_MGR=0xC04408B8, F_VOL=0xC04408F8, F_CTOR=0xC03660A8,
                     F_OPEN=0xC03661C8, F_READ=0xC0366278, F_CLOSE=0xC0366238,
                     F_DTOR=0xC03660E8, DCACHE=0xC000E91C, ICACHE=0xC000EABC,
                     TICK_US=0xC0029320, AR_START=0xC03DA970),
}
BASE, SCRATCH, HEAP, STACK, DONE = (0xC1000000, 0x45000000, 0x46000000,
                                    0x47000000, 0x48000000)
STAMP, NOW, MANAGER = SCRATCH + 0x20, 0x12345678, 0x45000100
BUFFER, STAGE2 = HEAP + 0x1000, HEAP + 0x1018
FILE = struct.pack('<7I', 0x4E494256, 1, 0, 4, 0, 4, 0xE12FFF1E)


def loader(name=None, profile=False):
    defines = [f'LOADER_BASE={BASE}', f'POOL_DESC={SCRATCH}',
               'BIN_PATH="\\\\fpSup.BIN"']
    if name is not None:
        defines += get_camera(name).loader_defines()
    if profile:
        defines += [f'LOAD_START_US={STAMP}']
    return assemble(HERE / 'asm/loader.S', defines)


def branches(code):
    """Decode ARM B/BL independently, including sign extension and PC bias."""
    for offset in range(0, len(code), 4):
        word = struct.unpack_from('<I', code, offset)[0]
        if word >> 24 in (0xEA, 0xEB):
            delta = word & 0xFFFFFF
            if delta & 0x800000:
                delta -= 0x1000000
            yield offset, BASE + offset + 8 + delta * 4


class Stage0:
    def __init__(self, test, name, code, *, allocation=True, files=(1,), volume=5):
        self.test, self.code = test, code
        self.allocation, self.files, self.volume = allocation, files, volume
        self.calls, self.opens, self.autorun = [], [], None
        self.by_address = {address: name for name, address in EXPECTED[name].items()}
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for address, size in ((0xC0000000, 0x600000), (BASE, 0x1000),
                              (SCRATCH, 0x1000), (HEAP, 0x10000),
                              (STACK - 0x10000, 0x10000), (DONE, 0x1000)):
            self.mu.mem_map(address, size)
        self.mu.mem_write(BASE, code)
        self.mu.hook_add(UC_HOOK_CODE, self.hook)

    def r(self, reg):
        return self.mu.reg_read(reg)

    def hook(self, mu, address, size, _):
        t = self.test
        if BASE <= address < BASE + len(self.code):
            return
        t.assertEqual(self.r(UC_ARM_REG_CPSR) & 0x20, 0, 'firmware calls must be ARM')
        if address == STAGE2:
            t.assertEqual(self.calls[-2:], ['DCACHE', 'ICACHE'])
            t.assertEqual(self.r(UC_ARM_REG_R0), BUFFER)
            t.assertEqual(self.r(UC_ARM_REG_SP) % 8, 0)
            self.calls.append('STAGE2')
            return  # execute the actual bx lr, rather than simulating a return
        t.assertIn(address, self.by_address,
                   f'unexpected firmware execution at {address:#010x}')
        name = self.by_address[address]
        self.calls.append(name)
        args = tuple(self.r(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                         UC_ARM_REG_R2, UC_ARM_REG_R3))
        value = 0
        if name == 'AR_START':
            self.autorun = (*args[:2], self.r(UC_ARM_REG_LR), self.r(UC_ARM_REG_SP))
        else:
            t.assertEqual(self.r(UC_ARM_REG_SP) % 8, 0, name)
        if name == 'H_GET':
            t.assertEqual(args, (SCRATCH, 0, 0x10000, 0))
        elif name == 'H_ADDR':
            t.assertEqual(args[0], SCRATCH)
            value = HEAP if self.allocation else 0
        elif name == 'H_FREE':
            t.assertEqual(args[:2], (SCRATCH, 2))
        elif name == 'F_MGR':
            value = MANAGER
        elif name == 'F_VOL':
            t.assertEqual(args[:2], (MANAGER, 0))
            value = self.volume
        elif name == 'F_CTOR':
            t.assertEqual(args[0], HEAP)
            self.current_volume = args[1]
        elif name == 'F_OPEN':
            t.assertEqual((args[0], args[2]), (HEAP, 1))
            path = bytes(mu.mem_read(args[1], 32)).split(b'\0')[0]
            t.assertEqual(path, b'\\fpSup.BIN')
            self.opens.append(self.current_volume)
            value = int(self.current_volume in self.files)
        elif name == 'F_READ':
            t.assertEqual(args, (HEAP, BUFFER, 0xF000, 0))
            mu.mem_write(BUFFER, FILE)
            value = len(FILE)
        elif name == 'F_CLOSE':
            t.assertEqual(args[0], HEAP)
        elif name == 'F_DTOR':
            t.assertEqual(args[:2], (HEAP, 2))
        elif name == 'TICK_US':
            value = NOW
        # Force real AAPCS caller-save handling, particularly around profiling.
        for reg in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12):
            mu.reg_write(reg, 0xBAD00000 + reg)
        mu.reg_write(UC_ARM_REG_R0, value)
        mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))

    def run(self, hook=False):
        saved = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                 UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
        for reg in saved:
            self.mu.reg_write(reg, 0xABC00000 + reg)
        sp = STACK - (4 if hook else 8)  # hook must tolerate stock misalignment
        self.mu.reg_write(UC_ARM_REG_SP, sp)
        self.mu.reg_write(UC_ARM_REG_LR, DONE)
        self.mu.reg_write(UC_ARM_REG_R0, 0x12340000)
        self.mu.reg_write(UC_ARM_REG_R1, 1)
        self.mu.emu_start(BASE + (4 if hook else 0), DONE, count=2000)
        self.test.assertEqual(self.r(UC_ARM_REG_PC), DONE, 'loader did not return')
        self.test.assertEqual(self.r(UC_ARM_REG_SP), sp)
        for reg in saved:
            self.test.assertEqual(self.r(reg), 0xABC00000 + reg)
        return self.r(UC_ARM_REG_R0)


@unittest.skipIf(Uc is None, 'requires unicorn')
class LoaderProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = {(name, profile): loader(name, profile)
                    for name in EXPECTED for profile in (False, True)}

    def test_selected_arm_branches_reach_literal_firmware_map(self):
        for (name, profile), code in self.code.items():
            with self.subTest(camera=name, profile=profile):
                expected = set(EXPECTED[name].values())
                if not profile:
                    expected.remove(EXPECTED[name]['TICK_US'])
                targets = {target for _, target in branches(code)
                           if not BASE <= target < BASE + len(code)}
                self.assertEqual(targets, expected)
                for offset, target in branches(code):
                    self.assertEqual(target % 4, 0)
                    self.assertTrue(-(1 << 25) <= target - (BASE + offset + 8) < (1 << 25))

    def test_success_closes_and_frees_after_publishing_stage2(self):
        for (name, profile), code in self.code.items():
            with self.subTest(camera=name, profile=profile):
                cam = Stage0(self, name, code, volume=1)
                self.assertEqual(cam.run(), 1)
                self.assertEqual(cam.calls, (['TICK_US'] if profile else []) + [
                    'H_GET', 'H_ADDR', 'F_MGR', 'F_VOL', 'F_CTOR', 'F_OPEN',
                    'F_READ', 'F_CLOSE', 'F_DTOR', 'DCACHE', 'ICACHE', 'STAGE2', 'H_FREE'])
                self.assertEqual(struct.unpack('<I', cam.mu.mem_read(STAMP, 4))[0],
                                 NOW if profile else 0)

    def test_allocation_failure_returns_without_file_io_or_free(self):
        for name in EXPECTED:
            with self.subTest(camera=name):
                cam = Stage0(self, name, self.code[name, False], allocation=False)
                self.assertEqual(cam.run(), 0)
                self.assertEqual(cam.calls, ['H_GET', 'H_ADDR'])

    def test_ssd_miss_destroys_object_then_retries_sd(self):
        for name in EXPECTED:
            with self.subTest(camera=name):
                cam = Stage0(self, name, self.code[name, False])
                self.assertEqual(cam.run(), 1)
                self.assertEqual(cam.opens, [5, 1])
                self.assertEqual(cam.calls, [
                    'H_GET', 'H_ADDR', 'F_MGR', 'F_VOL', 'F_CTOR', 'F_OPEN',
                    'F_DTOR', 'F_CTOR', 'F_OPEN', 'F_READ', 'F_CLOSE', 'F_DTOR',
                    'DCACHE', 'ICACHE', 'STAGE2', 'H_FREE'])

    def test_missing_file_frees_and_hook_fallback_preserves_args_lr_sp(self):
        for name in EXPECTED:
            for hook in (False, True):
                with self.subTest(camera=name, hook=hook):
                    cam = Stage0(self, name, self.code[name, True], files=())
                    self.assertEqual(cam.run(hook), 0)
                    self.assertEqual(cam.opens, [5, 1])
                    self.assertEqual(cam.calls, [
                        'TICK_US', 'H_GET', 'H_ADDR', 'F_MGR', 'F_VOL', 'F_CTOR',
                        'F_OPEN', 'F_DTOR', 'F_CTOR', 'F_OPEN', 'F_DTOR', 'H_FREE']
                        + (['AR_START'] if hook else []))
                    self.assertEqual(cam.autorun,
                                     (0x12340000, 1, DONE, STACK - 4) if hook else None)

    def test_wrong_model_call_mutation_is_rejected(self):
        # Break exactly one instruction IN MEMORY. The independent oracle must
        # reject the fp F_MGR target in the fp L loader, even though it is ARM.
        code = bytearray(self.code['fp-l-3.02', False])
        offsets = [off for off, target in branches(code)
                   if target == 0xC04408B8]
        self.assertEqual(len(offsets), 1)
        off = offsets[0]
        struct.pack_into('<I', code, off,
                         0xEB000000 | (((0xC0444658 - BASE - off - 8) >> 2) & 0xFFFFFF))
        with self.assertRaisesRegex(AssertionError, 'unexpected firmware execution at 0xc0444658'):
            Stage0(self, 'fp-l-3.02', bytes(code)).run()


class ProfileBuildTests(unittest.TestCase):
    def build(self, out, *args):
        return subprocess.run([sys.executable, '-B', str(HERE / 'build_autorun.py'),
                               '--loader', '--no-four-box-bar', '--out', str(out), *args],
                              capture_output=True, text=True)

    def test_default_and_explicit_fp_artifacts_are_identical(self):
        self.assertEqual(loader(), loader('fp-5.02'))
        with tempfile.TemporaryDirectory() as tmp:
            dirs = [pathlib.Path(tmp) / name for name in ('default', 'explicit')]
            for directory, args in zip(dirs, ((), ('--camera', 'fp-5.02'))):
                result = self.build(directory / 'AutoRun.txt', *args)
                self.assertEqual(result.returncode, 0, result.stderr)
            def artifacts(directory):
                return {str(p.relative_to(directory)): p.read_bytes()
                        for p in directory.rglob('*') if p.is_file()}
            default = artifacts(dirs[0])
            self.assertIn('AutoRun.txt', default)
            self.assertIn('fpSup.BIN', default)
            self.assertEqual(default, artifacts(dirs[1]))

    def test_fpl_refusal_creates_nothing_and_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp) / 'card'
            for existing in (False, True):
                with self.subTest(existing=existing):
                    if existing:
                        directory.mkdir()
                        for name in ('AutoRun.txt', 'fpSup.BIN'):
                            (directory / name).write_bytes(b'existing output\x00' + name.encode())
                    before = {p.name: p.read_bytes() for p in directory.glob('*')}
                    result = self.build(directory / 'AutoRun.txt', '--camera', 'fp-l-3.02')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('generic product-card packaging is not supported yet', result.stderr)
                    self.assertEqual(directory.exists(), existing)
                    self.assertEqual({p.name: p.read_bytes() for p in directory.rglob('*')
                                      if p.is_file()}, before)

    def test_unknown_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unknown camera firmware'):
            get_camera('fp-l-5.02')
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / 'absent' / 'AutoRun.txt'
            result = self.build(out, '--camera', 'fp-l-5.02')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('invalid choice', result.stderr)
            self.assertFalse(out.parent.exists())


class ProfileHeaderTests(unittest.TestCase):
    """The stage2 constants, against literals from the research inventory.

    Independent on purpose: the values here come from the fp-vs-fp L research
    pass (prerequisites/inventory.json), not from the headers -- a header
    edited to a wrong address must fail here, not pass silently because the
    build-time .equ moved with it.
    """
    STAGE2 = {
        'fp-5.02': dict(FW_FRAMEBUF=0xC3757A7C, FW_MEM_HEAP=0xC001CF78,
                        FW_MEM_GET=0xC001D038, FW_POFF_MGR=0xC0023A98,
                        FW_POFF_ADD=0xC0024118, FW_CAVE_LO=0xC072D000,
                        FW_CAVE_HI=0xC0735000, FW_LH_SITE=0xC03DA420),
        # fp L has no cave: its structural counterpart is IMU-owned image
        # space, so the journal exclusion is EMPTY (LO == HI) and resident
        # code lives in payload-allocated memory instead.
        'fp-l-3.02': dict(FW_FRAMEBUF=0xC37588BC, FW_MEM_HEAP=0xC001CF78,
                         FW_MEM_GET=0xC001D038, FW_POFF_MGR=0xC00239B8,
                         FW_POFF_ADD=0xC0024038, FW_CAVE_LO=0xC072B8E4,
                         FW_CAVE_HI=0xC072B8E4, FW_LH_SITE=0xC03DA638),
    }

    def test_stage2_constants_per_camera(self):
        for name, want in self.STAGE2.items():
            defines = get_camera(name).loader_defines()
            camera = defines[0].split('=')[1]
            lines = [f'#include "firmware/loader.h"']
            for constant, value in want.items():
                lines += [f'#if {constant} != 0x{value:08X}',
                          f'#error {constant} is wrong for {name}', '#endif']
            with tempfile.TemporaryDirectory() as tmp:
                src = pathlib.Path(tmp) / 'check.h'
                src.write_text('\n'.join(lines) + '\n')
                r = subprocess.run(['clang', '-target', 'armv7-none-eabi',
                                   f'-DFPSUP_CAMERA={camera}',
                                   '-I', str(HERE), '-E', str(src)],
                                  capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn('#error', r.stdout)


class OfficialImageTests(unittest.TestCase):
    def check_image(self, env, name, size, digest, table, echo, hook):
        if not os.environ.get(env):
            self.skipTest(f'set {env} to the inspected declared-length MAIN image')
        path = pathlib.Path(os.environ[env])
        image = path.read_bytes()
        self.assertEqual(len(image), size)
        self.assertEqual(hashlib.sha256(image).hexdigest(), digest)
        self.assertEqual(get_camera(name).verify_main(path), image)
        offset = table - 0xC0000000 + 17 * 0x18
        self.assertEqual(image[offset:offset + 20], b'echo' + b'\0' * 16)
        self.assertEqual(struct.unpack_from('<I', image, offset + 20)[0], echo)
        self.assertEqual(struct.unpack_from('<I', image, hook - 0xC0000000)[0], 0xEB0000CC)
        self.assertEqual(hook + 8 + 0xCC * 4, EXPECTED[name]['AR_START'])

    def test_fp_image_fingerprint_and_stock_sites(self):
        self.check_image('FPSUP_FP_MAIN', 'fp-5.02', 49245696,
                         'aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622',
                         0xC0BAC14C, 0xC03D99A0, 0xC03DA420)

    def test_fpl_image_fingerprint_and_stock_sites(self):
        self.check_image('FPSUP_FPL_MAIN', 'fp-l-3.02', 49310208,
                         'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9',
                         0xC0BD2398, 0xC03D9BB8, 0xC03DA638)


if __name__ == '__main__':
    unittest.main()
