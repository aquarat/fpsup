"""Scratch-only fp L guard experiment; never an installable/allowlisted body.

Run: python3 -B -m unittest -v test_fpl_worker_guards
Real relocated worker instructions, mocked firmware/DMA, no lifecycle exclusion.
"""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

import test_fpl_worker_dispatch as d
import test_fpl_worker_lifecycle as life


def variant(*, gate=True, wait_status=True, pointer=True):
    source = d.SOURCE.read_text()
    source = source.replace('#include "../firmware/worker.h"',
                            f'#include "{d.SOURCE.parent.parent / "firmware/worker.h"}"')

    def replace(old, new, count=1):
        nonlocal source
        assert source.count(old) == count, (old, source.count(old))
        source = source.replace(old, new)

    # PC-relative address with a movw delta: all uses precede the owned words.
    pin_address = ('    movw    r2, #:lower16:(guard_pins - . - 12)\n'
                   '    add     r2, pc, r2\n')
    # Pin at descriptor preparation, NOT on entry to wait_done. OUT and IN
    # must be separate: MEMW sends READY on IN before waiting for data OUT.
    replace('    ldr     r7, [r0]\n    str     r5, [r7]',
            '    ldr     r7, [r0]\n' + pin_address +
            '    str     r7, [r2, #4]\n    str     r5, [r7]', 3)
    # First occurrence is command OUT; the other two are IN.
    start = source.index('arm_out:\n')
    pos = source.index('    str     r7, [r2, #4]', start)
    source = source[:pos] + source[pos:].replace('    str     r7, [r2, #4]',
                                               '    str     r7, [r2]', 1)
    replace('    ldr     r1, [r1]\n    str     r0, [r1]',
            '    ldr     r1, [r1]\n' + pin_address +
            '    str     r1, [r2]\n    str     r0, [r1]')
    if gate:
        replace('no_swap:\n', 'no_swap:\n    bl guard_ready\n    cmp r0, #0\n    bne hold\n')
        for label in ('arm_out', 'arm_in', 'arm_in_block'):
            old = label + ':\n    push    {r4, r5, r6, r7, r12, lr}\n'
            replace(old, old + '    bl guard_ready\n    cmp r0, #0\n'
                    '    popne {r4, r5, r6, r7, r12, pc}\n')
        replace('1:  mov     r0, #TO_BUS\n',
                '1:  bl guard_ready\n    cmp r0, #0\n    bne fault\n'
                '    mov     r0, #TO_BUS\n')
    begin, end = source.index('wait_done:\n'), source.index('/* r0 = refusal code:')
    source = source[:begin] + '''wait_done:
    push {r4, r5, r6, r7, r8, lr}
    mov r4, r0
    mov r5, r1
    LDA r6, TRB_OUT
''' + pin_address + '''    cmp r4, #LOG_OUT
    beq guard_wait_out
    LDA r6, TRB_IN
    add r2, r2, #4
guard_wait_out:
    ldr r7, [r2]
guard_wait_loop:
''' + ('''    ldr r0, [r6]
    cmp r0, r7
    bne guard_wait_bad
    cmp r7, #0
    beq guard_wait_bad
    tst r7, #15
    bne guard_wait_bad
    ldr r0, [r7, #12]
''' if pointer else '''    ldr r0, [r6]
    ldr r0, [r0, #12]
''') + '''    tst r0, #1
    moveq r0, #0
    beq guard_wait_return
    cmp r5, #0
    ble guard_wait_bad
    mov r0, r4
    mov r1, #WAIT_SLICE
    LDA r12, FN_WAIT
    blx r12
''' + ('''    cmp r0, #0
    bne guard_wait_return
''' if wait_status else '') + '''    sub r5, r5, #WAIT_SLICE
    b guard_wait_loop
guard_wait_bad:
    mvn r0, #0
guard_wait_return:
    pop {r4, r5, r6, r7, r8, pc}

''' + source[end:]
    replace('wbody_end:\n', '''guard_ready:
    LDA r0, 0xC3077794
    ldr r0, [r0]
    cmp r0, #5
    bne guard_not_ready
    LDA r0, 0xC31E1D6C
    ldrb r0, [r0]
    cmp r0, #1
    bne guard_not_ready
    LDA r0, 0xC3032A92
    ldrb r0, [r0]
    cmp r0, #1
    bne guard_not_ready
    LDA r0, 0x2100C704
    ldr r0, [r0]
    tst r0, #0x80000000
    moveq r0, #1
    movne r0, #0
    bx lr
guard_not_ready:
    mov r0, #1
    bx lr
guard_pins:
    .word 0, 0
wbody_end:
''')
    return source


