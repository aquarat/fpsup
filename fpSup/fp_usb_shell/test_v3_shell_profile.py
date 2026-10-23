"""fp-only v3 shell packaging after worker constants moved to profiles."""
import itertools
import os
from pathlib import Path
import re
import struct
import sys
import unittest
from unittest.mock import patch

from armasm import assemble, symbols
import patches

sys.path.insert(0, str(Path(__file__).resolve().parent / 'v3'))
import build_v3 as B

PROFILE = B.SHELL / 'firmware/worker_fp_502.h'
WORKER = B.SHELL / 'camera/worker.S'
IMAGE = Path(os.environ.get('FPSUP_FP_MAIN', Path.home() /
             '.local/share/fpsup/firmware/FP__V502/MAIN.bin'))


class ShellProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = PROFILE.read_text()
        cls.state = int(re.search(r'^#define FW_WSTATE\s+(0x\w+)',
                                 cls.profile, re.M)[1], 16)
        cls.code = assemble(WORKER, ['FPSUP_CAMERA=502'])
        cls.spawn = symbols(WORKER, ['FPSUP_CAMERA=502'])['spawn']

    def expected_rows(self, ep, burst, noptp):
        rows = [(self.state, bytes(96), 2)]
        for enabled, table in ((True, patches.IFACE), (ep, patches.PUSH),
                               (burst, patches.BURST15), (noptp, patches.NOPTP)):
            if enabled:
                rows += [(a, struct.pack('<I', v), 2) for a, v, *_ in table]
        return rows

    def test_real_worker_and_patch_rows_for_every_option_combination(self):
        for ep, burst, noptp in itertools.product((False, True), repeat=3):
            with self.subTest(ep=ep, burst=burst, noptp=noptp), \
                    patch.object(B, 'patch_sup', return_value=b'captured') as package:
                self.assertEqual(B.shell_sup(ep, burst, noptp), b'captured')
                package.assert_called_once_with('SHEL', self.expected_rows(ep, burst, noptp),
                                                self.code, self.spawn)
        with patch.object(B, 'patch_sup') as package:
            B.shell_sup()
            self.assertEqual(package.call_args.args[1], self.expected_rows(False, False, True))

    def test_explicit_fp_defines_for_both_assembly_and_symbols(self):
        with patch.object(B, 'assemble', wraps=B.assemble) as asm, \
                patch.object(B, 'symbols', wraps=B.symbols) as sym, \
                patch.object(B, 'patch_sup'):
            B.shell_sup()
        asm.assert_called_once_with(WORKER, ['FPSUP_CAMERA=502'])
        sym.assert_called_once_with(WORKER, ['FPSUP_CAMERA=502'])

    def test_missing_malformed_nonfixed_or_unaligned_state_refuses(self):
        original = Path.read_text
        for definition in ('', '#define FW_WSTATE FW_WSTATE_OFF',
                           '#define FW_WSTATE 0xC072F000 + 4',
                           '#define FW_WSTATE 0x1000', '#define FW_WSTATE 0',
                           '#define FW_WSTATE 0xC072F002',
                           '#define FW_WSTATE 0xFFFFFFFC',
                           '#define FW_WSTATE 0xC072F000\n#define FW_WSTATE 0xC072F004'):
            altered = re.sub(r'^#define FW_WSTATE[^\n]*', definition, self.profile, flags=re.M)
            def read(path, *args, **kwargs):
                return altered if path == PROFILE else original(path, *args, **kwargs)
            with self.subTest(definition=definition), patch.object(Path, 'read_text', read), \
                    patch.object(B, 'assemble') as asm, patch.object(B, 'patch_sup') as package:
                with self.assertRaisesRegex(B.BuildError, 'FW_WSTATE'):
                    B.shell_sup()
                asm.assert_not_called()
                package.assert_not_called()

    @unittest.skipUnless(IMAGE.exists(), 'requires the inspected fp MAIN')
    def test_actual_sup_equals_pre_profile_parser_equivalent(self):
        # Old code parsed a literal STATE from worker.S, then used the default
        # fp assembler. Supply that old parser input in memory, deriving its
        # value from the profile rather than duplicating a firmware constant.
        from firmware import get_camera
        get_camera('fp-5.02').verify_main(IMAGE)
        old_source = f'.equ STATE, 0x{self.state:X}\n'
        old_state = int(re.search(r'^\.equ\s+STATE,\s*(0x[0-9A-Fa-f]+)',
                                  old_source, re.M)[1], 16)
        old_code, old_spawn = assemble(WORKER), symbols(WORKER)['spawn']
        self.assertEqual((old_code, old_spawn), (self.code, self.spawn))
        with patch.object(B, 'IMAGE', IMAGE):
            for ep, burst, noptp in itertools.product((False, True), repeat=3):
                with self.subTest(ep=ep, burst=burst, noptp=noptp):
                    rows = self.expected_rows(ep, burst, noptp)
                    rows[0] = (old_state, bytes(96), 2)
                    expected = B.patch_sup('SHEL', rows, old_code, old_spawn)
                    actual = B.shell_sup(ep, burst, noptp)
                    self.assertEqual(actual, expected)
                    self.assertEqual(struct.unpack_from('<I', actual)[0], B.SL_MAGIC)
                    self.assertEqual(struct.unpack_from('<I', actual, 8)[0], len(actual))


if __name__ == '__main__':
    unittest.main()
