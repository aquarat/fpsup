"""OFFLINE experiment, not a host runner or installable payload.

Compile a temporary optional-latch branch into the ACTUAL shared drain, then
execute one bounded batch in Unicorn. No production source is written. Python
classify() is a proposed report policy, not code installed on the camera.
See docs/FPL_GYRO_DRAIN_COHERENCE.md for its conditional assumptions.
"""
from dataclasses import dataclass
from pathlib import Path
import struct
import tempfile
import unittest

import unicorn as uc
from unicorn import arm_const as ar
from armasm import assemble, symbols

HERE = Path(__file__).resolve().parent
SHARED = HERE.parent / 'gyro/gyro_drain.S'
CODE, STATE, OUTPUT, STACK, STOP = 0x45000000, 0x45004000, 0x45005000, 0x450F0000, 0x48000000
P, R, GLOBAL, N = 0x2E006004, 0x2E00644C, 0xC31E23CC, 600
UNARMED = 0xFFFFFFFF

# Proposed optional branch only; exact anchor fails closed on upstream drift.
ANCHOR = '    ldr     r5, [r8]                @ where the firmware is writing now'
OPTION = '''#ifdef GYRO_LATCHED_HEAD_PTR
    movw    r5, #:lower16:GYRO_LATCHED_HEAD_PTR
    movt    r5, #:upper16:GYRO_LATCHED_HEAD_PTR
    ldr     r5, [r5]
#else
''' + ANCHOR + '\n#endif'

# One finite call, with cursor input explicitly supplied by the offline harness.
# Metadata: cursor_in, status, count, observed, padbad, drops, cursor_out,
# reserved, latch, reserved, pre(P,R,H), post(P,R,H). No printf, delay or I/O.
WRAPPER = r'''
.syntax unified
.arm
.text
entry:
    push {r4-r10, lr}
    ldr r4, =STATE
    mov r0, #0
    str r0, g_gcount
    str r0, g_padbad
    str r0, [r4, #8]
    str r0, [r4, #20]
    ldr r2, [r4]
    cmn r2, #1
    beq cursor_ok
    bl valid_head
    cmp r0, #0
    movne r0, #8
    bne finish
cursor_ok:
    str r2, g_ghead
    adr r0, descriptor
    str r0, descriptor_ptr
    ldr r0, =0x2E00644C
    str r0, descriptor_ring
    add r7, r4, #40
    bl snapshot
    cmp r0, #0
    bne finish
    str r2, [r4, #32]
    bl gyro_drain
    add r7, r4, #52
    bl snapshot
    cmp r0, #0
    moveq r0, #1
finish:
    str r0, [r4, #4]
    ldr r0, g_gcount
    str r0, [r4, #12]
    ldr r0, g_padbad
    str r0, [r4, #16]
    ldr r0, g_ghead
    str r0, [r4, #24]
    pop {r4-r10, pc}
snapshot:
    ldr r1, =0xC31E23CC
    ldr r1, [r1]
    str r1, [r7]
    mov r0, #3
    cmp r1, #0
    bxeq lr
    mov r0, #4
    ldr r2, =0x2E006004
    cmp r1, r2
    bxne lr
    ldr r1, [r1, #0x60]
    str r1, [r7, #4]
    mov r0, #5
    ldr r2, =0x2E00644C
    cmp r1, r2
    bxne lr
    ldr r2, [r1]
    str r2, [r7, #8]
valid_head:
    mov r0, #6
    ldr r1, =0x2E00644C
    sub r3, r2, r1
    cmp r3, #8
    bxlo lr
    movw ip, #0x12C0
    cmp r3, ip
    bxhi lr
    tst r3, #7
    bxne lr
    mov r0, #0
    bx lr
stream_claim:
    ldr r2, =STATE
    ldr r3, [r2, #8]
    ldr r1, =CAPACITY
    sub r1, r1, r3
    cmp r1, r0
    movhi r1, r0
    cmp r1, #0
    ldreq ip, [r2, #20]
    addeq ip, ip, r0
    streq ip, [r2, #20]
    ldr r0, =OUTPUT
    add r0, r0, r3, lsl #3
    bx lr
stream_commit:
    ldr r2, =STATE
    ldr r3, [r2, #8]
    add r3, r3, r0
    str r3, [r2, #8]
    bx lr
#define GYRO_DESC_PTR (CODE + descriptor_ptr - entry)
#include "DRAIN_PATH"
.balign 4
g_ghead: .word -1
g_gcount: .word 0
g_padbad: .word 0
descriptor_ptr: .word 0
descriptor: .space 0x60
descriptor_ring: .word 0
.ltorg
'''


