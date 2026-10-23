"""Offline only: real ARM payload in Unicorn and injectable host transport.

Run with durable clang on PATH:
  PATH=/path/to/arm-toolchain/bin:$PATH \
    python3 -B -m unittest test_fpl_imu_snapshot
No live Backend is instantiated by these tests.
"""
from contextlib import nullcontext
import hashlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import unicorn as uc
from unicorn import arm_const as ar

import fpl_imu_snapshot as snap
import fpl_getfile as gf

POOL, ROOM, WORKER = 0x45000000, 0x100000, 0x47000000
PUB = [POOL, ROOM, WORKER]
CAPS = dict(pool=POOL, pool_size=ROOM, xfer=16776192)
PLAN = gf.layout(CAPS, PUB, snap.RESULT_ROOM)
P, R, GLOBAL, ACCEL = 0x2E006004, 0x2E00644C, 0xC31E23CC, 0xC37772F4
VERSION = 'model       = w91c1\nrel version = 3.02.0.V90\n'


def emulate(code, descriptor=P, ring=R, head=None, change=None, change_on=R+0x100):
    """Read/write/fetch oracle: no firmware writes, no calls outside payload."""
    machine = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    machine.mem_map(POOL, ROOM)
    machine.mem_map(0x2E000000, 0x10000)
    machine.mem_map(GLOBAL & ~0xFFF, 0x1000)
    machine.mem_map(ACCEL & ~0xFFF, 0x1000)
    stop = 0x48000000
    machine.mem_map(stop, 0x1000)
    def word(at, value):
        machine.mem_write(at, struct.pack('<I', value))
    word(GLOBAL, descriptor)
    word(P+0x60, ring)
    word(P+0x64, 0x87654321)
    word(P+0x68, 0x01234567)
    head = R+8 if head is None else head
    expected = struct.pack('<I', head) + b''.join(
        struct.pack('<hhhh', i-300, 300-i, 0, -i) for i in range(600))
    machine.mem_write(R, expected)
    machine.mem_write(ACCEL, struct.pack('<hhh', -32768, -1, 32767))
    machine.mem_write(PLAN.code, code)
    stack = POOL+ROOM-0x100
    machine.reg_write(ar.UC_ARM_REG_SP, stack)
    machine.reg_write(ar.UC_ARM_REG_LR, stop)
    machine.reg_write(ar.UC_ARM_REG_R0, 0xBAD00000)  # dispatcher args ignored
    saved = {reg: 0x12340000+reg for reg in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    for reg, value in saved.items():
        machine.reg_write(reg, value)
    firmware = [(0x2E000000, 0x10000), (GLOBAL & ~0xFFF, 0x1000), (ACCEL & ~0xFFF, 0x1000)]
    before = {at: bytes(machine.mem_read(at, size)) for at, size in firmware}
    reads, writes = [], []
    injected = []
    def memory(mu, access, at, size, value, unused):
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in [
                (PLAN.param, PLAN.param+64), (PLAN.buffer, PLAN.buffer+snap.RING_BYTES),
                (stack-32, stack)]), f'firmware/out-of-bounds write {at:x}'
            writes.append((at, size))
        else:
            reads.append((at, size))
            if change and not injected and at == change_on:
                address, new = change
                word(address, new)
                injected.append(change)
    def execution(mu, at, size, unused):
        assert PLAN.code <= at < PLAN.code+len(code), f'escaped payload {at:x}'
    machine.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    machine.hook_add(uc.UC_HOOK_CODE, execution)
    machine.emu_start(PLAN.code, stop, count=10000)
    assert machine.reg_read(ar.UC_ARM_REG_PC) == stop, 'did not return within finite budget'
    assert machine.reg_read(ar.UC_ARM_REG_SP) == stack
    for reg, value in saved.items():
        assert machine.reg_read(reg) == value, 'callee-saved register changed'
    for at, size in firmware:
        wanted = bytearray(before[at])
        for address, value in injected:
            if at <= address < at+size:
                struct.pack_into('<I', wanted, address-at, value)
        assert machine.mem_read(at, size) == wanted, 'firmware memory changed'
    assert writes[-1] == (PLAN.param, 4), 'completion magic was not final write'
    param = bytes(machine.mem_read(PLAN.param, gf.PARAM_ROOM))
    result = bytes(machine.mem_read(PLAN.buffer, snap.RESULT_ROOM))
    return param, result, reads, expected


