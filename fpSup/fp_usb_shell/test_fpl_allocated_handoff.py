"""Offline-only relocation proof using real allocator + worker ARM instructions.

No USB backend instantiated. Synthetic heap/peripherals, cache calls stubbed.
Run with durable clang on PATH: python3 -B -m unittest -v test_fpl_allocated_handoff
"""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_SP, UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_R0,
    UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
)
from armasm import assemble, symbols
from firmware import get_camera
import fpl_swapworker as sw
from test_fpl_worker_guards import variant

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import fpl_allocator_audit as native

MAIN = Path(os.environ.get('FPL_MAIN', str(Path.home() /
    '.local/share/fpsup/firmware/FPL_V302/MAIN.bin')))
POOL, STUB, STATUS = 0x45000000, 0x45010000, 0x45010400
SOURCE, EXPECTED = 0x45011000, 0x45013000
COOKIE = 0x1937AB42
ASM = Path(__file__).parent / 'asm/fpl_allocated_handoff_prototype.S'


def candidate():
    """One explicit scratch source transform; this is NOT an install interface."""
    text = variant()
    # Ack only after serve's upload/window reset. PC-relative to retained record.
    text = text.replace('next_round:\n', '''next_round:
    movw r0, #:lower16:(handoff_record - . - 12)
    add r0, pc, r0
    mov r1, #2
    dsb sy
    str r1, [r0, #24]
    dsb sy
''')
    text = text.replace('wbody_end:\n', '''handoff_record:
    .space 32
wbody_end:
''')
    with tempfile.TemporaryDirectory(prefix='fpl-allocated-offline-') as temp:
        src = Path(temp) / 'candidate.S'
        src.write_text(text)
        defs = get_camera('fp-l-3.02').loader_defines()
        labels = symbols(src, defs)
        blob = assemble(src, defs)[labels['wbody']:labels['wbody_end']]
    return blob, {k: v - labels['wbody'] for k, v in labels.items()}


class AllocatedHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not MAIN.is_file():
            raise FileNotFoundError('Set FPL_MAIN to the external official fp L 3.02 MAIN image')
        cls.image = MAIN.read_bytes()
        assert hashlib.sha256(cls.image).hexdigest() == native.SHA256
        cls.old_body = sw.reviewed_body(True)
        cls.new_body, cls.labels = candidate()
        assert len(cls.new_body) > sw.SIZE

    def trial(self, *, fail=None, mutation=None, fault=0, old_pong=True, pause=None):
        m = native.Machine(self.image)
        m.stubs.update({0xC001E328: 0, 0xC001E3C8: 0})
        m.put(0xC30739D8, native.CHANNEL)
        m.put(0xC3073A10, native.CHANNEL)
        m.put(native.CHANNEL, 0, 0)
        m.call(0xC0010310, native.CHANNEL + 8)
        m.call(0xC00103A8, native.CHANNEL + 8, native.HEAP)
        for address in (native.HEAP, native.HEAP + native.HEAP_SIZE - 0x40):
            m.put(native.DESC + 0x100, address, 0x40)
            m.call(0xC00103E8, native.CHANNEL + 8, native.DESC + 0x100)
        m.call(0xC001D740, native.DESC, 0, sw.SIZE, 0)
        old = m.call(0xC001D7F0, native.DESC)
        old_body = sw.reviewed_body(old_pong)
        m.mu.mem_write(old, old_body)
        # Forget original descriptor just as spawn does. No attempt to recreate/free it.
        m.put(native.DESC, 0, 0, 0, 0)
        accounting = m.words(native.CHANNEL, 9)
        m.mu.mem_map(POOL, 0x100000)
        m.mu.mem_map(0x2100C000, 0x1000)
        m.put(sw.gf.PUBLICATION, POOL, 0x100000, old)
        m.put(POOL + 0x1000, 0x4C485356)
        m.put(POOL + 0x1008, fault)
        m.put(POOL + 0x10C0, STUB)
        m.put(POOL + 0x1080, 0x50415753)
        m.put(STATUS, COOKIE if fail != 'generation' else COOKIE + 1)
        m.mu.mem_write(SOURCE, self.new_body)
        m.mu.mem_write(EXPECTED, old_body)
        if fail == 'old':
            m.put(EXPECTED + 100, 0)
        m.put(0x2100C720, 0x24)
        m.put(0xC3077794, 5)
        m.mu.mem_write(0xC31E1D6C, b'\x01')
        m.mu.mem_write(0xC3032A92, b'\x01')
        m.put(0x2100C704, 0x80000000)
        m.put(0xC31E1668, POOL + 0x8000)
        defs = dict(POOL=POOL, STATUS=STATUS, OLD=old, STUB=STUB,
                    COOKIE=COOKIE, EXPECTED=EXPECTED, SOURCE=SOURCE,
                    NEW_SIZE=0x20000 if fail == 'allocation' else len(self.new_body),
                    RECORD=self.labels['handoff_record'], NEW_SERVE=self.labels['serve'])
        args = [f'{k}={v}' for k, v in defs.items()]
        labels = symbols(ASM, args)
        code = bytearray(assemble(ASM, args))
        if mutation == 'unwind':
            struct.pack_into('<I', code, labels['unwind'], 0xE1A00000)
        if mutation == 'cache':
            code[:] = code.replace(struct.pack('<I', sw.gf.ICACHE),
                                   struct.pack('<I', sw.gf.DCACHE))
        if mutation == 'publication':
            struct.pack_into('<I', code, labels['publish'], 0xE1A00000)
        self.assertLess(len(code), 1024)
        m.mu.mem_write(STUB, bytes(code))
        events, publication_writes, frees = [], [], []
        new_address = None
        damaged = False

        def hook(mu, address, size, _):
            nonlocal new_address, damaged
            checkpoints = {'prepared': STUB + labels['publish'],
                           'published': STUB + labels['publish'] + 4}
            if new_address:
                checkpoints.update(entering=new_address + self.labels['serve'],
                                   acknowledged=new_address + self.labels['no_swap'])
            if pause and address == checkpoints.get(pause):
                events.append('paused')
                mu.emu_stop()
                return
            if address == STUB + labels['copy'] and new_address is None:
                new_address = m.words(STATUS + 16)[0]
                self.assertNotEqual(new_address, old)
                self.assertFalse(old < new_address + len(self.new_body) and
                                 new_address < old + sw.SIZE)
            if fail == 'copy' and address == STUB + labels['verify_new'] and not damaged:
                m.put(new_address + 100, 0xBAD)
                damaged = True
            if address == 0xC001D7A0:
                frees.append(m.words(mu.reg_read(UC_ARM_REG_R0), 4))
                self.assertEqual(m.words(sw.gf.PUBLICATION + 8), (old,))
                self.assertEqual(mu.reg_read(UC_ARM_REG_R1), 2)
            if address in (sw.gf.DCACHE, sw.gf.ICACHE, 0xC01E35C8):
                self.assertEqual(mu.reg_read(UC_ARM_REG_SP) % 8, 0)
                events.append(address)
                # Deliberately clobber ABI caller-saved registers.
                for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3):
                    mu.reg_write(reg, 0)
                mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
            if new_address and address == new_address + self.labels['serve']:
                self.assertEqual(events, [sw.gf.DCACHE, sw.gf.ICACHE])
                self.assertEqual(mu.reg_read(UC_ARM_REG_SP), native.STACK)
                self.assertEqual(m.words(sw.gf.PUBLICATION + 8), (new_address,))
                self.assertEqual(m.words(new_address + self.labels['handoff_record'] + 24), (1,))
                events.append('candidate')
            if address == 0xC01E3400:
                events.append('start-out')
                mu.emu_stop()

        def store(mu, access, address, size, value, _):
            self.assertFalse(old <= address < old + sw.SIZE, 'old code overwritten')
            if address == sw.gf.PUBLICATION + 8:
                self.assertEqual(size, 4)
                self.assertEqual(m.words(address), (old,))
                self.assertEqual(events, [sw.gf.DCACHE, sw.gf.ICACHE])
                publication_writes.append(value)

        m.mu.hook_add(UC_HOOK_CODE, hook)
        m.mu.hook_add(UC_HOOK_MEM_WRITE, store)
        m.mu.reg_write(UC_ARM_REG_SP, native.STACK)
        m.mu.reg_write(UC_ARM_REG_LR, native.STOP)
        m.mu.emu_start(old + sw.EXPECT['serve'], 0, count=150000)
        if pause:
            self.assertEqual(events[-1], 'paused')
            self.assertEqual(frees, [])
            self.assertEqual(bytes(m.mu.mem_read(old, sw.SIZE)), old_body)
            self.assertEqual(m.words(POOL + 0x1080), (0,))
            return m, new_address, old
        self.assertEqual(events[-1], 'start-out')
        self.assertEqual(bytes(m.mu.mem_read(old, sw.SIZE)), old_body)
        self.assertEqual(m.words(POOL + 0x1080), (0,))
        self.assertEqual(m.words(POOL + 0x1008), (fault,))
        self.assertEqual(m.mu.reg_read(UC_ARM_REG_SP), native.STACK - 32 - 24)
        if fail:
            self.assertEqual(publication_writes, [])
            self.assertNotIn('candidate', events)
            self.assertEqual(m.words(sw.gf.PUBLICATION + 8), (old,))
            after = m.words(native.CHANNEL, 9)
            self.assertEqual(after[:7] + after[8:], accounting[:7] + accounting[8:])
            self.assertEqual(len(frees), int(fail == 'copy'))
            if fail == 'copy':
                self.assertEqual(m.words(STATUS + 16), (0,))
        else:
            self.assertEqual(publication_writes, [new_address])
            self.assertEqual(frees, [])
            record = new_address + self.labels['handoff_record']
            self.assertEqual(m.words(record, 8),
                             (new_address, 0, new_address, len(self.new_body), COOKIE, old, 2, 0))
            pins = self.labels['guard_pins']
            actual = bytes(m.mu.mem_read(new_address, len(self.new_body)))
            self.assertEqual(actual[:pins], self.new_body[:pins])
            self.assertEqual(actual[pins + 8:self.labels['handoff_record']],
                             self.new_body[pins + 8:self.labels['handoff_record']])
            self.assertEqual(m.words(new_address + pins), (POOL + 0x8000,))
            self.assertNotEqual(hashlib.sha256(actual).digest(), hashlib.sha256(self.new_body).digest())
        return m, new_address

    def test_larger_guard_worker_at_real_allocated_address(self):
        for pong in (False, True):
            with self.subTest(old_pong=pong):
                self.trial(old_pong=pong)

    def test_fault_state_survives_relocation(self):
        self.trial(fault=1)

    def test_refusals_and_unpublished_candidate_release(self):
        for fail in ('old', 'generation', 'allocation', 'copy'):
            with self.subTest(fail=fail):
                self.trial(fail=fail)

    def test_single_instruction_mutations_are_detected(self):
        for mutation in ('unwind', 'cache', 'publication'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.trial(mutation=mutation)

    def test_interruption_snapshots_do_not_confuse_publication_with_entry(self):
        for pause in ('prepared', 'published', 'entering', 'acknowledged'):
            with self.subTest(pause=pause):
                m, new, old = self.trial(pause=pause)
                self.assertEqual(m.words(sw.gf.PUBLICATION + 8),
                                 (old if pause == 'prepared' else new,))
                record = new + self.labels['handoff_record']
                self.assertEqual(m.words(record + 24),
                                 (2 if pause == 'acknowledged' else 1,))
                self.assertEqual(m.words(record, 6),
                                 (new, 0, new, len(self.new_body), COOKIE, old))
                # Both descriptors remain allocated even while publication is old.
                # No retry/free is justified by an absent execution acknowledgement.
                self.assertNotEqual(new, old)


if __name__ == '__main__':
    unittest.main()
