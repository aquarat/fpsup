"""Offline ARM + host acceptance; no live Backend is ever instantiated.

PATH=/path/to/arm-toolchain/bin:$PATH \
  python3 -B -m unittest test_fpl_gyro_latched
"""
from contextlib import nullcontext
from dataclasses import replace
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
import fpl_gyro_latched as lat
from test_fpl_gyro_capture_host import Fake as StrictFake

POOL, ROOM, WORKER = 0x45000000, 0x100000, 0x47000000
PUB = [POOL, ROOM, WORKER]
CAPS = dict(pool=POOL, pool_size=ROOM, xfer=0xfffc00)
P, R, GLOBAL, DELAY = lat.P, lat.R, 0xC31E23CC, 0xC01F5244
STACK, STOP = POOL+0xF0000, 0x48000000


def mutation_source():
    """Expand only the adapter for temporary source mutations of the real core."""
    core = lat.SOURCE.resolve().parents[2]/'gyro/latched_capture.inc.S'
    return lat.SOURCE.read_text().replace('#include "../../gyro/latched_capture.inc.S"',
        core.read_text().replace('"gyro_drain.S"', '"../../gyro/gyro_drain.S"'))


def emulate(code, syms, plan, capacity=1200, *, start=0, step=50, advance=1,
             advance_batch=None, pending=False, mid_record=False, fault=None,
            descriptor=P, ring=R, initial_head=None, pad=0, runtime_refs=None,
             rejected=False, poison_old=False, inject=None):
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    pages = set()
    for address, size in ((POOL, ROOM), (0x2E000000, 0x10000),
                          (GLOBAL & ~4095, 4096), (DELAY & ~4095, 4096), (STOP, 4096),
                          (plan.code, lat.CODE_ROOM), (plan.state, lat.STATE_ROOM),
                          (plan.output, plan.output_room)):
        pages.update(range(address & ~4095, (address+size+4095) & ~4095, 4096))
    for address in pages:
        m.mem_map(address, 4096)
    old = lat.layout(CAPS, PUB, capacity)
    if poison_old:
        assert plan.code != old.code and plan.state != old.state and plan.output != old.output
        for at, size in ((old.code, lat.CODE_ROOM), (old.state, lat.STATE_ROOM),
                         (old.output, old.output_room)):
            m.mem_write(at, b'\xFE'*size)
    def word(at, value):
        m.mem_write(at, struct.pack('<I', value))
    def readword(at):
        return struct.unpack('<I', m.mem_read(at, 4))[0]
    def head(i):
        return R+8*(i+1)
    current, generation = start, 0
    def producer(n, partial=False):
        nonlocal current, generation
        for _ in range(n):
            current = (current+1) % 600
            generation += 1
            v = 1000+generation
            m.mem_write(R+4+current*8, struct.pack('<hhhh', v, -v, pad, v+1))
            word(R, head(current))
        if partial:
            m.mem_write(R+4+((current+1) % 600)*8, struct.pack('<hh', 30000, -30000))
    m.mem_write(plan.code, bytes(code))
    if runtime_refs is not None:
        m.mem_write(plan.code+syms['runtime_refs'], struct.pack('<5I', *runtime_refs))
    m.mem_write(plan.state, b'\xCC'*lat.STATE_ROOM)  # reset must erase stale state
    m.mem_write(plan.output, lat.strict.SENTINEL*plan.output_room)
    word(GLOBAL, descriptor)
    word(P+0x60, ring)
    word(R, head(start) if initial_head is None else initial_head)
    for i in range(600):
        m.mem_write(R+4+i*8, struct.pack('<hhhh', i, -i, pad, i+1))
    allowed = [(STACK-80, STACK)]
    if not rejected:
        allowed += [(plan.state, plan.state+lat.STATE_ROOM), (plan.output, plan.output+capacity*8)]
        allowed += [(plan.code+syms[k], plan.code+syms[k]+4) for k in lat.MUTABLE]
    firmware_before = {at: bytes(m.mem_read(at, size)) for at, size in
                       ((0x2E000000, 0x10000), (GLOBAL & ~4095, 4096))}
    # Memory hooks prohibit every CPU store to firmware, while producer hooks
    # intentionally simulate external writes, which Unicorn does not hook.
    batch, reads, writes, delays, injected, expected = -1, [], [], [], set(), []
    read_counts = {}
    def maybe_fault(stage):
        if fault and fault[:2] == (batch, stage):
            word(fault[2], fault[3])
    def memory(mu, access, at, size, value, unused):
        if inject:
            inject(mu, 'write' if access == uc.UC_MEM_WRITE else 'read', at, batch)
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in allowed), f'bad store {at:x}'
            writes.append((at, size))
            return
        readable = [(plan.code, plan.code+len(code)), (plan.state, plan.state+lat.STATE_ROOM),
                    (STACK-80, STACK), (GLOBAL, GLOBAL+4), (P+0x60, P+0x64), (R, R+4804)]
        assert any(lo <= at and at+size <= hi for lo, hi in readable), f'bad read {at:x}'
        if R+4 <= at < R+4804:
            reads.append((batch, at, size))
            read_counts[batch] = read_counts.get(batch, 0)+1
            if batch not in injected and read_counts[batch] == (2 if mid_record else 1):
                injected.add(batch)
                if advance_batch is None or batch == advance_batch:
                    producer(advance, pending)
                maybe_fault('copy')
    def execution(mu, at, size, unused):
        nonlocal batch
        if inject:
            inject(mu, 'execute', at, batch)
        if at == DELAY:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            assert mu.reg_read(ar.UC_ARM_REG_R0) == 20
            delays.append(20)
            producer(step)
            for reg in (ar.UC_ARM_REG_R0, ar.UC_ARM_REG_R1, ar.UC_ARM_REG_R2,
                        ar.UC_ARM_REG_R3, ar.UC_ARM_REG_R12):
                mu.reg_write(reg, 0xBAD00000+reg)
            mu.reg_write(ar.UC_ARM_REG_CPSR, mu.reg_read(ar.UC_ARM_REG_CPSR) | 0xF0000000)
            mu.reg_write(ar.UC_ARM_REG_PC, mu.reg_read(ar.UC_ARM_REG_LR))
            return
        assert plan.code <= at < plan.code+len(code), f'escaped payload {at:x}'
        if at == plan.code+syms['loop']:
            batch += 1
            maybe_fault('pre')
        if at == plan.code+syms['gyro_drain']:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            row = plan.state+64+batch*80
            prior, latch = readword(row+4), readword(row+8)
            delta = 0 if prior == lat.UNARMED else ((latch-prior) % 4800)//8
            amount = min(delta, capacity-readword(plan.state+12))
            want = bytearray()
            for k in range(amount):
                idx = ((prior-R)//8+k) % 600
                rec = bytearray(m.mem_read(R+4+idx*8, 8))
                rec[4:6] = b'\0\0'
                want += rec
            expected.append((batch, bytes(want)))
            maybe_fault('drain')
        if at in [plan.code+syms[s] for s in ('stream_claim', 'stream_commit')]:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
    saved = {r: 0xABCDE000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    for r, value in saved.items():
        m.reg_write(r, value)
    m.reg_write(ar.UC_ARM_REG_SP, STACK)
    m.reg_write(ar.UC_ARM_REG_LR, STOP)
    m.reg_write(ar.UC_ARM_REG_R0, 0xBAD00000)
    m.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    m.hook_add(uc.UC_HOOK_CODE, execution)
    m.emu_start(plan.code, STOP, count=1000000)
    assert m.reg_read(ar.UC_ARM_REG_PC) == STOP, 'not finite'
    assert m.reg_read(ar.UC_ARM_REG_SP) == STACK
    assert all(m.reg_read(r) == value for r, value in saved.items())
    if rejected:
        assert m.reg_read(ar.UC_ARM_REG_R0) == 15, 'invalid refs not refused'
        assert not reads and not delays
        assert m.mem_read(plan.state, lat.STATE_ROOM) == b'\xCC'*lat.STATE_ROOM
    else:
        assert writes[-1] == (plan.state, 4), 'completion marker not last'
    if poison_old:
        for at, size in ((old.code, lat.CODE_ROOM), (old.state, lat.STATE_ROOM),
                         (old.output, old.output_room)):
            assert m.mem_read(at, size) == b'\xFE'*size
    state = bytes(m.mem_read(plan.state, lat.STATE_ROOM))
    output = bytes(m.mem_read(plan.output, plan.output_room))
    actual_code = bytes(m.mem_read(plan.code, lat.CODE_ROOM))
    # Explicit no-motion case also verifies all firmware bytes unchanged.
    if not step and not advance and not pending and not fault:
        for at, before in firmware_before.items():
            assert m.mem_read(at, len(before)) == before
    return state, output, actual_code, expected, delays, reads


class Fake(StrictFake):
    def __init__(self, capacity=1200, *, runtime=False, **emulation):
        super().__init__(capacity)
        self.plan = lat.layout(self.caps(), self.publication, capacity)
        self.emulation = emulation
        self.runtime = runtime

    def sh(self, command, **kwargs):
        self.calls.append((command, self.handler, kwargs))
        assert kwargs['retries'] == 0
        if command == 'version':
            return self.version
        assert command == 'echo'
        if self.handler == self.fail_handler:
            return 'ERR uncertain'
        if self.handler == self.plan.code:
            _, syms = lat.code_for(self.plan, self.capacity, runtime=self.runtime)
            state, output, code, *_ = emulate(self.memory[self.plan.code], syms, self.plan,
                                               self.capacity, **self.emulation)
            self.memory.update({self.plan.state: bytearray(state), self.plan.output: bytearray(output),
                                self.plan.code: bytearray(code)})
            if self.mutate:
                self.mutate(self)
        return ''


class Payload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = lat.layout(CAPS, PUB, 1200)
        cls.code, cls.syms = lat.code_for(cls.plan, 1200)

    def run_case(self, **kwargs):
        result = emulate(self.code, self.syms, self.plan, **kwargs)
        report = lat.decode(result[0], result[1], 1200)
        lat.verify_code(self.code, result[2], self.syms)
        return report, result

    def test_live_like_moving_head_and_call_abi(self):
        report, result = self.run_case()
        self.assertEqual(report['status_code'], 100)
        self.assertEqual(report['proven_valid_records'], 0)
        self.assertFalse(report['hidden_laps_excluded'])
        self.assertEqual(report['appended_records'], 50+18*51)
        self.assertEqual(report['conditional_prefix_records'], report['appended_records'])
        self.assertEqual(result[4], [20]*20)
        expected = b''.join(data for _, data in result[3])
        self.assertEqual(result[1][:len(expected)], expected)
        for i, row in enumerate(report['batches']):
            self.assertEqual(row['disposition'], 'conditional_window_pass' if i else 'armed_no_copy')
            self.assertEqual(row['consumed_cursor'], row['latched_head'])
            if i > 1:
                self.assertEqual(row['prior_cursor'], report['batches'][i-1]['latched_head'])
                self.assertNotEqual(row['prior_cursor'], report['batches'][i-1]['post_head'])

    def test_wrap_stationary_and_padding(self):
        report, result = self.run_case(start=598, step=3, pad=7)
        expected = b''.join(data for _, data in result[3])
        self.assertEqual(result[1][:len(expected)], expected)
        self.assertEqual(report['copied_nonzero_padding_count'], report['appended_records'])
        report, result = self.run_case(step=0, advance=0)
        self.assertEqual(report['appended_records'], 0)
        self.assertEqual(result[5], [])
        self.assertEqual([b['disposition'] for b in report['batches']], ['armed_no_copy']+['no_observed_delta']*19)

    def test_reinvocation_rearms_even_with_mutated_payload_state(self):
        _, first = self.run_case()
        second = emulate(first[2], self.syms, self.plan)
        self.assertEqual(second[:2], first[:2])
        self.assertEqual(struct.unpack_from('<I', second[0], 68)[0], lat.UNARMED)

    def test_partial_unpublished_write_strict_boundary(self):
        for adv, disposition in ((595, 'conditional_window_pass'), (596, 'possible_overwrite')):
            report, result = self.run_case(step=4, advance=adv, advance_batch=1, pending=True, mid_record=True)
            row = report['batches'][1]
            self.assertEqual(row['disposition'], disposition)
            self.assertEqual(row['unread_slack'], 596)
            if adv == 596:
                self.assertEqual(report['conditional_prefix_records'], 0)
                self.assertEqual(report['appended_records'], 4)
                self.assertEqual(len(result[4]), 1)
                self.assertNotEqual(result[1][:32], result[3][1][1])

    def test_hidden_full_lap_counterexample(self):
        report, result = self.run_case(step=4, advance=600, advance_batch=1)
        self.assertEqual(report['batches'][1]['disposition'], 'conditional_window_pass')
        self.assertEqual(report['batches'][1]['observed_advance'], 0)
        self.assertNotEqual(result[1][:32], result[3][1][1])
        self.assertEqual(report['proven_valid_records'], 0)

    def test_invalid_and_changed_publications(self):
        for kw, status in ((dict(descriptor=0), 10), (dict(descriptor=P+4), 11),
                           (dict(ring=0), 12), (dict(initial_head=0), 13),
                           (dict(initial_head=R+9), 13), (dict(initial_head=R+4804), 13)):
            report, result = self.run_case(**kw)
            self.assertEqual(report['status_code'], status)
            self.assertEqual(report['appended_records'], 0)
            self.assertEqual(result[5], [])
        for stage in ('pre', 'drain', 'copy'):
            for address, value, status in ((GLOBAL, 0, 10), (GLOBAL, 0xDEADBEEF, 11),
                                            (P+0x60, 0xDEADBEEF, 12), (R, R+9, 13)):
                report, result = self.run_case(fault=(2, stage, address, value), advance=0)
                self.assertEqual(report['status_code'], status)
                self.assertEqual(report['conditional_prefix_records'], 50)
                self.assertEqual(len(result[4]), 2)

    def test_capacity_loss_and_maximum_bound(self):
        for capacity in (1, 55, 12000):
            plan = lat.layout(CAPS, PUB, capacity)
            code, syms = lat.code_for(plan, capacity)
            state, output, _, expected, delays, _ = emulate(code, syms, plan, capacity)
            report = lat.decode(state, output, capacity)
            if capacity < 1200:
                self.assertEqual(report['status_code'], 5)
                self.assertEqual(report['conditional_prefix_records'], capacity)
                self.assertGreater(report['dropped_for_capacity'], 0)
                self.assertLess(len(delays), 20)
            self.assertEqual(output[:report['appended_records']*8], b''.join(d for _, d in expected))

    def test_decoder_rejects_header_rows_counts_and_guards(self):
        _, (state, output, *_rest) = self.run_case(step=4, advance=0)
        # Change every semantically checked word except pad counters (not
        # independently measurable) and actual component values (raw samples).
        for at in (0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48,
                   *range(64, 144, 4), *range(144, 224, 4), 1664, 2044):
            with self.subTest(offset=at):
                changed = bytearray(state)
                struct.pack_into('<I', changed, at, struct.unpack_from('<I', changed, at)[0]^1)
                with self.assertRaises(RuntimeError):
                    lat.decode(changed, output, 1200)
        for at in (4, len(output)-1, 19*4*8):
            changed = bytearray(output)
            changed[at] ^= 1
            with self.assertRaises(RuntimeError):
                lat.decode(state, changed, 1200)

    def test_mutable_mask_exact_every_byte(self):
        allowed = {self.syms[name]+i for name in lat.MUTABLE for i in range(4)}
        for at in range(len(self.code)):
            code = bytearray(self.code)
            code[at] ^= 1
            if at in allowed:
                lat.verify_code(self.code, code, self.syms)
            else:
                with self.assertRaises(RuntimeError):
                    lat.verify_code(self.code, code, self.syms)

    def test_default_strict_and_base_bytes_unchanged(self):
        fixed, symbols = lat.code_for(lat.layout(CAPS, PUB, 1200), 1200)
        self.assertEqual(hashlib.sha256(fixed[:symbols['body_end']]).hexdigest(),
                         '637751fa583c79d0f690ffeb91a06d2c8be6df94c5d775a2e79131a78499dfcd')
        for src, defs, expected in (
            (lat.strict.SOURCE, ['CODE=0x45000000', 'STATE=0x45004000', 'OUTPUT=0x45005000', 'CAPACITY=1200'],
             '1830a6d42266056991de2d7d80068c0b0563076bce1b310ad629433c8e436253'),
            (lat.SOURCE.parent.parent.parent/'gyro/gcsv_task.S', ['FPGYRO_EDITION_BASE=1'],
             '5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38')):
            self.assertEqual(hashlib.sha256(lat.armasm.assemble(src, defs)).hexdigest(), expected)

    def test_source_mutations_fail_oracles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shared = lat.SOURCE.parent.parent.parent/'gyro/gyro_drain.S'
            for old, new, predicate in (
                ('add     r6, r6, #8', 'add     r6, r6, #0', 'data'),
                ('    ldr     r5, [r5]', '    ldr     r5, [r8]', 'ledger')):
                text = shared.read_text()
                self.assertEqual(text.count(old), 1)
                drain = root/'drain.S'
                drain.write_text(text.replace(old, new).replace('"imu_stream.inc.S"',
                                       f'"{shared.parent}/imu_stream.inc.S"'))
                source = root/'capture.S'
                source.write_text(mutation_source().replace('"../../gyro/gyro_drain.S"', f'"{drain}"'))
                with patch.object(lat, 'SOURCE', source):
                    code, syms = lat.code_for(self.plan, 1200)
                if predicate == 'data':
                    state, output, _, expected, *_ = emulate(code, syms, self.plan, advance=0)
                    lat.decode(state, output, 1200)
                    with self.assertRaises(AssertionError):
                        self.assertEqual(output[:19*50*8], b''.join(d for _, d in expected))
                else:
                    # Unlatched load follows head changed after pre-validation.
                    state, output, *_ = emulate(code, syms, self.plan,
                                                fault=(1, 'drain', R, R+8*60))
                    with self.assertRaises(RuntimeError):
                        lat.decode(state, output, 1200)
            source = root/'weak-window.S'
            source.write_text(mutation_source().replace(
                'movhs r0, #4\n    bhs row_done', 'movhi r0, #4\n    bhi row_done').replace(
                    '"../../gyro/gyro_drain.S"', f'"{shared}"'))
            with patch.object(lat, 'SOURCE', source):
                code, syms = lat.code_for(self.plan, 1200)
            state, output, *_ = emulate(code, syms, self.plan, step=4, advance=596,
                                         advance_batch=1, pending=True, mid_record=True)
            with self.assertRaisesRegex(RuntimeError, 'window disposition'):
                lat.decode(state, output, 1200)

    def test_compile_extent_guards(self):
        good = dict(CODE=self.plan.code, STATE=self.plan.state,
                    OUTPUT=self.plan.output, CAPACITY=1200)
        for key, value in (('CODE', self.plan.state), ('STATE', self.plan.output),
                           ('OUTPUT', 0xFFFFFFF8), ('OUTPUT', self.plan.output+1),
                           ('CAPACITY', 0), ('CAPACITY', 12001)):
            defs = dict(good)
            defs[key] = value
            with self.subTest(key=key, value=value), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    lat.armasm.assemble(lat.SOURCE, [f'{k}={v}' for k, v in defs.items()])


class Host(unittest.TestCase):
    def run_fake(self, fake):
        with patch.object(lat.gf, 'staging_lock', return_value=nullcontext()), \
             patch.object(lat.gf, 'Backend', side_effect=AssertionError('live backend forbidden')):
            return lat.capture(fake, capacity=fake.capacity, runtime=fake.runtime)

    def test_actual_arm_through_fake_transport(self):
        fake = Fake()
        report, _, _ = self.run_fake(fake)
        self.assertEqual(report['status_code'], 100)
        self.assertEqual([h for c, h, _ in fake.calls if c == 'echo'],
                         [lat.gf.DCACHE, lat.gf.ICACHE, fake.plan.code])
        self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)
        self.assertEqual([(a, len(b)) for a, b in fake.writes],
                         [(fake.plan.code, 4096), (fake.plan.state, 2048),
                          (fake.plan.output, fake.plan.output_room)])
        times = report['host_echo_bounds']
        self.assertLessEqual(times['monotonic_before_ns'], times['monotonic_after_ns'])
        self.assertEqual(report['proven_valid_records'], 0)

    def test_uncertain_cache_capture_and_restore_no_reexecution(self):
        for failing in (lat.gf.DCACHE, lat.gf.ICACHE, Fake().plan.code):
            fake = Fake()
            fake.fail_handler = failing
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                self.run_fake(fake)
            self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)
            self.assertEqual(sum(c == 'echo' and h == failing for c, h, _ in fake.calls), 1)
        fake = Fake()
        fake.restore_failure = True
        with self.assertRaisesRegex(RuntimeError, 'verify'):
            self.run_fake(fake)
        fake = Fake()
        original = fake.sh
        def lost_reply(command, **kwargs):
            result = original(command, **kwargs)
            if command == 'echo' and fake.handler == fake.plan.code:
                raise TimeoutError('uncertain reply')
            return result
        fake.sh = lost_reply
        with self.assertRaises(TimeoutError):
            self.run_fake(fake)
        self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)
        self.assertEqual(sum(c == 'echo' and h == fake.plan.code for c, h, _ in fake.calls), 1)

    def test_preflight_and_upload_fail_before_execution(self):
        for fault in ('version', 'owner', 'caps', 'upload'):
            fake = Fake()
            if fault == 'version':
                fake.version += 'model = w91c1\n'
            elif fault == 'owner':
                fake.handler = 0
            elif fault == 'caps':
                fake.caps = lambda: None
            else:
                fake.bad_upload = True
            with self.assertRaises((RuntimeError, ValueError)):
                self.run_fake(fake)
            self.assertEqual(fake.sets, [])
            if fault != 'upload':
                self.assertEqual(fake.writes, [])

    def test_post_readback_guards_and_mutables(self):
        for target in ('code', 'latch', 'descriptor', 'state', 'output', 'publication', 'short'):
            fake = Fake()
            _, syms = lat.code_for(fake.plan, fake.capacity)
            def mutate(f):
                if target == 'publication':
                    f.publication[2] = 0
                elif target == 'short':
                    f.memory[f.plan.state] = f.memory[f.plan.state][:-4]
                else:
                    address, offset = {
                        'code': (f.plan.code, 0), 'latch': (f.plan.code, syms['g_latched_head']),
                        'descriptor': (f.plan.code, syms['descriptor_ring']),
                        'state': (f.plan.state, 2044), 'output': (f.plan.output, f.plan.output_room-1)
                    }[target]
                    f.memory[address][offset] ^= 1
            fake.mutate = mutate
            with self.subTest(target=target), self.assertRaises(RuntimeError):
                self.run_fake(fake)
            self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)

    def test_bounds_capacity_lock_and_fresh_cli(self):
        with patch.object(lat.gf, 'Backend', side_effect=AssertionError('live forbidden')), \
             patch.object(lat.gf, 'staging_lock', side_effect=AssertionError('must reject first')):
            for bad in (0, -1, 12001, True, 1.5, '1', None):
                with self.assertRaises(ValueError):
                    lat.capture(capacity=bad)
        plan = Fake().plan
        for bad in (replace(plan, output=plan.state), replace(plan, state=plan.code),
                    replace(plan, output_room=1024), replace(plan, code=plan.code+4)):
            with self.assertRaises(ValueError):
                lat.code_for(bad, 1200)
        for capacity in (1, 1200, 12000):
            shifted = [PUB[0]+4, PUB[1], PUB[2]]
            caps = dict(CAPS, pool=shifted[0])
            aligned = lat.layout(caps, shifted, capacity)
            self.assertEqual(aligned.code % 1024, 0)
            self.assertLessEqual(aligned.state+2048, aligned.output)
            self.assertLessEqual(aligned.output+aligned.output_room, shifted[0]+shifted[1])
            lat.code_for(aligned, capacity)
        with self.assertRaises(ValueError):
            lat.layout(dict(CAPS, pool_size=0x14000), [POOL, 0x14000, WORKER], 12000)
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory)/'lock'
            lock.with_suffix('.pending').touch()
            with patch.object(lat.gf, 'LOCK_PATH', lock), patch.object(lat.gf, 'Backend') as backend:
                with self.assertRaisesRegex(RuntimeError, 'pending'):
                    lat.capture()
                backend.assert_not_called()
            out = Path(directory)/'new'
            result = self.run_fake(Fake(step=0, advance=0))
            with patch.object(lat, 'capture', return_value=result):
                lat.main(['--out', str(out)])
            self.assertEqual((out/'state.bin').stat().st_size, 2048)
            with patch.object(lat, 'capture', side_effect=AssertionError('live forbidden')):
                with self.assertRaises(FileExistsError):
                    lat.main(['--out', str(out)])
        command = ('import socket; socket.socket=lambda *a,**k: (_ for _ in ()).throw('
                   'AssertionError("network forbidden")); import fpl_gyro_latched as l; l.main(["--help"])')
        result = subprocess.run([sys.executable, '-B', '-c', command], cwd=lat.SOURCE.parent.parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
