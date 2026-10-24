"""Native reconstruction from an external real DNG, not a captured object graph."""
import os
from pathlib import Path
import struct
import unittest
import tempfile
from unicorn.arm_const import *

import audit_formatter as A
import test_fpl_formatter as F
import test_fpl_tag_capacity as N
import test_fpl_observer as T
import tag_capacity as C
import fsg2
import formatter_contract as FC

DEST = 0x4A000000


class DngMachine(F.Formatter):
    def hook(self, mu, addr, size, userdata):
        if addr == 0xC0015058:
            r = [mu.reg_read(x) for x in T.REGS]
            assert r[2] <= 0x20000
            mu.mem_write(r[0], bytes([r[1] & 255])*r[2])
            self.ret(r[0])
            return
        if any(a <= addr < a+n for a, n in (
                (0xC00B5468, 0x40), (0xC00B6510, 0x1F0),
                (0xC00BD0B0, 0x70), (0xC00BD428, 0xD0),
                (0xC0697018, 0x40), (0xC06A29F8, 0x40),
                (0xC06A2AD0, 0x34), (0xC0720758, 0x44),
                (0xC0697A38, 0x40))):
            return
        super().hook(mu, addr, size, userdata)

    def reconstruct(self, prefix):
        self.mu.mem_map(DEST, 0x40000)
        self.call(0xC00B5468, T.BUILDER)
        self.write(T.BUILDER+8, N.ROOT)
        for obj in (N.ROOT, N.EXIF):
            self.call(0xC00BA888, obj)
        self.call(0xC00BD0B0, N.MAKER)
        self.write(N.MAKER+0x28, 0x401)
        root = fsg2.ifd_entries(prefix, 8)
        exif_at = root[0x8769][2]
        exif = fsg2.ifd_entries(prefix, exif_at)
        for ifd, at in ((0, 8), (2, exif_at), (5, exif[0x927C][2]+10)):
            for tag, (ty, count, value) in fsg2.ifd_entries(prefix, at).items():
                if tag in (0x8769, 0x927C):
                    assert self.add(ifd, tag, ty, count) == 1
                    obj, child = (N.ROOT, N.EXIF) if tag == 0x8769 else (N.EXIF, N.MAKER)
                    entry = self.call(0xC00BAA10, obj, tag)
                    self.write(entry+0x14, child)
                    continue
                length = C.TYPE_BYTES[ty]*count
                data = struct.pack('<I', value)[:length] if length <= 4 else prefix[value:value+length]
                self.mu.mem_write(N.SOURCE, data)
                assert self.add(ifd, tag, ty, count) == 1
        self.construct()
        ledger = self.word(F.LEFT+0x10)
        for k in range(5):
            self.write(ledger+0x20+8*k, (0x18000, 0, 0, 0, 0x5400)[k])
            self.write(ledger+0x24+8*k, 0)

    def output(self):
        size = self.call(0xC00B6510, T.BUILDER)
        self.mu.mem_write(DEST, b'\xA5'*0x20000)
        assert self.call(0xC00B65A0, T.BUILDER, DEST, size) == 1
        sp = T.STACK+0xFE00
        self.mu.reg_write(UC_ARM_REG_SP, sp)
        self.mu.reg_write(UC_ARM_REG_R4, F.LEFT)
        self.mu.reg_write(UC_ARM_REG_R5, T.BUILDER)
        self.write(sp+0x28, DEST)
        self.mu.emu_start(0xC06A29F8, 0xC06A2A38, count=100000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == 0xC06A2A38
        h = self.word(self.word(F.LEFT+0x10)+0x24)
        self.mu.emu_start(0xC06A2AD0, 0xC06A2B00, count=100000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == 0xC06A2B00
        assert self.call(0xC00B65A0, T.BUILDER, DEST, size) == 1
        return size, h, bytes(self.mu.mem_read(DEST, h))


class RealDng(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('FPL_DNG_PREFIX')
        if not path or not Path(path).is_file():
            raise unittest.SkipTest('external FPL_DNG_PREFIX absent; real DNG replay unavailable')
        cls.prefix = A.load_dng_prefix(path)
        F.NativeFormatter.setUpClass()

    def machine(self):
        m = DngMachine(N.NativeCapacity.image, F.NativeFormatter.data,
                       N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        return m

    def test_native_baseline(self):
        m = self.machine()
        size, h, output = m.output()
        self.assertEqual((size, h), (0x135C4, 0x13800))
        self.assertEqual(self.values(output), self.values(self.prefix))
        self.assertEqual(output[size:], bytes(h-size))
        self.assertEqual(self.prefix[size:h], bytes(h-size))

    @staticmethod
    def values(b):
        root = fsg2.ifd_entries(b, 8)
        exif = fsg2.ifd_entries(b, root[0x8769][2])
        maker = fsg2.ifd_entries(b, exif[0x927C][2]+10)
        result = []
        for entries in (root, exif, maker):
            values = {}
            for tag, (ty, n, v) in entries.items():
                size = C.TYPE_BYTES[ty]*n
                data = struct.pack('<I', v)[:size] if size <= 4 else b[v:v+size]
                if tag == 0x8769:
                    data = b'child Exif'
                elif tag == 0x927C:
                    data = b'child MakerNote'
                values[tag] = (ty, n, data)
            result.append(values)
        return result

    def parse_arm(self, m, b):
        m.mu.mem_write(DEST, b)
        m.write(0xC358E9E8, DEST)
        m.write(0xC358E9E4, len(b))
        m.attach()
        m.notify(2)
        return m.var(16)

    def test_real_prefix_has_no_writable_gtag(self):
        m = self.machine()
        self.assertIsNone(fsg2.gtag_area(self.prefix))
        self.assertEqual(self.parse_arm(m, self.prefix[:0x13800]), 0)
        with self.assertRaisesRegex(C.CapacityError, 'native tag absent'):
            C.validate_header(self.prefix, serialized_bytes=0x13800,
                              owner_bytes=0x15400, raw_start=0x13800, tag_bytes=768)

    def test_native_added_tag_boundaries_and_shared_parser(self):
        for n in (559, 560, 561, 768, 7727, 7728, 7729, 18991, 18992):
            with self.subTest(n=n):
                m = self.machine()
                m.mu.mem_write(N.SOURCE, bytes(n))
                self.assertEqual(m.add(count=n), 1)
                size, h, b = m.output()
                self.assertEqual(size, 0x135C4+12+((n+1) & ~1))
                self.assertEqual(h, (size+0x3FF) & ~0x3FF)
                self.assertEqual(fsg2.ifd_entries(b, 8)[0x111], (4, 1, h))
                original, augmented = self.values(self.prefix), self.values(b)
                # Only the offset, MakerNote count and added tag should change.
                for group, values in enumerate(original):
                    for tag, value in values.items():
                        if (group, tag) not in ((0, 0x111), (1, 0x927C)):
                            self.assertEqual(augmented[group][tag], value)
                area = fsg2.gtag_area(b)
                self.assertEqual(self.parse_arm(m, b), area[0])
                self.assertEqual(C.validate_header(b, serialized_bytes=h,
                    owner_bytes=0x18000, raw_start=h, tag_bytes=n), area)
                record = T.DATA+0x31000
                for off, val in ((0x68, DEST), (0x128, 0x15400),
                                 (0x4C, DEST+0x15400), (0x14C, h), (0x12C, 0)):
                    m.write(record+off, val)
                if n <= 7728:
                    self.assertEqual(FC.recording_layout(m.mu.mem_read, record,
                        serialized_bytes=h, frame_bytes=0x810400)[3], h)
                else:
                    with self.assertRaises(FC.CapacityError):
                        FC.recording_layout(m.mu.mem_read, record,
                            serialized_bytes=h, frame_bytes=0x810400)

    def test_beyond_reservation_asserts_and_rounding_mutation_is_detected(self):
        m = self.machine()
        m.mu.mem_write(N.SOURCE, bytes(18993))
        m.add(count=18993)
        self.assertEqual(m.call(0xC00B6510, T.BUILDER), 0x18002)
        with self.assertRaises(N.NativeAssert):
            m.output()
        m = self.machine()
        # Mutate writer alignment from 0x400 to 0x200, in emulator memory only.
        self.assertEqual(m.word(0xC06A2A14), 0xE3A02B01)
        m.write(0xC06A2A14, 0xE3A02C02)
        m.mu.ctl_remove_cache(0xC06A2A14, 0xC06A2A18)
        self.assertEqual(m.output()[1], 0x13600)

    def test_fixture_hash_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'prefix'
            p.write_bytes(self.prefix[:-1]+bytes([self.prefix[-1] ^ 1]))
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                A.load_dng_prefix(p)

    def test_inline_and_small_undefined_lengths(self):
        for n in (1, 4, 5):
            m = self.machine()
            m.mu.mem_write(N.SOURCE, bytes(8))
            m.add(count=n)
            size, h, _ = m.output()
            self.assertEqual(size, 0x135C4+12+(0 if n <= 4 else 6))
            self.assertEqual(h, 0x13800)