def head(index):
    return R + 8*(index+1)


def index(value):
    delta = value-R
    if not 8 <= delta <= 4800 or delta % 8:
        raise ValueError('invalid completed head')
    return delta//8-1


def patched_shared():
    text = SHARED.read_text()
    assert text.count(ANCHOR) == 1, 'shared head load changed; review required'
    return text.replace(ANCHOR, OPTION).replace(
        '"imu_stream.inc.S"', f'"{SHARED.parent}/imu_stream.inc.S"')


def build(capacity=600, latch=True, mutation=False):
    assert 0 <= capacity <= 600  # zero is useful for the offline exhausted case
    with tempfile.TemporaryDirectory() as tmp:
        drain = Path(tmp)/'drain.S'
        text = patched_shared()
        if mutation:
            text = text.replace('add     r6, r6, #8', 'add     r6, r6, #0')
        drain.write_text(text)
        src = Path(tmp)/'batch.S'
        src.write_text(WRAPPER.replace('DRAIN_PATH', str(drain)))
        defs = [f'CODE={CODE}', f'STATE={STATE}', f'OUTPUT={OUTPUT}', f'CAPACITY={capacity}']
        if latch:
            defs.append(f'GYRO_LATCHED_HEAD_PTR={STATE+32}')
        return assemble(src, defs), symbols(src, defs)


@dataclass(frozen=True)
class Batch:
    words: tuple
    data: bytes
    source_reads: tuple

    def classify(self):
        w = self.words
        result = dict(cursor_in=w[0], cursor_out=w[6], pre=w[12], post=w[15],
                      appended=w[2], observed=w[3], dropped=w[5], padbad=w[4],
                      conditional_prefix_records=0, unconditional_valid_records=0,
                      hidden_laps_excluded=False, disposition='invalid',
                      advance=None, slack=None)
        if w[1] != 1 or (w[10], w[11], w[13], w[14]) != (P, R, P, R):
            return result
        try:
            pre, post = index(w[12]), index(w[15])
            old = None if w[0] == UNARMED else index(w[0])
        except ValueError:
            return result
        if w[8] != w[12] or w[6] != w[12]:
            return result
        d = 0 if old is None else (pre-old) % N
        a = (post-pre) % N
        if w[3] != d or w[2]+w[5] != d or w[4] > w[2]:
            return result
        result.update(advance=a, slack=N-d)
        if old is None:
            result['disposition'] = 'armed_no_copy'
        elif d == 0:
            result['disposition'] = 'no_observed_delta'
        elif a >= N-d:
            result['disposition'] = 'possible_overwrite'
        else:
            result.update(disposition='conditional_window_pass', conditional_prefix_records=w[2])
        return result


