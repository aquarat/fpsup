"""Offline ARM/transport tests. Use ~/.local/share/fpsup-toolchain/bin on PATH."""
from contextlib import nullcontext
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar

import fpl_getfile as gf
import fpl_metadata_snapshot as snap

POOL, ROOM, WORKER = 0x45000000, 0x100000, 0x47000000
PUB = [POOL, ROOM, WORKER]
CAPS = dict(pool=POOL, pool_size=ROOM, xfer=16776192)
PLAN = gf.layout(CAPS, PUB, snap.RESULT_ROOM)
VERSION = 'model = w91c1\nrel version = 3.02.0.V90\n'
RAW = (0xFFFFFFFF, 0, 0x80000000)
NAME = b'\xff\xfeRAW\0' + bytes(range(26))


def emulate(code, settings=1, lens=1, name=NAME, changes=()):
    """Exact read/store oracle, including guard-dependent forbidden payloads.

    Changes are (trigger address, occurrence, destination, value); they model
    another firmware task, not writes performed by the diagnostic.
    """
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    m.mem_map(POOL, ROOM)
    pages = (0xC31F6000, 0xC31F7000, 0xC3465000, 0xC3477000)
    for page in pages:
        m.mem_map(page, 0x1000)
    stop, stack = 0x48000000, POOL+ROOM-0x100
    m.mem_map(stop, 0x1000)
    def put(at, value):
        m.mem_write(at, struct.pack('<I', value))
    put(snap.SETTINGS_GUARD, settings)
    put(snap.LENS_GUARD, lens)
    for at, val in zip((snap.WIDTH, snap.HEIGHT, snap.FORMAT), RAW):
        put(at, val)
    assert len(name) == 32
    m.mem_write(snap.NAME, name)
    put(snap.FOCAL, 0xFEDCBA98)
    firmware = {page: bytes(m.mem_read(page, 0x1000)) for page in pages}
    m.mem_write(PLAN.code, bytes(code))
    m.reg_write(ar.UC_ARM_REG_SP, stack)
    m.reg_write(ar.UC_ARM_REG_LR, stop)
    m.reg_write(ar.UC_ARM_REG_R0, 0xDEADBEEF)
    saved = {reg: 0x12340000+reg for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    for reg, value in saved.items():
        m.reg_write(reg, value)
    allowed = {(snap.SETTINGS_GUARD, 4), (snap.LENS_GUARD, 4)}
    if settings == 1:
        allowed.update((a, 4) for a in (snap.WIDTH, snap.HEIGHT, snap.FORMAT))
    if lens == 1:
        allowed.update((snap.NAME+i, 1) for i in range(32))
        allowed.add((snap.FOCAL, 4))
    reads, writes, events, injected, counts = [], [], [], [], {}
    def memory(mu, access, at, size, value, _):
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in (
                (PLAN.param, PLAN.param+16), (PLAN.buffer, PLAN.buffer+snap.RESULT_BYTES),
                (stack-32, stack))), f'forbidden store {at:x}'
            writes.append((at, size))
        else:
            assert (at, size) in allowed or stack-32 <= at and at+size <= stack, f'forbidden read {at:x}'
            reads.append((at, size))
            events.append(('read', at))
            counts[at] = counts.get(at, 0)+1
            for trigger, occurrence, destination, new in changes:
                if at == trigger and counts[at] == occurrence:
                    put(destination, new)
                    injected.append((destination, new))
    def execute(mu, at, size, _):
        assert PLAN.code <= at < PLAN.code+len(code), f'escaped code {at:x}'
        if bytes(mu.mem_read(at, 4)) == struct.pack('<I', 0xF57FF05F):
            events.append(('dmb', at))
    m.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    m.hook_add(uc.UC_HOOK_CODE, execute)
    m.emu_start(PLAN.code, stop, count=2000)
    assert m.reg_read(ar.UC_ARM_REG_PC) == stop, 'finite budget exceeded'
    assert m.reg_read(ar.UC_ARM_REG_SP) == stack
    assert m.reg_read(ar.UC_ARM_REG_R0) == 0
    for reg, value in saved.items():
        assert m.reg_read(reg) == value, 'callee-saved register changed'
    assert writes[-1] == (PLAN.param, 4), 'completion not last'
    for page, before in firmware.items():
        expected = bytearray(before)
        for at, value in injected:
            if page <= at < page+0x1000:
                struct.pack_into('<I', expected, at-page, value)
        assert bytes(m.mem_read(page, 0x1000)) == expected, 'firmware changed'
    return (bytes(m.mem_read(PLAN.param, gf.PARAM_ROOM)),
            bytes(m.mem_read(PLAN.buffer, snap.RESULT_ROOM)), reads, events)