class Payload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = snap.code_for(PLAN)

    def run_case(self, status, **kwargs):
        p, r, reads, expected = emulate(self.code, **kwargs)
        report = snap.decode(p, r)
        self.assertEqual(report['status_code'], status)
        return report, r, reads, expected

    def test_normal_complete_copy_and_abi(self):
        report, result, reads, expected = self.run_case(1)
        self.assertEqual(result[:snap.RING_BYTES], expected)
        self.assertEqual(report['last_completed_index_before'], 0)
        self.assertEqual(report['accel_raw_i16'], [-32768, -1, 32767])
        self.assertEqual(report['descriptor_64_uninterpreted'], 0x87654321)
        self.assertEqual(report['descriptor_68_uninterpreted'], 0x01234567)
        self.assertEqual(len(report['records_storage_order']), 600)
        self.assertEqual(report['records_storage_order'][-1], [299, -299, 0, -599])

    def test_last_head_boundary(self):
        report, _, _, _ = self.run_case(1, head=R+0x12C0)
        self.assertEqual(report['last_completed_index_before'], 599)
        self.assertEqual(report['next_index_before'], 0)

    def test_zero_descriptor_no_dereference(self):
        report, result, reads, _ = self.run_case(3, descriptor=0)
        self.assertFalse(any(0x2E000000 <= a < 0x2E010000 for a, _ in reads))
        self.assertEqual(result, bytes(snap.RESULT_ROOM))

    def test_invalid_descriptor_alignment_extent_and_identity(self):
        for pointer in (P+1, P+4, 0x2E006000, 0x2E00770C, 0x2E1FFFFC, 0xFFFFFFFC):
            with self.subTest(pointer=hex(pointer)):
                _, _, reads, _ = self.run_case(4, descriptor=pointer)
                self.assertFalse(any(0x2E000000 <= a < 0x2E010000 for a, _ in reads))

    def test_invalid_ring_no_data_dereference(self):
        for pointer in (0, R+1, R+4, P, 0x2E00770C, 0x2E1FFFFC, 0xFFFFFFFC):
            with self.subTest(pointer=hex(pointer)):
                _, result, reads, _ = self.run_case(5, ring=pointer)
                self.assertFalse(any(R <= a < R+snap.RING_BYTES for a, _ in reads))
                self.assertEqual(result, bytes(snap.RESULT_ROOM))

    def test_invalid_heads_including_zero(self):
        for head in (0, R, R+4, R+9, R+0x12C4, 0xFFFFFFFF):
            with self.subTest(head=hex(head)):
                report, result, _, _ = self.run_case(6, head=head)
                self.assertEqual(report['copied_bytes'], 0)
                self.assertEqual(result, bytes(snap.RESULT_ROOM))

    def test_changes_detected_without_dereferencing_new_pointer(self):
        for address, value in ((GLOBAL, 0xDEADBEEF), (GLOBAL, 0),
                               (P+0x60, 0xDEADBEEF), (P+0x60, 0), (R, R+16)):
            with self.subTest(address=hex(address), value=hex(value)):
                report, _, reads, _ = self.run_case(2, change=(address, value))
                self.assertEqual(report['copied_bytes'], snap.RING_BYTES)
                self.assertFalse(any(a == 0xDEADBEEF for a, _ in reads))

    def test_invalid_end_head(self):
        self.run_case(6, change=(R, 0))

    def test_real_code_mutation_copy_stride_detected(self):
        code = bytearray(self.code)
        old = struct.pack('<I', 0xE4901004)  # ldr r1,[r0],#4
        self.assertEqual(code.count(old), 1)
        offset = code.index(old)
        code[offset:offset+4] = struct.pack('<I', 0xE4901000)
        _, result, _, expected = emulate(bytes(code))
        with self.assertRaises(AssertionError):
            self.assertEqual(result[:snap.RING_BYTES], expected)