def run_batch(code, syms, *, old=0, pre=4, capacity=600, advance=0,
              trigger='copy', pending=False, publication=None,
              descriptor=P, ring=R, raw_head=None, raw_cursor=None, initial_laps=0):
    m = uc.Uc(uc.UC_ARCH_ARM, uc.UC_MODE_ARM)
    for at, size in ((CODE, 0x100000), (0x2E000000, 0x10000),
                     (GLOBAL & ~4095, 4096), (STOP, 4096)):
        m.mem_map(at, size)
    def word(at, value):
        m.mem_write(at, struct.pack('<I', value))
    def record(i, generation=0):
        value = i + 600*generation
        return struct.pack('<hhhh', value, -value, 0, value+1)
    m.mem_write(CODE, code)
    m.mem_write(OUTPUT, b'\xa5'*(600*8+16))
    word(STATE, (UNARMED if old is None else head(old)) if raw_cursor is None else raw_cursor)
    word(GLOBAL, descriptor)
    word(P+0x60, ring)
    word(R, head(pre) if raw_head is None else raw_head)
    for i in range(N):
        m.mem_write(R+4+i*8, record(i, initial_laps))
    allowed = [(STATE, STATE+64), (OUTPUT, OUTPUT+capacity*8), (STACK-80, STACK)]
    allowed += [(CODE+syms[s], CODE+syms[s]+4) for s in
                ('g_ghead', 'g_gcount', 'g_padbad', 'descriptor_ptr', 'descriptor_ring')]
    reads, injected = [], []
    def producer():
        if injected:
            return
        injected.append(True)
        for k in range(1, advance+1):
            i = (pre+k) % N
            m.mem_write(R+4+i*8, record(i, 1+(k-1)//N))
            word(R, head(i))  # publish only AFTER the complete record
        if pending:
            i = (pre+advance+1) % N
            # First word of a not-yet-published record: two components change.
            m.mem_write(R+4+i*8, record(i, 3)[:4])
        if publication:
            word(*publication)
    def memory(mu, access, at, size, value, unused):
        if access == uc.UC_MEM_WRITE:
            assert any(lo <= at and at+size <= hi for lo, hi in allowed), f'bad store {at:x}'
        else:
            readable = [(CODE, CODE+len(code)), (STATE, STATE+64), (STACK-80, STACK),
                        (GLOBAL, GLOBAL+4), (P+0x60, P+0x64), (R, R+4804)]
            assert any(lo <= at and at+size <= hi for lo, hi in readable), f'bad read {at:x}'
            if R+4 <= at < R+4804:
                reads.append((at, size))
                if trigger == 'copy' or (trigger == 'mid_record' and len(reads) == 2):
                    producer()
    def execution(mu, at, size, unused):
        assert CODE <= at < CODE+len(code), f'escaped payload {at:x}'
        if at == CODE+syms['gyro_drain']:
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            if trigger == 'before_drain':
                producer()
        if at in (CODE+syms['stream_claim'], CODE+syms['stream_commit']):
            assert mu.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
    m.hook_add(uc.UC_HOOK_MEM_READ | uc.UC_HOOK_MEM_WRITE, memory)
    m.hook_add(uc.UC_HOOK_CODE, execution)
    saved = {r: 0xABCDE000+r for r in range(ar.UC_ARM_REG_R4, ar.UC_ARM_REG_R11+1)}
    for r, v in saved.items():
        m.reg_write(r, v)
    m.reg_write(ar.UC_ARM_REG_SP, STACK)
    m.reg_write(ar.UC_ARM_REG_LR, STOP)
    m.emu_start(CODE, STOP, count=100000)
    assert m.reg_read(ar.UC_ARM_REG_PC) == STOP
    assert m.reg_read(ar.UC_ARM_REG_SP) == STACK
    assert all(m.reg_read(r) == v for r, v in saved.items())
    w = struct.unpack('<16I', m.mem_read(STATE, 64))
    assert w[2] <= capacity
    assert m.mem_read(OUTPUT+capacity*8, 16) == b'\xa5'*16
    return Batch(w, bytes(m.mem_read(OUTPUT, w[2]*8)), tuple(reads))


def expected(old, count):
    return b''.join(struct.pack('<hhhh', i, -i, 0, i+1)
                    for i in ((old+k) % N for k in range(1, count+1)))


def summarize(batches, initial_cursor=UNARMED):
    """Finite proposed provenance ledger; never call this a proven-valid prefix.

    An error or capacity loss stops continuation; bytes of a failing batch are
    tentative. Even earlier accepted batches retain the no-hidden-lap caveat.
    """
    if len(batches) > 20:
        raise ValueError('at most twenty diagnostic batches')
    if initial_cursor != UNARMED:
        index(initial_cursor)  # explicit offline seed, never silently inferred
    ledger, prefix, appended, cursor = [], 0, 0, initial_cursor
    stop = 'end_of_supplied_batches'
    for batch in batches:
        report = batch.classify()
        report['output_start'] = appended
        appended += report['appended']
        report['output_end'] = appended
        if report['cursor_in'] != cursor:
            report.update(disposition='cursor_provenance_mismatch', conditional_prefix_records=0)
        ledger.append(report)
        if report['disposition'] not in ('conditional_window_pass', 'armed_no_copy', 'no_observed_delta'):
            stop = report['disposition']
            break
        prefix += report['conditional_prefix_records']
        cursor = report['cursor_out']
        if report['dropped']:
            stop = 'capacity_loss'
            break
    return dict(batches=ledger, appended_records=appended, conditional_prefix_records=prefix,
                unconditional_valid_records=0, initial_cursor=initial_cursor,
                next_cursor=cursor, stop=stop)


class Coherence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code, cls.syms = build()

    def run_case(self, **kw):
        return run_batch(self.code, self.syms, **kw)

    def test_forward_movement_before_and_during_copy(self):
        for trigger in ('before_drain', 'copy', 'mid_record'):
            b = self.run_case(advance=3, trigger=trigger)
            self.assertEqual(b.data, expected(0, 4))
            self.assertEqual(b.words[6], head(4))  # NOT the post-head 7
            self.assertEqual(b.classify()['conditional_prefix_records'], 4)
            self.assertEqual(b.classify()['advance'], 3)

    def test_both_source_and_post_head_wrap(self):
        for old, pre, advance in ((598, 1, 2), (590, 598, 4), (598, 0, 1)):
            b = self.run_case(old=old, pre=pre, advance=advance)
            d = (pre-old) % N
            self.assertEqual(b.data, expected(old, d))
            self.assertEqual(b.classify()['conditional_prefix_records'], d)
            wanted_addresses = {R+4+((old+k) % N)*8+off
                                for k in range(1, d+1) for off in (0, 2, 4, 6)}
            self.assertEqual({a for a, _ in b.source_reads}, wanted_addresses)

    def test_unarmed_and_equal_head_are_not_freshness_proofs(self):
        for old, disposition in ((None, 'armed_no_copy'), (4, 'no_observed_delta')):
            b = self.run_case(old=old, advance=600, trigger='before_drain')
            self.assertEqual(b.data, b'')
            self.assertEqual(b.source_reads, ())
            self.assertEqual(b.classify()['disposition'], disposition)

    def test_strict_slack_reserves_unpublished_record(self):
        # d=4, slack=596. A=595 plus one in-flight write is outside interval.
        b = self.run_case(advance=595, pending=True)
        self.assertEqual(b.data, expected(0, 4))
        self.assertEqual(b.classify()['conditional_prefix_records'], 4)
        # At equality the pending write can already corrupt its first record.
        b = self.run_case(advance=596, pending=True)
        self.assertNotEqual(b.data, expected(0, 4))
        self.assertEqual(b.classify()['disposition'], 'possible_overwrite')
        self.assertEqual(b.classify()['conditional_prefix_records'], 0)
        torn = self.run_case(advance=596, pending=True, trigger='mid_record')
        self.assertEqual(struct.unpack_from('<hh', torn.data), (1, -1801))
        self.assertEqual(torn.classify()['disposition'], 'possible_overwrite')
        for advance in (597, 599):
            self.assertEqual(self.run_case(advance=advance).classify()['disposition'],
                             'possible_overwrite')

    def test_one_free_slot_boundary(self):
        b = self.run_case(pre=599, pending=True)
        self.assertEqual(b.data, expected(0, 599))
        self.assertEqual(b.classify()['slack'], 1)
        self.assertEqual(b.classify()['conditional_prefix_records'], 599)
        b = self.run_case(pre=599, advance=1, pending=True)
        self.assertEqual(b.classify()['disposition'], 'possible_overwrite')

    def test_hidden_laps_can_pass_window_with_corrupt_data(self):
        for advance in (600, 601, 1200):
            b = self.run_case(advance=advance)
            report = b.classify()
            self.assertNotEqual(b.data, expected(0, 4))
            self.assertEqual(report['disposition'], 'conditional_window_pass')
            self.assertEqual(report['unconditional_valid_records'], 0)
            self.assertFalse(report['hidden_laps_excluded'])
        b = self.run_case(initial_laps=1)
        self.assertNotEqual(b.data, expected(0, 4))
        self.assertEqual(b.classify()['disposition'], 'conditional_window_pass')

    def test_invalid_initial_pointers_heads_and_cursor(self):
        cases = [dict(descriptor=0), dict(descriptor=P+4), dict(ring=R+4)]
        cases += [dict(raw_head=v) for v in (0, R, R+4, R+9, R+4804, 0xFFFFFFFF)]
        cases += [dict(raw_cursor=v) for v in (0, R+4, R+9, R+4804)]
        for kw in cases:
            with self.subTest(kw=kw):
                b = self.run_case(**kw)
                self.assertEqual(b.classify()['disposition'], 'invalid')
                self.assertEqual(b.data, b'')
                self.assertEqual(b.source_reads, ())

    def test_publication_changes_and_invalid_post_head(self):
        for target, value in ((GLOBAL, 0), (GLOBAL, 0xDEADBEEF),
                              (P+0x60, 0xDEADBEEF), (R, 0), (R, R+9)):
            for trigger in ('before_drain', 'copy', 'mid_record'):
                b = self.run_case(publication=(target, value), trigger=trigger)
                self.assertEqual(b.classify()['disposition'], 'invalid')
                self.assertEqual(b.classify()['conditional_prefix_records'], 0)
                self.assertEqual(b.data, expected(0, 4))

    def test_capacity_exhaustion_keeps_cursor_and_drops_explicit(self):
        for cap in (0, 2):
            code, syms = build(capacity=cap)
            b = run_batch(code, syms, capacity=cap, advance=1, trigger='before_drain')
            self.assertEqual(b.data, expected(0, cap))
            self.assertEqual(b.words[6], head(4))
            self.assertEqual(b.classify()['dropped'], 4-cap)
            self.assertEqual(b.classify()['conditional_prefix_records'], cap)

    def test_finite_ledger_retains_only_conditional_prefix(self):
        good1 = self.run_case(advance=1)
        good2 = self.run_case(old=4, pre=8, advance=1)
        bad = self.run_case(old=8, pre=12, advance=596, pending=True)
        ledger = summarize([good1, good2, bad, good1], initial_cursor=head(0))
        self.assertEqual(ledger['conditional_prefix_records'], 8)
        self.assertEqual(ledger['appended_records'], 12)
        self.assertEqual(ledger['unconditional_valid_records'], 0)
        self.assertEqual(ledger['stop'], 'possible_overwrite')
        self.assertEqual(ledger['next_cursor'], head(8))
        self.assertEqual([(b['output_start'], b['output_end']) for b in ledger['batches']],
                         [(0, 4), (4, 8), (8, 12)])
        # Using post-head (5) as next cursor silently skips a sample: reject it.
        wrong = self.run_case(old=5, pre=8)
        self.assertEqual(summarize([good1, wrong], initial_cursor=head(0))['stop'],
                         'cursor_provenance_mismatch')
        self.assertEqual(summarize([good1])['stop'], 'cursor_provenance_mismatch')
        armed = self.run_case(old=None, pre=0)
        self.assertEqual(summarize([armed, good1])['conditional_prefix_records'], 4)
        code, syms = build(capacity=2)
        partial = run_batch(code, syms, capacity=2)
        ledger = summarize([partial, good1], initial_cursor=head(0))
        self.assertEqual(ledger['conditional_prefix_records'], 2)
        self.assertEqual(ledger['stop'], 'capacity_loss')
        self.assertEqual(len(ledger['batches']), 1)
        with self.assertRaises(ValueError):
            summarize([good1]*21)

    def test_absent_option_preserves_actual_capture_and_default_base_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            drain = Path(tmp)/'drain.S'
            drain.write_text(patched_shared())
            for source, defs in ((HERE/'asm/fpl_gyro_capture.S',
                                  [f'CODE={CODE}', f'STATE={STATE}', f'OUTPUT={OUTPUT}', 'CAPACITY=1200']),
                                 (HERE.parent/'gyro/gcsv_task.S', ['FPGYRO_EDITION_BASE=1'])):
                # Mirror only assembly sources; never copy release artifacts.
                if source.name == 'gcsv_task.S':
                    mirror = Path(tmp)/'gyro'
                    mirror.mkdir()
                    for asm in source.parent.glob('*.S'):
                        (mirror/asm.name).write_bytes(asm.read_bytes())
                    (mirror/'gyro_drain.S').write_text(patched_shared())
                    candidate = mirror/source.name
                else:
                    candidate = Path(tmp)/source.name
                    candidate.write_text(source.read_text().replace(
                        '"../../gyro/gyro_drain.S"', f'"{drain}"'))
                self.assertEqual(assemble(candidate, defs), assemble(source, defs))

    def test_mutated_latch_and_copy_are_detected(self):
        # Without the latch, the producer's movement before drain extends the
        # copied interval beyond the validated pre-head; provenance rejects it.
        code, syms = build(latch=False)
        b = run_batch(code, syms, advance=3, trigger='before_drain')
        self.assertNotEqual(b.data, expected(0, 4))
        self.assertEqual(b.classify()['disposition'], 'invalid')
        code, syms = build(mutation=True)
        b = run_batch(code, syms)
        with self.assertRaises(AssertionError):
            self.assertEqual(b.data, expected(0, 4))


if __name__ == '__main__':
    unittest.main()
