"""Offline actual ARM shared drain; no transport imports or live operations.

PATH=/path/to/arm-toolchain/bin:$PATH \
  python3 -B -m unittest test_fpl_gyro_capture
Synthetic placement only; temporary assembly artifacts stay in TMPDIR.
"""
import hashlib
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
from armasm import assemble, symbols

HERE = Path(__file__).resolve().parent
SRC = HERE / 'asm/fpl_gyro_capture.S'
CODE, STATE, OUTPUT = 0x45000000, 0x45004000, 0x45005000
P, R, GLOBAL, DELAY = 0x2E006004, 0x2E00644C, 0xC31E23CC, 0xC01F5244
STACK, STOP = 0x450F0000, 0x48000000


def build(capacity=1200, source=SRC):
    defs = [f'CODE={CODE}', f'STATE={STATE}', f'OUTPUT={OUTPUT}', f'CAPACITY={capacity}']
    code = assemble(source, defs)
    assert len(code) <= 4096, 'payload exceeds its owned code reservation'
    return code, symbols(source, defs)


def emulate(code, syms, capacity=1200, start=0, step=1, descriptor=P, ring=R,
            head=None, change=None, race=None, pad=0, repeat=False, during_copy=None):
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    for at, size in ((CODE, 0x100000), (0x2E000000, 0x10000),
                     (GLOBAL & ~4095, 4096), (DELAY & ~4095, 4096), (STOP, 4096)):
        m.mem_map(at, size)
    def word(at, v):
        m.mem_write(at, struct.pack('<I', v & 0xFFFFFFFF))
    def get(at):
        return struct.unpack('<I', m.mem_read(at, 4))[0]
    word(GLOBAL, descriptor)
    word(P+0x60, ring)
    word(R, R+8*(start+1) if head is None else head)
    raw = b''.join(struct.pack('<hhhh', i-300, 300-i, pad, -i) for i in range(600))
    m.mem_write(R+4, raw)
    m.mem_write(CODE, code)
    m.mem_write(OUTPUT, b'\xA5'*(capacity*8+16))
    # Both APIs are hostile AAPCS callees: delay clobbers ALL caller-saved regs.
    saved = {reg: 0x12340000+reg for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    delays, reads, writes, changes = [], [], [], []
    def mutate(at, v):
        word(at, v)
        changes.append((at, v))
    firmware_ranges = ((0x2E000000, 0x10000), (GLOBAL & ~4095, 4096))
    before = {at: bytes(m.mem_read(at, size)) for at, size in firmware_ranges}
    data_words = [CODE+syms[s] for s in ('g_ghead', 'g_gcount', 'g_padbad',
                                      'descriptor_ptr', 'descriptor_ring')]
    allowed = [(a, a+4) for a in data_words] + [(STATE, STATE+256),
               (OUTPUT, OUTPUT+capacity*8), (STACK-80, STACK)]
    copy_changed = []
    def memory(mu, access, at, size, value, unused):
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in allowed), f'bad store {at:x}'
            writes.append((at, size))
        else:
            reads.append(at)
            if during_copy and not copy_changed and R+4 <= at < R+0x12C4:
                mutate(*during_copy)
                copy_changed.append(True)
    raced = []
    def execution(mu, at, size, unused):
        if at == DELAY:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            assert mu.reg_read(ar.UC_ARM_REG_R0) == 20
            delays.append(20)
            n = len(delays)
            if change and n == 1:
                mutate(*change)
            elif step:
                mutate(R, R+8*((start+n*step) % 600+1))
            for reg in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1, ar.UC_ARM_REG_R2,
                        ar.UC_ARM_REG_R3, ar.UC_ARM_REG_R12):
                mu.reg_write(reg, 0xBAD00000+reg)
            mu.reg_write(ar.UC_ARM_REG_PC, mu.reg_read(ar.UC_ARM_REG_LR))
            return
        assert CODE <= at < CODE+len(code), f'escaped code {at:x}'
        if at in [CODE+syms[s] for s in ('gyro_drain', 'stream_claim', 'stream_commit')]:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
        # Change publications immediately after validate, before shared re-read.
        if race and not raced and at == CODE+syms['gyro_drain'] and len(delays) == 1:
            mutate(*race)
            raced.append(True)
    m.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    m.hook_add(uc.UC_HOOK_CODE, execution)
    for _ in range(2 if repeat else 1):
        m.reg_write(ar.UC_ARM_REG_SP, STACK)
        m.reg_write(ar.UC_ARM_REG_LR, STOP)
        m.reg_write(ar.UC_ARM_REG_R0, 0xBAD00000)
        for reg, val in saved.items():
            m.reg_write(reg, val)
        m.emu_start(CODE, STOP, count=1000000)
        assert m.reg_read(ar.UC_ARM_REG_PC) == STOP, 'not finite'
        assert m.reg_read(ar.UC_ARM_REG_SP) == STACK
        for reg, val in saved.items():
            assert m.reg_read(reg) == val, 'callee register clobbered'
    for at, size in firmware_ranges:
        wanted = bytearray(before[at])
        for addr, value in changes:
            if at <= addr < at+size:
                struct.pack_into('<I', wanted, addr-at, value)
        assert m.mem_read(at, size) == wanted, 'firmware changed'
    assert writes[-1] == (STATE, 4)
    state = struct.unpack('<64I', m.mem_read(STATE, 256))
    assert state[0] == 0x50414347
    assert m.mem_read(OUTPUT+capacity*8, 16) == b'\xA5'*16
    return state, bytes(m.mem_read(OUTPUT, state[3]*8)), delays, reads