class Payload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = snap.code_for(PLAN)

    def test_raw_values_abi_bounds_and_order(self):
        p, r, reads, events = emulate(self.code)
        report = snap.decode(p, r)
        self.assertEqual(struct.unpack_from('<4I', p), (snap.MAGIC, 1, 3, 0x60))
        group = report['settings_snapshot']
        self.assertEqual([group['payload'][k]['raw_u32'] for k in ('width', 'height', 'format')], list(RAW))
        self.assertEqual([group['payload'][k]['address'] for k in ('width', 'height', 'format')],
                         [snap.WIDTH, snap.HEIGHT, snap.FORMAT])
        self.assertFalse(report['calibrated'])
        self.assertEqual(report['units'], 'unknown')
        self.assertEqual(report['consistency'], 'unverified')
        self.assertEqual(report['lens_snapshot']['payload']['focal']['raw_u32'], 0xFEDCBA98)
        self.assertEqual(reads.count((snap.SETTINGS_GUARD, 4)), 2)
        self.assertEqual(reads.count((snap.LENS_GUARD, 4)), 2)
        for address in (snap.WIDTH, snap.HEIGHT, snap.FORMAT, snap.FOCAL):
            self.assertEqual(reads.count((address, 4)), 1)
        for i in range(32):
            self.assertEqual(reads.count((snap.NAME+i, 1)), 1)
        for guard, first, last in ((snap.SETTINGS_GUARD, snap.WIDTH, snap.FORMAT),
                                   (snap.LENS_GUARD, snap.NAME, snap.FOCAL)):
            before = events.index(('read', guard))
            after = len(events)-1-events[::-1].index(('read', guard))
            self.assertEqual(events[before+1][0], 'dmb')
            self.assertEqual(events[after-1][0], 'dmb')
            self.assertLess(before, events.index(('read', first)))
            self.assertLess(events.index(('read', last)), after)

    def test_all_guard_classes_independently(self):
        for settings in (0, 1, 2, 3, 0x80000001, 0xFFFFFFFF):
            for lens in (0, 1, 2, 3, 0x80000001, 0xFFFFFFFF):
                with self.subTest(settings=settings, lens=lens):
                    p, r, reads, _ = emulate(self.code, settings=settings, lens=lens)
                    report = snap.decode(p, r)
                    for key, value, address in (('settings_snapshot', settings, snap.SETTINGS_GUARD),
                                                ('lens_snapshot', lens, snap.LENS_GUARD)):
                        group = report[key]
                        self.assertEqual(group['status'], 'constructed_cache_observed' if value == 1
                                         else 'not_ready' if value == 0 else 'initializing_or_unknown')
                        self.assertEqual('payload' in group, value == 1)
                        self.assertEqual('guard_after' in group, value == 1)
                        self.assertEqual(reads.count((address, 4)), 2 if value == 1 else 1)

    def test_guard_change_discards_payload_retains_raw(self):
        for guard, field, key in ((snap.SETTINGS_GUARD, snap.WIDTH, 'settings_snapshot'),
                                  (snap.LENS_GUARD, snap.NAME, 'lens_snapshot')):
            for value in (0, 2, 3, 0xFFFFFFFF):
                p, r, _, _ = emulate(self.code, changes=[(field, 1, guard, value)])
                report = snap.decode(p, r)
                self.assertEqual(report[key]['status'], 'guard_changed')
                self.assertEqual(report[key]['guard_after'], value)
                self.assertNotIn('payload', report[key])
                self.assertEqual(report['raw_result_hex'], r[:0x60].hex())
                self.assertTrue(any(r[0x10:0x1c] if key == 'settings_snapshot' else r[0x30:0x54]))

    def test_names_binary_empty_embedded_nul_and_unterminated(self):
        for name, length, nul in ((NAME, 5, True), (bytes(32), 0, True), (b' '*32, 32, False),
                                  (b'\xff'*31+b'\0', 31, True), (b'\xff'*32, 32, False)):
            p, r, _, _ = emulate(self.code, name=name)
            value = snap.decode(p, r)['lens_snapshot']['payload']['name']
            self.assertEqual((value['raw_hex'], value['byte_length'], value['nul_seen'], value['limit_reached']),
                             (name.hex(), length, nul, not nul))

    def test_decoder_integrity_and_masked_skipped_payload_refusal(self):
        p, r, _, _ = emulate(self.code)
        for at, value in ((0, 0), (4, 2), (8, 0), (8, 4), (12, 0), (16, 1)):
            bad = bytearray(p)
            struct.pack_into('<I', bad, at, value)
            with self.assertRaises(RuntimeError):
                snap.decode(bad, r)
        for at, value in ((0, 0), (8, 0), (12, 1), (0x1c, 1), (0x20, 3),
                          (0x28, 0), (0x2c, 1), (0x54, 1), (0x60, 1)):
            bad = bytearray(r)
            struct.pack_into('<I', bad, at, value)
            with self.assertRaises(RuntimeError):
                snap.decode(p, bad)
        p0, r0, _, _ = emulate(self.code, settings=0, lens=3)
        for at in (4, 8, 0x10, 0x24, 0x28, 0x30, 0x50):
            bad = bytearray(r0)
            struct.pack_into('<I', bad, at, 1)
            with self.assertRaises(RuntimeError):
                snap.decode(p0, bad)
        for pp, rr in ((p[:-1], r), (p, r[:-1])):
            with self.assertRaises(RuntimeError):
                snap.decode(pp, rr)

    def test_mutation_guard_bypass_is_detected(self):
        code = bytearray(self.code)
        compare = struct.pack('<I', 0xE3500001)  # cmp r0,#1
        self.assertEqual(code.count(compare), 2)
        at = code.index(compare)+4
        code[at:at+4] = struct.pack('<I', 0xE320F000)  # remove conditional branch
        with self.assertRaisesRegex(AssertionError, 'forbidden read'):
            emulate(code, settings=3)

    def test_mutation_name_overrun_is_detected(self):
        code = bytearray(self.code)
        old = struct.pack('<I', 0xE3510020)  # cmp r1,#32
        self.assertEqual(code.count(old), 1)
        at = code.index(old)
        code[at:at+4] = struct.pack('<I', 0xE3510021)
        with self.assertRaisesRegex(AssertionError, 'forbidden read'):
            emulate(code)

    def test_mutation_firmware_store_is_detected(self):
        code = bytearray(self.code)
        at = code.index(struct.pack('<I', 0xE5980000))  # ldr r0,[r8]
        code[at:at+4] = struct.pack('<I', 0xE5880000)  # str r0,[r8]
        with self.assertRaisesRegex(AssertionError, 'forbidden store'):
            emulate(code)


