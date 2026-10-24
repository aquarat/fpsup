"""Offline host teardown/marker and frame-listing checks for fpl_gtagpf.py."""
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fpl_gtagpf as P

OBJ = 0x4534B000


class Fake:
    """Subject slots and owner words only; set_word can be made to stick."""

    def __init__(self, recording=False, stuck=False):
        self.mem = {P.SUBJECT + 4 * i: v for i, v in
                    enumerate([1, 2, 3, 0, 4, 5, OBJ, 0, 6])}
        for i in range(6):
            self.mem[P.OWNER + 4 * i] = 0
        self.mem[P.OWNER] = int(recording)
        self.stuck = stuck

    def words(self, address, count):
        return [self.mem.get(address + 4 * i, 0) for i in range(count)]

    def set_word(self, address, value):
        if not self.stuck:
            self.mem[address] = value


def log(key, value):
    pass


class Teardown(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        marker = Path(self.tmp.name) / 'fpl-staging.pending'
        patcher = patch.object(P, 'MARKER', marker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.marker = marker

    def run_with(self, io, take):
        with patch.object(P.gf, 'assemble', return_value=b'\0' * 16), \
                patch.object(P.armasm, 'symbols', return_value=dict(ret0=0, observer=8)), \
                patch.object(P, 'attach_and_take', side_effect=take):
            plan = type('Plan', (), dict(code=OBJ - 0x900, param=OBJ - 0x100, buffer=OBJ + 0xB00))
            return P.run(io, log, [1, 2, 3], plan)

    def test_clean_take_clears_slot_and_marker(self):
        io = Fake()
        seen = []
        self.assertEqual(self.run_with(io, lambda *a: seen.append(self.marker.exists()) or 'ok'), 'ok')
        self.assertEqual(seen, [True])            # marker present while attached
        self.assertNotIn(OBJ, io.words(P.SUBJECT, P.SLOTS))
        self.assertEqual(io.words(P.SUBJECT, 4), [1, 2, 3, 0])   # others untouched
        self.assertFalse(self.marker.exists())

    def test_failed_take_still_detaches_when_idle(self):
        io = Fake()

        def take(*a):
            raise RuntimeError('lost read')
        with self.assertRaisesRegex(RuntimeError, 'lost read'):
            self.run_with(io, take)
        self.assertNotIn(OBJ, io.words(P.SUBJECT, P.SLOTS))
        self.assertFalse(self.marker.exists())

    def test_recording_owner_keeps_observer_and_marker(self):
        io = Fake(recording=True)
        with self.assertRaisesRegex(RuntimeError, 'retained'):
            self.run_with(io, lambda *a: 'ok')
        self.assertIn(OBJ, io.words(P.SUBJECT, P.SLOTS))
        self.assertEqual(json.loads(self.marker.read_text())['obj'], OBJ)

    def test_slot_that_will_not_clear_keeps_marker(self):
        io = Fake(stuck=True)
        with self.assertRaisesRegex(RuntimeError, 'retained'):
            self.run_with(io, lambda *a: 'ok')
        self.assertTrue(self.marker.exists())

    def test_existing_marker_refuses_before_any_write(self):
        self.marker.write_text('{}')
        io = Fake()
        with self.assertRaises(FileExistsError):
            self.run_with(io, lambda *a: self.fail('attached past a marker'))
        self.assertEqual(self.marker.read_text(), '{}')

    def test_foreign_marker_is_not_read_as_ours(self):
        self.marker.write_text(json.dumps(dict(plan=[1], sha256='x')))
        with self.assertRaisesRegex(RuntimeError, 'not a GTAG observer marker'):
            P.read_marker()


class Frames(unittest.TestCase):
    def listing(self, numbers, date='20261024'):
        return '\n'.join(f'2026/10/24  09:13:36    8447488 A001_004_{date}_{n:06d}.DNG'
                         for n in numbers)

    def test_contiguous_run(self):
        self.assertEqual(P.take_frames(self.listing(range(1, 84)), 'A001_004'),
                         ('A001_004_20261024', 83))

    def test_gap_or_mixed_pattern_refused(self):
        for listing in (self.listing([1, 2, 4]), self.listing([]),
                        self.listing([1]) + '\n' + self.listing([2], '20261025')):
            with self.assertRaises(RuntimeError):
                P.take_frames(listing, 'A001_004')



def block(index, tick, prev, before, latched, due, written=None, dropped=0, status=0):
    written = due if written is None else written
    return dict(magic=P.GMAGIC, index=index, tick=tick, prev_tick=prev, before=before,
                latched=latched, after=latched, due=due, written=written,
                dropped=dropped, padbad=0, status=status, tick_after=tick + 30,
                capacity=189, total_written=0, total_dropped=0)


def head(n):
    """Published head after n records in all (R + 8*(j+1))."""
    return P.GYRO_R + 8 * ((n - 1) % 600 + 1)


def steady(frames, rate=2500.0, dt=41708):
    out, n, tick = [], 0, 1000000
    for f in range(1, frames + 1):
        due = round(rate * dt * f / 1e6) - round(rate * dt * (f - 1) / 1e6)
        out.append(block(f, tick + dt, tick, head(n) if n else head(600), head(n + due), due))
        n, tick = n + due, tick + dt
    return out


class GyroReport(unittest.TestCase):
    def test_steady_take_is_complete_and_measures_rate(self):
        r = P.gyro_report(steady(40), 40)
        self.assertTrue(r['complete'])
        self.assertAlmostEqual(r['rate_hz'], 2500, delta=2)
        self.assertEqual(r['frame_dt_us']['median'], 41708)
        self.assertEqual((r['chain_breaks'], r['lap_suspects'], r['bad_blocks']), ([], [], []))

    def test_each_defect_is_reported_and_not_complete(self):
        cases = {
            'chain_breaks': lambda b: b[5].update(before=b[4]['latched'] + 8),
            'lap_suspects': lambda b: b[7].update(tick=b[7]['prev_tick'] + 300000),
            'bad_blocks': lambda b: b[3].update(index=9),
            'status': lambda b: b[2].update(status=7),
            'dropped': lambda b: b[6].update(dropped=4, written=b[6]['due'] - 4),
        }
        for key, damage in cases.items():
            blocks = steady(20)
            damage(blocks)
            r = P.gyro_report(blocks, 20)
            self.assertFalse(r['complete'], key)
            self.assertTrue(r[key] if key != 'status' else r[key] != {0: 20}, key)
        self.assertFalse(P.gyro_report(steady(20), 21)['complete'])   # frame without notify

    def test_frame_one_lap_after_a_long_arming_gap(self):
        # Live 24 October: mode 2 to frame 1 took 331 ms; 827 due, 227 seen.
        blocks = steady(20)
        blocks[0].update(prev_tick=blocks[0]['tick'] - 330835, due=227, written=189, dropped=38)
        r = P.gyro_report(blocks, 20)
        self.assertEqual(r['lap_suspects'], [1])
        self.assertFalse(r['complete'])

    def test_backfilled_frame_one_is_not_a_lap(self):
        # The fixed observer: frame 1 reaches back one capacity from its latch.
        blocks = steady(20)
        latched = blocks[0]['latched']
        before = latched - 8 * 189 if latched - 8 * 189 >= P.GYRO_R + 8 else latched - 8 * 189 + 0x12C0
        blocks[0].update(prev_tick=blocks[0]['tick'] - 330835, before=before, due=189, written=189)
        r = P.gyro_report(blocks, 20)
        self.assertEqual(r['lap_suspects'], [])
        self.assertTrue(r['complete'])

    def test_parse_block_reads_header_and_records(self):
        n, off = P.GYRO.n, 0x102
        b = bytearray(0x200 + n)
        struct.pack_into('<2sHI', b, 0, b'II', 42, 8)
        for at, tag, typ, count, value in ((8, 0x8769, 4, 1, 32), (32, 0x927C, 7, 40, 64),
                                           (74, 0x4653, 7, n, off)):
            struct.pack_into('<HHHII', b, at, 1, tag, typ, count, value)
        b[64:72] = b'SIGMA\0\0\0'
        blk = (off + 3) & ~3
        hdr = block(1, 5, 1, head(600), head(3), 3)
        struct.pack_into('<16I', b, blk, *(hdr[k] for k in P.BLOCK))
        for k in range(3):
            struct.pack_into('<hhhh', b, blk + P.HDR + 8 * k, k, -k, 0, 3 * k)
        got, recs = P.parse_block(bytes(b))
        self.assertEqual((got['index'], got['written'], recs), (1, 3, [(0, 0, 0), (1, -1, 3), (2, -2, 6)]))
        struct.pack_into('<I', b, blk + 4 * P.BLOCK.index('written'), 1000)
        with self.assertRaisesRegex(RuntimeError, 'beyond its tag'):
            P.parse_block(bytes(b))


if __name__ == '__main__':
    unittest.main()
