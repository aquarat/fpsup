"""Offline real ARM and fake-transport tests; never instantiate live Backend.

PATH=/path/to/arm-toolchain/bin:$PATH \
  python3 -B -m unittest test_fpl_take_snapshot
Optional FPSUP_FPL_MAIN selects official-image evidence input (full hash checked).
"""
from contextlib import nullcontext
import hashlib
import os
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
import fpl_take_snapshot as snap

POOL, ROOM, WORKER = 0x45000000, 0x100000, 0x47000000
PUB = [POOL, ROOM, WORKER]
CAPS = dict(pool=POOL, pool_size=ROOM, xfer=16776192)
PLAN = gf.layout(CAPS, PUB, snap.RESULT_ROOM)
VERSION = 'model = w91c1\nrel version = 3.02.0.V90\n'
DEFAULT = dict(volume=5, vtable=snap.VTABLE, letter=65, reel=1,
               current_take=4, saved_take=9, gate44=0, gate45=1)
OFFSETS = (0, 4, 8, 0xC, 0x10, 0x2C, 0x44, 0x45)
SIZES = (4, 4, 1, 4, 4, 4, 1, 1)


def emulate(code, pointer=snap.CONTEXT, reset=0, ssd=None, sd=None, changes=()):
    """Changes: (trigger_address, read_number, destination, value, width).

    Read oracle permits only the audited fields, owned output and caller stack.
    Thus an invalid pointer must not merely avoid faults; it must not be read.
    """
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    m.mem_map(POOL, ROOM)
    pages = (0xC3074000, 0xC3075000, 0xC3439000)
    for page in pages:
        m.mem_map(page, 0x1000)
    stop, stack = 0x48000000, POOL+ROOM-0x100
    m.mem_map(stop, 0x1000)
    def put(at, value, size=4):
        m.mem_write(at, value.to_bytes(size, 'little'))
    put(snap.CONTEXT_PUB, pointer)
    put(snap.CONTEXT+0x5D5, reset, 1)
    put(snap.CONTEXT+0x5D6, 65, 1)
    put(snap.CONTEXT+0x5D8, 1, 2)
    allowed = {(snap.CONTEXT_PUB, 4), (snap.CONTEXT+0x5D5, 1),
               (snap.CONTEXT+0x5D6, 1), (snap.CONTEXT+0x5D8, 2)}
    for base, values in ((snap.SSD, DEFAULT | (ssd or {})),
                         (snap.SD, DEFAULT | {'volume': 1} | (sd or {}))):
        for name, off, size in zip(snap.FIELDS, OFFSETS, SIZES):
            put(base+off, values[name], size)
            allowed.add((base+off, size))
    firmware = {page: bytes(m.mem_read(page, 0x1000)) for page in pages}
    m.mem_write(PLAN.code, bytes(code))
    m.reg_write(ar.UC_ARM_REG_SP, stack)
    m.reg_write(ar.UC_ARM_REG_LR, stop)
    m.reg_write(ar.UC_ARM_REG_R0, 0xDEADBEEF)  # dispatcher input ignored
    saved = {reg: 0x12340000+reg for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    for reg, value in saved.items():
        m.reg_write(reg, value)
    reads, writes, injected, counts = [], [], [], {}
    def memory(mu, access, at, size, value, _):
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in (
                (PLAN.param, PLAN.param+16), (PLAN.buffer, PLAN.buffer+snap.RESULT_BYTES),
                (stack-32, stack))), f'forbidden store {at:x}'
            writes.append((at, size))
        else:
            assert ((at, size) in allowed or PLAN.buffer <= at < PLAN.buffer+snap.RESULT_BYTES
                    or stack-32 <= at < stack), f'forbidden read {at:x}'
            reads.append((at, size))
            counts[at] = counts.get(at, 0)+1
            for trigger, occurrence, destination, new, width in changes:
                if at == trigger and counts[at] == occurrence:
                    put(destination, new, width)
                    injected.append((destination, new, width))
    def execute(mu, at, size, _):
        assert PLAN.code <= at < PLAN.code+len(code), f'escaped code {at:x}'
    m.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    m.hook_add(uc.UC_HOOK_CODE, execute)
    m.emu_start(PLAN.code, stop, count=3000)
    assert m.reg_read(ar.UC_ARM_REG_PC) == stop, 'finite instruction budget exceeded'
    assert m.reg_read(ar.UC_ARM_REG_SP) == stack
    for reg, value in saved.items():
        assert m.reg_read(reg) == value, 'callee-saved register changed'
    assert writes[-1] == (PLAN.param, 4), 'completion was not last store'
    for page, before in firmware.items():
        expected = bytearray(before)
        for address, value, size in injected:
            if page <= address < page+0x1000:
                expected[address-page:address-page+size] = value.to_bytes(size, 'little')
        assert bytes(m.mem_read(page, 0x1000)) == expected, 'firmware changed'
    return (bytes(m.mem_read(PLAN.param, gf.PARAM_ROOM)),
            bytes(m.mem_read(PLAN.buffer, snap.RESULT_ROOM)), reads)


