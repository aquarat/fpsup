"""Offline upload/readback faults and real shared writer ARM execution."""
from pathlib import Path
import hashlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
from armasm import assemble
import fpl_getfile as gf
import fpl_putfile as pf
from test_fpl_getfile import Fake, CAPS, PUB


class UploadFake(Fake):
    def __init__(self, fault=None):
        super().__init__(fault)
        self.file = b'old-tail' if fault == 'tail' else b''
        self.writes = 0

    def sh(self, line, **kwargs):
        if line == 'echo' and self.slot == self.plan.code:
            p = bytearray(self.memory[self.plan.param])
            mode = struct.unpack_from('<I', p, 0x20)[0]
            if mode == 7:
                self.events.append(('echo', self.slot))
                if self.fault == self.slot:
                    raise OSError('uncertain write')
                self.writes += 1
                self.file = self.memory[self.plan.buffer][:3] + self.file[3:]
                struct.pack_into('<3I', p, 8, 4 if self.fault == 'write' else 2,
                                 0 if self.fault == 'open' else 1, 1)
                if self.fault == 'parameter':
                    struct.pack_into('<I', p, 0x14, 0)
                self.memory[self.plan.param] = bytes(p)
                return ''
            result = super().sh(line, **kwargs)
            p = bytearray(self.memory[self.plan.param])
            struct.pack_into('<I', p, 4, len(self.file))
            self.memory[self.plan.param] = bytes(p)
            self.memory[self.plan.buffer] = b'xyz' if self.fault == 'mismatch' else self.file
            return result
        return super().sh(line, **kwargs)