class Fake:
    def __init__(self, fault=None):
        self.fault, self.slot = fault, gf.ECHO_STOCK
        self.events, self.memory = [], {}
        self.executed = False

    def sh(self, line, **kwargs):
        assert kwargs.get('retries') == 0
        if line == 'version':
            return 'model=w91c1\nrel version=3.02.0.V90-extra\n' if self.fault == 'version' else VERSION
        assert line == 'echo'
        self.events.append(('echo', self.slot))
        if self.fault == self.slot:
            raise OSError('uncertain execution reply')
        if self.slot == PLAN.code:
            self.executed = True
            param, result, _, _ = emulate(self.memory[PLAN.code])
            self.memory[PLAN.param], self.memory[PLAN.buffer] = param, result
        return ''

    def words(self, address, count=1):
        if address == gf.PUBLICATION:
            if self.fault == 'publication' or (self.fault == 'postpub' and self.executed):
                return [POOL, ROOM, 0]
            return list(PUB)
        assert address == gf.ECHO_SLOT
        return [0] if self.fault == 'owner' else [self.slot]

    def caps(self):
        return None if self.fault == 'caps' else CAPS

    def set_word(self, address, value):
        assert address == gf.ECHO_SLOT
        self.events.append(('slot', value))
        if self.fault != ('slot', value):
            self.slot = value

    def write(self, address, data):
        self.events.append(('write', address))
        self.memory[address] = data

    def read(self, address, count):
        data = self.memory[address][:count]
        if self.fault == 'upload' or (self.executed and self.fault == 'short'):
            return data[:-1]
        if self.executed:
            if self.fault == 'magic' and address == PLAN.param:
                return bytes(4)+data[4:]
            if self.fault == 'code' and address == PLAN.code:
                return bytes(4)+data[4:]
            if self.fault == 'guard' and address == PLAN.buffer:
                return data[:-1]+b'\x01'
        return data