class Payload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = snap.code_for(PLAN)

    def capture(self, **kwargs):
        p, r, reads = emulate(self.code, **kwargs)
        return snap.decode(p, r), reads

    def test_normal_raw_fields_candidates_and_abi(self):
        report, reads = self.capture()
        self.assertEqual(report['changed_flags'], 0)
        self.assertEqual(report['candidates']['ssd']['number'], 10)
        self.assertEqual(report['candidates']['sd']['number'], 10)
        for frame in report['observations']:
            self.assertEqual({k: frame['ssd'][k] for k in snap.FIELDS}, DEFAULT)
            self.assertTrue(frame['sd']['volume_matches'])
        for off, size in zip(OFFSETS, SIZES):
            self.assertEqual(reads.count((snap.SSD+off, size)), 2)
            self.assertEqual(reads.count((snap.SD+off, size)), 2)
        self.assertEqual(reads.count((snap.CONTEXT_PUB, 4)), 4)

    def test_null_and_unknown_context_never_dereferenced(self):
        for ptr in (0, snap.CONTEXT+1, snap.CONTEXT+4, snap.CONTEXT-4,
                    snap.CONTEXT_END-4, 0xC3075000, 0x45001000, 0xFFFFFFFC, 0x1000):
            with self.subTest(ptr=hex(ptr)):
                report, reads = self.capture(pointer=ptr)
                self.assertFalse(any(snap.CONTEXT <= a < snap.CONTEXT_END for a, _ in reads))
                self.assertIsNone(report['candidates']['ssd']['number'])
                self.assertEqual(report['observations'][0]['context']['status'],
                                 'unavailable_null' if ptr == 0 else 'unknown_pointer_refused')

    def test_volume_and_vtable_are_independently_validated(self):
        for fields, v_ok, t_ok in (({'volume': 0}, False, True), ({'vtable': 0}, True, False),
                                  ({'volume': 1}, False, True), ({'vtable': snap.VTABLE+4}, True, False)):
            report, _ = self.capture(ssd=fields)
            manager = report['observations'][0]['ssd']
            self.assertEqual((manager['volume_matches'], manager['vtable_matches']), (v_ok, t_ok))
            self.assertIsNone(report['candidates']['ssd']['number'])
            self.assertEqual(report['candidates']['sd']['number'], 10)

    def test_invalid_fields_and_readiness_gates(self):
        for fields in ({'current_take': 0xFFFFFFFF}, {'saved_take': 0x80000000},
                       {'current_take': 999}, {'saved_take': 999}, {'reel': 0}, {'reel': 1000},
                       {'letter': 64}, {'letter': 91}, {'letter': 66}, {'reel': 2},
                       {'gate44': 1}, {'gate45': 0}, {'gate45': 2}):
            with self.subTest(fields=fields):
                report, _ = self.capture(ssd=fields)
                self.assertIsNone(report['candidates']['ssd']['number'])

    def test_reset_and_candidate_boundaries(self):
        for reset, fields, candidate in ((1, {}, 5), (2, {}, 5),
                                         (0, {'current_take': 998}, 999),
                                         (1, {'current_take': 999}, None),
                                         (0, {'current_take': 0, 'saved_take': 0}, 1)):
            report, _ = self.capture(reset=reset, ssd=fields)
            self.assertEqual(report['candidates']['ssd']['number'], candidate)

    def test_tuple_context_and_publication_changes(self):
        cases = [((snap.SSD, 2, snap.SSD+0x10, 5, 4), 1),
                 ((snap.SD, 2, snap.SD+0x45, 0, 1), 2),
                 ((snap.CONTEXT+0x5D5, 2, snap.CONTEXT+0x5D5, 1, 1), 4),
                 ((snap.SSD, 1, snap.CONTEXT_PUB, 0xDEADBEEF, 4), 12),
                 ((snap.SSD, 1, snap.CONTEXT_PUB, 0, 4), 12)]
        for change, flags in cases:
            with self.subTest(change=change):
                report, reads = self.capture(changes=[change])
                self.assertEqual(report['changed_flags'], flags)
                self.assertTrue(all(c['number'] is None for c in report['candidates'].values()))
                self.assertNotIn((0xDEADBEEF, 1), reads)

    def test_decoder_rejects_inconsistent_extent_flags_and_fields(self):
        p, r, _ = emulate(self.code)
        for at, value in ((0, 0), (4, 2), (8, 1), (12, 0), (16, 1)):
            changed = bytearray(p)
            struct.pack_into('<I', changed, at, value)
            with self.assertRaises(RuntimeError):
                snap.decode(changed, r)
        for at, value in ((0, 0), (8, 2), (12, 256), (0x14, 65536),
                          (0x18, 1), (0x28, 256), (snap.RESULT_BYTES, 1)):
            changed = bytearray(r)
            struct.pack_into('<I', changed, at, value)
            with self.assertRaises(RuntimeError):
                snap.decode(p, changed)
        with self.assertRaises(RuntimeError):
            snap.decode(p[:-1], r)

    def test_mutation_wrong_field_is_detected(self):
        code = bytearray(self.code)
        old = struct.pack('<I', 0xE598002C)  # ldr r0,[r8,#2c]
        self.assertEqual(code.count(old), 1)
        at = code.index(old)
        code[at:at+4] = struct.pack('<I', 0xE5980010)
        p, r, _ = emulate(code)
        report = snap.decode(p, r)
        self.assertNotEqual(report['candidates']['ssd']['number'], 10)
        self.assertNotEqual(report['observations'][0]['ssd']['saved_take'], DEFAULT['saved_take'])

    def test_mutation_context_identity_guard_is_detected(self):
        # cmp r8,r0; bne context_done -> bypass identity check. An aligned
        # neighbor still passes coarse bounds but MUST NOT be dereferenced.
        old = struct.pack('<I', 0xE1580000)
        self.assertEqual(self.code.count(old), 2)  # lower bound and exact identity
        at = self.code.rindex(old)+4
        code = bytearray(self.code)
        code[at:at+4] = struct.pack('<I', 0xE320F000)
        with self.assertRaisesRegex(AssertionError, 'forbidden read'):
            emulate(bytes(code), pointer=snap.CONTEXT+4)

    def test_official_context_and_mmu_evidence(self):
        path = Path(os.environ.get('FPSUP_FPL_MAIN', str(Path.home()/'.local/share/fpsup/firmware/FPL_V302/MAIN.bin')))
        if not path.exists():
            self.skipTest('official fp L MAIN absent; firmware evidence not checked')
        data = path.read_bytes()
        self.assertEqual(len(data), 49310208)
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9')
        # Actual materialization, init guard extent, constructor publication,
        # owner/getter chain and fallback MMU record. No guessed generic range.
        for at, word in {0x21A24: 0xE3044BA8, 0x21A28: 0xE34C4307,
                         0x21A30: 0xE30005E4, 0x21A90: 0xEBFFFFE2,
                         0x21A98: 0xE5841058, 0x21A9C: 0xE5941058,
                         0x21AA0: 0xE584105C, 0x21B24: 0xE3054194,
                         0x21B28: 0xE34C4307, 0x21B64: 0xE59C105C}.items():
            self.assertEqual(struct.unpack_from('<I', data, at)[0], word)
        self.assertEqual(struct.unpack_from('<5I', data, 0x723AB4),
                         (0xC0000000, 0x400, 3, 1, 0x00400000))
        self.assertLessEqual(snap.CONTEXT+0x5DA, snap.CONTEXT_END)


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
            p, r, _ = emulate(self.memory[PLAN.code])
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
                   'AssertionError("network forbidden")); import fpl_take_snapshot as s; s.main(["--help"])')
        p = subprocess.run([sys.executable, '-B', '-c', command], cwd=gf.HERE, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--out', p.stdout)


if __name__ == '__main__':
    unittest.main()
