"""Offline replay of owner's hash-pinned context; no device access.

FPL_CONTEXT must name the external snapshot_C31F6ABC.bin; absent input skips.
"""
import os
from pathlib import Path
import struct
import unittest

import audit_formatter as A
import test_fpl_formatter as F
import test_fpl_formatter_edges as E
import test_fpl_tag_capacity as N
import test_fpl_observer as T

CONTEXT, RESULT = T.DATA+0x32000, T.DATA+0x33000
PVT, AVAILABLE, ALLOCATE = T.DATA+0x33100, T.DATA+0x33200, T.DATA+0x33204


class GeometryBoundary(RuntimeError):
    pass


class Replay(E.Edges):
    def __init__(self, *args):
        self.parameter_allocations = []
        self.parameter_fail = False
        self.geometry_args = None
        super().__init__(*args)
        self.parameter_pool = self.word(0xC2F3F908)  # official DATA, distinct pool
        self.write(self.parameter_pool, PVT)
        self.write(PVT+0x14, AVAILABLE)
        self.write(PVT+0xC, ALLOCATE)

    def hook(self, mu, addr, size, userdata):
        r = [mu.reg_read(reg) for reg in T.REGS]
        if addr in (AVAILABLE, ALLOCATE):
            assert r[0] == self.parameter_pool
            if addr == AVAILABLE:
                self.ret(1)
            else:
                assert r[1] == 0x134
                p = 0 if self.parameter_fail else self.next_heap
                self.parameter_allocations.append((r[1], p))
                if p:
                    self.next_heap += 0x140
                self.ret(p)
            return
        if addr == 0xC06A4440:
            self.geometry_args = tuple(r)
            raise GeometryBoundary('native factory reached runtime geometry construction')
        ranges = ((0xC06A2618, 0x1CC), (0xC0697830, 0xA0),
                  (0xC0698740, 0x78), (0xC06988B0, 0x60),
                  (0xC0697D88, 0x100), (0xC02E9B80, 0x4C),
                  (0xC02E9CA8, 0x60), (0xC03811C8, 0x54),
                  (0xC06A3AB8, 0x28), (0xC0374438, 0x48),
                  (0xC03755D8, 0x40))
        if any(a <= addr < a+n for a, n in ranges):
            self.trace.add(addr)
            return
        super().hook(mu, addr, size, userdata)


class LiveContextReplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('FPL_CONTEXT')
        if not path or not Path(path).is_file():
            raise unittest.SkipTest('external FPL_CONTEXT snapshot absent; live-state replay unavailable')
        cls.context = A.validate_live_context(Path(path).read_bytes())
        F.NativeFormatter.setUpClass()

    def machine(self):
        m = Replay(N.NativeCapacity.image, F.NativeFormatter.data,
                   N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.mu.mem_write(CONTEXT, self.context)
        return m

    def test_pre_take_snapshot_edges_are_not_mid_take_prediction(self):
        m = self.machine()
        self.assertEqual(tuple(m.word(CONTEXT+x) for x in (0x44, 0x30, 0xC)), (0, 0, 0))
        self.assertEqual((m.word(CONTEXT), m.word(CONTEXT+4)), (3840, 2160))
        m.selection = True  # geometry, selected constructor, allocation stubs explicit in Edges
        # These are predictions ONLY for this earlier captured input. The actual
        # take has a sentinel right leaf and +88=1; see test_fpl_formatter_take.
        m.call(0xC06A2490, CONTEXT, F.LEFT)
        self.assertIn(0xC06A40A0, [a for a, _ in m.edges])
        self.assertNotIn(0xC06A3FC8, [a for a, _ in m.edges])
        self.assertEqual(m.word(E.OPAQUE+0x14), 0xC2E4A5B0)
        m.edges.clear()
        m.call(0xC06A25C0, CONTEXT, F.LEFT)
        self.assertEqual([a for a, _ in m.edges], [0xC06A2438])
        # Right constructor is an opaque edge stub; official code establishes its table.
        self.assertEqual(m.word(0xC2E4A4B0+0x2C), 0xC06A1D58)

    def test_native_factory_builds_parameter_values_then_stops_at_geometry(self):
        m = self.machine()
        with self.assertRaises(GeometryBoundary):
            m.call(0xC06A2618, RESULT, CONTEXT)
        self.assertEqual(m.geometry_args[1], CONTEXT)
        self.assertEqual(m.parameter_pool, 0xC3828E54)
        self.assertEqual(len(m.parameter_allocations), 1)
        n, p = m.parameter_allocations[0]
        self.assertEqual(n, 0x134)
        # Native pair-copy reads contents at snapshot+1C; it never dereferences 0x2530.
        pair = bytes(self.context[0x1C:0x24])
        self.assertEqual(struct.unpack('<I', pair[:4])[0], 0x2530)
        self.assertEqual(bytes(m.mu.mem_read(p, 8)), pair)
        self.assertEqual(bytes(m.mu.mem_read(p+0x30, 8)), pair)
        self.assertEqual(m.word(p+0x130), 0xC2E49060)
        self.assertTrue({0xC0697830, 0xC0698740, 0xC06988B0,
                         0xC0697D88, 0xC02E9B80, 0xC06A2618} <= m.trace)
        self.assertEqual(m.word(RESULT), 0)  # no completed selected composite claimed

    def test_factory_parameter_allocation_failure_asserts(self):
        m = self.machine()
        m.parameter_fail = True
        with self.assertRaises(N.NativeAssert):
            m.call(0xC06A2618, RESULT, CONTEXT)
        self.assertIsNone(m.geometry_args)

    def test_capture_mutation_is_rejected(self):
        b = bytearray(self.context)
        b[0x30] ^= 1
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            A.validate_live_context(bytes(b))

    def test_fixed_registry_lookup_and_invalid_index(self):
        m = self.machine()
        self.assertEqual(m.call(0xC0374438), 0xC3520D84)
        m.write(0xC3520D88+7*4, E.RECORD)
        self.assertEqual(m.call(0xC03755D8, 0xC3520D84, 7), E.RECORD)
        for index in (0x60, 0xFFFFFFFF):
            self.assertEqual(m.call(0xC03755D8, 0xC3520D84, index), 0)


if __name__ == '__main__':
    unittest.main()
