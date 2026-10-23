"""Offline deployment integration tests, using the real locked upload/download."""
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fpl_deploy as deploy
import fpl_getfile as gf
from test_fpl_getfile import Fake


class CardFake(Fake):
    def __init__(self, test, fault=None):
        super().__init__(fault)
        self.test = test
        self.files = {'\\AutoRun.txt': b'auto', '\\fpSup.BIN': b'old'}
        self.operations = []
        self.before_write = lambda: None
        self.bin_reads = 0

    def sh(self, line, **kwargs):
        with self.test.assertRaises(BlockingIOError):
            with gf.staging_lock():
                self.test.fail('camera access outside staging lock')
        if line != 'echo' or self.slot != self.plan.code:
            return super().sh(line, **kwargs)
        self.test.assertEqual(kwargs['retries'], 0)
        p = bytearray(self.memory[self.plan.param])
        path = bytes(p[0x24:]).split(b'\0')[0].decode('ascii')
        count, _, mode = struct.unpack_from('<3I', p, 0x18)
        self.operations.append((mode, path))
        if mode == 7:
            self.before_write()
            self.files[path] = self.memory[self.plan.buffer][:count] + self.files[path][count:]
            if self.fault == 'uncertain':
                raise OSError('uncertain write')
            if self.fault == 'autorun-change':
                self.files['\\AutoRun.txt'] = b'oops'
            struct.pack_into('<3I', p, 8, 2, 1, 1)
        else:
            data = self.files[path]
            if path == '\\fpSup.BIN':
                self.bin_reads += 1
                if self.fault == 'second-read' and self.bin_reads == 3:
                    data = b'bad'
                if self.fault == 'upload-read' and self.bin_reads == 2:
                    data = b'bad'
            struct.pack_into('<4I', p, 4, len(data), 2, 1, 1)
            self.memory[self.plan.buffer] = data
        self.memory[self.plan.param] = bytes(p)
        return ''


