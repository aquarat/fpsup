"""Offline host fault injection and real shared getfile ARM execution."""
from contextlib import nullcontext
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
from armasm import assemble
import fpl_getfile as gf

POOL, ROOM, WORKER = 0x4533AEC0, 0x100000, 0x46000000
CAPS = dict(pool=POOL, pool_size=ROOM, xfer=16776192)
PUB = [POOL, ROOM, WORKER]


class Fake:
    def __init__(self, fault=None):
        self.fault = fault
        self.slot = gf.ECHO_STOCK
        self.events = []
        self.memory = {}
        self.plan = gf.layout(CAPS, PUB, 3)

    def sh(self, line, **kwargs):
        if line == 'version':
            return ('Ver.5.02' if self.fault == 'version' else
                    'model       = w91c1 \nrel version = 3.02.0.V90  \n')
        assert kwargs['retries'] == 0
        self.events.append(('echo', self.slot))
        if self.fault == self.slot:
            raise OSError('lost echo response')
        if self.slot == self.plan.code:
            p = bytearray(self.memory[self.plan.param])
            struct.pack_into('<4I', p, 4, 4 if self.fault == 'tail' else 3,
                             4 if self.fault == 'read' else 2, 1, 1)
            if self.fault == 'parameter':
                struct.pack_into('<I', p, 0x14, 0)
            self.memory[self.plan.param] = bytes(p)
            self.memory[self.plan.buffer] = b'abc'
        return ''

    def words(self, address, count=1):
        if address == gf.PUBLICATION:
            return PUB[:2] + [0] if self.fault == 'publication' else list(PUB)
        return [self.slot]

    def set_word(self, address, value):
        assert address == gf.ECHO_SLOT
        self.events.append(('slot', value))
        if self.fault != ('slot', value):
            self.slot = value

    def caps(self):
        return CAPS

    def write(self, address, data):
        self.events.append(('write', address))
        self.memory[address] = data

    def read(self, address, size):
        data = self.memory[address][:size]
        if self.fault == 'upload' or (self.fault == 'short' and address == self.plan.buffer):
            return data[:-1]
        return data


