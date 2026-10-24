"""Conditional native edges and frozen ownership; no asserted camera mode."""
from dataclasses import replace
import struct
import unittest
from unicorn.arm_const import UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_PC

import test_fpl_formatter as F
import test_fpl_tag_capacity as N
import test_fpl_observer as T
import formatter_contract as C

OWNER, RECORD = 0xC358E9D8, T.DATA+0x31000
PARAM, OPAQUE = T.DATA+0x31200, T.DATA+0x31400
EMPTY24, EMPTY2C = T.DATA+0x31800, T.DATA+0x31804


class Edges(F.Formatter):
    def __init__(self, *args):
        self.selection = False
        self.selection_fail = False
        self.edges, self.releases, self.transfers = [], [], []
        super().__init__(*args)

    def hook(self, mu, addr, size, userdata):
        r = [mu.reg_read(reg) for reg in T.REGS]
        if addr in (EMPTY24, EMPTY2C):
            self.edges.append((addr, tuple(r)))
            self.ret(0)  # missing builder dependency, not an emulated serializer
            return
        if self.selection:
            if addr == 0xC0437358:  # opaque geometry wrapper, not native geometry
                self.edges.append((addr, tuple(r)))
                self.write(r[0], OPAQUE+0x100)
                self.ret(r[0])
                return
            if addr == 0xC06A4180:
                self.edges.append((addr, tuple(r)))
                self.ret(0 if self.selection_fail else OPAQUE)
                return
            if addr in (0xC06A3FC8, 0xC06A40A0, 0xC022C028):
                self.edges.append((addr, tuple(r)))
                self.ret(r[0])
                return
            if addr in (0xC06A2438, 0xC0697510):
                self.edges.append((addr, tuple(r)))
                self.ret(OPAQUE if addr == 0xC06A2438 else 0)
                return
        if addr == 0xC001D2B8:
            self.releases.append((r[0], r[1]))
            self.ret()
            return
        if addr == 0xC00F8440:
            self.transfers.append(struct.unpack('<3I', mu.mem_read(r[0], 12)))
            self.ret()
            return
        ranges = ((0xC06A2490, 0x188), (0xC0696DB0, 0x60),
                  (0xC06973C8, 0x18), (0xC0010C98, 0x40),
                  (0xC038A508, 0x28), (0xC038C964, 0x34))
        ranges += ((0xC0022920, 0x288), (0xC06A28D0, 0xA8),
                   (0xC06A2C98, 0x10), (0xC0697298, 0x28),
                   (0xC0697AE0, 0x48))
        if any(a <= addr < a+n for a, n in ranges):
            self.trace.add(addr)
            return
        super().hook(mu, addr, size, userdata)

    def dma_fragment(self):
        # Not a function entry: seed documented live r5/SP and stop at the next
        # instruction. No surrounding frame routine or DMA hardware is simulated.
        self.mu.reg_write(UC_ARM_REG_R5, RECORD)
        self.mu.reg_write(UC_ARM_REG_SP, T.STACK+0xFE00)
        self.mu.emu_start(0xC038C964, 0xC038C998, count=1000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == 0xC038C998
        return self.transfers[-1]


class FormatterEdges(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        F.NativeFormatter.setUpClass()

    def machine(self):
        m = Edges(N.NativeCapacity.image, F.NativeFormatter.data,
                  N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.construct()
        return m

    def fixture(self):
        m = self.machine()
        size = m.snapshot().reserved_bytes
        source = m.call(0xC038A4A0, OWNER, size)
        m.add()
        m.write(OWNER+8, F.ROOT)
        m.write(OWNER+12, 876)
        m.write(RECORD+0x14C, 876)
        m.write(RECORD+0x4C, N.HEAP+0x80000)
        o = C.Ownership(source, size, 1, N.HEAP+0x70000, N.HEAP+0x90000)
        return m, o

    def freeze(self, m, o):
        return C.freeze_transfer(m.mu.mem_read, m.call, F.ROOT, N.MAKER,
                                 OWNER, RECORD, ownership=o, prefix_bytes=90)

    def test_conditional_selection_edges_not_mode_names(self):
        for kind, secondary, flag, ctor in (
                (2, 9, 0, 0xC06A3FC8), (2, 9, 1, 0xC06A40A0),
                (0, 0, 0, 0xC06A40A0), (0, 1, 0, 0xC06A40A0),
                (0, 9, 0, 0xC06A2438)):
            with self.subTest(inputs=(kind, secondary, flag)):
                m = self.machine()
                m.selection = True
                for off, val in ((0x44, kind), (0x30, secondary), (0xC, flag)):
                    m.write(PARAM+off, val)
                self.assertEqual(m.call(0xC06A2490, PARAM, F.LEFT), OPAQUE)
                self.assertIn(ctor, [a for a, _ in m.edges])
                if ctor != 0xC06A2438:
                    self.assertEqual(m.word(OPAQUE+0x14), 0xC2E4A5B0)
                m.edges.clear()
                right = m.call(0xC06A25C0, PARAM, F.LEFT)
                self.assertEqual(right, OPAQUE if kind != 2 and secondary == 0 else 0)

    def test_selection_allocation_failure_skips_constructor(self):
        m = self.machine()
        m.selection = m.selection_fail = True
        m.write(PARAM+0x44, 2)
        self.assertEqual(m.call(0xC06A2490, PARAM, F.LEFT), 0)
        self.assertNotIn(0xC06A3FC8, [a for a, _ in m.edges])

    def test_native_default_context_does_not_select_tiff_branch(self):
        m = self.machine()
        m.call(0xC0022920, PARAM)
        self.assertEqual(tuple(m.word(PARAM+x) for x in (0x44, 0x30, 0xC)), (0, 3, 1))
        m.selection = True
        m.call(0xC06A2490, PARAM, F.LEFT)
        self.assertEqual([a for a, _ in m.edges], [0xC06A2438])

    def test_selected_length_missing_builder_and_destination_returns_zero(self):
        for flag, getter in ((0, EMPTY24), (1, EMPTY2C)):
            m = self.machine()
            m.write(OPAQUE, OPAQUE+0x100)
            m.write(OPAQUE+0x124, EMPTY24)
            m.write(OPAQUE+0x12C, EMPTY2C)
            m.mu.mem_write(F.LEFT+0x88, bytes([flag]))
            # Run actual slot implementation's early failure path on a base
            # probe with zero destination, NOT a constructed selected instance.
            self.assertEqual(m.call(0xC06A28D0, F.LEFT, OPAQUE), 0)
            self.assertIn(getter, [a for a, _ in m.edges])

    def test_selection_instruction_mutation_changes_expected_edge(self):
        m = self.machine()
        m.selection = True
        m.write(PARAM+0x44, 2)
        m.write(PARAM+0x30, 9)
        m.call(0xC06A2490, PARAM, F.LEFT)
        self.assertIn(0xC06A3FC8, [a for a, _ in m.edges])
        self.assertEqual(m.word(0xC06A24A4), 0xE3520002)
        m.write(0xC06A24A4, 0xE3520003)
        m.mu.ctl_remove_cache(0xC06A24A4, 0xC06A24A8)
        m.edges.clear()
        m.call(0xC06A2490, PARAM, F.LEFT)
        self.assertEqual([a for a, _ in m.edges], [0xC06A2438])

    def test_composite_preparation_partitions_by_left_reservation(self):
        m = self.machine()
        base = N.HEAP+0x80000
        m.call(0xC0696DB0, F.ROOT, base)
        self.assertEqual(m.word(F.LEFT+4), base)
        self.assertEqual(m.word(F.RIGHT+4), base+0xB000)
        # Actual selected leaf has a different prepare slot; base probe only.
        self.assertEqual(m.word(0xC2E4A5B0+0x10), 0xC0720418)

    def test_template_reuse_release_and_same_address_generation(self):
        m, o = self.fixture()
        before = self.freeze(m, o)
        first = m.dma_fragment()
        self.assertEqual(m.dma_fragment(), first)
        self.assertEqual(m.word(OWNER+0x10), o.allocation)
        self.assertEqual(m.releases, [])
        m.call(0xC038A508, OWNER)
        self.assertEqual(m.releases, [(0x12345678, o.allocation)])
        self.assertEqual(m.word(OWNER+0x10), 0)
        with self.assertRaises(C.CapacityError):
            self.freeze(m, o)
        # Stub intentionally reuses address, so an externally tracked epoch matters.
        self.assertEqual(m.call(0xC038A4A0, OWNER, o.allocation_bytes), o.allocation)
        with self.assertRaises(C.CapacityError):
            C.admit_transfer(before, self.freeze(m, replace(o, generation=2)))

    def test_dma_native_subtraction_matches_frozen_contract(self):
        m, o = self.fixture()
        before = self.freeze(m, o)
        expected = C.admit_transfer(before, self.freeze(m, o))
        m.mu.mem_write(o.allocation, b'\xA5'*(o.allocation_bytes+16))
        m.call(0xC00BAC20, N.MAKER, 0x4949, o.allocation, o.allocation+90)
        self.assertEqual(bytes(m.mu.mem_read(o.allocation+876, 16)), b'\xA5'*16)
        self.assertEqual(bytes(m.mu.mem_read(o.allocation+o.allocation_bytes, 16)), b'\xA5'*16)
        self.assertEqual(C.admit_transfer(before, self.freeze(m, o)), expected)
        self.assertEqual(m.dma_fragment(), expected)
        self.assertEqual(expected, (o.allocation, N.HEAP+0x80000-876, 876))

    def test_same_size_ifd_payload_mutation_is_refused(self):
        m, o = self.fixture()
        before = self.freeze(m, o)
        entry = m.call(0xC00BAA10, N.MAKER, 0x4653)
        data = m.word(m.word(entry+0x10)+8)
        m.mu.mem_write(data, b'X')
        self.assertEqual(m.native_size(), 786)
        with self.assertRaises(C.CapacityError):
            C.admit_transfer(before, self.freeze(m, o))

    def test_missing_ownership_length_and_destination_failures(self):
        for field, val in ((OWNER+0x10, 0), (OWNER+12, 875),
                           (RECORD+0x14C, 875), (RECORD+0x4C, 100),
                           (RECORD+0x4C, N.HEAP+0x90001)):
            m, o = self.fixture()
            m.write(field, val)
            with self.subTest(field=hex(field)), self.assertRaises(C.CapacityError):
                self.freeze(m, o)
        m, o = self.fixture()
        with self.assertRaises(C.CapacityError):
            self.freeze(m, None)
        # Native subtraction wraps; independent frame extent must reject it.
        m.write(RECORD+0x4C, 100)
        self.assertEqual(m.dma_fragment()[1], (100-876) & 0xFFFFFFFF)

    def test_dma_instruction_mutation_disagrees_with_contract(self):
        m, o = self.fixture()
        expected = C.admit_transfer(self.freeze(m, o), self.freeze(m, o))
        self.assertEqual(m.dma_fragment(), expected)
        self.assertEqual(m.word(0xC0010CC4), 0xE04C2004)
        m.write(0xC0010CC4, 0xE08C2004)  # SUB -> ADD, emulator only
        m.mu.ctl_remove_cache(0xC0010CC4, 0xC0010CC8)
        self.assertNotEqual(m.dma_fragment(), expected)


if __name__ == '__main__':
    unittest.main()
