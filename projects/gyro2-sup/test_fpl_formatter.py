"""Offline native constructor/ledger probe, not a selected camera mode graph."""
import os
from pathlib import Path
import struct
import unittest

import audit_formatter as A
import formatter_contract as C
import test_fpl_tag_capacity as N
import test_fpl_observer as T

ROOT, LEFT, RIGHT = T.DATA+0x30000, T.DATA+0x30100, T.DATA+0x30200
PVT, AVAILABLE, ALLOCATE = T.DATA+0x30300, T.DATA+0x30400, T.DATA+0x30404


class Formatter(N.NativeTags):
    def __init__(self, image, data, code, offsets):
        self.trace = set()
        self.pool_calls = []
        self.available, self.pool_fail = 1, False
        super().__init__(image, code, offsets)
        self.mu.mem_write(A.DATA_BASE, data)
        self.mu.mem_map(0xC3800000, 0x100000)
        # Explicit provider stub setup, NOT execution of firmware pool startup.
        self.write(A.POOL, PVT)
        self.write(PVT+0x14, AVAILABLE)
        self.write(PVT+0xC, ALLOCATE)

    def hook(self, mu, addr, size, userdata):
        self.trace.add(addr)
        r = [mu.reg_read(reg) for reg in T.REGS]
        if addr in (AVAILABLE, ALLOCATE):
            assert r[0] == A.POOL
            self.pool_calls.append((addr, r[0], r[1]))
            if addr == AVAILABLE:
                self.ret(self.available)
            else:
                assert r[1] == 0x4C
                p = 0 if self.pool_fail else self.next_heap
                if p:
                    self.next_heap += 0x50
                self.ret(p)
            return
        if addr == 0xC0011130:
            raise N.NativeAssert('ledger allocation assertion')
        ranges = ((0xC0696BB8, 0x34), (A.SIZE_FN, 0x38),
                  (0xC0696E10, 0x48), (0xC0696E98, 0x40),
                  (0xC06976F0, 0x80), (A.TABLE_INIT, 0x44),
                  (0xC06987B8, 0x78), (0xC06978F8, 0x140),
                  (0xC06970E0, 0x30), (0xC0697178, 0x90),
                  (0xC0720C28, 0xA4))
        if any(a <= addr < a+n for a, n in ranges):
            return
        super().hook(mu, addr, size, userdata)

    def construct(self):
        for leaf in (LEFT, RIGHT):
            self.call(0xC0696E10, leaf, 0)
        self.call(0xC0696BB8, ROOT, LEFT, RIGHT)
        self.call(0xC0720C28, LEFT)

    def snapshot(self):
        return C.snapshot(self.mu.mem_read, self.call, ROOT)


class NativeFormatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        N.NativeCapacity.setUpClass()
        cls.data_path = Path(os.environ['FPL_DATA'])
        cls.evidence = A.audit(N.NativeCapacity.fpl, cls.data_path)
        cls.data = cls.data_path.read_bytes()

    def machine(self, construct=True):
        m = Formatter(N.NativeCapacity.image, self.data,
                      N.NativeCapacity.code, N.NativeCapacity.offsets)
        if construct:
            m.construct()
        return m

    def admission(self, m, before=None, **kw):
        current = m.snapshot()
        args = dict(allocation=N.HEAP+0xF0000,
                    allocation_bytes=current.reserved_bytes,
                    native_ifd_bytes=786, prefix_bytes=90, raw_start=None)
        args.update(kw)
        return C.admit(current if before is None else before, current, **args)

    def test_native_constructors_initializer_and_virtual_size(self):
        m = self.machine()
        self.assertEqual(m.word(ROOT+8), A.BASE_VTABLE)
        for leaf in (LEFT, RIGHT):
            ledger = m.word(leaf+12)
            self.assertEqual(m.word(leaf+16), ledger)
            self.assertEqual(m.word(leaf+20), 0xC2E48BF0)
            self.assertEqual(m.word(ledger+0x48), 0xC2E491C4)
        words = struct.unpack('<19I', m.mu.mem_read(m.word(LEFT+12), 0x4C))
        self.assertEqual(words[8:18:2], (0x5000, 0, 0x1000, 0x5000, 0))
        self.assertEqual(words[9:18:2], (0x5000, 0, 0, 0, 0))
        self.assertEqual(m.snapshot().reserved_bytes, 0xB000)
        self.assertEqual(m.call(m.word(m.word(ROOT+8)+0x10), ROOT), 0xB000)
        self.assertTrue({0xC06976F0, 0xC06987B8, A.TABLE_INIT,
                         A.SIZE_FN, 0xC0696EB8, 0xC06979F8} <= m.trace)
        self.assertEqual(sum(a == ALLOCATE for a, _, _ in m.pool_calls), 2)

    def test_zero_initializer_and_pool_failures(self):
        m = self.machine(False)
        m.call(A.TABLE_INIT, LEFT)
        self.assertEqual(bytes(m.mu.mem_read(LEFT, 72)), bytes(72))
        self.assertEqual(m.word(LEFT+72), 0xC2E48F44)
        for unavailable in (False, True):
            m = self.machine(False)
            if unavailable:
                m.available = 0
                m.call(0xC0696E10, LEFT, 0)
                self.assertEqual(m.word(LEFT+12), 0)
                self.assertFalse(any(a == ALLOCATE for a, _, _ in m.pool_calls))
            else:
                m.pool_fail = True
                with self.assertRaises(N.NativeAssert):
                    m.call(0xC0696E10, LEFT, 0)

    def test_null_graph_and_ledger_rejected_before_native_call(self):
        for address in (ROOT, ROOT+4, LEFT+12):
            m = self.machine()
            m.write(address, 0)
            with self.assertRaises(C.CapacityError):
                m.snapshot()

    def test_native_sum_wrap_is_refused(self):
        m = self.machine()
        m.call(0xC0697178, RIGHT, 0, 0xFFFFFFFF)
        self.assertEqual(m.call(A.SIZE_FN, ROOT), 0xAFFF)
        with self.assertRaisesRegex(C.CapacityError, 'wrap'):
            m.snapshot()

    def test_used_over_reservation_asserts_and_host_refuses(self):
        m = self.machine()
        with self.assertRaises(N.NativeAssert):
            m.call(0xC06971A0, LEFT, 2, 0x1001)
        with self.assertRaisesRegex(C.CapacityError, 'used row'):
            m.snapshot()

    def test_body_size_is_distinct_and_alignment_can_wrap(self):
        m = self.machine()
        m.call(0xC06970E0, LEFT, 0, 5)
        self.assertEqual(m.call(0xC0696E98, LEFT), 8)
        self.assertEqual(m.snapshot().reserved_bytes, 0xB000)
        m.call(0xC06970E0, LEFT, 0, 0xFFFFFFFF)
        self.assertEqual(m.call(0xC0696E98, LEFT), 0)

    def test_same_total_metadata_change_refused(self):
        m = self.machine()
        before = m.snapshot()
        m.call(0xC06971A0, LEFT, 2, 1)
        self.assertEqual(m.snapshot().reserved_bytes, before.reserved_bytes)
        with self.assertRaisesRegex(C.CapacityError, 'metadata changed'):
            self.admission(m, before, raw_start=4096)

    def test_raw_unknown_null_owner_bounds_and_overflow_refused(self):
        m = self.machine()
        cases = ({}, {'raw_start': 875}, {'raw_start': 4096, 'allocation': 0},
                 {'raw_start': 4096, 'allocation_bytes': 875},
                 {'raw_start': 4096, 'allocation': 0x7FFFFFC0},
                 {'raw_start': 4096, 'native_ifd_bytes': 0xFFFFFFFF})
        for kw in cases:
            with self.subTest(kw=kw), self.assertRaises(C.CapacityError):
                self.admission(m, **kw)

    def test_native_template_allocation_and_guarded_ifd_write(self):
        m = self.machine()
        before = m.snapshot()
        n = before.reserved_bytes
        dest = m.call(0xC038A4A0, 0xC358E9D8, n)
        self.assertEqual(m.template_request, (0x12345678, n, 64, 0, 0))
        self.assertEqual(m.add(), 1)
        # RAW=4096 is independent SYNTHETIC fixture evidence, not a mode result.
        length = self.admission(m, before, allocation=dest,
                                native_ifd_bytes=m.native_size(), raw_start=4096)
        m.mu.mem_write(dest, b'\xA5'*(n+16))
        # Native serializer writes the MakerNote IFD into the actual owner allocation.
        m.call(0xC00BAC20, N.MAKER, 0x4949, dest, dest+N.MN_IFD)
        self.assertEqual(length, 876)
        self.assertEqual(bytes(m.mu.mem_read(dest+length, 16)), b'\xA5'*16)
        self.assertEqual(bytes(m.mu.mem_read(dest+n, 16)), b'\xA5'*16)
        self.assertEqual(struct.unpack('<HHII', m.mu.mem_read(dest+92, 12)),
                         (0x4653, 7, 768, 108))
        m = self.machine()
        m.fail_size = n
        dest = m.call(0xC038A4A0, 0xC358E9D8, n)
        self.assertEqual(dest, 0)
        with self.assertRaises(C.CapacityError):
            self.admission(m, allocation=dest, raw_start=4096)

    def test_instruction_mutation_breaks_native_size_contract(self):
        m = self.machine()
        self.assertEqual(m.snapshot().reserved_bytes, 0xB000)
        # Skip first child's contribution, after native code has been translated.
        self.assertEqual(m.word(0xC0696D00), 0xE0844001)
        m.write(0xC0696D00, 0xE1A00000)
        m.mu.ctl_remove_cache(0xC0696D00, 0xC0696D04)
        self.assertEqual(m.call(A.SIZE_FN, ROOT), 0)
        with self.assertRaisesRegex(C.CapacityError, 'disagrees'):
            m.snapshot()


if __name__ == '__main__':
    unittest.main()
