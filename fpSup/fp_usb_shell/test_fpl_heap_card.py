"""Drive the emitted trial AutoRun at real addresses against the real image.

Executes the actual generated command lines, not a parallel reimplementation.
Firmware services stubbed: local-static guard, allocator telemetry, and the
privileged cache routines (their call ORDER is the oracle; CP15 is not
emulated, so cache effects are not). The allocator, descriptor and dispatch
targets run real fp L 3.02 instructions. No camera semantics are claimed.
"""
import os
from pathlib import Path
import struct
import sys
import unittest

from armasm import assemble
from firmware import get_camera
from fpl_heap_probe import (card_script, inspect_result, BASE, DIR_ENTRY,
                            DIR_SLOT, PROBE_LEN, RESULT_ADDR, ECHO_SLOT,
                            ECHO_STOCK, TABLE, TABLE_LEN)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from fpl_allocator_audit import Machine, CHANNEL, HEAP, HEAP_SIZE, DESC
from unicorn import UC_HOOK_CODE

GET, ADDR, FREE = 0xC001D740, 0xC001D7F0, 0xC001D7A0
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
CTX = 0xC3757744


class Trial:
    """Applies the emitted script to the machine; snapshots `mem save` files."""

    def __init__(self, test, image, lines):
        self.t, self.image, self.lines = test, image, lines
        m = Machine(image)
        m.stubs.update({0xC0013090: 1, 0xC00131E4: 0,
                        0xC001E328: 0, 0xC001E3C8: 0,
                        DCACHE: 0, ICACHE: 0})
        # Synthetic class-0 channel: real allocator instructions, fake region.
        m.put(0xC30739D8, CHANNEL)
        m.put(0xC3073A10, CHANNEL)
        m.put(CHANNEL, 0, 0)
        m.call(0xC0010310, CHANNEL + 8)
        m.call(0xC00103A8, CHANNEL + 8, HEAP)
        for address in (HEAP, HEAP + HEAP_SIZE - 0x40):
            m.put(DESC + 0x100, address, 0x40)
            m.call(0xC00103E8, CHANNEL + 8, DESC + 0x100)
        self.m = m
        self.saved, self.timeline, self.current = {}, [], -1
        m.mu.hook_add(UC_HOOK_CODE, self.trace)

    def trace(self, mu, address, size, _):
        line = self.current
        if address in (DCACHE, ICACHE):
            self.timeline.append((line, 'D' if address == DCACHE else 'I'))
        elif address in (GET, ADDR, FREE):
            self.timeline.append((line, {GET: 'GET', ADDR: 'ADDR', FREE: 'FREE'}[address]))
        elif HEAP <= address < HEAP + HEAP_SIZE:
            self.timeline.append((line, 'EXEC'))

    def word(self, address):
        return struct.unpack('<I', self.m.mu.mem_read(address, 4))[0]

    def run(self):
        for index, line in enumerate(self.lines):
            self.current = index
            line = line.strip()
            if line.startswith('mem save'):
                _, _, path, spec = line.split()
                start, size = (int(part, 16) for part in spec.split(',,'))
                self.saved[path] = bytes(self.m.mu.mem_read(start, size))
            elif line.startswith('mem set'):
                _, _, address, value = line.split()
                address, value = int(address, 16), int(value, 16)
                allowed = (DIR_ENTRY <= address < DIR_ENTRY + PROBE_LEN
                           and address + 4 <= DIR_ENTRY + PROBE_LEN) or address == ECHO_SLOT
                self.t.assertTrue(allowed, f'script writes outside the borrowed '
                                           f'range at {address:#x}')
                self.m.mu.mem_write(address, struct.pack('<I', value))
            elif line == 'echo':
                slot = self.word(ECHO_SLOT)
                self.m.call(slot, CTX, 0, 0)
            elif line == 'dir':
                slot = self.word(DIR_SLOT)
                self.t.assertEqual(slot, DIR_ENTRY)
                self.m.call(slot, CTX, 0, 0)
            elif line.startswith('#'):
                continue
            else:
                raise AssertionError(f'unmodelled script line: {line!r}')
        self.current = -1
        return self

    def dir_slot_value(self):
        return self.word(DIR_SLOT)


@unittest.skipIf(not os.environ.get('FPSUP_FPL_MAIN'),
                 'set FPSUP_FPL_MAIN to official fp L 3.02 MAIN')
class TrialCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        camera = get_camera('fp-l-3.02')
        cls.image = camera.verify_main(os.environ['FPSUP_FPL_MAIN'])
        cls.lines, cls.body, cls.stock = card_script(cls.image)
        source = Path(__file__).resolve().parent / 'asm/heap_probe.S'
        # The script must carry exactly the freshly assembled body.
        assert assemble(source, camera.loader_defines()) == cls.body

    def stock_slice(self, start, length):
        return self.image[start - BASE:start - BASE + length]

    def assert_clean(self, trial):
        t = self
        t.assertEqual(trial.dir_slot_value(), DIR_ENTRY, 'dir slot was modified')
        t.assertEqual(trial.word(ECHO_SLOT), ECHO_STOCK, 'echo slot not restored')
        t.assertEqual(bytes(trial.m.mu.mem_read(DIR_ENTRY, PROBE_LEN)), self.stock,
                      'dir body not restored to stock bytes')
        t.assertEqual(trial.saved['\\FPLPROBE\\PRE.BIN'], self.stock)
        t.assertEqual(trial.saved['\\FPLPROBE\\WROTE.BIN'], self.body,
                      'captured body differs from the assembled probe')
        t.assertEqual(trial.saved['\\FPLPROBE\\RESTORED.BIN'], self.stock)
        t.assertEqual(trial.saved['\\FPLPROBE\\SLOTS.BIN'],
                      self.stock_slice(TABLE, TABLE_LEN))
        report = inspect_result(trial.saved['\\FPLPROBE\\RESULT.BIN'])
        t.assertTrue(report['execution_evidence_passed'], report)

    def line_index(self, text):
        return self.lines.index(text)

    def test_script_executes_publishes_runs_restores_and_evidences(self):
        trial = Trial(self, self.image, self.lines).run()
        self.assert_clean(trial)
        # Global ordering oracle: publication before dispatch, probe order,
        # republish after the body writes, slot restore last.
        pub_echo = [i for i, line in enumerate(self.lines) if line == 'echo']
        dir_line = self.line_index('dir')
        restore_lines = [i for i, line in enumerate(self.lines)
                         if line.startswith(f'mem set 0x{DIR_ENTRY:08X}') and i > dir_line]
        slot_restore = [i for i, line in enumerate(self.lines)
                        if line == f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_STOCK:08X}']
        self.assertEqual(len(pub_echo), 4)
        self.assertEqual(pub_echo[:2], sorted(pub_echo[:2]))
        self.assertLess(pub_echo[1], dir_line)
        self.assertLess(dir_line, restore_lines[0])
        self.assertLess(restore_lines[-1], pub_echo[2])
        self.assertLess(pub_echo[3], slot_restore[0])
        self.assertEqual(len(slot_restore), 3)
        # During `dir`: allocate, publish the copy, execute, then free.
        during = [kind for i, kind in trial.timeline if i == dir_line]
        leaf_words = 10  # 40-byte leaf
        self.assertEqual(during[:4], ['GET', 'ADDR', 'D', 'I'])
        self.assertEqual(during[4:4 + leaf_words], ['EXEC'] * leaf_words)
        self.assertEqual(during[-1], 'FREE')
        # Publication windows land exactly on the dispatched echo lines; the
        # probe's own D/I pair for its leaf copy lands on the `dir` line.
        cache_events = [(i, kind) for i, kind in trial.timeline if kind in ('D', 'I')]
        self.assertEqual(cache_events, [(pub_echo[0], 'D'), (pub_echo[1], 'I'),
                                        (dir_line, 'D'), (dir_line, 'I'),
                                        (pub_echo[2], 'D'), (pub_echo[3], 'I')])

    def test_second_execution_over_restored_state_is_clean(self):
        # The bring-up saw one boot run the script twice; a clean first run
        # must leave state the second run restores again without residue.
        trial = Trial(self, self.image, self.lines).run()
        self.assert_clean(trial)
        trial.run()
        self.assert_clean(trial)

    def test_missing_restore_word_leaves_body_modified_and_evidence_catches_it(self):
        # Drop one stock-restore command (the last write of the body region).
        dir_line = self.line_index('dir')
        restore = [line for i, line in enumerate(self.lines)
                   if line.startswith(f'mem set 0x{DIR_ENTRY:08X}') and i > dir_line]
        damaged = list(self.lines)
        damaged.remove(restore[-1])
        self.assertNotEqual(damaged, self.lines)
        trial = Trial(self, self.image, damaged).run()
        self.assertNotEqual(bytes(trial.m.mu.mem_read(DIR_ENTRY, PROBE_LEN)), self.stock)
        self.assertNotEqual(trial.saved['\\FPLPROBE\\RESTORED.BIN'], self.stock)

    def test_corrupted_probe_word_is_detected_by_result_and_wrote_evidence(self):
        # Mutate one emitted body word: the leaf's execution marker.
        target = f'0x{0xE3041148:08X}'
        hits = [line for line in self.lines if line.endswith(target)]
        self.assertEqual(len(hits), 1)
        damaged = [line.replace(target, f'0x{0xE3041149:08X}') for line in self.lines]
        trial = Trial(self, self.image, damaged).run()
        self.assertNotEqual(trial.saved['\\FPLPROBE\\WROTE.BIN'], self.body)
        report = inspect_result(trial.saved['\\FPLPROBE\\RESULT.BIN'])
        self.assertFalse(report['execution_evidence_passed'])


if __name__ == '__main__':
    unittest.main()
