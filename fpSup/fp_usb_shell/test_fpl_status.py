import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fpl_status as status


class Backend:
    def __init__(self):
        self.publication = [0x45000000, 0x100000, 0x45200000]
        self.c = dict(pool=self.publication[0], pool_size=self.publication[1],
                      xfer=0x100000, windows=[[0, 0, 0]] * 8)
        self.reads = []
        self.states = 0
        self.changed = False

    def sh(self, command, **kwargs):
        assert command == 'version' and kwargs == {'retries': 0}
        return 'model = w91c1\nrel version = 3.02.0.V90\n'

    def caps(self):
        return copy.deepcopy(self.c)

    def words(self, address, count):
        self.reads.append(address)
        if address == status.gf.PUBLICATION:
            p = self.publication.copy()
            if self.changed and self.states == 2:
                p[2] += 4
            return p
        if address == self.publication[0] + 0x1000:
            self.states += 1
            return [0xFFFFFFFE if self.states == 1 else 3] * 16
        # Deliberately invalid pointer values: must not dereference these.
        return [0xDEADBEEF] * count


class StatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        lock = patch.object(status.gf, 'LOCK_PATH', Path(temp.name) / 'lock')
        lock.start()
        self.addCleanup(lock.stop)

    def test_dynamic_pool_wrap_and_no_pointer_following(self):
        io = Backend()
        result = status.snapshot(io)
        self.assertEqual(result['counter_delta_mod32'], dict.fromkeys(status.COUNTERS, 5))
        self.assertNotIn(0xDEADBEEF, io.reads)
        self.assertIn(io.publication[0] + 0x1000, io.reads)
        self.assertEqual(result['lifecycle_fields'], {
            'active_mode': 0xDEADBEEF, 'configured_byte': 0xEF,
            'backend_selector': 0xAD, 'controller_running': True})

    def test_pending_is_observable_and_preserved(self):
        marker = status.gf.LOCK_PATH.with_suffix('.pending')
        marker.write_text('uncertain')
        self.assertTrue(status.snapshot(Backend())['pending_exists'])
        self.assertEqual(marker.read_text(), 'uncertain')

    def test_publication_change_rejected(self):
        io = Backend()
        io.changed = True
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            status.snapshot(io)

    def test_bad_caps_refuse_before_dynamic_reads(self):
        io = Backend()
        io.c['pool'] += 4
        with self.assertRaises(ValueError):
            status.snapshot(io)
        self.assertEqual(io.reads, [status.gf.PUBLICATION])

    def test_capability_change_rejected(self):
        io = Backend()
        def caps():
            result = copy.deepcopy(io.c)
            if io.states == 2:
                result['windows'][0] = [0x46000000, 4096, 1]
            return result
        io.caps = caps
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            status.snapshot(io)

    def test_short_or_nonword_read_rejected(self):
        for bad in ([], [True] * 3, [-1] * 3):
            io = Backend()
            io.words = lambda *args: bad
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                status.snapshot(io)

    def test_wrong_version_refuses_all_memory_reads(self):
        io = Backend()
        io.sh = lambda *args, **kwargs: 'echo model = w91c1 but no version'
        with self.assertRaises(ValueError):
            status.snapshot(io)
        self.assertEqual(io.reads, [])


if __name__ == '__main__':
    unittest.main()
