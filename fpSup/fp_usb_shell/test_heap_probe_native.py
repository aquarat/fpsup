"""Run the assembled probe through actual fp L allocator instructions.

FPSUP_FPL_MAIN selects the private official image. USER heap/list state is
synthetic; only static guards, telemetry and privileged cache calls are stubbed.
This complements test_heap_probe's strict independent call/write-range oracle.
"""
import os
from pathlib import Path
import struct
import sys
import unittest

from armasm import assemble, symbols
from firmware import get_camera
from fpl_heap_probe import inspect_result

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from fpl_allocator_audit import Machine, CHANNEL, HEAP, HEAP_SIZE, DESC
from unicorn import UC_HOOK_CODE

BODY = 0xC3FC0000  # synthetic mapped storage, NOT a proposed camera cave


class NativeHeapProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('FPSUP_FPL_MAIN'):
            raise unittest.SkipTest('set FPSUP_FPL_MAIN to official fp L 3.02 MAIN')
        cam = get_camera('fp-l-3.02')
        cls.image = cam.verify_main(os.environ['FPSUP_FPL_MAIN'])
        source = Path(__file__).resolve().parent / 'asm/heap_probe.S'
        cls.code = assemble(source, cam.loader_defines())
        cls.labels = symbols(source, cam.loader_defines())

    def exercise(self, exhausted=False, broken_address=False):
        m = Machine(self.image)
        m.stubs.update({0xC0013090: 1, 0xC00131E4: 0,
                        0xC001E328: 0, 0xC001E3C8: 0})
        m.put(0xC30739D8, CHANNEL)
        m.put(0xC3073A10, CHANNEL)
        m.put(CHANNEL, 0, 0)
        m.call(0xC0010310, CHANNEL + 8)
        m.call(0xC00103A8, CHANNEL + 8, HEAP)
        for address in (HEAP, HEAP + HEAP_SIZE - 0x40):
            m.put(DESC + 0x100, address, 0x40)
            m.call(0xC00103E8, CHANNEL + 8, DESC + 0x100)
        if exhausted:
            m.call(0xC001D740, DESC, 0, 0xFE00, 0)
            self.assertNotEqual(m.call(0xC001D7F0, DESC), 0)
        before = m.words(CHANNEL, 9)
        m.mu.mem_write(BODY, self.code)
        m.stubs.update({0xC000E91C: 0, 0xC000EABC: 0})
        if broken_address:
            # Deliberately hide a successful allocation from the probe. The
            # test must detect the resulting loss of execution/accounting.
            m.mu.mem_write(0xC001D7F4, struct.pack('<I', 0xE3A01000))
        cache_calls, execution = [], []

        def trace(mu, address, size, _):
            if address in (0xC000E91C, 0xC000EABC):
                cache_calls.append(address)
            if HEAP <= address < HEAP + HEAP_SIZE:
                execution.append(address)

        m.mu.hook_add(UC_HOOK_CODE, trace)
        result = m.call(BODY)
        self.assertEqual(result, BODY + self.labels['heap_result'])
        raw = bytes(m.mu.mem_read(result, 64))
        report = inspect_result(raw)
        self.assertEqual(report['execution_evidence_passed'], not exhausted)
        after = m.words(CHANNEL, 9)
        # Only high-water accounting (+1c) may grow after a returned allocation.
        self.assertEqual(after[:7], before[:7])
        self.assertEqual(after[8:], before[8:])
        if exhausted:
            self.assertEqual(cache_calls, [])
            self.assertEqual(execution, [])
            self.assertEqual(struct.unpack_from('<I', raw, 8)[0], 1)
            self.assertEqual(struct.unpack_from('<I', raw, 44)[0], 0)
            m.call(0xC001D7A0, DESC, 2)  # test fixture owns this earlier block
        else:
            self.assertEqual(cache_calls, [0xC000E91C, 0xC000EABC])
            self.assertEqual(execution, list(range(0x44400080, 0x444000A8, 4)))
            self.assertEqual(struct.unpack_from('<I', raw, 12)[0], 0x44400080)
        return m

    def test_actual_allocator_execute_return_free_restores_list(self):
        self.exercise()

    def test_actual_exhausted_allocator_returns_cleanly(self):
        self.exercise(exhausted=True)

    def test_native_address_load_mutation_is_rejected(self):
        with self.assertRaises(AssertionError):
            self.exercise(broken_address=True)


if __name__ == '__main__':
    unittest.main()
