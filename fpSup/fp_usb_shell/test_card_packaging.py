"""Offline shared VBIN and restricted ordinary fp L CLI acceptance."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from armasm import symbols
from card_build import build_vbin, ordinary_card, card
import test_fpl_shell_card as trial_tests
from test_fpl_shell_card import (IMAGE, CAMERA, Uc, ShellTrial,
                                 DIR_ENTRY, DIR_SLOT, RESTORE_LEN, ECHO_SLOT,
                                 ECHO_STOCK, POOL, CODE, STAGING)

HERE = Path(__file__).resolve().parent
FLAGS = ['--camera', 'fp-l-3.02', '--fpl-shell', '--loader',
         '--no-four-box-bar', '--no-fast-echo', '--no-ep-patches']


def cli(out, extra=(), flags=FLAGS, main=IMAGE):
    return subprocess.run([sys.executable, '-B', str(HERE / 'build_autorun.py'),
                           *flags, '--main', str(main), '--out', str(out), *extra],
                          text=True, capture_output=True)


class VbinTests(unittest.TestCase):
    def test_complete_table_nonzero_entry_and_legacy_layout(self):
        sections = [(0, b'STAG' * 3), (0xC072DE64, b'DATA'),
                    (0, b'HEAD' + b'CODE')]
        blob, entry, actual = build_vbin(sections, [(2, 4)])
        # Independent old ordinary layout, including every table row.
        want = (struct.pack('<4sIII', b'VBIN', 3, 60, 24)
                + struct.pack('<6I', 0, 12, 0xC072DE64, 4, 0, 8)
                + b'STAG' * 3 + b'DATAHEADCODE')
        self.assertEqual(blob, want)
        self.assertEqual(blob[entry:entry + 4], b'CODE')
        self.assertEqual(actual, sections)

    def test_multi_entry_order_and_table_relocation(self):
        sections = [(0, b'STAG'), (0, b'WORKCODE'), (0, b'BOOTCODE')]
        blob, entry, actual = build_vbin(
            sections, [(1, 4), (2, 0), 0xC072DE64, (2, 4)])
        self.assertEqual(len(actual), 4)
        self.assertEqual(entry, 68)  # full 48-byte header/table + 20 bytes
        table = symbols(HERE / 'asm/entries.S')['table']
        self.assertEqual(struct.unpack_from('<6I', blob, entry + table),
                         (entry + table, 56, 60, 0xC072DE64, 64, 0))
        self.assertEqual(blob[56:60], b'CODE')
        self.assertEqual(blob[60:64], b'BOOT')

    def test_no_entry_and_invalid_entries(self):
        self.assertEqual(build_vbin([(0, b'CODE')], [])[1], 0)
        self.assertEqual(build_vbin([(0, b'CODE')], [(0, 1)])[1], 25)
        self.assertEqual(build_vbin([(0, b'CODE')], [0xC072DE65])[1], 0xC072DE65)
        for entry in [0, -1, 0x100000000, (0, 4), (0, -4), (0, 2), (1, 0)]:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                build_vbin([(0, b'CODE')], [entry])
        with self.assertRaises(ValueError):
            build_vbin([(0xC072DE64, b'CODE')], [(0, 0)])
        with self.assertRaises(ValueError):
            build_vbin([(0, b'bad')], [])


class RestrictedCliTests(unittest.TestCase):
    def test_unsupported_switches_refuse_before_output_or_image_reads(self):
        options = [('--store-boot',), ('--loader-hook',), ('--loader-hook-off',),
                   ('--four-box-bar',), ('--fast-echo',), ('--retain-ram',),
                   ('--no-shell',), ('--profile',), ('--payload', 'missing.S'),
                   ('--entry', 'spawn'), ('--payload-addr', '0xC072DE64'),
                   ('--also', '0:missing.S'), ('--also-bin', '0:missing.bin'),
                   ('--boot-bin', 'missing.bin:0'), ('--late-boot-bin', 'missing.bin:0'),
                   ('--boot-call', '0:missing.S'), ('--vshl-entry', '0xC072DE64'),
                   ('--read-cap', '0xF000'), ('--splash-dir', 'UI'),
                   ('--banner', 'hello'), ('--bin-name', 'OTHER.BIN'),
                   ('--loader-hook-mark', '0xC072F000'),
                   ('--loader-hook-banner-at', '0'), ('--no-pad',),
                   ('--no-strip-comments',)]
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'absent' / 'AutoRun.txt'
            for extra in options:
                with self.subTest(extra=extra):
                    result = cli(out, extra, main='missing-main')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('--fpl-shell supports only', result.stderr)
                    self.assertFalse(out.parent.exists())
            for missing in ['--loader', '--no-four-box-bar', '--no-fast-echo',
                            '--no-ep-patches']:
                with self.subTest(missing=missing):
                    self.assertNotEqual(cli(out, flags=[f for f in FLAGS if f != missing],
                                            main='missing-main').returncode, 0)
                    self.assertFalse(out.parent.exists())


@unittest.skipIf(Uc is None or not IMAGE.exists(), 'needs unicorn and fp L MAIN')
class OrdinaryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = CAMERA.verify_main(IMAGE)
        cls.text, cls.art = ordinary_card(IMAGE)

    def assert_installed(self, cam):
        trial_tests.ShellCardTests.assert_worker_installed(self, cam)
        self.assertEqual(bytes(cam.mu.mem_read(DIR_ENTRY, RESTORE_LEN)),
                         self.image[DIR_ENTRY - 0xC0000000:
                                    DIR_ENTRY - 0xC0000000 + RESTORE_LEN])
        self.assertEqual(cam.word(DIR_SLOT), DIR_ENTRY)
        self.assertEqual(cam.word(ECHO_SLOT), ECHO_STOCK)
        self.assertEqual(cam.word(0xC003178C), 0xE3A00000)
        self.assertEqual(cam.word(0xC01E3F84), 0x4628E01E)

    def test_real_cli_copy_chain_and_trial_equivalence(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'ordinary' / 'AutoRun.txt'
            result = cli(out)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = out.read_text()
            blob = (out.parent / 'fpSup.BIN').read_bytes()
            self.assertEqual(text, self.text)
            trial_lines, _, trial_art = card(self.image, diag=True)
            self.assertEqual(blob, trial_art['binfile'])
            self.assertEqual(text.splitlines(), [line for line in trial_lines
                             if not line.startswith(('#', 'mem save ', 'ctrl sleep '))])
            self.assertEqual(set(p.name for p in out.parent.iterdir()),
                             {'AutoRun.txt', 'fpSup.BIN'})
            cam = ShellTrial(self, self.image, text.splitlines(), blob).run()
            self.assert_installed(cam)
            self.assertEqual([a for _, _, a in cam.allocations], [STAGING, POOL, CODE])
            self.assertEqual([n for _, n in cam.timeline].count('H_FREE'), 1)
            self.assertEqual([flag for _, flag in cam.registered], [0, 1])
            self.assertEqual(cam.saved, {})
            self.assertEqual(cam.slept_ms, 0)
            cam.run()
            self.assert_installed(cam)  # second AutoRun still has only one task
            before = out.read_bytes()
            self.assertNotEqual(cli(out).returncode, 0)
            self.assertEqual(out.read_bytes(), before)

    def test_real_entry_offset_and_mutation_breaks_install_oracle(self):
        blob = self.art['binfile']
        self.assertEqual(struct.unpack_from('<4sII', blob),
                         (b'VBIN', 2, 32 + len(self.art['stage2'])))
        self.assertEqual(blob[self.art['entry']:], self.art['worker'])
        broken = bytearray(blob)
        struct.pack_into('<I', broken, 8, 0)  # single-line header-entry mutation
        cam = ShellTrial(self, self.image, self.text.splitlines(), bytes(broken)).run()
        with self.assertRaises(AssertionError):
            self.assert_installed(cam)

    def test_bad_image_refused_without_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / 'MAIN.bin'
            bad.write_bytes(b'not the inspected image')
            out = Path(td) / 'absent' / 'AutoRun.txt'
            result = cli(out, main=bad)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not the inspected', result.stderr)
            self.assertFalse(out.parent.exists())


if __name__ == '__main__':
    unittest.main()
