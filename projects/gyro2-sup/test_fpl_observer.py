"""Real fp L notify/dispatch/rate/tag-wrapper instructions + shared observer.

FP_MAIN and FPL_MAIN select external official images. No camera operations.
Only guard/lock, context and tag descriptor/insertion boundaries are stubbed; execution outside
the listed native routines/shared text fails. Frame callback is a test-owned sink,
not an fp L sample producer. Existing test_gyr2 covers unchanged FSG2 production.
"""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
import unittest

import build as G
import audit_observer as A
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                              UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
                              UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
                              UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
                              UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

CODE, DATA, STACK = 0x45000000, 0x46000000, 0x47000000
POOL, BUILDER, CONTEXT = DATA, DATA + 0x10000, DATA + 0x11000
TEMPLATE, OBS, OVT = DATA + 0x12000, DATA + 0x14000, DATA + 0x14100
CALLBACK, DONE = DATA + 0x20000, DATA + 0x20004
SUBJECT, NOTIFY, ATTACH = 0xC31AB0D0, 0xC0053028, 0xC00CF208
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
SAVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
         UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)


def template(capacity=768):
    """Minimal structural TIFF fixture: IFD0 -> Exif -> Sigma MakerNote -> GTAG.
    Deliberately unaligned value, exercising the existing parser's alignment.
    This is not claimed as a native fp L serialized DNG capture.
    """
    b = bytearray(0x200 + capacity)
    struct.pack_into('<2sHI', b, 0, b'II', 42, 8)
    for off, tag, typ, count, value in ((8, 0x8769, 4, 1, 32),
                                      (32, 0x927C, 7, 40, 64),
                                      (74, 0x4653, 7, capacity, 0x102)):
        struct.pack_into('<HHHII', b, off, 1, tag, typ, count, value)
    b[64:72] = b'SIGMA\0\0\0'
    return bytes(b)


