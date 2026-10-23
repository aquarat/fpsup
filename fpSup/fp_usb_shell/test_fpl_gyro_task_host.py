"""Offline host + actual ARM pipeline. No real transport calls.

Allocation runs real descriptor/channel/list instructions on a synthetic USER
heap. Retained launch/capture/query run the existing real-instruction harness.
USB, cache operations, scheduler and native task creation remain explicit mocks.
"""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar
import fpl_gyro_task as host
import test_fpl_gyro_task_retained as retained
from fpl_allocator_audit import Machine as Allocator, CHANNEL, DESC

base, gf = retained.base, host.gf
POOL, ROOM, WORKER = 0x44FF0000, 0x20000, 0x47000000
STAGE, OWNER = POOL+0x10000, base.OWNED
VERSION = f'model = w91c1\nrel version = 3.02.0.V90\ngit hash = {host.GIT_HASH}\n'


class TaskMachine(retained.Machine):
    def __init__(self, *args, stage=STAGE, **kwargs):
        super().__init__(*args, **kwargs)
        self.stage = stage
        _, syms = host.small_body('fpl_task_entry.S', [f'TARGET={stage+0x1000}'])
        self.trampoline_result = stage+0x400+syms['result']

    def memory(self, m, access, address, size, value, unused):
        if access == uc.UC_MEM_WRITE and self.stage+0x400 <= address < self.stage+0x800:
            assert self.context == 'external'
            lo = self.trampoline_result
            assert lo <= address and address+size <= lo+16
            return
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        if pc == self.stage+0x1000:
            assert self.reg(0) == pc, 'loader entry r0 was echo argv'
        if self.stage+0x400 <= pc < self.stage+0x4000:
            # Current command trampoline and launcher remain owned pool staging.
            # They are not a native worker reference after launch returns.
            assert self.context == 'external', 'worker escaped into staging'
            return
        super().execute(m, pc, size, unused)


