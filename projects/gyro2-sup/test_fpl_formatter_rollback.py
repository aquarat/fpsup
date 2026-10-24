"""Native rollback primitive and limits of an offline padding-only policy.

The experimental transaction runs ARM, but is NOT a camera callback or a proven
insertion point. Calls into insertion/search/remove/size/serialization execute
official ARM. The caller-supplied final graph is reconstructed, not a mode-0
capture; no take cancellation or real destination ownership is claimed.
"""
import struct
import unittest
import tempfile
from pathlib import Path

import build as G
import test_fpl_formatter_dng as D
import test_fpl_tag_capacity as N
import test_fpl_observer as T

GATE = 0x4B000000
# Experimental synchronous transaction, deliberately NOT an observer installer.
# ABI: (builder, MakerNote IFD, immutable source, N), trusted owned graph only.
# Returns 1 accepted, 0 refused/rolled back, 2 rollback could not be verified.
# The caller must prove this is the FINAL graph and prevent concurrent mutation.
TRANSACTION = r'''
.syntax unified
.arm
.text
.macro call addr
    ldr ip, =\addr
    blx ip
.endm
    push {r4-r8, lr}
    sub sp, sp, #8
    mov r4, r0
    mov r5, r1
    mov r6, r2
    mov r7, r3
    cmp r7, #560
    bne refuse
    call 0xC00B6510
    ldr r1, =0x135C4
    cmp r0, r1
    bne refuse
    mov r8, r0
    mov r0, r5
    movw r1, #0x4653
    call 0xC00BAA10
    cmp r0, #0
    bne refuse
    str r7, [sp]
    str r6, [sp, #4]
    mov r0, r4
    mov r1, #5
    movw r2, #0x4653
    mov r3, #7
    call 0xC00B6B20
    mov r0, r5
    movw r1, #0x4653
    call 0xC00BAA10
    cmp r0, #0
    beq rollback
    ldrh r1, [r0, #10]
    cmp r1, #7
    bne rollback
    ldr r1, [r0, #12]
    cmp r1, r7
    bne rollback
    ldr r0, [r0, #16]
    cmp r0, #0
    beq rollback
    ldr r1, [r0, #12]
    cmp r1, r7
    bne rollback
    ldr r0, [r0, #8]
    cmp r0, #0
    beq rollback
    mov r2, #0
compare:
    ldrb r1, [r0, r2]
    ldrb r3, [r6, r2]
    cmp r1, r3
    bne rollback
    add r2, r2, #1
    cmp r2, r7
    blo compare
    mov r0, r4
    call 0xC00B6510
    ldr r1, =0x13800
    cmp r0, r1
    bne rollback
    mov r0, #1
    b done
rollback:
    mov r0, r5
    movw r1, #0x4653
    call 0xC00BAA98
    mov r0, r5
    movw r1, #0x4653
    call 0xC00BAA10
    cmp r0, #0
    bne broken
    mov r0, r4
    call 0xC00B6510
    cmp r0, r8
    bne broken
refuse:
    mov r0, #0
    b done
broken:
    mov r0, #2
done:
    add sp, sp, #8
    pop {r4-r8, pc}
.ltorg
'''


class GateMachine(D.DngMachine):
    def hook(self, mu, addr, size, userdata):
        if GATE <= addr < GATE+0x1000 or 0xC03790CC <= addr < 0xC03790E4:
            return
        super().hook(mu, addr, size, userdata)


