"""Real ARM handoff tests. Cache services are NO-OP simulations, not cache proof."""
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_R0
from armasm import symbols
import fpl_swapworker as sw

POOL, DEST, STACK = 0x45000000, 0x46000000, 0x47008000


class HandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body = sw.known_body()
        cls.p = sw.plan([POOL, 0x100000, DEST],
                        dict(pool=POOL, pool_size=0x100000, xfer=0x100000), 0x12345678)
        cls.code = sw.stub(cls.p)
        cls.labels = symbols(sw.gf.HERE / 'asm/fpl_swapworker.S',
                             [f'{k}={v}' for k, v in cls.p.items()])

    def emulate(self, mutation=None, abort=False, rounds=1, fault=0, upgrade=False):
        target = sw.reviewed_body(True) if upgrade else self.body
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for base, size in ((POOL, 0x100000), (DEST, 0x10000),
                           (STACK & ~0xFFFF, 0x10000), (0x48000000, 0x1000),
                           (0xC3758000, 0x1000), (0xC31E1000, 0x1000),
                           (0x2100C000, 0x1000), (0xC000E000, 0x1000),
                           (0xC01E3000, 0x1000)):
            mu.mem_map(base, size)
        def word(a, v):
            mu.mem_write(a, struct.pack('<I', v))
        def get(a):
            return struct.unpack('<I', mu.mem_read(a, 4))[0]
        mu.mem_write(DEST, self.body)
        mu.mem_write(sw.gf.PUBLICATION, struct.pack('<3I', POOL, 0x100000, DEST))
        word(POOL + 0x1000, 0x4C485356)
        word(POOL + 0x1008, fault)
        word(0x2100C720, 0x24)
        word(0xC31E1668, 0x48000000)
        mu.reg_write(UC_ARM_REG_SP, STACK)
        events, writes = [], []
        def hook(uc, a, size, _):
            if a in (sw.gf.DCACHE, sw.gf.ICACHE, 0xC01E35C8):
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP) % 8, 0)
                events.append(a)
                if a == sw.gf.DCACHE:
                    self.assertEqual(len(writes), sw.SIZE // 4)
                uc.reg_write(UC_ARM_REG_R0, 0)
                uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
            if a == 0xC01E3400:
                events.append(a)
                uc.emu_stop()
        def store(uc, access, a, size, value, _):
            if DEST <= a < DEST + sw.SIZE:
                self.assertTrue(self.p['STUB'] <= uc.reg_read(UC_ARM_REG_PC) < self.p['STUB'] + 1024)
                writes.append(a)
        mu.hook_add(UC_HOOK_CODE, hook)
        mu.hook_add(UC_HOOK_MEM_WRITE, store)
        for iteration in range(rounds):
            events.clear()
            writes.clear()
            code = bytearray(self.code)
            if mutation == 'stack':
                struct.pack_into('<I', code, self.labels['unwind'], 0xE1A00000)
            if mutation == 'destination':
                # Copy stores to r8 (already at the end after verification).
                offset = self.labels['copy'] + 4
                insn = struct.unpack_from('<I', code, offset)[0]
                struct.pack_into('<I', code, offset, (insn & ~0xF0000) | 0x80000)
            if mutation == 'cache':
                old, new = sw.gf.ICACHE, sw.gf.DCACHE
                code[:] = bytes(code).replace(struct.pack('<I', old), struct.pack('<I', new))
            mu.mem_write(self.p['STUB'], bytes(code))
            mu.mem_write(self.p['SOURCE'], target)
            mu.mem_write(self.p['EXPECTED_SOURCE'], self.body if iteration == 0 else target)
            if abort:
                word(self.p['EXPECTED_SOURCE'], 0)
            word(self.p['STATUS'], 0)
            word(POOL + 0x10C0, self.p['STUB'])
            word(POOL + 0x1080, 0x50415753)
            start = DEST + (120 if iteration == 0 else 200)
            mu.emu_start(start, 0, count=30000)
            self.assertEqual(events[-1], 0xC01E3400)
            self.assertEqual(mu.reg_read(UC_ARM_REG_SP), STACK - 32 - 24)
            self.assertEqual(get(POOL + 0x1080), 0)
            self.assertEqual(get(POOL + 0x1008), fault)
            self.assertEqual(bytes(mu.mem_read(DEST, sw.SIZE)), self.body if abort else target)
            self.assertEqual(get(self.p['STATUS']), 0 if abort else self.p['COOKIE'])
            self.assertEqual(events, ([] if abort else [sw.gf.DCACHE, sw.gf.ICACHE]) +
                             ([0xC01E35C8] if fault else []) + [0xC01E3400])
            self.assertEqual(len(writes), 0 if abort else sw.SIZE // 4)
            # We stopped inside arm_out; simulate its return before another round.
            mu.reg_write(UC_ARM_REG_SP, STACK - 32)

    def test_repeated(self):
        self.emulate(rounds=3)

    def test_different_reviewed_image(self):
        self.assertNotEqual(sw.reviewed_body(True), self.body)
        self.emulate(upgrade=True, rounds=3)

    def test_fault_preserved(self):
        self.emulate(fault=1)

    def test_guard_abort(self):
        self.emulate(abort=True)

    def test_mutations_detected(self):
        for mutation in ('stack', 'cache', 'destination'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.emulate(mutation=mutation)

    def test_pending_blocks_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'fpl-staging.lock'
            with patch.object(sw.gf, 'LOCK_PATH', lock):
                with sw.gf.staging_lock():
                    marker = sw.write_pending({'test': True})
                self.assertTrue(marker.exists())
                with self.assertRaises(RuntimeError), sw.gf.staging_lock():
                    self.fail('pending bypassed')
                with sw.gf.staging_lock(permit_pending=True):
                    with self.assertRaises(BlockingIOError), sw.gf.staging_lock(permit_pending=True):
                        self.fail('lock bypassed')

    def test_host_success_and_uncertain_arm(self):
        outer = self
        class Fake:
            def __init__(self, fail, initial_magic=0):
                self.fail = fail
                self.memory = {DEST: outer.body}
                self.values = {sw.gf.PUBLICATION: [POOL, 0x100000, DEST],
                               sw.gf.ECHO_SLOT: [sw.gf.ECHO_STOCK],
                               POOL + 0x1080: [initial_magic]}
                self.arms = 0
            def caps(self):
                return dict(pool=POOL, pool_size=0x100000, xfer=0x100000,
                            windows=[(0, 0, 0)] * 8)
            def words(self, address, count=1):
                return self.values.get(address, [0])
            def set_word(self, address, value):
                self.values[address] = [value]
            def read(self, address, count):
                return self.memory[address][:count]
            def write(self, address, data):
                self.memory[address] = data
            def sh(self, line, **kwargs):
                if line == 'version':
                    return 'model=w91c1 rel version=3.02.0.V90'
                if line.startswith('mem set'):
                    outer.assertEqual(kwargs['retries'], 0)
                    outer.assertTrue(sw.gf.LOCK_PATH.with_suffix('.pending').exists())
                    _, _, address, value = line.split()
                    address, value = int(address, 16), int(value, 16)
                    self.set_word(address, value)
                    if address == POOL + 0x1080:
                        self.arms += 1
                        if self.fail:
                            raise RuntimeError('lost reply')
                        self.set_word(address, 0)
                        self.set_word(POOL + 0x10400, 42)
                        self.memory[DEST] = self.memory[POOL + 0x10800][:sw.SIZE]
                return 'OK'
        for fail, initial_magic, pong in ((False, 0, None), (True, 0, None),
                                          (False, 0x97600180, None), (False, 0, True)):
            with tempfile.TemporaryDirectory() as tmp:
                lock = Path(tmp) / 'fpl-staging.lock'
                io = Fake(fail, initial_magic)
                with patch.object(sw.gf, 'LOCK_PATH', lock), \
                     patch.object(sw, 'resident', side_effect=lambda io, dest: io.read(dest, sw.SIZE)), \
                     patch.object(sw.secrets, 'randbits', return_value=42):
                    if fail:
                        with self.assertRaises(RuntimeError):
                            sw.handoff(io, pong=pong)
                    else:
                        sw.handoff(io, pong=pong)
                    self.assertEqual(io.arms, 1)
                    self.assertEqual(lock.with_suffix('.pending').exists(), fail)

    def test_active_window_refuses_before_upload(self):
        from unittest.mock import Mock
        io = Mock()
        io.sh.return_value = 'model=w91c1 rel version=3.02.0.V90'
        io.words.return_value = [POOL, 0x100000, DEST]
        io.caps.return_value = dict(windows=[(0x44000000, 4, 1)] + [(0, 0, 0)] * 7)
        with tempfile.TemporaryDirectory() as tmp, patch.object(sw.gf, 'LOCK_PATH', Path(tmp) / 'lock'):
            with self.assertRaisesRegex(RuntimeError, 'active MEM1 windows'):
                sw.handoff(io)
        io.write.assert_not_called()

    def test_read_window_restored_on_failure(self):
        class Fake:
            windows = [(0, 0, 0)] + [(0x44000000, 4, 1)] * 7
            def caps(self):
                return dict(windows=list(self.windows))
        io = Fake()
        original = list(io.windows)
        def window(slot, base, length, perm):
            io.windows[slot] = (base, length, perm)
        with patch.object(sw.gf.transport, 'mem_window', side_effect=window):
            with self.assertRaises(RuntimeError):
                with sw.resident_window(io, DEST):
                    self.assertEqual(io.windows[0], (DEST, sw.SIZE, 1))
                    raise RuntimeError('read failed')
        self.assertEqual(io.windows, original)


if __name__ == '__main__':
    unittest.main()