class Capture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.syms = build()

    def run_case(self, **kwargs):
        return emulate(self.code, self.syms, **kwargs)

    def test_normal_shared_drain_and_call_abi(self):
        state, data, delays, _ = self.run_case()
        self.assertEqual(state[1:8], (1, 20, 19, 19, 0, 0, 0))
        self.assertEqual(data, b''.join(struct.pack('<hhhh', i-300, 300-i, 0, -i)
                                     for i in range(1, 20)))
        self.assertEqual(delays, [20]*20)
        self.assertEqual(state[8:28], tuple(R+8*(i+1) for i in range(20)))
        self.assertEqual(state[28:48], state[8:28])

    def test_wrap_and_pad_accounting(self):
        state, data, _, _ = self.run_case(start=598, step=3, pad=7)
        indexes = [(599+i) % 600 for i in range(57)]
        self.assertEqual(state[3:7], (57, 57, 57, 0))
        self.assertEqual(data, b''.join(struct.pack('<hhhh', i-300, 300-i, 0, -i)
                                     for i in indexes))

    def test_unarmed_stationary_and_entry_reset(self):
        state, data, delays, reads = self.run_case(step=0, repeat=True)
        self.assertEqual(state[1:8], (2, 20, 0, 0, 0, 0, 19))
        self.assertEqual(data, b'')
        self.assertEqual(len(delays), 40)
        self.assertFalse(any(R+4 <= a < R+0x12C4 for a in reads))

    def test_invalid_before_first_drain(self):
        cases = [(dict(descriptor=v), 3 if v == 0 else 4) for v in (0, P+4, 0xFFFFFFFF)]
        cases += [(dict(ring=v), 5) for v in (0, R+4, 0xFFFFFFFF)]
        cases += [(dict(head=v), 6) for v in (0, R, R+4, R+9, R+0x12C4, 0xFFFFFFFF)]
        for kw, status in cases:
            with self.subTest(kw=kw):
                s, data, delays, reads = self.run_case(**kw)
                self.assertEqual(s[1], status)
                self.assertEqual(data, b'')
                self.assertEqual(delays, [])
                self.assertFalse(any(R+4 <= a < R+0x12C4 for a in reads))

    def test_each_iteration_revalidates(self):
        for change, status in (((GLOBAL, 0), 3), ((GLOBAL, P+4), 4),
                               ((P+0x60, R+4), 5), ((R, 0), 6)):
            s, data, delays, _ = self.run_case(change=change)
            self.assertEqual(s[1], status)
            self.assertEqual(len(delays), 1)
            self.assertEqual(data, b'')

    def test_racing_publications_are_not_followed(self):
        for race, status in (((GLOBAL, 0xDEADBEEF), 4), ((P+0x60, 0xDEADBEEF), 5),
                             ((R, R+24), 7), ((R, 0xFFFFFFFF), 6)):
            s, _, delays, reads = self.run_case(race=race)
            self.assertEqual(s[1], status)
            self.assertEqual(len(delays), 1)
            self.assertNotIn(0xDEADBEEF, reads)
            self.assertLessEqual(s[3], 1200)

    def test_capacity_partial_then_exhausted(self):
        code, syms = build(5)
        s, data, _, _ = emulate(code, syms, capacity=5, step=3, pad=-1)
        self.assertEqual(s[3:7], (5, 57, 5, 52))
        self.assertEqual(len(data), 40)

    def test_changes_during_copy_invalidate_batch(self):
        for change, status in (((R, R+40), 7), ((GLOBAL, 0), 3),
                               ((P+0x60, 0), 5), ((R, 0), 6)):
            s, data, delays, _ = self.run_case(step=3, during_copy=change)
            self.assertEqual(s[1], status)
            self.assertEqual(len(delays), 1)
            self.assertEqual(len(data), 24)  # retained but invalid batch

    def test_equal_head_does_not_prove_no_lap(self):
        s, data, _, _ = self.run_case(step=600)
        self.assertEqual(s[1], 2)  # deliberately only "no observed motion"
        self.assertEqual(data, b'')

    def test_compile_bounds_reject(self):
        cases = [('CAPACITY', 0), ('CAPACITY', 12001), ('STATE', CODE),
                 ('OUTPUT', STATE), ('OUTPUT', OUTPUT+1), ('CODE', CODE+1)]
        for key, value in cases:
            defs = dict(CODE=CODE, STATE=STATE, OUTPUT=OUTPUT, CAPACITY=1200)
            defs[key] = value
            with self.subTest(key=key, value=value), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    assemble(SRC, [f'{k}={v}' for k, v in defs.items()])

    def test_default_fp_base_bytes_frozen_before_edit(self):
        code = assemble(HERE.parent/'gyro/gcsv_task.S', ['FPGYRO_EDITION_BASE=1'])
        self.assertEqual(len(code), 13896)
        self.assertEqual(hashlib.sha256(code).hexdigest(),
                         '5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38')

    def test_shared_source_mutation_is_detected(self):
        # Compile a deliberately broken copy of the REAL shared source; no
        # model-only test can pass this oracle accidentally.
        shared = HERE.parent/'gyro/gyro_drain.S'
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp)/'drain.S'
            text = shared.read_text().replace('add     r6, r6, #8', 'add     r6, r6, #0')
            text = text.replace('"imu_stream.inc.S"', f'"{shared.parent}/imu_stream.inc.S"')
            broken.write_text(text)
            probe = Path(tmp)/'capture.S'
            probe.write_text(SRC.read_text().replace('"../../gyro/gyro_drain.S"', f'"{broken}"'))
            code, syms = build(source=probe)
            _, data, _, _ = emulate(code, syms, step=3)
            expected = b''.join(struct.pack('<hhhh', i-300, 300-i, 0, -i) for i in range(1, 58))
            with self.assertRaises(AssertionError):
                self.assertEqual(data, expected)


if __name__ == '__main__':
    unittest.main()
