"""Native fp L tag storage/IFD serialization with a bounded synthetic object tree.

Uses official instructions down to the heap backend and memcpy boundary. This is
not a stock camera DNG or a model of available hardware header/RAW memory.
"""
import os
from pathlib import Path
import struct
import unittest

import build as G
import test_fpl_observer as T
import tag_capacity as C
import audit_tag_capacity as A
from unicorn.arm_const import UC_ARM_REG_SP

HEAP = 0x48000000
ROOT, EXIF, MAKER = T.DATA+0x22000, T.DATA+0x22100, T.DATA+0x22200
SOURCE = T.DATA+0x23000
MN = 80
MN_IFD = MN+10


class NativeAssert(RuntimeError):
    pass


class NativeTags(T.Machine):
    def __init__(self, image, code, offsets):
        super().__init__(image, code, offsets)
        self.mu.mem_map(HEAP, 0x100000)
        self.next_heap = HEAP
        self.allocations = []
        self.frees = []
        self.fail_size = None
        self.fail_at = None
        self.logs = []
        self.template_request = None
        for obj in (ROOT, EXIF, MAKER):
            self.call(0xC00BA888, obj)  # actual IFD/vector constructors
        self.write(T.BUILDER+8, ROOT)
        self.write(T.BUILDER+12, 0x4949)
        self.mu.mem_write(SOURCE, bytes(4096))
        assert self.add(0, 0x8769, 4, 1) == 1
        entry = self.call(0xC00BAA10, ROOT, 0x8769)
        self.write(entry+0x14, EXIF)
        assert self.add(2, 0x927C, 7, 10) == 1
        entry = self.call(0xC00BAA10, EXIF, 0x927C)
        self.write(entry+0x14, MAKER)

    def hook(self, mu, addr, size, userdata):
        r = [mu.reg_read(reg) for reg in T.REGS]
        if addr in (0xC01F570C, 0xC01F555C):  # heap mutex backend only
            self.ret(0)
            return
        if addr in (0xC0019DC0, 0xC001A288):  # allocator's zero-size diagnostic
            self.logs.append(addr)
            self.ret(0)
            return
        if addr == 0xC001CF78:
            assert r[0] == 12
            self.ret(0x12345678)
            return
        if addr == 0xC001D038:
            self.template_request = (*r, self.word(mu.reg_read(UC_ARM_REG_SP)))
            self.ret(0 if self.fail_size == r[1] else HEAP+0xF0000)
            return
        if addr == 0xC03D8E98:  # heap allocation backend, real outer wrapper ran
            n = r[0]
            fail = len(self.allocations) == self.fail_at or n == self.fail_size
            pointer = 0 if fail else self.next_heap
            self.allocations.append((n, pointer))
            if pointer:
                self.next_heap += (n+15) & ~15
                if self.next_heap > HEAP+0x100000:
                    raise AssertionError('test heap exhausted')
            self.ret(pointer)
            return
        if addr == 0xC03D9090:
            self.frees.append(r[0])  # recorded, not recycled in this bounded fixture
            self.ret()
            return
        if addr == 0xC03D9198:  # native base destructor's opaque runtime cleanup
            self.ret()
            return
        if addr == 0xC001510C:
            mu.mem_write(r[0], bytes(mu.mem_read(r[1], r[2])))
            self.ret(r[0])
            return
        if addr == 0xC0011100:
            raise NativeAssert(f'native assert, source={r[0]:#x}, line={r[1]:#x}')
        # Actual bounded tag library region: constructors/refcounts, descriptor,
        # value-copy, vector growth/search/sort, native IFD size/write and adder.
        # In particular do NOT fall through to the old descriptor/insertion stubs.
        if (0xC00B9A00 <= addr < 0xC00BC5B0 or
                0xC00B9508 <= addr < 0xC00B9550 or
                0xC00B6700 <= addr < 0xC00B6958 or
                0xC00B6A38 <= addr < 0xC00B6AB8 or
                0xC03D8DE8 <= addr < 0xC03D8E98 or
                0xC038A4A0 <= addr < 0xC038A508 or
                0xC03D9038 <= addr < 0xC03D9090):
            return
        super().hook(mu, addr, size, userdata)

    def add(self, ifd=5, tag=0x4653, kind=7, count=768):
        sp = T.STACK+0xFFF0
        self.write(sp, count)
        self.write(sp+4, SOURCE)
        return self.call(0xC00B6B20, T.BUILDER, ifd, tag, kind)

    def native_size(self):
        return self.call(0xC00BAB08, MAKER)

    def serialize(self, *, raw_start=4096, capacity=None):
        size = MN_IFD+self.native_size()
        capacity = size if capacity is None else capacity
        # Host-supplied TIFF envelope. Only the MakerNote IFD and value offsets
        # below are produced by the native serializer; no full-take claim.
        self.mu.mem_write(T.TEMPLATE, b'\xA5'*8192)
        prefix = bytearray(MN_IFD)
        struct.pack_into('<2sHI', prefix, 0, b'II', 42, 8)
        struct.pack_into('<H', prefix, 8, 2)
        struct.pack_into('<HHII', prefix, 10, 0x111, 4, 1, raw_start)
        struct.pack_into('<HHII', prefix, 22, 0x8769, 4, 1, 48)
        struct.pack_into('<H', prefix, 48, 1)
        struct.pack_into('<HHII', prefix, 50, 0x927C, 7, size-MN, MN)
        prefix[MN:MN+8] = b'SIGMA\0\0\0'
        self.mu.mem_write(T.TEMPLATE, bytes(prefix))
        self.call(0xC00BAC20, MAKER, 0x4949, T.TEMPLATE, T.TEMPLATE+MN_IFD)
        return bytes(self.mu.mem_read(T.TEMPLATE, size)), bytes(
            self.mu.mem_read(T.TEMPLATE+capacity, 16))


