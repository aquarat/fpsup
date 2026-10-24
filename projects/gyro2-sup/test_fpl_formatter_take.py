"""Owner's non-atomic CinemaDNG RAM capture, replayed offline from FPL_TAKE."""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_SP, UC_ARM_REG_PC

import audit_formatter as A
import formatter_contract as C
import test_fpl_formatter as F
import test_fpl_formatter_edges as E
import test_fpl_formatter_live_context as L
import test_fpl_tag_capacity as N
import test_fpl_observer as T


class TakeMachine(L.Replay):
    def __init__(self, *args):
        self.opaque_calls = []
        super().__init__(*args)

    def hook(self, mu, addr, size, userdata):
        r = [mu.reg_read(reg) for reg in T.REGS]
        if addr == 0xC0697770:
            # Alternate base's auxiliary parameter factory, not its size ledger.
            self.opaque_calls.append((addr, tuple(r)))
            self.write(r[0], 0)
            self.ret(r[0])
            return
        if addr in (0xC06A1428, 0xC02E9C10, 0xC06A1270):
            # Descriptor construction/copy: no captured geometry graph available.
            self.opaque_calls.append((addr, tuple(r)))
            self.ret(r[0])
            return
        ranges = ((0xC0697510, 0xF0), (0xC0720120, 0x78),
                  (0xC06A2838, 0x20), (0xC0720418, 0x40),
                  (0xC0697298, 0x28), (0xC0697AE0, 0x48),
                  (0xC0381E44, 0x14), (0xC037E5EC, 0x14),
                  (0xC0203B70, 0x48), (0xC0203D70, 0x10),
                  (0xC039E040, 0x14))
        if not self.selection:
            ranges += ((0xC06A3FC8, 0x58),)
        if any(a <= addr < a+n for a, n in ranges):
            self.trace.add(addr)
            return
        super().hook(mu, addr, size, userdata)

    def fragment(self, start, end, register, record):
        self.mu.reg_write(register, record)
        self.mu.reg_write(UC_ARM_REG_SP, T.STACK+0xFE00)
        self.mu.emu_start(start, end, count=1000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == end

    def load_graph(self, snap):
        # Only captured words are restored. Geometry fields are deliberately
        # absent and their descriptor-preparation dependency is explicitly stubbed.
        self.mu.mem_write(snap['F'], struct.pack('<4I', *snap['F_words']))
        for name, leaf in snap['leaves'].items():
            fields = leaf['+4..+14']
            self.mu.mem_write(leaf['ptr']+4, struct.pack('<5I', *fields))
            for pointer, key in zip(fields[2:4], ('ledger0', 'ledger1')):
                self.mu.mem_write(pointer, struct.pack('<19I', *leaf[key]))
            if name == 'L':
                self.write(leaf['ptr']+0x88, leaf['+88'])

    def load_buffer(self, buf):
        for key, val in buf.items():
            if key.startswith('0x'):
                self.write(buf['ptr']+int(key, 16), val)


class LiveTake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ.get('FPL_TAKE')
        if not path or not Path(path).is_file():
            raise unittest.SkipTest('external FPL_TAKE take.json absent; live-take replay unavailable')
        cls.path = Path(path)
        cls.take = A.load_live_take(path)
        F.NativeFormatter.setUpClass()

    def machine(self):
        return TakeMachine(N.NativeCapacity.image, F.NativeFormatter.data,
                           N.NativeCapacity.code, N.NativeCapacity.offsets)

    def test_native_constructors_explain_live_sentinel_and_flag(self):
        m = self.machine()
        s = self.take['snaps'][0]
        right = s['leaves']['R']
        self.assertEqual(right['ptr'], 0xC3824B7C)
        # Native sentinel constructor; size-ledger and parameter-pool allocation stubs.
        m.call(0xC0697558, right['ptr'], 3, 0x800)
        self.assertEqual(m.word(right['ptr']+8), right['+4..+14'][1])
        self.assertEqual(m.word(right['ptr']+0x14), right['+4..+14'][4])
        self.assertEqual(m.word(right['ptr']+0x14), 0xC2E490F0)
        # Actual alternate left constructor writes +88=1 and reservations.
        m.call(0xC06A3FC8, F.LEFT, E.OPAQUE)
        self.assertEqual(m.word(F.LEFT+0x88) & 255, s['leaves']['L']['+88'])
        ledger = m.word(F.LEFT+0xC)
        self.assertEqual(m.word(ledger+0x20), 0x18000)
        self.assertEqual(m.word(ledger+0x40), 0x5400)

    def test_native_context_rewrite_of_earlier_capture_selects_live_edges(self):
        path = os.environ.get('FPL_CONTEXT')
        if not path or not Path(path).is_file():
            self.skipTest('external FPL_CONTEXT absent for before/after context replay')
        captured = A.validate_live_context(Path(path).read_bytes())
        m = self.machine()
        ctx = 0xC31F6ABC
        m.mu.mem_write(ctx, captured)
        self.assertEqual(m.word(ctx+0x44), 0)
        # Real recording-control fragment, initialized-singleton guard stub.
        m.fragment(0xC039E040, 0xC039E054, UC_ARM_REG_R4, E.OPAQUE)
        self.assertEqual(m.word(ctx+0x44), 2)
        right = self.take['snaps'][0]['leaves']['R']['ptr']
        m.call(0xC0697558, right, 3, 0x800)
        m.selection = True  # selected constructor/geometry dependencies remain opaque
        m.call(0xC06A2490, ctx, F.LEFT)
        self.assertIn(0xC06A3FC8, [a for a, _ in m.edges])
        self.assertEqual(m.call(0xC06A25C0, ctx, F.LEFT), right)
        # Omit the native context publication: previous snapshot's edge reappears.
        m.mu.mem_write(ctx, captured)
        self.assertEqual(m.word(0xC039E050), 0xE5812044)
        m.write(0xC039E050, 0xE1A00000)
        m.mu.ctl_remove_cache(0xC039E050, 0xC039E054)
        m.fragment(0xC039E040, 0xC039E054, UC_ARM_REG_R4, E.OPAQUE)
        m.edges.clear()
        m.call(0xC06A2490, ctx, F.LEFT)
        self.assertIn(0xC06A40A0, [a for a, _ in m.edges])

    def test_live_ledger_sum_and_actual_prepare_slots(self):
        for s in self.take['snaps']:
            m = self.machine()
            m.load_graph(s)
            size = m.call(m.word(m.word(s['F']+8)+0x10), s['F'])
            self.assertEqual(size, 0x1D400)
            self.assertLessEqual(s['H'], size)
            m.call(m.word(m.word(s['F']+8)+0x1C), s['F'], s['S'])
            self.assertEqual(m.word(s['leaves']['L']['ptr']+4), s['S'])
            self.assertEqual(m.word(s['leaves']['R']['ptr']+4), s['S']+size)
            self.assertEqual(m.word(s['leaves']['R']['ptr']+4),
                             s['leaves']['R']['+4..+14'][0])
            self.assertIn(0xC06A1270, [a for a, _ in m.opaque_calls])

    def test_producer_then_retreat_is_not_two_header_writes(self):
        s = self.take['snaps'][0]
        b = next(iter(s['buffers'].values()))
        m = self.machine()
        m.load_buffer(b)
        r = b['ptr']
        m.fragment(0xC0381E44, 0xC0381E58, UC_ARM_REG_R5, r)
        self.assertEqual(m.word(r+0x4C), b['0x68']+b['0x128'])
        layout = C.recording_layout(m.mu.mem_read, r, serialized_bytes=s['H'], frame_bytes=0x810400)
        self.assertEqual(layout[4], b['0x68']+0x1C00)
        m.fragment(0xC037E5EC, 0xC037E600, UC_ARM_REG_R4, r)
        self.assertEqual(m.word(r+0x4C), layout[4])
        with self.assertRaisesRegex(C.CapacityError, 'pre-retreat'):
            C.recording_layout(m.mu.mem_read, r, serialized_bytes=s['H'], frame_bytes=0x810400)

    def test_all_captured_buffers_classify_without_claiming_atomicity(self):
        accepted = rejected = 0
        bases = set()
        for s in self.take['snaps']:
            self.assertFalse(s['registry_after_same'])
            self.assertEqual(s['H'], 0x13800)
            for b in s['buffers'].values():
                bases.add(b['0x68'])
                m = self.machine()
                m.load_buffer(b)
                self.assertEqual(b['0x128'], 0x15400)  # THIS live mode only
                if b['0x4c'] == b['0x68']+b['0x128']:
                    result = C.recording_layout(m.mu.mem_read, b['ptr'],
                                                serialized_bytes=s['H'], frame_bytes=0x810400)
                    self.assertEqual(result[4], b['dest'])
                    accepted += 1
                else:
                    self.assertEqual(b['0x4c'], b['0x68']+0x1C00)
                    with self.assertRaises(C.CapacityError):
                        C.recording_layout(m.mu.mem_read, b['ptr'],
                                           serialized_bytes=s['H'], frame_bytes=0x810400)
                    rejected += 1
        self.assertGreater(accepted, 0)
        self.assertGreater(rejected, 0)
        ordered = sorted(bases)
        self.assertTrue(all((y-x) % 0x810400 == 0 for x, y in zip(ordered, ordered[1:])))

    def test_headroom_failure_and_mutated_native_retreat(self):
        s = self.take['snaps'][0]
        b = next(iter(s['buffers'].values()))
        m = self.machine()
        m.load_buffer(b)
        r = b['ptr']
        m.fragment(0xC0381E44, 0xC0381E58, UC_ARM_REG_R5, r)
        m.write(r+0x14C, b['0x128']+1)
        with self.assertRaises(C.CapacityError):
            C.recording_layout(m.mu.mem_read, r, serialized_bytes=b['0x128']+1, frame_bytes=0x810400)
        m.write(r+0x14C, s['H'])
        self.assertEqual(m.word(0xC037E5FC), 0xE584204C)
        m.write(0xC037E5FC, 0xE1A00000)  # remove pointer publication
        m.mu.ctl_remove_cache(0xC037E5FC, 0xC037E600)
        m.fragment(0xC037E5EC, 0xC037E600, UC_ARM_REG_R4, r)
        self.assertNotEqual(m.word(r+0x4C), b['0x68']+0x1C00)

    def test_take_hash_mutation_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'take.json'
            p.write_bytes(self.path.read_bytes()+b' ')
            with self.assertRaisesRegex(ValueError, 'fingerprint'):
                A.load_live_take(p)

    def test_headroom_fields_are_bound_to_frozen_ifd_contract(self):
        # Prior native flat-IFD fixture, not a claim of captured full DNG metadata.
        m, o = E.FormatterEdges().fixture()
        m.write(E.RECORD+0x68, o.frame_start)
        m.write(E.RECORD+0x128, m.word(E.RECORD+0x4C)-o.frame_start)
        def freeze():
            return C.freeze_transfer(m.mu.mem_read, m.call, F.ROOT, N.MAKER,
                E.OWNER, E.RECORD, ownership=o, prefix_bytes=90,
                require_recording_headroom=True)
        before = freeze()
        self.assertEqual(C.admit_transfer(before, freeze())[2], 876)
        m.write(E.RECORD+0x128, m.word(E.RECORD+0x128)+1)
        with self.assertRaisesRegex(C.CapacityError, 'pre-retreat'):
            freeze()


if __name__ == '__main__':
    unittest.main()
