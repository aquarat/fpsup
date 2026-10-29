"""Resident host orchestration faults; ARM transactions live in test_fpl_ui_guard."""
from types import SimpleNamespace
import struct
import unittest
from unittest.mock import patch

import fpl_ui_hook_trial as trial


class Resident(unittest.TestCase):
    def exercise(self, *, covered=True, fail=None):
        image = bytes(0x600000)
        owner = 0x45400000
        entries = [owner+0x1100, owner+0x1200, owner+0x1300]
        plan = SimpleNamespace(code=0x45010000, param=0x45011000, buffer=0x45012000)
        self.events = []
        self.command = 0
        self.report = {}
        def upload(at, data):
            self.assertEqual(at, plan.param)
            self.command = struct.unpack_from('<I', data)[0]
        def call(at, label):
            self.events.append(label)
            if label == fail:
                raise RuntimeError('injected execution failure')
        def words(at, n):
            i = list(trial.ui.STRING_SITES.values()).index(at)
            return [0xF000F8DF, entries[i]] if self.command == 1 else [0, 0]
        def sh(command, retries):
            self.assertEqual(retries, 0)
            self.events.append(command)
            return 'ERR injected key failure' if command == fail else 'OK'
        io = SimpleNamespace(words=words, read=lambda a, n: bytes(n), sh=sh)
        with patch.object(trial.restore, 'inspect', return_value={'complete': covered}), \
             patch.object(trial.guard, 'decode', return_value={'result': 2}), \
             patch.object(trial.time, 'sleep'):
            trial.resident_roundtrip(io, image, owner, entries, plan, call, upload,
                                     self.report, lambda: None)

    def test_missing_journal_refuses_before_install(self):
        with self.assertRaisesRegex(RuntimeError, 'six stock journal'):
            self.exercise(covered=False)
        self.assertEqual(self.events, [])

    def test_gui_runs_between_install_and_removal(self):
        self.exercise()
        self.assertLess(self.events.index('resident-install'), self.events.index('key MENUON'))
        self.assertLess(self.events.index('key CAPTUREOFF'), self.events.index('resident-remove'))
        self.assertEqual(len(self.report['resident_transactions']), 2)

    def test_checker_failure_still_removes_acknowledged_install(self):
        with self.assertRaisesRegex(RuntimeError, 'injected execution'):
            self.exercise(fail='resident-string-check')
        self.assertIn('resident-remove', self.events)
        self.assertNotIn('key MENUON', self.events)

    def test_failed_key_is_never_retried_and_hooks_are_removed(self):
        with self.assertRaisesRegex(RuntimeError, 'no key retry'):
            self.exercise(fail='key MENUON')
        self.assertEqual(self.events.count('key MENUON'), 1)
        self.assertNotIn('key CAPTUREON', self.events)
        self.assertIn('resident-remove', self.events)

    def test_uncertain_install_does_not_claim_removal(self):
        with self.assertRaisesRegex(RuntimeError, 'injected execution'):
            self.exercise(fail='resident-install')
        self.assertNotIn('resident-remove', self.events)
        self.assertNotIn('resident-string-check', self.events)


if __name__ == '__main__':
    unittest.main()