class Host(unittest.TestCase):
    def run_fake(self, fake, records=600):
        with patch.object(gf, 'staging_lock', nullcontext), \
             patch.object(gf, 'Backend', side_effect=AssertionError('live backend forbidden')):
            return snap.snapshot(fake, records=records)

    def test_real_code_through_fake_transport(self):
        fake = Fake()
        report, param, result = self.run_fake(fake)
        self.assertEqual(report['status_code'], 1)
        self.assertEqual(fake.slot, gf.ECHO_STOCK)
        self.assertEqual([v for k,v in fake.events if k == 'echo'], [gf.DCACHE, gf.ICACHE, PLAN.code])
        self.assertEqual(len([e for e in fake.events if e[0] == 'write']), 4)

    def test_faults_and_no_uncertain_retry(self):
        for fault in ('version', 'publication', 'owner', 'caps', 'upload', 'postpub',
                      'short', 'magic', 'code', 'guard', gf.DCACHE, gf.ICACHE,
                      PLAN.code, ('slot', gf.ICACHE)):
            with self.subTest(fault=fault):
                fake = Fake(fault)
                with self.assertRaises((RuntimeError, ValueError, OSError)):
                    self.run_fake(fake)
                self.assertEqual(fake.slot, gf.ECHO_STOCK)
                echoes = [v for k,v in fake.events if k == 'echo']
                self.assertLessEqual(echoes.count(PLAN.code), 1)
                if fault in (gf.DCACHE, gf.ICACHE):
                    self.assertNotIn(PLAN.code, echoes)
                if fault in ('version', 'publication', 'owner', 'caps'):
                    self.assertFalse(fake.events)

    def test_restore_failure_not_success(self):
        with self.assertRaisesRegex(RuntimeError, 'echo slot'):
            self.run_fake(Fake(('slot', gf.ECHO_STOCK)))

    def test_timestamps_bracket_only_probe_even_on_uncertain_reply(self):
        for fault in (None, PLAN.code):
            with self.subTest(fault=fault):
                fake = Fake(fault)
                def clock(name, values):
                    values = iter(values)
                    def read():
                        value = next(values)
                        fake.events.append((name, value))
                        return value
                    return read
                with patch.object(snap.time, 'time_ns', side_effect=clock('utc', [1000, 900])), \
                     patch.object(snap.time, 'monotonic_ns', side_effect=clock('mono', [200, 300])):
                    if fault:
                        with self.assertRaises(OSError):
                            self.run_fake(fake, records=16)
                    else:
                        report, _, _ = self.run_fake(fake, records=16)
                        bounds = report['host_probe_echo_bounds']
                        self.assertEqual([bounds[k] for k in ('utc_before_ns', 'utc_after_ns',
                                         'monotonic_before_ns', 'monotonic_after_ns')],
                                         [1000, 900, 200, 300])
                        self.assertIn('not sample timestamps', bounds['meaning'])
                start = fake.events.index(('slot', PLAN.code))
                self.assertEqual(fake.events[start:], [
                    ('slot', PLAN.code), ('utc', 1000), ('mono', 200),
                    ('echo', PLAN.code), ('mono', 300), ('utc', 900),
                    ('slot', gf.ECHO_STOCK)])
                self.assertEqual(fake.events[start-1], ('echo', gf.ICACHE))

    def test_decoder_rejects_inconsistent_completion(self):
        _, param, result = self.run_fake(Fake())
        for offset, value in ((0, 0), (4, 0), (4, 2), (4, 3), (4, 4), (4, 5),
                              (4, 6), (8, 0), (0x34, 4), (0x38, 1), (0x28, 65535)):
            with self.subTest(offset=offset, value=value):
                changed = bytearray(param)
                struct.pack_into('<I', changed, offset, value)
                with self.assertRaises(RuntimeError):
                    snap.decode(changed, result)

    def test_lock_and_pending_refusal(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gf, 'LOCK_PATH', Path(tmp)/'lock'), \
             patch.object(gf, 'Backend', side_effect=AssertionError('must not connect')):
            with gf.staging_lock():
                with self.assertRaises(BlockingIOError):
                    snap.snapshot()
            gf.LOCK_PATH.with_suffix('.pending').write_text('pending')
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                snap.snapshot()

    def test_cli_fresh_output_and_offline_import_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'new'
            fake_result = self.run_fake(Fake())
            with patch.object(snap, 'snapshot', return_value=fake_result):
                self.assertEqual(snap.main(['--out', str(out)]), 0)
            self.assertEqual((out/'ring.bin').stat().st_size, snap.RING_BYTES)
            with patch.object(snap, 'snapshot', side_effect=AssertionError('must not connect')):
                with self.assertRaises(FileExistsError):
                    snap.main(['--out', str(out)])
        command = ('import socket; socket.socket=lambda *a,**k: (_ for _ in ()).throw('
                   'AssertionError("network forbidden")); import fpl_imu_snapshot as s; '
                   's.main(["--help"])')
        result = subprocess.run([sys.executable, '-B', '-c', command],
                                cwd=gf.HERE, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--out', result.stdout)


class Recent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codes = {n: snap.code_for(PLAN, n) for n in (1, 16, 32, 599, 600)}

    def verify_recent(self, n, last, change=None):
        first = (last-n+1) % 600
        param, result, reads, source = emulate(
            self.codes[n], head=R+8*(last+1), change=change,
            change_on=R+4+first*8)
        report = snap.decode(param, result, n)
        # Independent ring slicing oracle, including both sides of wrap.
        indexes = [(first+i) % 600 for i in range(n)]
        expected = struct.pack('<I', R+8*(last+1)) + b''.join(
            source[4+index*8:12+index*8] for index in indexes)
        self.assertEqual(result[:4+n*8], expected)
        self.assertEqual(result[4+n*8:], bytes(snap.RESULT_ROOM-4-n*8))
        self.assertEqual(report['copied_bytes'], 4+n*8)
        self.assertEqual(report['record_order'], 'recent_chronological')
        self.assertNotIn('records_storage_order', report)
        self.assertEqual(report['first_record_storage_index'], first)
        self.assertEqual(report['last_completed_index_before'], last)
        self.assertEqual(report['records_chronological_order'],
                         [[i-300, 300-i, 0, -i] for i in indexes])
        self.assertEqual(report['status_code'], 2 if change else 1)
        # No other record reads, including in the wrap case. Header reads are
        # separate and the copy must not fetch the header as a sample word.
        data_reads = [a for a, size in reads if R+4 <= a < R+snap.RING_BYTES]
        self.assertEqual(data_reads, [R+4+i*8+word for i in indexes for word in (0, 4)])
        return report, param, result

    def test_recent_counts_and_wrap_boundaries(self):
        for n in (1, 16, 32, 599):
            for last in (0, 1, n-1, 598, 599):
                with self.subTest(n=n, last=last):
                    self.verify_recent(n, last)

    def test_moving_head_and_publications_stale(self):
        for change in ((R, R+16), (GLOBAL, 0), (P+0x60, 0xDEADBEEF)):
            with self.subTest(change=change):
                self.verify_recent(16, 0, change)

    def test_recent_invalid_pointers_and_heads(self):
        for kw, expected in ((dict(descriptor=0), 3), (dict(descriptor=P+4), 4),
                             (dict(ring=0), 5), (dict(ring=R+4), 5),
                             (dict(head=0), 6), (dict(head=R+9), 6)):
            with self.subTest(kw=kw):
                p, r, _, _ = emulate(self.codes[16], **kw)
                self.assertEqual(snap.decode(p, r, 16)['status_code'], expected)
                self.assertEqual(r, bytes(snap.RESULT_ROOM))

    def test_recent_shortened_guard_and_header(self):
        _, param, result = self.verify_recent(16, 0)
        for at in (4+16*8, snap.RESULT_ROOM-1):
            changed = bytearray(result)
            changed[at] = 1
            with self.assertRaisesRegex(RuntimeError, 'guard'):
                snap.decode(param, changed, 16)
        changed = bytearray(result)
        struct.pack_into('<I', changed, 0, R+16)
        with self.assertRaisesRegex(RuntimeError, 'latched head'):
            snap.decode(param, changed, 16)
        with self.assertRaisesRegex(RuntimeError, 'extent'):
            snap.decode(param, result, 32)

    def test_default_bytes_and_artifact_hashes_unchanged(self):
        code = snap.code_for(PLAN)
        self.assertEqual(code, self.codes[600])
        param, result, _, source = emulate(code)
        self.assertEqual(result[:snap.RING_BYTES], source)
        # Frozen before this enhancement, at the documented synthetic PLAN.
        for data, digest in (
            (code, '68e7195c05936ca268c98c4c056f6daacdcc0c07721ba0561cab235475e4e1f5'),
            (param, '9d1e2035f98ecac59c5061d2beee18298c968df653a8d8e7f61bf029fbe6ae52'),
            (result, '65478bc6241c441e1499085d9e9ad6ae743031adce68a65d66240f5276795b64'),
            (result[:4804], '8732890d7b69fddd1f4bc3c78718616917adaead878a2f1399d1e60d72114ef4')):
            self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
        self.assertEqual(snap.decode(param, result)['record_order'], 'ring_storage')

    def test_local_count_rejected_before_any_camera_or_lock(self):
        for n in (0, -1, 601, 2**32, 16.0, True, '16', None):
            with self.subTest(n=n), \
                 patch.object(gf, 'Backend', side_effect=AssertionError('camera forbidden')), \
                 patch.object(gf, 'staging_lock', side_effect=AssertionError('lock forbidden')):
                with self.assertRaises(ValueError):
                    snap.snapshot(records=n)
                with self.assertRaises(ValueError):
                    snap._snapshot_locked(Fake(), n)
                with self.assertRaises(ValueError):
                    snap.code_for(PLAN, n)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(snap, 'snapshot', side_effect=AssertionError('camera forbidden')):
            for value in ('0', '-1', '601', '16.5'):
                out = Path(tmp)/value
                with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                    snap.main(['--out', str(out), '--records', value])
                self.assertFalse(out.exists())

    def test_assembler_rejects_out_of_range_constant(self):
        for n in (0, 601):
            with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit):
                gf.assemble(snap.HERE/'asm/fpl_imu_snapshot.S',
                            [f'PARAM={PLAN.param}', f'RESULT={PLAN.buffer}', f'RECORD_COUNT={n}'])

    def test_recent_host_path_and_cli_artifact(self):
        with patch.object(gf, 'staging_lock', nullcontext), \
             patch.object(gf, 'Backend', side_effect=AssertionError('camera forbidden')):
            report, param, result = snap.snapshot(Fake(), records=16)
        self.assertEqual(report['copied_bytes'], 132)
        self.assertEqual(report['record_order'], 'recent_chronological')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'recent'
            with patch.object(snap, 'snapshot', return_value=(report, param, result)) as capture:
                snap.main(['--out', str(out), '--records', '16'])
                capture.assert_called_once_with(records=16)
            self.assertEqual((out/'ring.bin').read_bytes(), result[:132])

    def test_recent_mutation_wrong_wrap_is_detected(self):
        code = bytearray(self.codes[16])
        # addlo r0,r0,r1 -> nop: a wrapping request reads before ring data.
        old = struct.pack('<I', 0x30800001)
        self.assertEqual(code.count(old), 1)
        at = code.index(old)
        code[at:at+4] = struct.pack('<I', 0xE320F000)
        _, result, _, source = emulate(bytes(code), head=R+8)
        expected = struct.pack('<I', R+8) + source[4+585*8:4804] + source[4:12]
        with self.assertRaises(AssertionError):
            self.assertEqual(result[:132], expected)


if __name__ == '__main__':
    unittest.main()
