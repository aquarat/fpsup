"""Offline host tests: every camera boundary is replaced with an in-memory fake."""
from contextlib import nullcontext
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import fpl_gyro_capture as cap
import fpl_getfile as gf


def completed(capacity, *, moving=False):
    state = bytearray(cap.STATE_ROOM)
    observed = 19 if moving else 0
    count = min(observed, capacity)
    struct.pack_into('<8I', state, 0, cap.MAGIC, 1 if moving else 2, 20,
                     count, observed, 0, observed-count, 0 if moving else 19)
    heads = [cap.RING + 8*(i+1 if moving else 1) for i in range(20)]
    struct.pack_into('<40I', state, 32, *(heads+heads))
    room = ((capacity*8+2047)//1024)*1024
    output = bytearray(cap.SENTINEL * room)
    for i in range(count):
        struct.pack_into('<hhHh', output, i*8, i, -i, 0, 12)
    return state, output


class Fake:
    def __init__(self, capacity=1200):
        self.capacity = capacity
        self.publication = [0x45000000, 0x100000, 0x46000000]
        self.handler = gf.ECHO_STOCK
        self.memory = {}
        self.writes, self.sets, self.calls = [], [], []
        self.fail_handler = None
        self.mutate = None
        self.bad_upload = False
        self.restore_failure = False
        self.version = 'model = w91c1\nrel version = 3.02.0.V90\n'
        self.plan = cap.layout(self.caps(), self.publication, capacity)

    def caps(self):
        return dict(pool=self.publication[0], pool_size=self.publication[1], xfer=0xfffc00)

    def words(self, address, count=1):
        if address == gf.PUBLICATION:
            return list(self.publication)
        assert address == gf.ECHO_SLOT
        return [self.handler]

    def set_word(self, address, value):
        assert address == gf.ECHO_SLOT
        self.sets.append((address, value))
        if not (self.restore_failure and value == gf.ECHO_STOCK):
            self.handler = value

    def write(self, address, data):
        self.writes.append((address, bytes(data)))
        self.memory[address] = bytearray(data)
        if self.bad_upload:
            self.memory[address][0] ^= 1

    def read(self, address, count):
        return bytes(self.memory[address][:count])

    def sh(self, command, **kwargs):
        self.calls.append((command, self.handler, kwargs))
        assert kwargs['retries'] == 0
        if command == 'version':
            return self.version
        assert command == 'echo'
        if self.handler == self.fail_handler:
            return 'ERR uncertain'
        if self.handler == self.plan.code:
            self.memory[self.plan.state], self.memory[self.plan.output] = completed(self.capacity)
            if self.mutate:
                self.mutate(self)
        return ''


class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = Fake().plan
        cls.code, cls.symbols = cap.code_for(cls.plan, 1200)

    def run_fake(self, fake):
        with patch.object(gf, 'staging_lock', return_value=nullcontext()):
            return cap.capture(fake, capacity=fake.capacity)

    def test_invalid_before_camera_or_lock(self):
        with patch.object(gf, 'Backend') as backend, patch.object(gf, 'staging_lock') as lock:
            for value in (0, -1, 12001, True, 2.5, '12'):
                with self.assertRaises(ValueError):
                    cap.capture(capacity=value)
            backend.assert_not_called()
            lock.assert_not_called()

    def test_pending_refuses_before_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'staging.lock'
            lock.with_suffix('.pending').touch()
            with patch.object(gf, 'LOCK_PATH', lock), patch.object(gf, 'Backend') as backend:
                with self.assertRaisesRegex(RuntimeError, 'pending'):
                    cap.capture()
                backend.assert_not_called()

    def test_exact_three_staging_writes_and_handler_only(self):
        fake = Fake()
        report, state, output = self.run_fake(fake)
        self.assertEqual(report['status'], 'no_observed_motion')
        self.assertEqual([(a, len(b)) for a, b in fake.writes],
                         [(fake.plan.code, 4096), (fake.plan.state, 1024),
                          (fake.plan.output, fake.plan.output_room)])
        self.assertEqual(fake.writes[1][1], bytes(1024))
        self.assertEqual([v for a, v in fake.sets],
                         [gf.DCACHE, gf.ICACHE, fake.plan.code, gf.ECHO_STOCK])
        self.assertEqual([h for c, h, k in fake.calls if c == 'echo'],
                         [gf.DCACHE, gf.ICACHE, fake.plan.code])
        self.assertEqual(fake.handler, gf.ECHO_STOCK)
        self.assertEqual(report['host_echo_bounds']['meaning'], 'host echo call only, not sample timestamps')

    def test_uncertain_each_execution_restores_without_retry(self):
        for handler in (gf.DCACHE, gf.ICACHE, self.plan.code):
            fake = Fake()
            fake.fail_handler = handler
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                self.run_fake(fake)
            self.assertEqual(fake.handler, gf.ECHO_STOCK)
            self.assertEqual(sum(c == 'echo' and h == handler for c, h, k in fake.calls), 1)

    def test_transport_exception_restores_without_retry(self):
        fake = Fake()
        original = fake.sh
        def sh(command, **kwargs):
            reply = original(command, **kwargs)
            if command == 'echo' and fake.handler == fake.plan.code:
                raise TimeoutError('lost reply after execution')
            return reply
        fake.sh = sh
        with self.assertRaises(TimeoutError):
            self.run_fake(fake)
        self.assertEqual(fake.handler, gf.ECHO_STOCK)
        self.assertEqual(sum(c == 'echo' and h == fake.plan.code for c, h, k in fake.calls), 1)

    def test_restoration_must_verify(self):
        fake = Fake()
        fake.restore_failure = True
        with self.assertRaisesRegex(RuntimeError, 'did not verify'):
            self.run_fake(fake)
        self.assertEqual(sum(v == gf.ECHO_STOCK for a, v in fake.sets), 8)

    def test_upload_failure_never_executes(self):
        fake = Fake()
        fake.bad_upload = True
        with self.assertRaisesRegex(RuntimeError, 'upload'):
            self.run_fake(fake)
        self.assertEqual(fake.sets, [])
        self.assertEqual(len(fake.writes), 1)

    def test_version_and_owner_refused_without_write(self):
        for version in ('model = w91c1\nrel version = 3.02.0.V900',
                        'model = w91c1\nmodel = w91c1\nrel version = 3.02.0.V90'):
            fake = Fake()
            fake.version = version
            with self.assertRaises(ValueError):
                self.run_fake(fake)
            self.assertEqual(fake.writes, [])
        fake = Fake()
        fake.handler = 0x12345678
        with self.assertRaisesRegex(RuntimeError, 'stock'):
            self.run_fake(fake)
        self.assertEqual(fake.writes, [])

    def test_layout_bounds_and_nonoverlap(self):
        fake = Fake()
        for capacity in (1, 1200, 12000):
            plan = cap.layout(fake.caps(), fake.publication, capacity)
            self.assertLessEqual(plan.code+4096, plan.state)
            self.assertLessEqual(plan.state+1024, plan.output)
            self.assertLessEqual(plan.output+plan.output_room, fake.publication[0]+fake.publication[1])
            self.assertGreaterEqual(plan.output_room, capacity*8+1024)
        caps = fake.caps()
        caps['pool'] += 4
        with self.assertRaises(ValueError):
            cap.layout(caps, fake.publication, 1200)
        fake.publication[1] = 0x12000
        with self.assertRaises(ValueError):
            cap.layout(fake.caps(), fake.publication, 12000)

    def test_real_compile_capacity_extremes_and_unaligned_pool(self):
        fake = Fake()
        fake.publication[0] += 4
        for capacity in (1, 12000):
            plan = cap.layout(fake.caps(), fake.publication, capacity)
            code, symbols = cap.code_for(plan, capacity)
            self.assertEqual(len(code), 4096)
            self.assertEqual(plan.code % 1024, 0)
            self.assertGreaterEqual(plan.code, fake.publication[0]+0x10000)
            self.assertLess(plan.code, fake.publication[0]+0x10400)
            cap.verify_code(code, code, symbols)

    def test_symbol_mask_is_exact_not_whole_descriptor(self):
        mutable = {self.symbols[name]+i for name in cap.MUTABLE for i in range(4)}
        for offset in range(len(self.code)):
            changed = bytearray(self.code)
            changed[offset] ^= 1
            if offset in mutable:
                cap.verify_code(self.code, changed, self.symbols)
            else:
                with self.assertRaisesRegex(RuntimeError, 'static'):
                    cap.verify_code(self.code, changed, self.symbols)

    def test_post_execution_static_mutation_rejected_restored(self):
        fake = Fake()
        fake.mutate = lambda f: f.memory[f.plan.code].__setitem__(0, 0)
        with self.assertRaisesRegex(RuntimeError, 'static'):
            self.run_fake(fake)
        self.assertEqual(fake.handler, gf.ECHO_STOCK)

    def test_capacity_count_and_chronological_records(self):
        for capacity in (1, 10, 1200):
            state, output = completed(capacity, moving=True)
            result = cap.decode(state, output, capacity)
            self.assertEqual(result['appended_records'], min(19, capacity))
            self.assertEqual(result['dropped_for_capacity'], max(0, 19-capacity))
            self.assertEqual([r[0] for r in result['records_chronological_order']], list(range(min(19, capacity))))

    def test_malformed_counts_status_marker_and_guards(self):
        for offset, value in ((0, 0), (4, 0), (4, 99), (8, 21), (12, 1201),
                              (16, 1), (20, 1), (24, 1), (28, 20), (192, 1), (256, 1)):
            state, output = completed(1200)
            struct.pack_into('<I', state, offset, value)
            with self.assertRaises(RuntimeError):
                cap.decode(state, output, 1200)
        state, output = completed(1200)
        output[-1] ^= 1
        with self.assertRaisesRegex(RuntimeError, 'sentinel'):
            cap.decode(state, output, 1200)

    def test_partial_stale_is_diagnostic(self):
        for status in range(3, 8):
            state = bytearray(cap.STATE_ROOM)
            struct.pack_into('<8I', state, 0, cap.MAGIC, status, 1, 1, 1, 0, 0, 0)
            struct.pack_into('<2I', state, 32, cap.RING+8, cap.RING+16)
            struct.pack_into('<2I', state, 112, cap.RING+8, cap.RING+24)
            output = bytearray(cap.SENTINEL * 2048)
            struct.pack_into('<hhHh', output, 0, 1, 2, 0, 3)
            result = cap.decode(state, output, 1)
            self.assertTrue(result['diagnostic_only'])
            self.assertEqual(result['last_batch_invalid'], status == 7)

    def test_help_and_existing_output_are_offline(self):
        with patch.object(cap, 'capture') as capture:
            with self.assertRaises(SystemExit) as result:
                cap.main(['--help'])
            self.assertEqual(result.exception.code, 0)
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(FileExistsError):
                    cap.main(['--out', directory])
            capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
