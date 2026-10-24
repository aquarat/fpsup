"""The per-frame observer's GYRO build, against native fp L code.

Runs the exact fpSup/fp_usb_shell/asm/fpl_gtagpf.S bytes built with GYRO=1:
native Subject/attach/notify/add-tag/serialize on the real-DNG
reconstruction (as test_fpl_gtagpf), plus the SHARED gyro/gyro_drain.S
draining a simulated coprocessor ring into the frame's block.  The ring
producer and the TickTimer (C0029320) are simulated: this proves the block
format, latching, wrap, capacity and failure accounting, not fp L's rate,
scales, axes or ring coherence, which are what a live take would measure.
"""
import struct
import sys
import unittest
from pathlib import Path

import fsg2
import test_fpl_gtagpf as P

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fpSup/fp_usb_shell'))
import armasm  # noqa: E402

N = 1584                                   # largest N keeping H at 0x13C00
DEFINES = [f'PARAM={P.PARAM:#x}', f'SRC={P.SRC:#x}', f'N={N}', 'GYRO=1']
GLOBAL, PDESC, RING = 0xC31E23CC, 0x2E006004, 0x2E00644C
SPAN, F_TICK = 600, 0xC0029320
GMAGIC, HDR = 0x474C5046, 0x40
FIELDS = ('magic', 'index', 'tick', 'prev_tick', 'before', 'latched', 'after', 'due',
          'written', 'dropped', 'padbad', 'status', 'tick_after', 'capacity',
          'total_written', 'total_dropped')


class GyroMachine(P.GtagMachine):
    tick = 1000000
    on_drain = None

    def hook(self, mu, addr, size, userdata):
        if addr == F_TICK:
            self.tick += 37
            self.ret(self.tick)
            return
        if self.on_drain and addr == P.CODE + self.sym['gyro_drain']:
            self.on_drain()
        super().hook(mu, addr, size, userdata)