class Fake:
    def __init__(self, fault=None):
        self.fault, self.slot = fault, gf.ECHO_STOCK
        self.memory, self.events = {}, []
        self.executed = False

    def sh(self, line, **kwargs):
        assert kwargs.get('retries') == 0
        if line == 'version':
            return VERSION+'model=w91c1\n' if self.fault == 'version' else VERSION
        assert line == 'echo'
        self.events.append(('echo', self.slot))
        if self.fault == self.slot:
            raise OSError('uncertain reply')
        if self.slot == PLAN.code:
            self.executed = True
            p, r, _, _ = emulate(self.memory[PLAN.code])
            self.memory[PLAN.param], self.memory[PLAN.buffer] = p, r
        return ''

    def words(self, at, count=1):
        if at == gf.PUBLICATION:
            return [POOL, ROOM, 0] if (self.fault == 'pub' or self.executed and self.fault == 'postpub') else list(PUB)
        assert at == gf.ECHO_SLOT
        return [0] if self.fault == 'owner' else [self.slot]

    def caps(self):
        return None if self.fault == 'caps' else CAPS | ({'pool': POOL+4} if self.fault == 'caps_mismatch' else {})

    def write(self, at, data):
        self.events.append(('write', at))
        self.memory[at] = data

    def read(self, at, count):
        data = self.memory[at][:count]
        if self.fault == 'upload' or self.executed and self.fault == 'short':
            return data[:-1]
        if self.executed:
            if self.fault == 'magic' and at == PLAN.param or self.fault == 'code' and at == PLAN.code:
                return bytes(4)+data[4:]
            if self.fault == 'guard' and at == PLAN.buffer or self.fault == 'unused' and at == PLAN.fobj:
                return data[:-1]+b'\1'
        return data

    def set_word(self, at, value):
        assert at == gf.ECHO_SLOT
        self.events.append(('slot', value))
        if self.fault != ('slot', value):
            self.slot = value