class Machine:
    def __init__(self, image, code, offsets):
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu.mem_map(A.BASE, 0x3800000)
        self.mu.mem_write(A.BASE, image)
        for addr, size in ((CODE, 0x10000), (DATA, 0x40000), (STACK, 0x10000)):
            self.mu.mem_map(addr, size)
        self.mu.mem_write(CODE, code)
        self.offsets = offsets
        self.size = len(code)
        self.calls, self.tags, self.frames = [], [], []
        self.copied = None
        self.write(POOL, 0xC07333D4)
        self.write(POOL + 0x45D0, BUILDER)
        self.write(CONTEXT + 0x14, 3)  # native enum 3: 25000/1000, not calibration
        self.write(OBS, OVT)
        self.write(OVT + 12, CODE + offsets['tag_observer'])
        self.mu.hook_add(UC_HOOK_CODE, self.hook)

    def word(self, addr):
        return struct.unpack('<I', self.mu.mem_read(addr, 4))[0]

    def write(self, addr, value):
        self.mu.mem_write(addr, struct.pack('<I', value))

    def var(self, offset):
        return self.word(CODE + self.offsets['vars'] + offset)

    def ret(self, value=0):
        self.mu.reg_write(UC_ARM_REG_R0, value)
        self.mu.reg_write(UC_ARM_REG_PC, self.mu.reg_read(UC_ARM_REG_LR))

    def hook(self, mu, addr, size, _):
        if addr == DONE:
            mu.emu_stop()
            return
        r = [mu.reg_read(reg) for reg in REGS]
        sp = mu.reg_read(UC_ARM_REG_SP)
        if addr in (0xC0013090, 0xC001CCE0, 0xC001CD18):
            self.calls.append(addr)  # initialized singleton guard; native attach lock
            self.ret()
            return
        if addr in (0xC0021B20, 0xC0021B60):
            self.ret(CONTEXT)
            return
        if addr == 0xC00B9AE8:  # source descriptor boundary; this older seam fixture captures bytes
            if sp % 8:
                raise AssertionError('tag copy SP misaligned')
            self.copied = bytes(mu.mem_read(r[1], r[2]))
            self.ret(BUILDER + 0x100)
            return
        if addr == 0xC00B6A38:  # native insertion backend after the real wrapper
            self.tags.append((tuple(r), self.word(sp), self.word(sp+4), self.copied))
            self.ret(1)
            return
        if addr == CALLBACK:
            if sp % 8:
                raise AssertionError('frame callback SP misaligned')
            self.frames.append((r[0], r[1], self.var(16), self.var(20)))
            self.ret()
            return
        ranges = ((0xC0054E28, 0x40), (ATTACH, 0xB0), (NOTIFY, 0xC8),
                  (0xC0053618, 0x68), (0xC00533D0, 0x14), (0xC00533E8, 0x14),
                  (0xC0053430, 0x28), (0xC0053D80, 0x20), (0xC0053CD8, 0x68),
                  (0xC038A310, 0x40), (0xC038A530, 0x10),
                  (0xC00C6378, 0x120), (0xC00B6B20, 0x68), (0xC00BC568, 0x48),
                  (CODE, self.size))
        if not any(start <= addr < start+n for start, n in ranges):
            raise AssertionError(f'unstubbed native execution {addr:#x}')

    def call(self, address, *args):
        sp = STACK + 0xFFF0
        for reg, value in zip(REGS, args):
            self.mu.reg_write(reg, value)
        preserved = [0x12340000+i for i in range(len(SAVED))]
        for reg, value in zip(SAVED, preserved):
            self.mu.reg_write(reg, value)
        self.mu.reg_write(UC_ARM_REG_SP, sp)
        self.mu.reg_write(UC_ARM_REG_LR, DONE)
        self.mu.emu_start(address, DONE, count=100000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == DONE, 'instruction bound exhausted'
        assert self.mu.reg_read(UC_ARM_REG_SP) == sp, 'SP not restored'
        assert [self.mu.reg_read(r) for r in SAVED] == preserved, 'callee-saved register damaged'
        return self.mu.reg_read(UC_ARM_REG_R0)

    def attach(self):
        assert self.call(0xC0054E28) == SUBJECT
        self.call(ATTACH, SUBJECT, OBS)
        assert self.word(SUBJECT) == OBS

    def notify(self, mode, kind=3):
        self.call(NOTIFY, SUBJECT, mode, kind, POOL)


class Observer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Missing inputs are an error, not a green skipped port suite.
        cls.fp = Path(os.environ['FP_MAIN'])
        cls.fpl = Path(os.environ['FPL_MAIN'])
        cls.code, cls.offsets, cls.evidence = G.observer_probe(
            cls.fp, cls.fpl, sample_hz=1234, tag_capacity=768, frame_callback=CALLBACK)
        cls.image = cls.fpl.read_bytes()

    def machine(self):
        m = Machine(self.image, self.code, self.offsets)
        m.attach()
        return m

    def test_explicit_inputs_and_no_installer_or_fp_calibration(self):
        with self.assertRaises(TypeError):
            G.observer_probe(self.fp, self.fpl)
        for key, value in [('sample_hz', 0), ('tag_capacity', 128), ('frame_callback', 0xC0000000)]:
            params = dict(sample_hz=1234, tag_capacity=768, frame_callback=CALLBACK)
            params[key] = value
            with self.subTest(key=key), self.assertRaises(G.BuildError):
                G.observer_probe(self.fp, self.fpl, **params)
        for name in ('entry', 'drain', 'snapshot', 'accel_hook', 'vd_hook', 'mode_info'):
            self.assertNotIn(name, self.offsets)
        for value in (400085400, 0x39109F6C, 0x3A800000, 0xC050D4C8, 0xC0125480):
            self.assertNotIn(struct.pack('<I', value), self.code)

    def test_native_build_notify_describes_undefined_tag_and_preserves_observer(self):
        m = self.machine()
        m.notify(0)
        self.assertEqual(len(m.tags), 1)
        regs, typ, copied_ptr, zeros = m.tags[0]
        self.assertEqual(regs, (BUILDER, 5, 0, 0x4653))
        self.assertEqual((typ, copied_ptr), (7, BUILDER+0x100))
        self.assertEqual(zeros, bytes(768))
        self.assertEqual((m.var(168), m.var(172)), (1, 768))
        self.assertEqual(m.word(POOL+0x45E0), 0)
        self.assertEqual(m.word(POOL+0x45E4), 3)
        self.assertEqual(m.word(SUBJECT), OBS)  # observer returned 1, not detached

    def test_native_rate_table_controls_tag_size_not_fp_sample_hz(self):
        code, offsets, _ = G.observer_probe(self.fp, self.fpl, sample_hz=100,
                                           tag_capacity=768, frame_callback=CALLBACK)
        m = Machine(self.image, code, offsets)
        m.attach()
        m.write(CONTEXT+0x14, 8)  # 60000/1001
        m.notify(0)
        # ceil(100*1001/60000)=2; 60 header + 288 events + 3 align + 4*6*2.
        self.assertEqual(len(m.tags[0][3]), 399)

    def test_real_rate_table_including_unknown_enum_fallback(self):
        m = self.machine()
        expected = [(30000, 1001), (24000, 1001), (24000, 1000), (25000, 1000),
                    (30000, 1001), (30000, 1001), (48000, 1000), (50000, 1000),
                    (60000, 1001), (100000, 1000), (120000, 1001), (30000, 1001)]
        for enum, rate in enumerate(expected):
            with self.subTest(enum=enum):
                m.write(CONTEXT+0x14, enum)
                m.call(0xC00C6378, BUILDER)
                self.assertEqual((m.word(BUILDER), m.word(BUILDER+4)), rate)

    def test_serialized_then_frame_uses_mapped_template_and_shared_parser(self):
        m = self.machine()
        hdr = template()
        m.mu.mem_write(TEMPLATE, hdr)
        m.write(0xC358E9E8, TEMPLATE)
        m.write(0xC358E9E4, len(hdr))
        owner = m.call(0xC038A310)
        self.assertEqual(owner, 0xC358E9D8)
        self.assertEqual(m.call(0xC038A530, owner), TEMPLATE)
        m.notify(2)
        self.assertEqual((m.var(12), m.var(16), m.var(20), m.var(64)),
                         (TEMPLATE, 0x104, 1, (768-2-60-288)//6))
        m.notify(3)
        self.assertEqual(m.frames, [(TEMPLATE, len(hdr), 0x104, 1)])
        self.assertEqual(bytes(m.mu.mem_read(TEMPLATE, len(hdr))), hdr)
        self.assertEqual(m.word(POOL+0x45D4), 0)  # native notify postcondition

    def test_wrong_type_unknown_event_and_missing_builder_do_not_add(self):
        m = self.machine()
        for mode, kind in ((0, 2), (1, 3), (7, 3), (2, 2), (3, 2)):
            m.notify(mode, kind)
        self.assertEqual((m.tags, m.frames), ([], []))
        # Another valid DataPool member prevents the native check asserting;
        # its CinemaDNG builder is absent, so shared observer backs off.
        m.write(POOL+0x45D0, 0)
        m.write(POOL+0x45C8, BUILDER)
        m.notify(0)
        self.assertEqual(m.tags, [])

    def test_malformed_template_has_no_reserved_frame_place(self):
        m = self.machine()
        m.write(0xC358E9E8, TEMPLATE)
        m.write(0xC358E9E4, 512)
        m.notify(2)
        self.assertEqual(m.var(16), 0)
        m.notify(3)
        self.assertEqual(m.frames[0][2], 0)

    def test_native_subject_attach_is_idempotent(self):
        m = self.machine()
        m.call(ATTACH, SUBJECT, OBS)
        self.assertEqual([m.word(SUBJECT+4*i) for i in range(9)], [OBS]+[0]*8)

    def test_wrong_firmware_is_refused_before_assembly(self):
        with tempfile.TemporaryDirectory() as d:
            wrong = Path(d) / 'wrong.bin'
            wrong.write_bytes(b'not official firmware')
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                G.observer_probe(self.fp, wrong, sample_hz=1234,
                                 tag_capacity=768, frame_callback=CALLBACK)

    def test_mutated_event_slot_is_detected_by_real_native_dispatch(self):
        # Isolated machine-code mutation: ldr ip,[r0,#0x40] -> builder slot.
        pattern = struct.pack('<I', 0xE590C040)
        self.assertEqual(self.code.count(pattern), 1)
        broken = self.code.replace(pattern, struct.pack('<I', 0xE590C02C))
        m = Machine(self.image, broken, self.offsets)
        m.attach()
        m.notify(0)
        self.assertEqual(m.tags, [])  # the positive mode-0 assertion would fail

    def test_default_fp_artifact_is_release_exact(self):
        saved = G.B.IMAGE
        try:
            G.B.IMAGE = self.fp
            blob, _ = G.build()
        finally:
            G.B.IMAGE = saved
        self.assertEqual(hashlib.sha256(blob).hexdigest(),
                         '2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3')


if __name__ == '__main__':
    unittest.main()