class Rollback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        D.RealDng.setUpClass.__func__(cls)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'transaction.S'
            p.write_text(TRANSACTION)
            cls.gate_code = G.assemble(p)

    def machine(self):
        import test_fpl_formatter as F
        m = GateMachine(N.NativeCapacity.image, F.NativeFormatter.data,
                        N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        m.mu.mem_map(GATE, 0x1000)
        m.mu.mem_write(GATE, self.gate_code)
        return m

    def stored(self, m, n):
        entry = m.call(0xC00BAA10, N.MAKER, 0x4653)
        if not entry:
            return False
        tag, kind, count = struct.unpack('<HHI', m.mu.mem_read(entry+8, 8))
        value = m.word(entry+0x10)
        if (tag, kind, count) != (0x4653, 7, n) or not value:
            return False
        data, length = m.word(value+8), m.word(value+12)
        return bool(data and length == n and bytes(m.mu.mem_read(data, n)) == bytes(n))

    def transaction(self, m, n):
        m.mu.mem_write(N.SOURCE, bytes(n))
        status = m.call(GATE, T.BUILDER, N.MAKER, N.SOURCE, n)
        if status == 2:
            raise RuntimeError('rollback failed: no safe continuation established')
        self.assertIn(status, (0, 1))
        return bool(status)

    def test_native_remove_restores_serialized_baseline(self):
        m = self.machine()
        baseline = m.output()
        self.assertTrue(self.transaction(m, 560))
        self.assertTrue(self.stored(m, 560))
        self.assertEqual(m.output()[:2], (0x13800, 0x13800))
        frees_before = len(m.frees)
        m.call(0xC00BAA98, N.MAKER, 0x4653)
        self.assertFalse(m.call(0xC00BAA10, N.MAKER, 0x4653))
        self.assertGreater(len(m.frees), frees_before)
        self.assertEqual(m.output(), baseline)

    def test_missing_storage_is_detected_and_native_rollback_restores_bytes(self):
        # Descriptor object, data allocation and entry allocation failures.
        for nth in (0, 1, 2):
            with self.subTest(allocation=nth):
                m = self.machine()
                baseline = m.output()
                m.fail_at = len(m.allocations)+nth
                self.assertFalse(self.transaction(m, 560))
                m.fail_at = None
                self.assertEqual(m.output(), baseline)

    def test_oversize_and_wrong_baseline_refuse_before_insertion(self):
        m = self.machine()
        baseline = m.output()
        allocations = len(m.allocations)
        self.assertFalse(self.transaction(m, 561))
        self.assertEqual(len(m.allocations), allocations)
        self.assertEqual(m.output(), baseline)
        # A late producer can add bytes after a mode-0 check: existing payload
        # length is not an immutable bound on the eventual builder.
        m.mu.mem_write(N.SOURCE, bytes(6))
        m.add(tag=0x4654, count=6)
        allocations = len(m.allocations)
        self.assertFalse(self.transaction(m, 560))
        self.assertEqual(len(m.allocations), allocations)
        self.assertFalse(m.call(0xC00BAA10, N.MAKER, 0x4653))

    def test_mutated_removal_is_detected_not_treated_as_cancel(self):
        m = self.machine()
        m.fail_at = len(m.allocations)+1
        # Skip the native vector erase; the released entry remains visible.
        self.assertEqual(m.word(0xC00BAAE4), 0xEBFFFE93)
        m.write(0xC00BAAE4, 0xE1A00000)
        m.mu.ctl_remove_cache(0xC00BAAE4, 0xC00BAAE8)
        with self.assertRaisesRegex(RuntimeError, 'rollback failed'):
            self.transaction(m, 560)

    def test_later_native_add_invalidates_an_earlier_padding_decision(self):
        m = self.machine()
        self.assertTrue(self.transaction(m, 560))
        # Counterexample to treating a successful earlier check as final-state
        # evidence. Not a claim that this particular extra tag occurs live.
        m.mu.mem_write(N.SOURCE, bytes(6))
        m.add(tag=0x4654, count=6)
        self.assertEqual(m.output()[:2], (0x13812, 0x13C00))

    def test_writer_zero_is_published_not_immediately_branched_as_error(self):
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_SP, UC_ARM_REG_PC
        m = self.machine()
        record = T.DATA+0x31000
        m.mu.reg_write(UC_ARM_REG_R0, 0)
        m.mu.reg_write(UC_ARM_REG_R4, record)
        m.mu.reg_write(UC_ARM_REG_SP, T.STACK+0xFE00)
        m.write(record+0x14C, 0xDEADBEEF)
        m.write(0xC358E9E4, 0xDEADBEEF)
        m.mu.emu_start(0xC03790CC, 0xC03790E4, count=1000)
        self.assertEqual(m.mu.reg_read(UC_ARM_REG_PC), 0xC03790E4)
        self.assertEqual(m.word(record+0x14C), 0)
        self.assertEqual(m.word(0xC358E9E4), 0)


if __name__ == '__main__':
    unittest.main()