class Deployment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.candidate = self.root / 'candidate'
        self.previous = self.root / 'previous'
        self.backup = self.root / 'backup'
        for directory, data in ((self.candidate, b'new'), (self.previous, b'old')):
            directory.mkdir()
            (directory / 'AutoRun.txt').write_bytes(b'auto')
            (directory / 'fpSup.BIN').write_bytes(data)
        lock = patch.object(gf, 'LOCK_PATH', self.root / 'lock')
        lock.start()
        self.addCleanup(lock.stop)

    def run_card(self, fake):
        return deploy.deploy(self.candidate, self.previous, self.backup, fake)

    def test_verified_update_and_durable_backup_before_write(self):
        fake = CardFake(self)
        with patch.object(os, 'fsync', wraps=os.fsync) as sync:
            def before_write():
                self.assertEqual(sync.call_count, 4)  # both files, directory, parent
                self.assertEqual((self.backup / 'AutoRun.txt').read_bytes(), b'auto')
                self.assertEqual((self.backup / 'fpSup.BIN').read_bytes(), b'old')
            fake.before_write = before_write
            self.assertEqual(self.run_card(fake), 'updated')
        self.assertEqual(fake.operations, [(1, '\\AutoRun.txt'), (1, '\\fpSup.BIN'),
                                          (7, '\\fpSup.BIN'), (1, '\\fpSup.BIN'),
                                          (1, '\\fpSup.BIN'), (1, '\\AutoRun.txt')])
        self.assertEqual(fake.slot, gf.ECHO_STOCK)
        with gf.staging_lock():
            pass  # all paths release the lock

    def test_idempotent_noop(self):
        fake = CardFake(self)
        fake.files['\\fpSup.BIN'] = b'new'
        self.assertEqual(self.run_card(fake), 'unchanged')
        self.assertEqual(fake.operations, [(1, '\\AutoRun.txt'), (1, '\\fpSup.BIN'),
                                          (1, '\\AutoRun.txt')])
        self.assertFalse(self.backup.exists())

    def test_unrecognized_remote_or_wrong_exact_length_refuses_write(self):
        for path, data in [('\\AutoRun.txt', b'oops'), ('\\AutoRun.txt', b'auto-tail'),
                           ('\\fpSup.BIN', b'bad'), ('\\fpSup.BIN', b'old-tail'),
                           ('\\fpSup.BIN', b'ol')]:
            with self.subTest(path=path, data=data):
                fake = CardFake(self)
                fake.files[path] = data
                with self.assertRaises(RuntimeError):
                    self.run_card(fake)
                self.assertFalse(any(mode == 7 for mode, _ in fake.operations))
                self.assertFalse(self.backup.exists())

    def test_backup_sync_failure_prevents_write(self):
        for fail_at in range(4):
            with self.subTest(fail_at=fail_at):
                self.backup = self.root / f'backup-{fail_at}'
                fake = CardFake(self)
                with patch.object(os, 'fsync', side_effect=[None] * fail_at + [OSError('disk failure')]):
                    with self.assertRaisesRegex(OSError, 'disk failure'):
                        self.run_card(fake)
                self.assertFalse(any(mode == 7 for mode, _ in fake.operations))
                self.assertEqual(fake.files['\\fpSup.BIN'], b'old')

    def test_backup_directory_race_does_not_overwrite(self):
        fake = CardFake(self)
        original = deploy.backup_card

        def raced(directory, current):
            directory.mkdir()
            (directory / 'fpSup.BIN').write_bytes(b'keep')
            original(directory, current)

        with patch.object(deploy, 'backup_card', side_effect=raced):
            with self.assertRaises(FileExistsError):
                self.run_card(fake)
        self.assertEqual((self.backup / 'fpSup.BIN').read_bytes(), b'keep')
        self.assertFalse(any(mode == 7 for mode, _ in fake.operations))

    def test_post_write_failures_stop_without_retry_and_preserve_backup(self):
        for fault in ('uncertain', 'upload-read', 'second-read', 'autorun-change'):
            with self.subTest(fault=fault):
                self.backup = self.root / ('backup-' + fault)
                fake = CardFake(self, fault)
                with self.assertRaises((OSError, RuntimeError)):
                    self.run_card(fake)
                self.assertEqual(sum(mode == 7 for mode, _ in fake.operations), 1)
                self.assertEqual((self.backup / 'fpSup.BIN').read_bytes(), b'old')
                self.assertEqual(fake.slot, gf.ECHO_STOCK)
                with gf.staging_lock():
                    pass

    def test_preflight_faults(self):
        for fault in ('version', 'publication', 'upload'):
            with self.subTest(fault=fault):
                fake = CardFake(self, fault)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.run_card(fake)
                self.assertFalse(fake.operations)
                self.assertFalse(self.backup.exists())

    def test_lock_contention_and_pending_handoff_prevent_camera_calls(self):
        with patch.object(gf, 'Backend', side_effect=AssertionError('offline')):
            with gf.staging_lock():
                with self.assertRaises(BlockingIOError):
                    self.run_card(None)
            gf.LOCK_PATH.with_suffix('.pending').touch()
            with self.assertRaisesRegex(RuntimeError, 'handoff pending'):
                self.run_card(None)

    def test_invalid_local_inputs_are_offline(self):
        with patch.object(gf, 'staging_lock', side_effect=AssertionError('must stay offline')):
            for directory in (self.candidate, self.previous):
                extra = directory / 'FPSUPUI'
                extra.mkdir()
                with self.assertRaises(ValueError):
                    self.run_card(None)
                extra.rmdir()
                target = directory / 'fpSup.BIN'
                original = target.read_bytes()
                target.unlink()
                target.symlink_to(self.root / 'missing')
                with self.assertRaises(ValueError):
                    self.run_card(None)
                target.unlink()
                target.write_bytes(original)
            for name, data in [('AutoRun.txt', b'different'), ('fpSup.BIN', b'longer'),
                               ('fpSup.BIN', b'')]:
                target = self.candidate / name
                original = target.read_bytes()
                target.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.run_card(None)
                target.write_bytes(original)
            self.backup.mkdir()
            with self.assertRaises(ValueError):
                self.run_card(None)
            self.backup = self.root / 'missing' / 'backup'
            with self.assertRaises(ValueError):
                self.run_card(None)

    def test_import_and_help_offline(self):
        for args in (['-c', 'import fpl_deploy'], ['fpl_deploy.py', '--help']):
            result = subprocess.run([sys.executable, *args], cwd=gf.HERE,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
