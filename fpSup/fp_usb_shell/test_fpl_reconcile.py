"""Offline reconciliation failures retain evidence; only window metadata writes."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import fpl_swapworker as sw

POOL, DEST = 0x45000000, 0x46000000
PUBLICATION = [POOL, 0x100000, DEST]


class Fake:
    def __init__(self, body, p):
        self.body = body
        self.values = {sw.gf.PUBLICATION: list(PUBLICATION),
                       sw.gf.ECHO_SLOT: [sw.gf.ECHO_STOCK],
                       p['STATUS']: [p['COOKIE']], POOL + 0x1080: [0]}
        self.capabilities = dict(pool=POOL, pool_size=0x100000, xfer=0x100000,
                                 windows=[(0, 0, 0)] * 8)
        self.version = 'model=w91c1 rel version=3.02.0.V90'
        self.calls, self.grants = [], []
        self.read_error = False
        self.after_read = lambda: None

    def sh(self, line, **kwargs):
        assert line == 'version' and kwargs == {'retries': 0}
        self.calls.append(line)
        return self.version

    def words(self, address, count=1):
        self.calls.append(address)
        return self.values[address]

    def caps(self):
        return copy.deepcopy(self.capabilities)

    def window(self, slot, base, length, permission):
        self.grants.append((slot, base, length, permission))
        self.capabilities['windows'][slot] = (base, length, permission)

    def read(self, address, count):
        assert (address, count) == (DEST, sw.SIZE)
        assert self.capabilities['windows'][0] == (DEST, sw.SIZE, 1)
        if self.read_error:
            raise RuntimeError('lost read reply')
        self.after_read()
        return self.body


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = Path(self.tmp.name) / 'staging.lock'
        self.marker = self.lock.with_suffix('.pending')
        self.body = bytes(sw.SIZE)
        # No assembler or hardware required: exercise hash verification itself.
        for target, attr, value in ((sw.gf, 'LOCK_PATH', self.lock),
                                    (sw, 'SHA', hashlib.sha256(self.body).hexdigest())):
            context = patch.object(target, attr, value)
            context.start()
            self.addCleanup(context.stop)
        self.p = sw.plan(PUBLICATION, dict(pool=POOL, pool_size=0x100000,
                                         xfer=4096), 42)
        self.record = dict(plan=self.p, publication=PUBLICATION, sha256=sw.SHA)
        hashes = patch.object(sw, 'supported_hashes', lambda: {sw.SHA}, create=True)
        hashes.start()
        self.addCleanup(hashes.stop)
        self.io = Fake(self.body, self.p)
        self.save()

    def save(self):
        self.marker.write_text(json.dumps(self.record))

    def run_reconcile(self):
        with patch.object(sw.gf.transport, 'mem_window', side_effect=self.io.window):
            return sw.reconcile(self.io)

    def retained(self):
        raw = self.marker.read_bytes()
        with self.assertRaises((RuntimeError, ValueError, TypeError)):
            self.run_reconcile()
        self.assertEqual(self.marker.read_bytes(), raw)

    def test_success_and_directory_sync(self):
        with patch.object(sw, 'sync_directory', wraps=sw.sync_directory) as sync:
            self.assertEqual(self.run_reconcile(), self.p)
            sync.assert_called_once_with(self.marker.parent)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.io.grants, [(0, DEST, sw.SIZE, 1), (0, 0, 0, 0)])

    def test_malformed_marker_before_camera(self):
        for raw in (b'{', b'null', b'[]', b'{}', b' ' * 4097,
                    b'{"plan":{},"plan":{}}'):
            with self.subTest(raw=raw[:40]):
                self.marker.write_bytes(raw)
                self.retained()
                self.assertEqual(self.io.calls, [])
                self.assertEqual(self.io.grants, [])

    def test_unknown_schema_hash_and_addresses_before_camera(self):
        original = copy.deepcopy(self.record)
        for mutation in ('schema', 'hash', 'status', 'pool', 'cookie', 'bool', 'extra'):
            with self.subTest(mutation=mutation):
                self.record = copy.deepcopy(original)
                if mutation == 'schema':
                    self.record['schema'] = 2
                elif mutation == 'hash':
                    self.record['sha256'] = 'f' * 64
                elif mutation == 'pool':
                    self.record['publication'][0] = 0xC0000000
                elif mutation == 'extra':
                    self.record['plan']['LENGTH'] = 4096
                else:
                    key = 'STATUS' if mutation == 'status' else 'COOKIE'
                    self.record['plan'][key] = {'status': 0xC0000000,
                                                 'cookie': 0, 'bool': True}[mutation]
                self.save()
                self.retained()
                self.assertEqual(self.io.calls, [])

    def test_wrong_firmware_changed_boot_or_publication(self):
        self.io.version = 'model=w91c1 rel version=3.02.0.V91'
        self.retained()
        self.io.version = 'model=w91c1 rel version=3.02.0.V90'
        self.io.values[sw.gf.PUBLICATION] = [POOL + 0x100000, 0x100000, DEST]
        self.retained()
        self.assertEqual(self.io.grants, [])

    def test_aborted_incomplete_cookie_armed_or_echo_owned(self):
        for address, values in ((self.p['STATUS'], [0]), (self.p['STATUS'], []),
                                (self.p['STATUS'], [43]), (POOL + 0x1080, [0x50415753]),
                                (sw.gf.ECHO_SLOT, [self.p['STUB']])):
            with self.subTest(address=address, values=values):
                self.io = Fake(self.body, self.p)
                self.io.values[address] = values
                self.retained()
                self.assertEqual(self.io.grants, [])

    def test_invalid_caps(self):
        for change in ({'xfer': 0}, {'pool_size': 0x200000}, {'windows': []},
                       {'windows': [(0, 0, True)] * 8}):
            with self.subTest(change=change):
                self.io = Fake(self.body, self.p)
                self.io.capabilities.update(change)
                self.retained()
                self.assertEqual(self.io.grants, [])

    def test_read_mismatch_short_or_failure_restores_window(self):
        for body, error in ((b'x' * sw.SIZE, False), (b'', False), (self.body, True)):
            with self.subTest(error=error, length=len(body)):
                self.io = Fake(body, self.p)
                self.io.read_error = error
                self.retained()
                self.assertEqual(self.io.capabilities['windows'], [(0, 0, 0)] * 8)
                self.assertEqual(self.io.grants[-1], (0, 0, 0, 0))

    def test_changed_publication_during_read(self):
        self.io.after_read = lambda: self.io.values.update({sw.gf.PUBLICATION: [0, 0, 0]})
        self.retained()

    def test_changed_caps_during_read(self):
        self.io.after_read = lambda: self.io.capabilities.update(xfer=8192)
        self.retained()

    def test_no_available_window_retains_without_metadata_writes(self):
        self.io.capabilities['windows'] = [(DEST, sw.SIZE, 1)] * 8
        self.retained()
        self.assertEqual(self.io.grants, [])

    def test_missing_marker_does_not_contact_camera(self):
        self.marker.unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_reconcile()
        self.assertEqual(self.io.calls, [])

    def test_explicit_supported_hash_extension(self):
        self.io.body = b'x' * sw.SIZE
        target_hash = hashlib.sha256(self.io.body).hexdigest()
        self.record['sha256'] = target_hash
        self.save()
        self.retained()
        self.assertEqual(self.io.calls, [])
        with patch.object(sw, 'supported_hashes', lambda: {sw.SHA, target_hash}):
            self.run_reconcile()
        self.assertFalse(self.marker.exists())

    def test_window_grant_or_restore_failure_retains(self):
        for fail_grant in (True, False):
            self.io = Fake(self.body, self.p)
            def faulty(slot, base, length, permission):
                if bool(base) == fail_grant:
                    return  # simulate silently lost metadata write
                self.io.window(slot, base, length, permission)
            with patch.object(sw.gf.transport, 'mem_window', side_effect=faulty):
                with self.assertRaises(RuntimeError):
                    sw.reconcile(self.io)
            self.assertTrue(self.marker.exists())

    def test_lock_is_held_and_pending_is_permitted(self):
        def check_lock():
            with self.assertRaises(BlockingIOError), sw.gf.staging_lock(permit_pending=True):
                self.fail('reconcile did not hold lock')
        self.io.after_read = check_lock
        self.run_reconcile()

    def test_import_and_help_offline(self):
        for arguments in (['-c', 'import fpl_swapworker'], ['fpl_swapworker.py', '--help']):
            result = subprocess.run([sys.executable, *arguments], cwd=sw.gf.HERE,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
