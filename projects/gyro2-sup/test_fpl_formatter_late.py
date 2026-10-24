"""Final-population tag ABI and failure-event enqueue, offline official ARM.

Population getters/provider serialization and tag insertion are explicit stubs
in the call-trace test. Separate real-native sizing/removal tests establish why
the finished prefix cannot determine the missing pre-population graph.
"""
import struct
import unittest
from unicorn.arm_const import UC_ARM_REG_SP

import test_fpl_formatter as F
import test_fpl_formatter_dng as D
import test_fpl_tag_capacity as N
import test_fpl_observer as T

ROOT_TAGS = (0x100, 0x101, 0x102, 0x103, 0x111, 0x116, 0x117,
             0xC61D, 0xC61F, 0xC65A, 0xC65B)
PROXY, KIND, MANAGER, EVENT, PROVIDER, PVT, AVAILABLE = [T.DATA+x for x in
    (0x38000, 0x38010, 0x38100, 0x38200, 0x38400, 0x38500, 0x38600)]


class LateMachine(D.DngMachine):
    def __init__(self, *args):
        self.adds, self.queued = [], []
        self.queue_room = 1
        self.record_adds = False
        super().__init__(*args)
        self.pool_serializer = self.word(0xC07333D4+0xC)
        self.write(PROXY, KIND)
        self.write(KIND, 0)
        self.write(0xC2F2F838, PROVIDER)
        self.write(PROVIDER, PVT)
        self.write(PVT+0x14, AVAILABLE)

    def hook(self, mu, addr, size, userdata):
        r = [mu.reg_read(x) for x in T.REGS]
        sp = mu.reg_read(UC_ARM_REG_SP)
        if self.record_adds and addr in (0xC00B6B20, 0xC00B6AB8):
            if addr == 0xC00B6B20:
                self.adds.append((r[1], r[2], r[3], self.word(sp)))
            else:
                self.adds.append((r[1], r[3], self.word(sp), self.word(sp+4)))
            self.ret(1)  # call ABI recorder, NOT successful native storage
            return
        if addr in (0xC02DE918, 0xC02DE818, 0xC0022C40):
            self.ret({0xC02DE918: 8, 0xC02DE818: 8367528, 0xC0022C40: PROXY}[addr])
            return
        if self.record_adds and addr == self.pool_serializer:
            assert r[2] == 0x4000
            mu.mem_write(r[1], bytes(r[2]))
            self.ret(r[2])  # provider contents opaque; fixed caller capacity
            return
        if addr == 0xC0388BA8:
            self.ret(MANAGER)
            return
        if addr == AVAILABLE:
            self.ret(self.queue_room)
            return
        if addr == 0xC03AC518:
            assert r[0] == 0x168
            self.ret(EVENT)
            return
        if addr == 0xC0014DAC:
            mu.mem_write(r[0], bytes(mu.mem_read(r[1], r[2])))
            self.ret(r[0])
            return
        if addr == 0xC036DB60:
            self.queued.append((tuple(r), bytes(mu.mem_read(r[2], 0x168))))
            self.ret(0)  # queue boundary only; NO consumer/task is executed
            return
        if addr == 0xC001A450:
            self.ret(0)  # queue-pressure diagnostic
            return
        ranges = ((0xC06A2858, 0x78), (0xC06A2F18, 0x3A0),
                  (0xC06A32B8, 0x98), (0xC06A3750, 0x118),
                  (0xC06A3910, 0x10), (0xC06A3940, 0x10),
                  (0xC0385978, 0x120), (0xC03A9798, 0x110))
        if any(a <= addr < a+n for a, n in ranges):
            return
        super().hook(mu, addr, size, userdata)


class LatePopulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        D.RealDng.setUpClass.__func__(cls)

    def machine(self):
        m = LateMachine(N.NativeCapacity.image, F.NativeFormatter.data,
                        N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        return m

    def populate(self, m, compressed=0, private=0):
        m.write(F.LEFT+0x14, 0xC2E4A5B0)
        m.write(F.LEFT+0x88, 1)
        m.write(F.LEFT+0x18, 3856)
        m.write(F.LEFT+0x1C, 2170)
        m.write(F.LEFT+0x6C, compressed)
        m.write(F.LEFT+0x80, 6)  # explicit synthetic tile count
        m.write(KIND, private)
        m.record_adds = True
        m.call(0xC06A2858, F.LEFT, T.BUILDER, T.POOL)
        return m.adds

    def test_uncompressed_final_population_fixed_request_shapes(self):
        expected = [(0, t, 3 if t in (0x102, 0x103, 0xC65A, 0xC65B) else 4,
                     2 if t == 0xC61F else 1) for t in ROOT_TAGS]
        expected.append((5, 0x200, 7, 0x4000))
        self.assertEqual(self.populate(self.machine()), expected)

    def test_mode_inputs_change_request_set_and_counts(self):
        m = self.machine()
        requests = self.populate(m, compressed=1, private=1)
        self.assertIn((0, 0x144, 4, 6), requests)
        self.assertIn((0, 0x145, 4, 6), requests)
        self.assertNotIn((0, 0x111, 4, 1), requests)
        for tag in (0x101F, 0x201F, 0x301F):
            self.assertIn((8, tag, 3, 4), requests)

    def test_mutation_omitting_makernote_population_changes_trace(self):
        m = self.machine()
        # The final BL in C06A2858 invokes the 16 KiB producer.
        original = m.word(0xC06A28C8)
        self.assertEqual(original >> 24, 0xEB)
        m.write(0xC06A28C8, 0xE1A00000)
        m.mu.ctl_remove_cache(0xC06A28C8, 0xC06A28CC)
        self.assertNotIn((5, 0x200, 7, 0x4000), self.populate(m))

    def test_final_extent_does_not_determine_initial_extent(self):
        m = self.machine()
        final = m.call(0xC00B6510, T.BUILDER)
        self.assertEqual(final, 0x135C4)
        for tag in ROOT_TAGS:
            m.call(0xC00BAA98, N.ROOT, tag)
        m.call(0xC00BAA98, N.MAKER, 0x200)
        without = m.call(0xC00B6510, T.BUILDER)
        self.assertEqual(final-without, 0x4098)
        self.assertEqual(without, 0xF52C)
        # 0x4098 is the all-absent hypothesis, NOT measured mode-0 delta.

    def test_failure_event_is_queued_not_a_synchronous_frame_barrier(self):
        m = self.machine()
        self.assertEqual(m.call(0xC0385978, 0, 0x1234, 0, 0x5678), 1)
        self.assertEqual(len(m.queued), 1)
        args, event = m.queued[0]
        self.assertEqual(args[0], MANAGER+8)
        self.assertEqual(struct.unpack_from('<I', event, 4)[0], 0x2B)
        self.assertEqual(struct.unpack_from('<I', event, 12)[0], 5)
        self.assertEqual(struct.unpack_from('<I', event, 0xE8)[0], 0x1234)
        self.assertEqual(struct.unpack_from('<I', event, 0xE4)[0], 0x5678)
        m.queue_room = 0
        self.assertEqual(m.call(0xC0385978, 0, 0x1234, 0, 0x5678), 0)
        self.assertEqual(len(m.queued), 1)  # even notification delivery can fail

    def test_event_id_mutation_loses_reserved_pool_admission(self):
        m = self.machine()
        self.assertEqual(m.word(0xC0385A6C), 0xE3A0C02B)
        m.write(0xC0385A6C, 0xE3A0C02A)
        m.mu.ctl_remove_cache(0xC0385A6C, 0xC0385A70)
        self.assertEqual(m.call(0xC0385978, 0, 0x1234, 0, 0x5678), 0)
        self.assertEqual(m.queued, [])


if __name__ == '__main__':
    unittest.main()