class Host(unittest.TestCase):
    def run_fake(self, fake):
        with patch.object(gf, 'staging_lock', nullcontext):
            return gf.download('\\TEST.BIN', 3, fake)

    def test_success_order_and_complete_bytes(self):
        fake = Fake()
        self.assertEqual(self.run_fake(fake), b'abc')
        self.assertEqual([e[1] for e in fake.events if e[0] == 'echo'],
                         [gf.DCACHE, gf.ICACHE, fake.plan.code])
        self.assertEqual(fake.events[-1], ('slot', gf.ECHO_STOCK))
        self.assertEqual(fake.slot, gf.ECHO_STOCK)

    def test_faults_restore_and_refuse(self):
        for fault in ('version', 'publication', 'upload', 'tail', 'read',
                      'parameter', 'short', gf.DCACHE, gf.ICACHE,
                      POOL + gf.STAGING_OFFSET, ('slot', gf.ICACHE)):
            with self.subTest(fault=fault):
                fake = Fake(fault)
                with self.assertRaises((ValueError, RuntimeError, OSError)):
                    self.run_fake(fake)
                self.assertEqual(fake.slot, gf.ECHO_STOCK)
                if fault in ('version', 'publication', 'upload'):
                    self.assertFalse(any(e[0] == 'echo' for e in fake.events))
                else:
                    self.assertIn(('echo', gf.DCACHE), fake.events)

    def test_failed_restore_is_not_success(self):
        fake = Fake(('slot', gf.ECHO_STOCK))
        with self.assertRaisesRegex(RuntimeError, 'echo slot'):
            self.run_fake(fake)

    def test_bounds_and_path(self):
        max_size = ROOM - gf.STAGING_OFFSET - 3 * 0x400 - gf.SLACK
        self.assertEqual(gf.layout(CAPS, PUB, max_size).buffer + max_size + gf.SLACK,
                         POOL + ROOM)
        for size in (-1, max_size + 1, 2**32):
            with self.assertRaises(ValueError):
                gf.layout(CAPS, PUB, size)
        for pub in ([POOL + 1, ROOM, WORKER], [POOL, ROOM, POOL],
                    [POOL, ROOM, None], [POOL, ROOM - 4, WORKER]):
            with self.assertRaises(ValueError):
                gf.layout(CAPS, pub, 3)
        for path in ('relative', '\\bad\0name', '\\' + 'x' * 188, '\\a\n'):
            with self.assertRaises(ValueError):
                gf.validate_request(path, 3)

    def test_prefix_asks_exact_count_and_refuses_mismatch(self):
        whole = gf.layout(CAPS, PUB, 3)
        prefix = gf.layout(CAPS, PUB, 3, prefix=True)
        self.assertEqual(whole.ask, 3 + gf.SLACK)
        self.assertEqual(prefix.ask, 3)
        self.assertEqual(prefix.buffer, whole.buffer)
        with self.assertRaises(ValueError):
            gf.layout(CAPS, PUB, 0, prefix=True)
        fake = Fake()
        fake.plan = prefix
        with patch.object(gf, 'staging_lock', nullcontext):
            self.assertEqual(gf.download('\\TEST.BIN', 3, fake, prefix=True), b'abc')
        # The parameter block carries the exact prefix count, not count + slack.
        self.assertEqual(struct.unpack_from('<I', fake.memory[prefix.param], 0x18)[0], 3)
        for fault in ('tail', 'short', 'read'):
            with self.subTest(fault=fault):
                fake = Fake(fault)
                fake.plan = prefix
                with patch.object(gf, 'staging_lock', nullcontext), \
                        self.assertRaises(RuntimeError):
                    gf.download('\\TEST.BIN', 3, fake, prefix=True)
                self.assertEqual(fake.slot, gf.ECHO_STOCK)

    def test_real_lock_excludes_second_holder(self):
        # A temporary lock path, never the live lock or any camera transport.
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp, patch.object(gf, 'LOCK_PATH', Path(tmp) / 'lock'):
            with gf.staging_lock():
                with self.assertRaises(BlockingIOError):
                    with gf.staging_lock():
                        self.fail('second holder acquired staging')

    def test_ack_count(self):
        class Memory:
            name = 'offline'
            buf = bytearray(8)
        for answer in ('OKR 3 1.0', 'OKW 4 1.0', 'ERR uncertain', 'OKR 4'):
            with patch.object(gf.transport, '_shared', return_value=Memory()), \
                    patch.object(gf.transport, 'mem_line', return_value=answer):
                with self.assertRaises(RuntimeError):
                    gf.Backend().read(0x44010000, 4)

    def test_help_import_offline(self):
        result = subprocess.run([sys.executable, str(gf.HERE / 'fpl_getfile.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--size', result.stdout)
        self.assertIn('--prefix', result.stdout)


# Independent literal call addresses; these are not read from the headers.
CALLS = {
    502: [0xC0444658, 0xC0444698, 0xC0365E90, 0xC0365FB0,
          0xC0366060, 0xC0366020, 0xC0365ED0],
    10302: [0xC04408B8, 0xC04408F8, 0xC03660A8, 0xC03661C8,
            0xC0366278, 0xC0366238, 0xC03660E8],
}


class Payload(unittest.TestCase):
    def emulate(self, camera, opened=1, read=1, buffer=True, mutation=False):
        code_at, param, fobj, buf = 0x45010000, 0x45010400, 0x45010800, 0x45010C00
        defines = [f'FPSUP_CAMERA={camera}', f'P={param}']
        code = bytearray(assemble(gf.HERE / 'asm/getfile.S', defines))
        if mutation:
            # Real machine-code mutation: replace the actual-count pointer
            # argument with P_STATUS. Our result oracle must catch this.
            instruction = struct.pack('<I', 0xE2843004)  # add r3,r4,#4
            self.assertEqual(code.count(instruction), 1)
            offset = code.index(instruction)
            code[offset:offset + 4] = struct.pack('<I', 0xE2843008)
        machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
        machine.mem_map(0x45000000, 0x20000)
        stop, printf = 0x47000000, 0x47000004
        machine.mem_map(stop, 0x1000)
        for page in {a & ~0xFFF for a in CALLS[camera]}:
            machine.mem_map(page, 0x1000)
        machine.mem_write(code_at, bytes(code))
        plan = gf.Layout(code_at, param, fobj, buf if buffer else 0, 0x1003)
        machine.mem_write(param, gf.parameters(plan, b'\\TEST.BIN\0'))
        machine.mem_write(0x45000000, struct.pack('<I', printf))
        machine.reg_write(ar.UC_ARM_REG_R0, 0x45000000)
        machine.reg_write(ar.UC_ARM_REG_SP, 0x4501F000)
        machine.reg_write(ar.UC_ARM_REG_LR, stop)
        saved = {}
        for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11 + 1):
            saved[reg] = 0x12340000 + reg
            machine.reg_write(reg, saved[reg])
        events = []

        def hook(mu, address, length, unused):
            if address == stop:
                mu.emu_stop()
                return
            if address not in CALLS[camera] and address != printf:
                return
            self.assertEqual(mu.reg_read(ar.UC_ARM_REG_SP) % 8, 0)
            if address == printf:
                mu.reg_write(ar.UC_ARM_REG_PC, mu.reg_read(ar.UC_ARM_REG_LR))
                return
            index = CALLS[camera].index(address)
            events.append(index)
            r = [mu.reg_read(x) for x in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1,
                                         ar.UC_ARM_REG_R2, ar.UC_ARM_REG_R3)]
            if index == 3:
                self.assertEqual(r[:3], [fobj, param + 0x24, 1])
            if index == 4:
                self.assertEqual(r[:3], [fobj, buf, 0x1003])
                mu.mem_write(r[3], struct.pack('<I', 3))
                mu.mem_write(buf, b'abc')
            mu.reg_write(ar.UC_ARM_REG_R0, opened if index == 3 else read if index == 4 else 1)
            mu.reg_write(ar.UC_ARM_REG_PC, mu.reg_read(ar.UC_ARM_REG_LR))

        machine.hook_add(uc.UC_HOOK_CODE, hook)
        machine.emu_start(code_at, stop + 8, count=1000)
        self.assertEqual(machine.reg_read(ar.UC_ARM_REG_PC), stop)
        self.assertEqual(machine.reg_read(ar.UC_ARM_REG_SP), 0x4501F000)
        for reg, value in saved.items():
            self.assertEqual(machine.reg_read(reg), value)
        actual, status = struct.unpack('<2I', machine.mem_read(param + 4, 8))
        if not buffer:
            self.assertEqual((actual, status, events), (0, 5, []))
        elif not opened:
            self.assertEqual((actual, status, events), (0, 3, [0, 1, 2, 3, 6]))
        else:
            self.assertEqual(actual, 3, 'actual count must use P_ACTUAL')
            self.assertEqual(status, 2 if read else 4)
            self.assertEqual(events, list(range(7)))

    def test_shared_reader_both_profiles(self):
        for camera in CALLS:
            for opened, read in ((1, 1), (0, 1), (1, 0)):
                with self.subTest(camera=camera, opened=opened, read=read):
                    self.emulate(camera, opened, read)

    def test_fpl_refuses_missing_supplied_buffer(self):
        self.emulate(10302, buffer=False)

    def test_mutation_wrong_actual_pointer_is_caught(self):
        with self.assertRaisesRegex(AssertionError, 'actual count'):
            self.emulate(10302, mutation=True)


if __name__ == '__main__':
    unittest.main()