class FakeIO:
    def __init__(self, image, artifact, out, *, fail=None, descriptor=None,
                 allocate_refusal=False, run_worker=True, pool=POOL, room=ROOM, **faults):
        self.out, self.fail, self.bad_descriptor = out, fail, descriptor
        self.run_worker = run_worker
        self.pool, self.room = pool, room
        self.stage = ((pool+gf.STAGING_OFFSET)//1024+bool((pool+gf.STAGING_OFFSET) % 1024))*1024
        self.m = TaskMachine(image, artifact, stage=self.stage, **faults)
        # Independently map the publication, including unaligned boundary pages.
        regions = list(self.m.m.mem_regions())
        for page in range(pool & ~4095, (pool+room+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in regions):
                self.m.m.mem_map(page, 4096)
        self.m.m.mem_map(WORKER, 4096)
        self.m.m.mem_write(WORKER, host.swap.reviewed_body(True))
        self.m.word(gf.ECHO_SLOT, gf.ECHO_STOCK)
        self.publication = [pool, room, WORKER]
        self.windows = [(0, 0, 0)]*8
        self.log, self.executions = [], []
        self.version = VERSION
        self.pings = 0
        self.ping_replies = ['OK pong seq=91 proof=PONG', 'OK pong seq=92 proof=PONG']
        self.allocator = Allocator(image)
        a = self.allocator
        start = self.stage & ~4095
        a.mu.mem_map(start, ((self.stage+0x4000+4095) & ~4095)-start)
        # Enough room for a 64-KiB-aligned 64-KiB request. The class channel's
        # synthetic first-fit placement returns exactly OWNER, not a fake GET.
        heap, size = OWNER-0x10000, 0x30000
        a.mu.mem_map(heap, size)
        a.stubs.update({0xC0013090: 1, 0xC00131E4: 0, 0xC001E328: 0, 0xC001E3C8: 0})
        a.put(0xC30739D8, CHANNEL)
        a.put(0xC3073A10, CHANNEL)
        a.put(CHANNEL, 0, 0)
        a.call(0xC0010310, CHANNEL+8)
        a.call(0xC00103A8, CHANNEL+8, heap)
        for address in (heap, heap+(0x10000 if allocate_refusal else size)-0x40):
            a.put(DESC+0x100, address, 0x40)
            a.call(0xC00103E8, CHANNEL+8, DESC+0x100)
        self.alloc_calls = 0

        def trace(mu, pc, size, unused):
            assert pc != 0xC001D7A0, 'free reached'
            if pc == 0xC001D740:
                self.alloc_calls += 1
                assert mu.reg_read(ar.UC_ARM_REG_R1) == 0
                assert mu.reg_read(ar.UC_ARM_REG_R2) == host.SIZE
                assert mu.reg_read(ar.UC_ARM_REG_R3) == host.SIZE
                assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
        a.mu.hook_add(uc.UC_HOOK_CODE, trace)

    def event(self, name):
        self.log.append(name)
        if name == self.fail:
            raise RuntimeError('injected '+name)

    def caps(self):
        self.event('caps')
        return dict(pool=self.pool, pool_size=self.room, xfer=0xFFFC00, windows=list(self.windows))

    def words(self, address, count=1):
        if address == gf.PUBLICATION:
            return list(self.publication)
        return [self.m.word(address+i*4) for i in range(count)]

    def read(self, address, count):
        self.event(f'read:{address:x}:{count:x}')
        return bytes(self.m.m.mem_read(address, count))

    def write(self, address, data):
        self.event(f'write:{address:x}:{len(data):x}')
        assert address % 1024 == len(data) % 1024 == 0
        assert (self.stage <= address and address+len(data) <= self.pool+self.room) or \
            (OWNER <= address and address+len(data) <= OWNER+host.SIZE and
             (OWNER, host.SIZE, 3) in self.windows)
        self.m.m.mem_write(address, data)
        if self.stage <= address < self.stage+0x4000:
            self.allocator.mu.mem_write(address, data)

    def set_word(self, address, value):
        self.event('restore' if value == gf.ECHO_STOCK else 'arm')
        assert address == gf.ECHO_SLOT
        self.m.word(address, value)

    def window(self, slot, address, length, perm):
        self.event('window-grant' if perm else 'window-revoke')
        self.windows[slot] = (address, length, perm)

    def ping(self):
        self.pings += 1
        self.event(f'ping:{self.pings}')
        manifest = json.loads((self.out/'manifest.json').read_text())
        assert manifest['operations'][-1]['operation'] in ('admission-pong', 'final-pong')
        assert manifest['operations'][-1]['state'] == 'intent'
        return self.ping_replies[self.pings-1]

    def sh(self, command, **kwargs):
        assert kwargs.get('retries') == 0
        if command == 'version':
            return self.version
        assert command == 'echo'
        manifest = json.loads((self.out/'manifest.json').read_text())
        assert gf.LOCK_PATH.with_suffix('.pending').exists()
        operation = manifest['operations'][-1]
        assert operation['state'] == 'intent'
        handler = self.m.word(gf.ECHO_SLOT)
        assert operation['handler'] == handler
        label = operation['operation']
        self.event('execute:'+label)
        self.executions.append(label)
        if handler in (gf.DCACHE, gf.ICACHE):
            self.event('after:'+label)
            return ''                # privileged cache effects explicitly mocked
        if handler == self.stage:
            a = self.allocator
            a.call(self.stage)
            data = bytes(a.mu.mem_read(self.stage, 1024))
            if self.bad_descriptor:
                b = bytearray(data)
                _, labels = host.small_body('fpl_task_allocate.S', host.CAMERA.loader_defines())
                struct.pack_into('<5I', b, labels['result']+4, *self.bad_descriptor)
                data = bytes(b)
            self.m.m.mem_write(self.stage, data)
        else:
            assert handler == self.stage+0x400
            if label == 'launch':
                assert manifest['descriptor'] == [OWNER, 0, OWNER, host.SIZE]
                assert (self.out/'ownership.bin').read_bytes() == \
                    bytes(self.m.m.mem_read(OWNER+host.OWNER_INFO, 1024))
            m = self.m
            m.context = 'external'
            m.word(retained.audit.CURRENT, retained.audit.CALLER)
            m.word(retained.audit.NEXT, retained.audit.CALLER)
            m.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
            # Stock caller may be four-byte phase; trampoline must realign.
            m.m.reg_write(ar.UC_ARM_REG_SP, base.HOST_STACK-4)
            m.m.reg_write(ar.UC_ARM_REG_LR, base.STOP)
            m.m.reg_write(ar.UC_ARM_REG_R0, 0xDEAD0000)
            saved = {r: 0xABC00000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
            for r, value in saved.items():
                m.m.reg_write(r, value)
            m.m.emu_start(handler, base.STOP, count=1000000)
            assert m.m.reg_read(ar.UC_ARM_REG_PC) == base.STOP
            assert m.m.reg_read(ar.UC_ARM_REG_SP) == base.HOST_STACK-4
            assert all(m.m.reg_read(r) == v for r, v in saved.items())
            if label == 'launch':
                m.entry_returned = True
                m.m.mem_write(self.stage+0x1000, b'\xFE'*0x3000)  # poison launcher/source
            if label == 'activate' and self.run_worker:
                m.run_task()
        self.event('after:'+label)    # lost reply AFTER execution must never retry
        return ''


class Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = host.CAMERA.verify_main(base.MAIN)
        cls.artifact = host.build_owned(OWNER)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root/'trial'
        self.lock = patch.object(gf, 'LOCK_PATH', self.root/'staging.lock')
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def io(self, **kwargs):
        return FakeIO(self.image, self.artifact, self.out, **kwargs)

    def run_trial(self, io, **kwargs):
        # Exercise the real resident()/resident_window() helper, mocking only
        # its existing shared transport boundary, never the hash/readback logic.
        with patch.object(gf.transport, 'mem_window', side_effect=io.window):
            return host.run(self.out, base.MAIN, io=io, **kwargs)

    def test_full_arm_pipeline_descriptor_capture_and_durable_order(self):
        io = self.io()
        result = self.run_trial(io)
        self.assertEqual(result['status'], 'completed-retained')
        self.assertEqual(result['capture']['appended_records'], 950)
        self.assertEqual(io.alloc_calls, 1)
        self.assertEqual(io.m.capture_calls, 1)
        self.assertEqual(io.m.events.count(base.CREATE), 1)
        self.assertEqual(io.m.events.count(base.ATTACH), 1)
        self.assertEqual(io.m.word(gf.ECHO_SLOT), gf.ECHO_STOCK)
        self.assertEqual(io.windows, [(0, 0, 0)]*8)
        self.assertEqual(result['firmware_git_hash'], host.GIT_HASH)
        self.assertEqual(result['resident']['sha256'], host.swap.PONG_SHA)
        self.assertEqual(result['admission_pong']['sequence'], 91)
        self.assertEqual(result['final_pong']['sequence'], 92)
        self.assertLess(io.log.index('ping:1'), io.log.index('execute:allocate'))
        self.assertGreater(io.log.index('ping:2'), max(i for i, x in enumerate(io.log)
                                                     if x == 'window-revoke'))
        self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())
        self.assertLess(io.executions.index('launch'), io.executions.index('observe-01'))
        self.assertLess(io.executions.index('observe-01'), io.executions.index('activate'))
        for label in ('allocate', 'launch', 'observe-01', 'activate', 'observe-02'):
            at = io.executions.index(label)
            self.assertEqual(io.executions[at-2:at], [label+'-dcache', label+'-icache'])
        self.assertEqual(host.build_owned(OWNER)[0], retained.build()[0])

    def test_native_aligned_pool_pipeline_preserves_alignment_gap_and_tail(self):
        # Captured alignment is a fixture, never a production placement. Exercise
        # another native-aligned base too, with a tight but sufficient pool size.
        for index, pool in enumerate((0x4533AEC0, 0x44FF03C0)):
            with self.subTest(pool=hex(pool)):
                self.out = self.root/f'unaligned-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'align-lock-{index}'):
                    io = self.io(pool=pool, room=0x14400)
                    self.assertEqual(pool % 64, 0)
                    self.assertNotEqual(pool % 1024, 0)
                    raw_start = pool+gf.STAGING_OFFSET
                    gap = b'\xD3'*(io.stage-raw_start)
                    tail_start = io.stage+0x4000
                    tail = b'\xB7'*(pool+io.room-tail_start)
                    self.assertTrue(gap and tail)
                    io.m.m.mem_write(raw_start, gap)
                    io.m.m.mem_write(tail_start, tail)
                    result = self.run_trial(io)
                    self.assertEqual(result['status'], 'completed-retained')
                    self.assertEqual(result['staging_address'], io.stage)
                    self.assertEqual(result['capture']['appended_records'], 950)
                    self.assertEqual(bytes(io.m.m.mem_read(raw_start, len(gap))), gap)
                    self.assertEqual(bytes(io.m.m.mem_read(tail_start, len(tail))), tail)
                    self.assertEqual(io.alloc_calls, 1)
                    self.assertEqual(io.m.capture_calls, 1)
                    for entry in io.log:
                        if entry.startswith('write:'):
                            _, address, length = entry.split(':')
                            address, length = int(address, 16), int(length, 16)
                            self.assertEqual(address % 1024, 0)
                            self.assertEqual(length % 1024, 0)
                            if address != OWNER:
                                self.assertGreaterEqual(address, io.stage)
                                self.assertLessEqual(address+length, tail_start)

    def test_alignment_padding_tail_overflow_refused_before_any_camera_write(self):
        io = self.io(pool=0x4533AEC0, room=0x14000)
        # The old unrounded extent fits exactly; only the required alignment
        # padding makes this insufficient. Generic publication checks allow it.
        gf.layout(io.caps(), io.publication, 0)
        self.assertEqual(io.pool+gf.STAGING_OFFSET+0x4000, io.pool+io.room)
        self.assertGreater(io.stage+0x4000, io.pool+io.room)
        with self.assertRaisesRegex(ValueError, 'aligned staging exceeds'):
            self.run_trial(io)
        self.assertEqual(io.alloc_calls, 0)
        self.assertFalse(any(x.startswith('write:') or x == 'window-grant' for x in io.log))
        self.assertFalse(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_native_allocation_refusal_no_owned_writes_or_create(self):
        io = self.io(allocate_refusal=True)
        self.assertEqual(self.run_trial(io)['status'], 'allocation-refused-no-create')
        self.assertEqual(io.alloc_calls, 1)
        self.assertNotIn(base.CREATE, io.m.events)
        self.assertFalse(any(x.startswith(f'write:{OWNER:x}') for x in io.log))

    def test_descriptor_and_bounds_fail_before_launch(self):
        cases = [(OWNER, OWNER, 1, OWNER, host.SIZE),
                 (OWNER, OWNER, 0, OWNER+4, host.SIZE),
                 (OWNER, OWNER, 0, OWNER, host.SIZE-4),
                 (OWNER+64, OWNER+64, 0, OWNER+64, host.SIZE),
                 (POOL, POOL, 0, POOL, host.SIZE),
                 (WORKER, WORKER, 0, WORKER, host.SIZE),
                 (0x46400000, 0x46400000, 0, 0x46400000, host.SIZE)]
        for index, desc in enumerate(cases):
            with self.subTest(desc=desc):
                self.out = self.root/f'bad-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io(descriptor=desc)
                    with self.assertRaises(ValueError):
                        self.run_trial(io)
                    self.assertNotIn(base.CREATE, io.m.events)
                    self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_finite_budget_no_reactivation_or_fake_completion(self):
        io = self.io(run_worker=False)
        result = self.run_trial(io, budget=2)
        self.assertEqual(result['status'], 'budget-exhausted-retained')
        self.assertEqual(len(result['observations']), 3)  # admission plus budget
        self.assertNotIn('capture', result)
        self.assertEqual(io.m.events.count(base.ATTACH), 1)
        self.assertEqual((self.out/'output.bin').stat().st_size, host.OUTPUT_ROOM)

    def test_dormant_create_is_not_admitted_to_attach(self):
        io = self.io(task_start=True)
        with self.assertRaisesRegex(RuntimeError, 'dormant'):
            self.run_trial(io)
        self.assertNotIn(base.ATTACH, io.m.events)
        self.assertEqual(io.alloc_calls, 1)
        self.assertTrue(io.m.allocated)

    def test_every_execution_failure_retains_and_never_retries(self):
        labels = [name for phase in ('allocate', 'launch', 'observe-01', 'activate', 'observe-02')
                  for name in (phase+'-dcache', phase+'-icache', phase)]
        for index, label in enumerate(labels):
            with self.subTest(label=label):
                self.out = self.root/f'exec-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io(fail='after:'+label)
                    with self.assertRaisesRegex(RuntimeError, 'injected|MCAPS'):
                        self.run_trial(io)
                    self.assertLessEqual(io.alloc_calls, 1)
                    self.assertEqual(io.executions.count(label), 1 if io.fail.startswith('after:') else 0)
                    self.assertEqual(io.m.word(gf.ECHO_SLOT), gf.ECHO_STOCK)
                    self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())
                    with patch.object(host, 'Backend', side_effect=AssertionError('backend forbidden')):
                        with self.assertRaisesRegex(RuntimeError, 'pending'):
                            host.run(self.root/f'again-{index}', base.MAIN)

    def test_transfer_window_and_restore_failures_retain(self):
        failures = [f'write:{STAGE:x}:400', f'read:{STAGE:x}:400', 'window-grant',
                    f'write:{OWNER:x}:10000', f'write:{STAGE+0x1000:x}:3000',
                    f'read:{OWNER:x}:400', f'read:{OWNER+0x2000:x}:1000',
                    f'read:{OWNER+0x5000:x}:{host.OUTPUT_ROOM:x}', 'window-revoke', 'restore']
        for index, failure in enumerate(failures):
            with self.subTest(failure=failure):
                self.out = self.root/f'io-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io(fail=failure)
                    with self.assertRaisesRegex(RuntimeError, 'injected|MCAPS'):
                        self.run_trial(io)
                    self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())
                    self.assertLessEqual(io.alloc_calls, 1)
                    self.assertFalse(io.m.deleted or io.m.released)

    def test_existing_out_pending_and_bad_version_prevent_writes(self):
        self.out.mkdir()
        with patch.object(host, 'Backend', side_effect=AssertionError('backend forbidden')):
            with self.assertRaises(FileExistsError):
                host.run(self.out, base.MAIN)
        self.out.rmdir()
        io = self.io()
        io.version = 'model = w91c1\nrel version = 3.02.0.V90-other\n'
        with self.assertRaises(ValueError):
            self.run_trial(io)
        self.assertFalse(any(x.startswith('write:') for x in io.log))

    def test_source_mutation_argv_abi_and_readback_corruption(self):
        original = host.small_body

        def mutated(name, defines=()):
            code, syms = original(name, defines)
            if name == 'fpl_task_entry.S':
                b = bytearray(code)
                # Replace BLX r0 with BLX r1: argv/uninitialized argument is not
                # the checked entry. Must not accidentally pass the pipeline.
                needle = struct.pack('<I', 0xE12FFF30)
                at = b.index(needle)
                b[at:at+4] = struct.pack('<I', 0xE12FFF31)
                return bytes(b), syms
            return code, syms
        io = self.io()
        with patch.object(host, 'small_body', side_effect=mutated):
            with self.assertRaises((AssertionError, uc.UcError)):
                self.run_trial(io)
        self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_observation_errors_and_forged_identity_are_rejected(self):
        for index, (offset, value, message) in enumerate(
                ((0x34, 0xFFFFFFEE, 'task_rc=-18'), (0x38, 0xFFFFFFD6, 'flag_rc=-42'),
                 (0x3C, base.SYS+8, 'exinf'), (0x48, 16, 'dormant'),
                 (0, 0, 'sequence'), (0xE0, 15, 'evidence'))):
            with self.subTest(offset=offset):
                self.out = self.root/f'obs-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io()
                    original = io.read

                    def read(address, count):
                        raw = original(address, count)
                        if address == OWNER+host.OBS and count == 256:
                            raw = bytearray(raw)
                            struct.pack_into('<I', raw, offset, value)
                        return bytes(raw)
                    with patch.object(io, 'read', side_effect=read):
                        with self.assertRaisesRegex(RuntimeError, message):
                            self.run_trial(io)
                    self.assertNotIn(base.ATTACH, io.m.events)
                    self.assertTrue((self.out/'observe-01.bin').exists())

    def test_silent_transfer_and_static_code_corruption_are_checked(self):
        for index, (address, count) in enumerate(((STAGE, 1024), (OWNER, host.SIZE),
                                                  (STAGE+0x1000, 0x3000),
                                                  (OWNER+0x1000, 4096),
                                                  (OWNER+0x2000, 4096),
                                                  (OWNER+host.OWNER_INFO, 1024))):
            with self.subTest(address=address, count=count):
                self.out = self.root/f'corrupt-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io()
                    original = io.read

                    def read(a, n):
                        raw = bytearray(original(a, n))
                        if (a, n) == (address, count):
                            raw[0] ^= 1
                        return bytes(raw)
                    with patch.object(io, 'read', side_effect=read):
                        with self.assertRaises(RuntimeError):
                            self.run_trial(io)
                    self.assertNotIn(base.ATTACH, io.m.events)
                    self.assertFalse(io.m.deleted or io.m.released)

    def test_persistence_failure_cannot_execute_without_intent(self):
        io = self.io()
        original, failed = host.durable, False

        def durable(path, data, **kwargs):
            nonlocal failed
            if path.name == 'manifest.json':
                report = json.loads(data)
                if not failed and report['operations'] and report['operations'][-1]['operation'] == 'allocate':
                    failed = True
                    raise OSError('durable intent unavailable')
            return original(path, data, **kwargs)
        with patch.object(host, 'durable', side_effect=durable):
            with self.assertRaisesRegex(OSError, 'intent'):
                self.run_trial(io)
        self.assertEqual(io.alloc_calls, 0)
        self.assertEqual(io.m.word(gf.ECHO_SLOT), gf.ECHO_STOCK)
        self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_native_create_and_attach_assertions_retain_allocated_owner(self):
        for index, fault in enumerate(('allocation', 'flag_create', 'task_create', 'attach')):
            with self.subTest(fault=fault):
                self.out = self.root/f'assert-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io(**{fault: True})
                    with self.assertRaises(base.NativeAssertion):
                        self.run_trial(io)
                    report = json.loads((self.out/'manifest.json').read_text())
                    self.assertEqual(report['descriptor'], [OWNER, 0, OWNER, host.SIZE])
                    self.assertEqual(io.alloc_calls, 1)
                    self.assertEqual(io.m.word(gf.ECHO_SLOT), gf.ECHO_STOCK)
                    self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_native_allocator_address_mutation_and_duplicate_dispatch_guard(self):
        io = self.io()
        io.allocator.mu.mem_write(0xC001D7F4, struct.pack('<I', 0xE3A01000))
        with self.assertRaisesRegex(ValueError, 'descriptor mismatch'):
            self.run_trial(io)
        self.assertNotIn(base.CREATE, io.m.events)
        # Even an accidental second native dispatch of this same helper cannot
        # allocate again: its result's attempted state is already nonzero.
        io.allocator.call(STAGE)
        self.assertEqual(io.alloc_calls, 1)

    def test_caps_echo_and_lock_refuse_before_staging(self):
        for index, fault in enumerate(('caps', 'echo', 'windows', 'publication')):
            self.out = self.root/f'preflight-{index}'
            io = self.io()
            if fault == 'echo':
                io.m.word(gf.ECHO_SLOT, 123)
            elif fault == 'windows':
                io.windows = [(OWNER, host.SIZE, 1)]*8
            elif fault == 'publication':
                io.publication[0] += 4
            else:
                original = io.caps
                io.caps = lambda: dict(original(), pool_size=ROOM+1024)
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                self.run_trial(io)
            self.assertEqual(io.alloc_calls, 0)
            self.assertFalse(any(x.startswith('write:') for x in io.log))
        with gf.staging_lock():
            with patch.object(host, 'Backend', side_effect=AssertionError('backend forbidden')):
                with self.assertRaises(BlockingIOError):
                    host.run(self.root/'locked', base.MAIN)

    def test_midflight_publication_or_echo_owner_change_stops_without_rearm(self):
        for index, kind in enumerate(('publication', 'echo')):
            self.out = self.root/f'owner-change-{index}'
            with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                io = self.io()
                original = io.sh

                def sh(command, **kwargs):
                    reply = original(command, **kwargs)
                    if io.executions and io.executions[-1] == 'launch':
                        if kind == 'publication':
                            io.publication[2] += 4096
                        else:
                            io.m.word(gf.ECHO_SLOT, 0xC0123450)
                    return reply
                with patch.object(io, 'sh', side_effect=sh):
                    with self.assertRaisesRegex(RuntimeError, 'publication|echo owner'):
                        self.run_trial(io)
                self.assertNotIn(base.ATTACH, io.m.events)
                self.assertEqual(io.alloc_calls, 1)
                if kind == 'echo':
                    self.assertEqual(io.m.word(gf.ECHO_SLOT), 0xC0123450)
                self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())

    def test_optional_sleep_diagnostic_is_checked_against_both_raw_samples(self):
        result = self.run_trial(self.io(), sleep_reason=1)
        self.assertEqual(result['status'], 'completed-retained')
        self.assertTrue(result['observations'][-1]['sampled_sleep_diagnostic'])
        self.assertFalse(result['observations'][-1]['release_authorized'])

    def test_exact_git_hash_required_before_any_window_or_allocation(self):
        io = self.io()
        io.version = VERSION.replace(host.GIT_HASH, '0'*40)
        with self.assertRaisesRegex(ValueError, 'exact'):
            self.run_trial(io)
        self.assertEqual(io.alloc_calls, 0)
        self.assertNotIn('window-grant', io.log)

    def test_unknown_legacy_or_unreadable_resident_restores_windows_no_allocation(self):
        for index, kind in enumerate(('unknown', 'legacy', 'read-failure', 'short-read')):
            with self.subTest(kind=kind):
                self.out = self.root/f'resident-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io()
                    if kind == 'unknown':
                        io.m.m.mem_write(WORKER, b'\x00'*host.swap.SIZE)
                    elif kind == 'legacy':
                        io.m.m.mem_write(WORKER, host.swap.reviewed_body(False))
                    elif kind == 'read-failure':
                        io.fail = f'read:{WORKER:x}:{host.swap.SIZE:x}'
                    else:
                        original = io.read
                        io.read = lambda a, n: original(a, n)[:-4] if a == WORKER else original(a, n)
                    with self.assertRaisesRegex(RuntimeError, 'resident|injected'):
                        self.run_trial(io)
                    self.assertEqual(io.alloc_calls, 0)
                    self.assertEqual(io.windows, [(0, 0, 0)]*8)
                    self.assertNotIn('execute:allocate', io.log)

    def test_structured_pong_required_initially_and_after_revocation(self):
        cases = [(1, ''), (1, 'OK pong seq=91 proof=EMPTY'), (1, 'OK pong seq=91'),
                 (2, ''), (2, 'OK pong seq=92 proof=EMPTY'), (2, 'ERR timeout'),
                 (2, None)]
        for index, (phase, reply) in enumerate(cases):
            with self.subTest(phase=phase, reply=reply):
                self.out = self.root/f'pong-{index}'
                with patch.object(gf, 'LOCK_PATH', self.root/f'lock-{index}'):
                    io = self.io()
                    if reply is None:
                        io.fail = 'ping:2'
                    else:
                        io.ping_replies[phase-1] = reply
                    with self.assertRaisesRegex(RuntimeError, 'PONG|injected'):
                        self.run_trial(io)
                    self.assertEqual(io.alloc_calls, 0 if phase == 1 else 1)
                    self.assertEqual(io.windows, [(0, 0, 0)]*8)
                    self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())
                    report = json.loads((self.out/'manifest.json').read_text())
                    if phase == 2:
                        self.assertEqual(report['status'], 'final-pong-uncertain-retained')
                        self.assertEqual(io.m.capture_calls, 1)

    def test_swap_words_idle_and_stable_with_stale_inactive_address(self):
        io = self.io()
        io.m.word(POOL+0x1080, 0x50415753)
        with self.assertRaisesRegex(RuntimeError, 'swap'):
            self.run_trial(io)
        self.assertEqual(io.alloc_calls, 0)
        self.out = self.root/'idle-with-stale-address'
        io = self.io()
        io.m.word(POOL+0x10C0, STAGE)
        result = self.run_trial(io)
        self.assertEqual(result['swap_words'], [0, STAGE])

    def test_retained_marker_is_not_a_reconcilable_worker_handoff(self):
        self.run_trial(self.io())
        marker = gf.LOCK_PATH.with_suffix('.pending')
        original = marker.read_bytes()
        with self.assertRaisesRegex(ValueError, 'schema'):
            host.swap.parse_pending(original)
        with patch.object(gf, 'Backend', side_effect=AssertionError('must reject before transport')):
            with self.assertRaisesRegex(ValueError, 'schema'):
                host.swap.reconcile()
        self.assertEqual(marker.read_bytes(), original)

    def test_foreign_window_change_is_not_adopted_before_owned_revoke(self):
        io = self.io()
        original = io.read

        def read(address, count):
            data = original(address, count)
            if address == OWNER+0x5000:
                io.windows[1] = (0x48000000, 4096, 1)
            return data
        with patch.object(io, 'read', side_effect=read):
            with self.assertRaisesRegex(RuntimeError, 'foreign MCAPS'):
                self.run_trial(io)
        self.assertEqual(io.windows[0], (OWNER, host.SIZE, 3))
        self.assertEqual(io.windows[1], (0x48000000, 4096, 1))
        # Only the admission resident-read grant was restored. No foreign
        # snapshot was adopted to make the final owned-window revoke pass.
        self.assertEqual(io.log.count('window-revoke'), 1)
        self.assertEqual(io.pings, 1)
        self.assertTrue(gf.LOCK_PATH.with_suffix('.pending').exists())


if __name__ == '__main__':
    unittest.main()