class NativeCapacity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp, cls.fpl = Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN'])
        cls.evidence = A.audit(cls.fp, cls.fpl)
        cls.code, cls.offsets, _ = G.observer_probe(
            cls.fp, cls.fpl, sample_hz=1234, tag_capacity=768, frame_callback=T.CALLBACK)
        cls.image = cls.fpl.read_bytes()

    def machine(self):
        return NativeTags(self.image, self.code, self.offsets)

    def test_native_tag_and_serialized_ifd(self):
        m = self.machine()
        self.assertEqual(m.add(), 1)
        self.assertEqual(m.word(MAKER+0x14), 1)
        self.assertEqual(m.native_size(), 18+768)
        b, guard = m.serialize()
        self.assertEqual(guard, b'\xA5'*16)
        import fsg2
        self.assertEqual(fsg2.gtag_area(b), (108, 876))
        m.mu.mem_write(T.TEMPLATE, b)
        m.write(0xC358E9E8, T.TEMPLATE)
        m.write(0xC358E9E4, len(b))
        m.attach()
        m.notify(2)
        self.assertEqual(m.var(16), 108)
        self.assertEqual(C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                          raw_start=4096, tag_bytes=768), (108, 876))

    def test_actual_observer_reaches_native_storage_and_shared_parser(self):
        m = self.machine()
        m.attach()
        m.notify(0)
        self.assertEqual(m.word(MAKER+0x14), 1)
        # Mutate the original zero source after the native insertion: the native
        # value is owned/copied, not a borrowed pointer to the probe's zeros.
        m.mu.mem_write(T.CODE+self.offsets['zbuf'], b'\xFF'*768)
        b, _ = m.serialize()
        self.assertEqual(b[108:876], bytes(768))
        m.write(0xC358E9E8, T.TEMPLATE)
        m.write(0xC358E9E4, len(b))
        m.notify(2)
        m.notify(3)
        self.assertEqual(m.frames, [(T.TEMPLATE, len(b), 108, 1)])

    def test_native_allocation_failures_return_values_are_not_admission(self):
        # Value-object, data bytes, entry object, initial pointer-vector growth.
        for nth, expected_return, expected_count in ((0, 0, 0), (1, 1, 1),
                                                      (2, 0, 0), (3, 1, 0)):
            with self.subTest(allocation=nth):
                m = self.machine()
                first = len(m.allocations)
                m.fail_at = first+nth
                self.assertEqual(m.add(), expected_return)
                self.assertEqual(m.allocations[first+nth][0], (20, 768, 24, 200)[nth])
                self.assertEqual(m.word(MAKER+0x14), expected_count)
                b, guard = m.serialize()
                self.assertEqual(guard, b'\xA5'*16)
                if nth == 1:
                    # Native tag count survives but the data object has no bytes;
                    # the serializer leaves the entry value as old buffer contents.
                    self.assertEqual(struct.unpack_from('<HHII', b, MN_IFD+2),
                                     (0x4653, 7, 768, 0xA5A5A5A5))
                with self.assertRaises(C.CapacityError):
                    C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                      raw_start=4096, tag_bytes=768)
                m.attach()
                m.write(0xC358E9E8, T.TEMPLATE)
                m.write(0xC358E9E4, len(b))
                m.notify(2)
                self.assertEqual(m.var(16), 0)  # actual shared parser admits no area

    def test_full_vector_grows_by_fifty_and_failed_growth_can_report_success(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                m = self.machine()
                for i in range(50):
                    self.assertEqual(m.add(tag=0x5000+i, count=8), 1)
                self.assertEqual(m.word(MAKER+0x18), 50)
                m.fail_size = 400 if fail else None
                self.assertEqual(m.add(), 1)
                self.assertEqual(m.word(MAKER+0x14), 50 if fail else 51)
                self.assertEqual(m.word(MAKER+0x18), 50 if fail else 100)
                b, _ = m.serialize()
                if fail:
                    with self.assertRaisesRegex(C.CapacityError, 'native tag absent'):
                        C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                          raw_start=4096, tag_bytes=768)
                else:
                    C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                      raw_start=4096, tag_bytes=768)

    def test_duplicate_native_add_replaces_instead_of_reserving_another_tag(self):
        m = self.machine()
        self.assertEqual(m.add(), 1)
        self.assertEqual(m.add(count=512), 1)
        self.assertEqual(m.word(MAKER+0x14), 1)
        b, _ = m.serialize()
        self.assertEqual(C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                          raw_start=4096, tag_bytes=512), (108, 620))
        with self.assertRaisesRegex(C.CapacityError, 'type/count mismatch'):
            C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                              raw_start=4096, tag_bytes=768)

    def test_native_serializer_has_no_capacity_parameter_and_overwrites_guard(self):
        m = self.machine()
        m.add()
        self.assertEqual(C.admit_serialization(native_ifd_bytes=m.native_size(),
                         prefix_bytes=MN_IFD, owner_bytes=876, raw_start=4096), 876)
        with self.assertRaises(C.CapacityError):
            C.admit_serialization(native_ifd_bytes=m.native_size(), prefix_bytes=MN_IFD,
                                  owner_bytes=512, raw_start=4096)
        # Deliberately bypass admission to demonstrate why pre-write is required.
        b, guard = m.serialize(capacity=512)
        self.assertNotEqual(guard, b'\xA5'*16)
        with self.assertRaisesRegex(C.CapacityError, 'allocation'):
            C.validate_header(b, serialized_bytes=len(b), owner_bytes=512,
                              raw_start=4096, tag_bytes=768)

    def test_sort_allocation_failure_asserts_for_nonempty_ifd(self):
        m = self.machine()
        m.add()
        m.fail_size = 4  # sort temporary for one entry
        with self.assertRaises(NativeAssert):
            m.serialize()

    def test_native_template_allocation_passes_owner_size_and_alignment(self):
        for fail in (False, True):
            m = self.machine()
            n = 876
            m.fail_size = n if fail else None
            result = m.call(0xC038A4A0, 0xC358E9D8, n)
            self.assertEqual(m.template_request, (0x12345678, n, 64, 0, 0))
            self.assertEqual(m.word(0xC358E9E8), result)
            self.assertEqual(result, 0 if fail else HEAP+0xF0000)
        m = self.machine()
        m.write(0xC358E9E8, HEAP)
        with self.assertRaises(NativeAssert):
            m.call(0xC038A4A0, 0xC358E9D8, 876)

    def test_lossless_value_is_separate_and_overlap_malformed_duplicates_refused(self):
        m = self.machine()
        m.add()
        m.add(tag=0xFD4C, count=128)
        b, guard = m.serialize()
        area = C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                                 raw_start=4096, tag_bytes=768)
        self.assertEqual(guard, b'\xA5'*16)
        # Two sorted entries. Mutation of native output only, never firmware/source.
        mutations = {
            'duplicate': (MN_IFD+2+12, '<H', 0x4653),
            'lossless_overlap': (MN_IFD+2+12+8, '<I', area[0]),
            'raw_overlap': (18, '<I', area[1]-1),
            'ifd_count': (MN_IFD, '<H', 65535),
            'value_bounds': (MN_IFD+2+8, '<I', 0xFFFFFFF0),
            'directory_alias': (MN_IFD+2+8, '<I', MN_IFD),
        }
        for name, (off, fmt, value) in mutations.items():
            mutated = bytearray(b)
            struct.pack_into(fmt, mutated, off, value)
            with self.subTest(name=name), self.assertRaises(C.CapacityError):
                C.validate_header(mutated, serialized_bytes=len(b), owner_bytes=len(b),
                                  raw_start=4096, tag_bytes=768)

    def test_native_store_mutation_breaks_the_positive_invariant(self):
        m = self.machine()
        # Skip vector's count publication after writing a newly appended pointer.
        self.assertEqual(m.word(0xC00BA530), 0xE584200C)
        m.write(0xC00BA530, 0xE1A00000)
        m.mu.ctl_remove_cache(0xC00BA530, 0xC00BA534)
        self.assertEqual(m.add(), 1)
        self.assertEqual(m.word(MAKER+0x14), 0)
        b, _ = m.serialize()
        with self.assertRaisesRegex(C.CapacityError, 'native tag absent'):
            C.validate_header(b, serialized_bytes=len(b), owner_bytes=len(b),
                              raw_start=4096, tag_bytes=768)


if __name__ == '__main__':
    unittest.main()