def build(**options):
    with tempfile.TemporaryDirectory(prefix='fpl-guard-') as directory:
        path = Path(directory) / 'worker.S'
        path.write_text(variant(**options))
        defines = d.get_camera('fp-l-3.02').loader_defines()
        return d.assemble(path, defines), d.symbols(path, defines)


class GuardCamera(life.Lifecycle):
    def hook(self, mu, address, size, user):
        if address == d.FW['WAIT'] and mu.reg_read(d.UC_ARM_REG_R0) == 2:
            # The base harness returns -1 even on its successful IN completion.
            # Strict status propagation intentionally rejects that old behavior.
            self.calls.append('WAIT_IN')
            self.alignments.append(('WAIT_IN', mu.reg_read(d.UC_ARM_REG_SP) % 8))
            self.word(d.IN_TRB + 12, self.word(d.IN_TRB + 12) & ~1)
            self.ret(0)
            return
        super().hook(mu, address, size, user)

    def wait(self):
        # Standalone wait tests model the pointer recorded by an earlier arm.
        self.word(self.at('guard_pins'), d.OUT_TRB)
        return super().wait()


@unittest.skipIf(d.Uc is None, 'needs unicorn')
class GuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.labels = build()

    def trial(self, **kwargs):
        return GuardCamera(self, self.blob, self.labels, **kwargs)

    def test_foreign_modes_and_readiness_hold(self):
        for mode in (0, 4, 8, 12, 13, 18):
            cam = self.trial(mode=mode).run('next_round')
            self.assertEqual((cam.out_starts, cam.lines, cam.transfers), (0, [], []))
            self.assertEqual(cam.word(d.OUT_BUSY), 0)
        for address, value, byte in ((life.CONFIGURED, 0, True),
                                     (life.CONFIGURED, 2, True),
                                     (life.BACKEND, 0, True), (life.DCTL, 0, False)):
            cam = self.trial()
            if byte:
                cam.mu.mem_write(address, bytes([value]))
            else:
                cam.word(address, value)
            cam.run('next_round')
            self.assertEqual((cam.out_starts, cam.lines, cam.transfers), (0, [], []))

    def test_cancel_propagates_exact_minus4(self):
        cam = self.trial(event='cancel')
        self.assertEqual(cam.wait(), 0xFFFFFFFC)
        self.assertEqual(cam.out_waits, 1)

    def test_any_nonzero_wait_status_survives_clear_hwo(self):
        class StatusCamera(GuardCamera):
            def ret(self, value=0):
                super().ret(result if value == -4 else value)
        for result in (-1, -5, 7):
            cam = StatusCamera(self, self.blob, self.labels, event='cancel')
            self.assertEqual(cam.wait(), result & 0xFFFFFFFF)

    def test_arm_helpers_recheck_readiness_before_descriptor_or_cleanup(self):
        for entry in ('arm_out', 'arm_in', 'arm_in_block'):
            cam = self.trial(mode=4)
            cam.word(d.STATE + 8, 1)
            before = bytes(cam.mu.mem_read(d.OUT_TRB, 32))
            cam.run(entry)
            self.assertNotEqual(cam.mu.reg_read(d.UC_ARM_REG_R0), 0)
            self.assertEqual(cam.calls, [])
            self.assertEqual(bytes(cam.mu.mem_read(d.OUT_TRB, 32)), before)
            self.assertEqual(cam.word(d.OUT_BUSY), 0)

    def test_wait_preserves_callee_saved_registers(self):
        cam = self.trial()
        registers = (d.UC_ARM_REG_R4, d.UC_ARM_REG_R5, d.UC_ARM_REG_R6,
                     d.UC_ARM_REG_R7, d.UC_ARM_REG_R8, d.UC_ARM_REG_R9,
                     d.UC_ARM_REG_R10, d.UC_ARM_REG_R11)
        before = [cam.mu.reg_read(r) for r in registers]
        self.assertEqual(cam.wait(), 0)
        self.assertEqual([cam.mu.reg_read(r) for r in registers], before)
        self.assertTrue(all(a == 0 for _, a in cam.alignments))

    def test_replaced_descriptor_rejected(self):
        cam = self.trial(event='replace')
        self.assertNotEqual(cam.wait(), 0)
        self.assertEqual(cam.word(d.OUT_TRB + 12) & 1, 1)
        self.assertEqual(cam.word(life.REPLACEMENT + 12), 0x812)

    def test_replacement_before_wait_entry_rejected(self):
        cam = self.trial()
        cam.word(d.TRB_TABLE, life.REPLACEMENT)
        self.assertNotEqual(cam.wait(), 0)
        self.assertEqual(cam.out_waits, 0)

    def test_normal_completion_and_shl(self):
        self.assertEqual(self.trial().wait(), 0)
        cam = self.trial().run('next_round')
        self.assertEqual(cam.lines, [b'echo lifecycle'])
        self.assertEqual(cam.word(d.STATE + 0x20), 1)
        self.assertEqual(cam.word(d.STATE + 0x24), 0)
        self.assertEqual(cam.transfers[0][1][20:35], b'lifecycle reply')
        self.assertTrue(all(a == 0 for _, a in cam.alignments))

    def test_mem1_caps_and_read_positive(self):
        for command in (9, 7):
            cam = self.trial()
            address = d.POOL + 0x10000
            data = bytes(range(256)) * 4
            cam.request = d.frame(command, struct.pack('<3I', address, len(data), 0)
                                  if command == 7 else b'')
            cam.mu.mem_write(address, data)
            cam.run('next_round')
            self.assertEqual(cam.word(d.STATE + 0x20), 1)
            self.assertEqual(cam.word(d.STATE + 0x24), 0)
            self.assertTrue(all(a == 0 for _, a in cam.alignments))
            if command == 7:
                self.assertEqual(cam.transfers, [(address, data)])
            else:
                payload = b''.join(t[1][20:20 + struct.unpack_from('<H', t[1], 12)[0]]
                                   for t in cam.transfers)
                self.assertEqual(payload, struct.pack('<4sIII', b'MEM1', 0xFFFC00,
                                                     d.POOL, d.POOL_SIZE) + bytes(96))

    def test_each_guard_mutation_breaks_desired_oracle(self):
        for option, event in (('gate', 'complete'), ('wait_status', 'cancel'),
                              ('pointer', 'replace')):
            blob, labels = build(**{option: False})
            cam = GuardCamera(self, blob, labels, mode=4 if option == 'gate' else 5,
                              event=event)
            if option == 'gate':
                cam.run('next_round')
                with self.assertRaises(AssertionError):
                    self.assertEqual(cam.out_starts, 0)
            else:
                with self.assertRaises(AssertionError):
                    self.assertNotEqual(cam.wait(), 0)

    def test_body_capacity_is_not_old_allocation(self):
        body = self.blob[self.labels['wbody']:self.labels['wbody_end']]
        self.assertGreater(len(body), 3572)
        self.assertEqual(self.labels['guard_pins'] + 8, self.labels['wbody_end'])
        self.assertEqual(struct.unpack_from('<I', self.blob,
                                           self.labels['mem_body_len'])[0], len(body))
        print('scratch guard body:', len(body), hashlib.sha256(body).hexdigest())


if __name__ == '__main__':
    unittest.main()
