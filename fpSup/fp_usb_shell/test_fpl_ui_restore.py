"""Real shared loader/stage2 journal and restore body with six fp L UI words."""
import os
from pathlib import Path
import struct
import unittest

import card_build
import fpl_ui_restore as restore
from test_fpl_shell_card import ShellTrial


class Restore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = Path(os.environ['FPL_MAIN'])
        cls.image = restore.CAMERA.verify_main(cls.main)
        cls.sections = restore.stock_sections(cls.image)
        cls.script, cls.art = card_build.ordinary_card(cls.main, stock_sections=cls.sections)

    def trial(self, art=None):
        c = ShellTrial(self, self.image, self.script.splitlines(), (art or self.art)['binfile']).run()
        obj = c.registered[0][0]
        self.assertEqual(c.registered, [(obj, 0), (obj, 1)])
        # The loader calls the stubbed manager API; inspect its recorded lists.
        c.mu.mem_write(restore.MANAGER, struct.pack('<I', 0xC0726CEC))
        for offset in (0x0C, 0x34):
            c.mu.mem_write(restore.MANAGER+offset, struct.pack('<10I', obj, *([0]*9)))
        return c, obj

    def inspect(self, c):
        return restore.inspect(lambda a, n: list(struct.unpack('<%dI' % n, c.mu.mem_read(a, 4*n))), self.image)

    def test_autorun_unchanged_and_six_words_restored(self):
        ordinary, art = card_build.ordinary_card(self.main)
        self.assertEqual(self.script, ordinary)
        for k in ('loader', 'worker', 'stage2'):
            self.assertEqual(self.art[k], art[k])
        c, obj = self.trial()
        self.assertTrue(self.inspect(c)['complete'])
        for reason in (1, 4):
            for a, data in self.sections:
                c.mu.mem_write(a, struct.pack('<I', 0xE7F000F0))
            c.dispatch(c.word(obj+4), r0=obj, r1=reason)
            self.assertEqual([bytes(c.mu.mem_read(a,4)) for a, _ in self.sections],
                             [data for _, data in self.sections])

    def test_missing_second_word_is_not_covered(self):
        _, art = card_build.ordinary_card(self.main, stock_sections=self.sections[:-1])
        c, _ = self.trial(art)
        report = self.inspect(c)
        self.assertFalse(report['complete'])
        self.assertEqual([s['covered'] for s in report['sites']], [True]*5+[False])

    def test_nonstock_duplicate_and_bootstrap_sections_refused(self):
        for sections in ([self.sections[0]]*2, [(self.sections[0][0], b'\0'*4)],
                         [(self.sections[0][0]+1, b'\0'*4)],
                         [(card_build.DIR_ENTRY, self.image[card_build.DIR_ENTRY-0xC0000000:card_build.DIR_ENTRY-0xC0000000+4])]):
            with self.assertRaises(ValueError):
                card_build.ordinary_card(self.main, stock_sections=sections)

    def test_corrupt_restore_code_and_journal_rejected(self):
        c, obj = self.trial()
        routine, journal = c.word(obj+4), c.word(obj+8)
        c.mu.mem_write(journal+8, b'\0'*4)
        self.assertFalse(self.inspect(c)['complete'])
        c.mu.mem_write(routine, b'\0'*4)
        with self.assertRaisesRegex(ValueError, 'code differs'):
            self.inspect(c)

    def test_mutation_omitted_restore_store_is_detected(self):
        c, obj = self.trial()
        code = restore.restore_code()
        # str r3,[r0],#4 -> nop, only in private emulator memory.
        at = code.index(struct.pack('<I', 0xE4803004))
        c.mu.mem_write(c.word(obj+4)+at, struct.pack('<I', 0xE320F000))
        for a, _ in self.sections: c.mu.mem_write(a, b'\0'*4)
        c.dispatch(c.word(obj+4), r0=obj, r1=1)
        with self.assertRaises(AssertionError):
            self.assertEqual([bytes(c.mu.mem_read(a,4)) for a, _ in self.sections],
                             [data for _, data in self.sections])


if __name__ == '__main__':
    unittest.main()
