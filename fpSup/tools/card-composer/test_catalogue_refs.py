"""Offline reference checks; no assembler, releases or page writes required."""
import struct
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import build_catalogue as c


def container(records, entry=0):
    body = b''.join(b + b'\0' * (-len(b) % 4) for _, b in records)
    return (struct.pack('<4sIII', b'VBIN', len(records), entry, len(body))
            + b''.join(struct.pack('<II', a, len(b)) for a, b in records) + body)


class ReferenceTests(unittest.TestCase):
    def test_zero_padding_only(self):
        blob = container([(0, b'help'), (0xC0001000, b'abc\0')])
        self.assertEqual(c.reference_bin(blob + b'\0' * 100), blob)

    def test_nonzero_tail_rejected(self):
        with self.assertRaisesRegex(ValueError, 'nonzero tail'):
            c.reference_bin(container([(0, b'help')]) + b'\0TAIL')

    def test_truncated_header_rejected(self):
        with self.assertRaises(ValueError):
            c.reference_bin(b'VBIN')

    def test_truncated_body_rejected(self):
        with self.assertRaises(ValueError):
            c.reference_bin(container([(0, b'help')])[:-1])

    def test_false_size_rejected(self):
        blob = bytearray(container([(0, b'help')]) + b'\0' * 4)
        struct.pack_into('<I', blob, 12, 8)
        with self.assertRaisesRegex(ValueError, 'section lengths'):
            c.reference_bin(blob)

    def test_autorun_padding(self):
        body = 'mem set 0x00000000 0x00000000\n'
        self.assertEqual(c.reference_autorun(c.autorun(body, 'X')), body)
        self.assertEqual(c.reference_autorun(body), body)

    def test_autorun_tail_command_rejected(self):
        with self.assertRaisesRegex(ValueError, 'padding suffix'):
            c.reference_autorun(c.autorun('echo test\n', 'X') + 'echo bad\n')

    def test_autorun_modified_comment_rejected(self):
        text = c.autorun('echo test\n', 'X')
        with self.assertRaises(ValueError):
            c.reference_autorun(text.replace(c.FILLER, c.FILLER + '# extra\n', 1))

    def signature(self, order=(0xC0001000, 0xC0002000), worker=b'work'):
        records = [(0, b'help'), (0xC0001000, worker), (0xC0002000, b'next')]
        entry = 16 + 8 * 4 + 12
        tramp = b'STUB' + struct.pack('<4I', entry + 4, *order, 0)
        return c.semantic_signature(container(records + [(0, tramp)], entry), b'STUB', 4)

    def test_entry_order_matters(self):
        self.assertNotEqual(self.signature(), self.signature((0xC0002000, 0xC0001000)))

    def test_worker_bytes_matter(self):
        self.assertNotEqual(self.signature(), self.signature(worker=b'evil'))

    def test_frozen_shell_reference_uses_frozen_bytes_and_call_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            shell, plain = root / 'shell', root / 'plain'
            shell.mkdir()
            plain.mkdir()
            (shell / 'fpSup.BIN').write_bytes(container(
                [(0, b'old!'), (0xC0003000, b'flag'), (0, b'FROZEN')], 48))
            # Plain has gyro then an absolute OG entry, represented by a trampoline.
            records = [(0, b'help'), (0xC0001000, b'og!!'), (0, b'gyro')]
            entry = 60
            tramp = b'STUB' + struct.pack('<4I', entry + 4, 56, 0xC0001000, 0)
            (plain / 'fpSup.BIN').write_bytes(container(records + [(0, tramp)], entry))
            with patch.object(c, 'latest', return_value=shell), \
                    patch.object(c, 'trampoline', return_value=(b'STUB', 4)), \
                    patch.object(c, 'push_sections', return_value=[]), \
                    patch.object(c.subprocess, 'run') as run:
                run.return_value.returncode = 0
                c.frozen_shell_reference(plain, root / 'out', root)
            cmd = run.call_args.args[0]
            boots = [cmd[i + 1] for i, v in enumerate(cmd) if v == '--boot-bin']
            self.assertEqual([pathlib.Path(b.rsplit(':', 1)[0]).read_bytes()
                              for b in boots], [b'FROZEN', b'gyro'])
            self.assertEqual([b.rsplit(':', 1)[1] for b in boots], ['0', '0'])
            self.assertEqual(cmd[-2:], ['--vshl-entry', '0xC0001000'])
            fixed = [cmd[i + 1] for i, v in enumerate(cmd) if v == '--also-bin']
            self.assertEqual([(a, pathlib.Path(p).read_bytes())
                              for a, p in (v.split(':', 1) for v in fixed)],
                             [('0xC0003000', b'flag'), ('0xC0001000', b'og!!')])
            self.assertIn('--no-shell', cmd)


if __name__ == '__main__':
    unittest.main()