class Host(unittest.TestCase):
    def run_fake(self, fake):
        with patch.object(gf, 'staging_lock', nullcontext), \
             patch.object(gf, 'Backend', side_effect=AssertionError('live forbidden')):
            return snap.snapshot(fake)

    def test_real_arm_through_host_and_clock_bounds(self):
        fake = Fake()
        with patch.object(snap.time, 'time_ns', side_effect=[100, 90]), \
             patch.object(snap.time, 'monotonic_ns', side_effect=[10, 20]):
            report, _, _ = self.run_fake(fake)
        self.assertEqual(fake.slot, gf.ECHO_STOCK)
        self.assertEqual([v for k, v in fake.events if k == 'echo'], [gf.DCACHE, gf.ICACHE, PLAN.code])
        bounds = report['host_probe_echo_bounds']
        self.assertEqual([bounds[k] for k in ('utc_before_ns', 'utc_after_ns', 'monotonic_before_ns', 'monotonic_after_ns')], [100, 90, 10, 20])

    def test_failures_restore_and_do_not_retry_probe(self):
        for fault in ('version', 'pub', 'owner', 'caps', 'caps_mismatch', 'upload', 'postpub',
                      'short', 'magic', 'code', 'guard', 'unused', gf.DCACHE, gf.ICACHE,
                      PLAN.code, ('slot', gf.ICACHE)):
            with self.subTest(fault=fault):
                fake = Fake(fault)
                with self.assertRaises((RuntimeError, ValueError, OSError)):
                    self.run_fake(fake)
                self.assertEqual(fake.slot, gf.ECHO_STOCK)
                echoes = [v for k, v in fake.events if k == 'echo']
                self.assertLessEqual(echoes.count(PLAN.code), 1)
                if fault in (gf.DCACHE, gf.ICACHE):
                    self.assertNotIn(PLAN.code, echoes)
                if fault in ('version', 'pub', 'owner', 'caps', 'caps_mismatch'):
                    self.assertFalse(fake.events)

    def test_restore_failure_never_reports_success(self):
        with self.assertRaisesRegex(RuntimeError, 'echo slot'):
            self.run_fake(Fake(('slot', gf.ECHO_STOCK)))

    def test_lock_and_pending_before_backend(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gf, 'LOCK_PATH', Path(tmp)/'lock'), \
             patch.object(gf, 'Backend', side_effect=AssertionError('live forbidden')):
            with gf.staging_lock():
                with self.assertRaises(BlockingIOError):
                    snap.snapshot()
            gf.LOCK_PATH.with_suffix('.pending').write_text('pending')
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                snap.snapshot()

    def test_fresh_output_and_import_help_offline(self):
        capture = self.run_fake(Fake())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'new'
            with patch.object(snap, 'snapshot', return_value=capture):
                self.assertEqual(snap.main(['--out', str(out)]), 0)
            self.assertEqual((out/'observations.bin').stat().st_size, snap.RESULT_ROOM)
            with patch.object(snap, 'snapshot', side_effect=AssertionError('live forbidden')):
                with self.assertRaises(FileExistsError):
                    snap.main(['--out', str(out)])
        command = ('import socket; socket.socket=lambda *a,**k: (_ for _ in ()).throw('
                   'AssertionError("network forbidden")); import fpl_metadata_snapshot as s; s.main(["--help"])')
        p = subprocess.run([sys.executable, '-B', '-c', command], cwd=gf.HERE, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--out', p.stdout)


if __name__ == '__main__':
    unittest.main()