class Host(unittest.TestCase):
    def run_fake(self, fake):
        # Real flock: proves write+download do not try to nest the lock.
        with tempfile.TemporaryDirectory() as tmp, patch.object(gf, 'LOCK_PATH', Path(tmp) / 'lock'):
            return pf.upload('\\UPTEST.BIN', b'abc', 3, fake)

    def test_complete_roundtrip(self):
        fake = UploadFake()
        self.assertEqual(self.run_fake(fake), hashlib.sha256(b'abc').hexdigest())
        self.assertEqual(fake.file, b'abc')
        self.assertEqual(fake.writes, 1)
        self.assertEqual([e[1] for e in fake.events if e[0] == 'echo'],
                         [gf.DCACHE, gf.ICACHE, fake.plan.code] * 2)
        self.assertEqual(fake.slot, gf.ECHO_STOCK)

    def test_lock_held_during_both_operations(self):
        test = self

        class LockedFake(UploadFake):
            def sh(self, line, **kwargs):
                with test.assertRaises(BlockingIOError):
                    with gf.staging_lock():
                        test.fail('staging was not locked')
                return super().sh(line, **kwargs)

        self.run_fake(LockedFake())

    def test_capacity_refused_before_staging(self):
        fake = UploadFake()
        size = CAPS['pool_size'] - gf.STAGING_OFFSET - 3 * 1024 - gf.SLACK + 1
        with tempfile.TemporaryDirectory() as tmp, patch.object(gf, 'LOCK_PATH', Path(tmp) / 'lock'):
            with self.assertRaisesRegex(ValueError, 'exceeds available staging'):
                pf.upload('\\TOOBIG.BIN', bytes(size), size, fake)
        self.assertFalse(fake.events)

    def test_faults_and_restoration(self):
        for fault in ('version', 'publication', 'upload', 'open', 'write', 'parameter',
                      'tail', 'mismatch', 'short', gf.DCACHE, gf.ICACHE,
                      PUB[0] + gf.STAGING_OFFSET, ('slot', gf.ICACHE)):
            with self.subTest(fault=fault):
                fake = UploadFake(fault)
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    self.run_fake(fake)
                self.assertEqual(fake.slot, gf.ECHO_STOCK)
                self.assertLessEqual(fake.writes, 1)

    def test_tail_explicit_rejection(self):
        fake = UploadFake('tail')
        with self.assertRaisesRegex(RuntimeError, 'file length 8, expected 3; refusing a prefix'):
            self.run_fake(fake)
        self.assertEqual(fake.file, b'abc-tail')  # no pretend truncation/rollback

    def test_restore_failure(self):
        with self.assertRaisesRegex(RuntimeError, 'echo slot'):
            self.run_fake(UploadFake(('slot', gf.ECHO_STOCK)))

    def test_local_bounds_before_io(self):
        with patch.object(gf, 'Backend', side_effect=AssertionError('must stay offline')):
            for remote, data, size in [('\\X', b'abc', 2), ('\\X', b'abc', -1),
                                       ('\\..\\X', b'abc', 3), ('\\', b'abc', 3)]:
                with self.assertRaises(ValueError):
                    pf.upload(remote, data, size)

    def test_help_offline(self):
        result = subprocess.run([sys.executable, str(gf.HERE / 'fpl_putfile.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--size', result.stdout)


CALLS = {
    502: [0xC0444658, 0xC0444698, 0xC0365E90, 0xC0365FB0,
          0xC03660E8, 0xC0366020, 0xC0365ED0],
    10302: [0xC04408B8, 0xC04408F8, 0xC03660A8, 0xC03661C8,
            0xC0366300, 0xC0366238, 0xC03660E8],
}


class Payload(unittest.TestCase):
    def test_fp_bytes_unchanged(self):
        # Pin the public pre-port source, including upstream's directory move.
        # HEAD would compare the implementation to itself after committing.
        reference = ('e79e3f1ff4622bce0b8a4cee9d322f184d7f6696:'
                     'fpSup/fp_usb_shell/asm/putfile.S')
        old = subprocess.check_output(['git', 'show', reference], cwd=gf.HERE)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'old.S'
            source.write_bytes(old)
            self.assertEqual(assemble(source), assemble(gf.HERE / 'asm/putfile.S'))

    def emulate(self, camera, opened=1, written=1, mutation=None):
        code_at, param, fobj, buf = 0x45010000, 0x45010400, 0x45010800, 0x45010C00
        code = bytearray(assemble(gf.HERE / 'asm/putfile.S',
                                 [f'FPSUP_CAMERA={camera}', f'P={param}']))
        if mutation:
            before, after = {'length': (0xE1A02005, 0xE3A02000),
                             'write-result': (0x13A06002, 0x13A06004)}[mutation]
            target = struct.pack('<I', before)
            self.assertEqual(code.count(target), 1)
            at = code.index(target)
            code[at:at + 4] = struct.pack('<I', after)
        mu = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
        mu.mem_map(0x45000000, 0x20000)
        stop, printf = 0x47000000, 0x47000004
        mu.mem_map(stop, 0x1000)
        for page in {a & ~0xFFF for a in CALLS[camera]}:
            mu.mem_map(page, 0x1000)
        mu.mem_write(code_at, bytes(code))
        mu.mem_write(param, pf.parameters(gf.Layout(code_at, param, fobj, buf, 0x1003), b'\\TEST.BIN\0', 3))
        mu.mem_write(buf, b'abc')
        mu.mem_write(0x45000000, struct.pack('<I', printf))
        mu.reg_write(ar.UC_ARM_REG_R0, 0x45000000)
        mu.reg_write(ar.UC_ARM_REG_SP, 0x4501F000)
        mu.reg_write(ar.UC_ARM_REG_LR, stop)
        saved = {reg: 0x12340000 + reg for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11 + 1)}
        for reg, value in saved.items():
            mu.reg_write(reg, value)
        events = []

        def hook(machine, address, length, unused):
            if address == stop:
                machine.emu_stop()
                return
            if address not in CALLS[camera] and address != printf:
                return
            self.assertEqual(machine.reg_read(ar.UC_ARM_REG_SP) % 8, 0)
            r = [machine.reg_read(reg) for reg in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1, ar.UC_ARM_REG_R2)]
            if address == printf:
                if camera == 10302:
                    self.assertEqual(bytes(machine.mem_read(r[0], 4)), b'%s \0')
            else:
                index = CALLS[camera].index(address)
                events.append(index)
                if index == 3:
                    self.assertEqual(r, [fobj, param + 0x24, 7])
                if index == 4:
                    self.assertEqual(r, [fobj, buf, 3], 'write arguments')
                    self.assertEqual(bytes(machine.mem_read(r[1], r[2])), b'abc')
                if index == 6:
                    self.assertEqual(r[:2], [fobj, 2])
                machine.reg_write(ar.UC_ARM_REG_R0, opened if index == 3 else written if index == 4 else 1)
            machine.reg_write(ar.UC_ARM_REG_PC, machine.reg_read(ar.UC_ARM_REG_LR))

        mu.hook_add(uc.UC_HOOK_CODE, hook)
        mu.emu_start(code_at, stop + 8, count=1000)
        self.assertEqual(mu.reg_read(ar.UC_ARM_REG_PC), stop)
        self.assertEqual(mu.reg_read(ar.UC_ARM_REG_SP), 0x4501F000)
        for reg, value in saved.items():
            self.assertEqual(mu.reg_read(reg), value)
        self.assertEqual(struct.unpack('<I', mu.mem_read(param + 8, 4))[0],
                         3 if not opened else 2 if written else 4, 'write status')
        self.assertEqual(events, list(range(7)) if opened else [0, 1, 2, 3, 6])

    def test_both_profiles(self):
        for camera in CALLS:
            for opened, written in ((1, 1), (0, 1), (1, 0)):
                with self.subTest(camera=camera, opened=opened, written=written):
                    self.emulate(camera, opened, written)

    def test_mutations_caught(self):
        for mutation, message in [('length', 'write arguments'), ('write-result', 'write status')]:
            with self.subTest(mutation=mutation), self.assertRaisesRegex(AssertionError, message):
                self.emulate(10302, mutation=mutation)


if __name__ == '__main__':
    unittest.main()