class GyroPf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        P.GtagPf.setUpClass.__func__(cls)
        cls.code = armasm.assemble(P.SOURCE, DEFINES)
        cls.sym = armasm.symbols(P.SOURCE, DEFINES)

    def machine(self, code=None):
        import test_fpl_formatter as F
        import test_fpl_tag_capacity as Ncap
        m = GyroMachine(Ncap.NativeCapacity.image, F.NativeFormatter.data,
                        Ncap.NativeCapacity.code, Ncap.NativeCapacity.offsets)
        m.sym = self.sym
        m.reconstruct(self.prefix)
        m.mu.mem_map(P.CODE, 0x4000)
        m.mu.mem_map(P.TEMPLATE, 0x40000)
        m.mu.mem_map(0x2E000000, 0x10000)
        m.mu.mem_write(P.CODE, code or self.code)
        m.mu.mem_write(P.SRC, bytes(N))
        m.write(P.OBJ, P.VT)
        for k in range(3):
            m.write(P.VT + 4 * k, P.CODE + self.sym['ret0'])
        m.write(P.VT + 12, P.CODE + self.sym['observer'])
        m.write(GLOBAL, PDESC)
        m.write(PDESC + 0x60, RING)
        self.head = 0                      # records published so far (all time)
        self.publish(m, SPAN)              # a full ring of history
        self.assertEqual(m.call(P.CODE), 0)
        self.assertEqual(m.word(P.PARAM), 2)
        return m

    def record(self, i):
        return (i & 0x7FFF, -(i & 0x7FFF), (3 * i) & 0x7FFF)

    def publish(self, m, count):
        """The coprocessor: `count` records, then the head (R + 8*(j+1))."""
        for _ in range(count):
            j = self.head % SPAN
            x, y, z = self.record(self.head)
            m.mu.mem_write(RING + 4 + 8 * j, struct.pack('<hhhh', x, y, 0, z))
            self.head += 1
        j = (self.head - 1) % SPAN if self.head else SPAN - 1
        m.write(RING, RING + 8 * (j + 1))

    def take(self, m):
        m.notify(0)
        size, h, header = m.output()
        self.assertEqual(h, 0x13C00)               # one 0x400 step, as N=561 live
        _, count, off = self.gtag(header)
        self.assertEqual(count, N)
        m.mu.mem_write(P.TEMPLATE, header)
        m.write(P.TPTR, P.TEMPLATE)
        m.write(P.TLEN, h)
        m.notify(2)
        self.assertEqual(m.word(P.PARAM + 0x3C), 1)
        return h, off

    def gtag(self, data):
        _, maker = fsg2.maker_note(data)
        return maker[fsg2.GTAG]

    def frame(self, m, h):
        """One mode-3 notify; the frame's DMA copy of its block and records."""
        m.notify(3)
        data = bytes(m.mu.mem_read(P.TEMPLATE, h))
        _, count, off = self.gtag(data)
        block = (off + 3) & ~3
        head = dict(zip(FIELDS, struct.unpack_from('<16I', data, block)))
        n = head['written']
        recs = [struct.unpack_from('<hhhh', data, block + HDR + 8 * k) for k in range(n)]
        self.assertTrue(all(r[2] == 0 for r in recs))      # the shared drain's tag 0
        return head, [(x, y, z) for x, y, _, z in recs]

    def addr(self, n):
        """The published head after n records in all."""
        return RING + 8 * ((n - 1) % SPAN + 1)

    def expect(self, first, count):
        return [self.record(i) for i in range(first, first + count)]

    def local(self, m, name):
        return m.word(P.CODE + self.sym[name])

    def test_frames_carry_the_records_since_the_last_notify(self):
        m = self.machine()
        h, off = self.take(m)
        self.assertEqual(self.local(m, 'arm_status'), 0)
        armed_tick = m.word(P.PARAM + 0xFC)
        cap = m.word(P.PARAM + 0xF8)
        self.assertEqual(cap, (N - ((off + 3) & ~3) + off - HDR) // 8)
        self.publish(m, 100)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['magic'], b1['index'], b1['status']), (GMAGIC, 1, 0))
        # Frame 1 reaches back one capacity from its own latch.
        self.assertEqual((b1['due'], b1['written'], b1['dropped']), (cap, cap, 0))
        self.assertEqual(r1, self.expect(self.head - cap, cap))
        self.assertEqual(b1['before'], self.addr(self.head - cap))
        self.assertEqual(b1['latched'], self.addr(self.head))
        self.assertEqual(b1['prev_tick'], armed_tick)        # frame 1: from mode 2
        self.assertLess(b1['prev_tick'], b1['tick'])
        self.assertLess(b1['tick'], b1['tick_after'])
        one = self.head
        self.publish(m, 530)                        # crosses the ring's end
        b2, r2 = self.frame(m, h)
        self.assertEqual((b2['index'], b2['due'], b2['written'], b2['dropped']),
                         (2, 530, cap, 530 - cap))
        self.assertEqual(r2, self.expect(one, cap))           # oldest first
        self.assertEqual(b2['before'], b1['latched'])         # the cursor chains
        self.assertEqual(b2['prev_tick'], b1['tick'])
        self.publish(m, 7)
        b3, r3 = self.frame(m, h)
        self.assertEqual(r3, self.expect(one + 530, 7))       # dropped ones are gone
        self.assertEqual((b3['total_written'], b3['total_dropped']),
                         (cap + cap + 7, 530 - cap))
        self.assertEqual(self.local(m, 'frames_ok'), 3)
        self.assertEqual(m.word(P.PARAM + 0x54), 3)          # writes, as the pattern build

    def test_long_arming_gap_cannot_lap_frame_one(self):
        # Live 24 October: mode 2 came 331 ms (827 records) before frame 1 and
        # the drain from the arming lost a lap.  Frame 1 must carry the true
        # last `capacity` records anyway.
        m = self.machine()
        h, _ = self.take(m)
        cap = m.word(P.PARAM + 0xF8)
        self.publish(m, 827)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['status'], b1['due'], b1['written'], b1['dropped']), (0, cap, cap, 0))
        self.assertEqual(r1, self.expect(self.head - cap, cap))
        self.publish(m, 50)
        b2, r2 = self.frame(m, h)
        self.assertEqual(r2, self.expect(self.head - 50, 50))

    def test_producer_moving_during_the_drain_is_latched(self):
        m = self.machine()
        h, _ = self.take(m)
        cap = m.word(P.PARAM + 0xF8)
        self.publish(m, 20)
        latched = self.head
        m.on_drain = lambda: self.publish(m, 5)
        b1, r1 = self.frame(m, h)
        m.on_drain = None
        self.assertEqual((b1['status'], b1['due'], b1['written']), (0, cap, cap))
        self.assertEqual(b1['latched'], self.addr(latched))
        self.assertEqual(b1['after'], self.addr(latched + 5))  # five more arrived
        self.assertEqual(r1, self.expect(latched - cap, cap))
        b2, r2 = self.frame(m, h)
        self.assertEqual(r2, self.expect(latched, 5))         # and go with the next

    def test_invalid_ring_is_a_status_not_a_copy(self):
        m = self.machine()
        h, _ = self.take(m)
        armed = self.head
        self.publish(m, 10)
        m.write(GLOBAL, 0)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['magic'], b1['status'], b1['written'], b1['latched']),
                         (GMAGIC, 3, 0, 0))
        m.write(GLOBAL, PDESC)
        m.write(PDESC + 0x60, RING + 8)
        b2, _ = self.frame(m, h)
        self.assertEqual((b2['status'], b2['written']), (5, 0))
        m.write(PDESC + 0x60, RING)
        m.write(RING, RING + 4)                               # head not on a record
        b3, _ = self.frame(m, h)
        self.assertEqual(b3['status'], 6)
        self.publish(m, 3)
        b4, r4 = self.frame(m, h)
        self.assertEqual((b4['index'], b4['status']), (4, 0))
        self.assertEqual(r4, self.expect(armed, 13))          # from the arming: nothing lost
        self.assertEqual(self.local(m, 'frames_ok'), 1)

    def test_arm_failure_does_not_matter_to_frame_one(self):
        m = self.machine()
        m.write(GLOBAL, 0)
        h, _ = self.take(m)
        self.assertEqual(self.local(m, 'arm_status'), 3)
        cap = m.word(P.PARAM + 0xF8)
        m.write(GLOBAL, PDESC)
        self.publish(m, 9)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['status'], b1['written']), (0, cap))
        self.assertEqual(r1, self.expect(self.head - cap, cap))
        one = self.head
        self.publish(m, 4)
        b2, r2 = self.frame(m, h)
        self.assertEqual(r2, self.expect(one, 4))

    def test_second_take_rearms_and_restarts_counts(self):
        m = self.machine()
        h, _ = self.take(m)
        cap = m.word(P.PARAM + 0xF8)
        self.publish(m, 50)
        self.frame(m, h)
        self.publish(m, 30)
        h, _ = self.take(m)
        self.publish(m, 6)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['index'], b1['total_written']), (1, cap))
        self.assertEqual(r1, self.expect(self.head - cap, cap))

    def test_mutation_without_the_frame_drain_writes_no_records(self):
        # Replace gyro_frame's BL to the shared drain with a NOP: the unmutated
        # assertion (frame 1 carries the records) must fail.
        start, drain = self.sym['gyro_frame'], self.sym['gyro_drain']
        end = self.sym['validate']
        code = bytearray(self.code)
        hits = [a for a in range(start, end, 4)
                if struct.unpack_from('<I', code, a)[0] ==
                0xEB000000 | (((drain - a - 8) >> 2) & 0xFFFFFF)]
        self.assertEqual(len(hits), 1)
        struct.pack_into('<I', code, hits[0], 0xE320F000)
        m = self.machine(bytes(code))
        h, _ = self.take(m)
        self.publish(m, 12)
        b1, r1 = self.frame(m, h)
        self.assertEqual((b1['written'], r1), (0, []))
        self.assertEqual(b1['status'], 7)            # and it says so


if __name__ == '__main__':
    unittest.main()
