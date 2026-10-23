"""Bounded real-worker lifecycle regressions; no camera or official MAIN needed.

Run from fp_usb_shell: python3 -B -m unittest -v test_fpl_worker_lifecycle
Requires the dispatch harness's clang ARM assembler and Unicorn. Three desired
behaviors are expected failures on the current worker, not implemented guards.
Firmware WAIT/DMA effects are synthetic; these tests do not execute teardown,
prove a hardware failure cause, or establish race-free lifecycle ownership.
"""
import struct
import unittest

import test_fpl_worker_dispatch as d

if d.Uc is not None:
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP

MODE = 0xC3077794
CONFIGURED, BACKEND = 0xC31E1D6C, 0xC3032A92
USB_STATE, DALEPENA, DCTL = 0xC31E1B48, 0x2100C720, 0x2100C704
REPLACEMENT = d.OUT_TRB + 0x100


class Lifecycle(d.Dispatch):
    """Extend the existing harness locally, including the previously skipped gate."""
    def __init__(self, test, blob, labels, *, mode=5, event='complete', suspended=False):
        self.event = event
        self.request = d.frame(3, b'shl echo lifecycle\0')
        self.round_entries = 0
        self.out_waits = 0
        self.out_starts = 0
        super().__init__(test, blob, labels, self.request, output=b'lifecycle reply\n')
        for page in (MODE & ~0xFFF, BACKEND & ~0xFFF, DCTL & ~0xFFF):
            self.mu.mem_map(page, 0x1000)
        self.word(MODE, mode)
        self.mu.mem_write(CONFIGURED, b'\x01')
        self.mu.mem_write(BACKEND, b'\x01')
        self.word(USB_STATE, 4 if suspended else 2)
        self.word(DALEPENA, 0xA7)
        self.word(DCTL, 0x80000000)
        self.word(0xC31E1E08, 1)
        self.mu.mem_write(0xC31E1C98, struct.pack('<8I', 1, 0, 1, 0, 1, 1, 2, 0))
        # Initialize independent descriptors; old submission belongs to OUT_TRB.
        self.mu.mem_write(d.OUT_TRB, struct.pack('<4I', d.POOL - 0x40000000,
                                               0, 0x4000, 0x813))
        self.mu.mem_write(REPLACEMENT, struct.pack('<4I', 0x06000000, 0, 0, 0x812))

    def hook(self, mu, address, size, user):
        if address == self.at('next_round'):
            self.round_entries += 1
            if self.entry == 'next_round' and self.round_entries == 1:
                return  # execute the actual first gate; base stops the next round
        if address == d.FW['START'] and mu.reg_read(UC_ARM_REG_R0) == 2:
            self.calls.append('START_OUT')
            self.alignments.append(('START_OUT', mu.reg_read(UC_ARM_REG_SP) % 8))
            self.out_starts += 1
            self.t.assertEqual(self.word(d.TRB_TABLE), d.OUT_TRB)
            self.t.assertEqual(self.word(d.OUT_TRB + 12), 0x813)
            self.t.assertEqual(self.word(d.OUT_TRB), d.POOL - 0x40000000)
            # StartTransfer succeeds; DMA completion occurs only in WAIT below.
            self.word(d.OUT_BUSY, 1)
            self.ret(0)
            return
        if address == d.FW['WAIT'] and mu.reg_read(UC_ARM_REG_R0) == 1:
            self.calls.append('WAIT_OUT')
            self.alignments.append(('WAIT_OUT', mu.reg_read(UC_ARM_REG_SP) % 8))
            self.out_waits += 1
            self.t.assertEqual(mu.reg_read(UC_ARM_REG_R1), 20)
            self.t.assertEqual(self.out_waits, 1, 'scenario unexpectedly waited twice')
            self.t.assertEqual(self.word(d.OUT_TRB + 12) & 1, 1)
            if self.event == 'complete':
                mu.mem_write(d.POOL, self.request)
                self.word(d.OUT_TRB + 12, 0x812)
                self.ret(0)
            elif self.event == 'cancel':
                # Synthetic cancellation outcome: descriptor returned, no data.
                # The separate official-firmware audit proves -4 calls teardown;
                # it does not prove teardown clears this TRB on real hardware.
                self.word(d.OUT_TRB + 12, 0x812)
                self.ret(-4)
            elif self.event == 'replace':
                # Different pointer is already HWO-clear. Original stays armed.
                self.word(d.TRB_TABLE, REPLACEMENT)
                self.ret(0)
            else:
                raise AssertionError(f'unknown event {self.event}')
            return
        super().hook(mu, address, size, user)

    def wait(self):
        self.mu.reg_write(UC_ARM_REG_R0, 1)
        self.mu.reg_write(UC_ARM_REG_R1, 40)
        self.run('wait_done')
        return self.mu.reg_read(UC_ARM_REG_R0)


@unittest.skipIf(d.Uc is None, 'needs unicorn')
class WorkerLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defines = d.get_camera('fp-l-3.02').loader_defines()
        cls.blob = d.assemble(d.SOURCE, defines)
        cls.labels = d.symbols(d.SOURCE, defines)

    def trial(self, **kwargs):
        return Lifecycle(self, self.blob, self.labels, **kwargs)

    def assert_excluded(self, cam):
        self.assertEqual(cam.out_starts, 0, 'foreign mode armed OUT')
        self.assertEqual(cam.lines, [], 'foreign mode dispatched SHL')
        self.assertEqual(cam.transfers, [], 'foreign mode submitted reply')
        self.assertEqual(cam.word(d.OUT_BUSY), 0, 'foreign mode claimed OUT_BUSY')

    def assert_wait_rejected(self, result):
        self.assertNotEqual(result, 0, 'lost transfer reported success')

    def test_mode5_real_gate_arm_dispatch_and_reply(self):
        cam = self.trial().run('next_round')
        self.assertEqual((cam.round_entries, cam.out_starts, cam.out_waits), (2, 1, 1))
        self.assertEqual(cam.lines, [b'echo lifecycle'])
        self.assertEqual(len(cam.transfers), 1)
        self.assertEqual(cam.transfers[0][1][20:35], b'lifecycle reply')
        self.assertEqual(cam.word(d.STATE + 0x20), 1)
        self.assertEqual(cam.word(d.STATE + 0x24), 0)
        self.assertTrue(all(a == 0 for _, a in cam.alignments), cam.alignments)

    @unittest.expectedFailure
    def test_mode4_identical_endpoint_mask_must_not_serve(self):
        # All other state deliberately equals the working control-mode fixture.
        # This isolates missing active-mode gating, not a realistic whole MSC init.
        self.assert_excluded(self.trial(mode=4).run('next_round'))

    def test_mode_exclusion_oracle_control_uses_real_suspend_gate(self):
        cam = self.trial(mode=4, suspended=True).run('next_round')
        self.assert_excluded(cam)
        self.assertEqual(cam.word(d.STATE + 0x28), 1)
        self.assertEqual(cam.out_waits, 0)
        # Same oracle must reject an actual mode-5 serving trace.
        with self.assertRaisesRegex(AssertionError, 'foreign mode armed OUT'):
            self.assert_excluded(self.trial().run('next_round'))

    def test_mode4_fixture_executes_without_harness_errors(self):
        # Keep setup/stack/budget failures outside expectedFailure too. This
        # remains valid if a future guard holds instead of serving the request.
        cam = self.trial(mode=4).run('next_round')
        self.assertEqual(cam.word(MODE), 4)
        self.assertEqual(cam.word(DALEPENA), 0xA7)
        self.assertEqual(cam.round_entries, 2)
        self.assertEqual(cam.word(d.STATE + 0x24), 0)

    def test_normal_pinned_out_completion_returns_success(self):
        cam = self.trial()
        self.assertEqual(cam.wait(), 0)
        self.assertEqual(cam.word(d.TRB_TABLE), d.OUT_TRB)
        self.assertEqual(cam.word(d.OUT_TRB + 12) & 1, 0)
        self.assertEqual(cam.out_waits, 1)

    @unittest.expectedFailure
    def test_minus4_with_hwo_clear_must_not_be_completion(self):
        self.assert_wait_rejected(self.trial(event='cancel').wait())

    @unittest.expectedFailure
    def test_replacement_clear_trb_must_not_complete_old_submission(self):
        self.assert_wait_rejected(self.trial(event='replace').wait())

    def test_failure_scenarios_reach_injected_wait_without_harness_errors(self):
        # Ordinary (non-xfail) runs ensure expectedFailure cannot hide a broken
        # hook, unexpected call, budget exhaustion or stack failure. No assertion
        # here demands the current buggy return value remain buggy after a fix.
        for event in ('cancel', 'replace'):
            with self.subTest(event=event):
                cam = self.trial(event=event)
                cam.wait()
                self.assertEqual(cam.out_waits, 1)
                self.assertEqual(cam.calls, ['WAIT_OUT'])
                self.assertEqual(cam.lines, [])
                self.assertEqual(cam.transfers, [])
                if event == 'replace':
                    self.assertEqual(cam.word(d.TRB_TABLE), REPLACEMENT)
                    self.assertEqual(cam.word(d.OUT_TRB + 12) & 1, 1)
                    self.assertEqual(cam.word(REPLACEMENT + 12) & 1, 0)
                else:
                    self.assertEqual(cam.word(d.TRB_TABLE), d.OUT_TRB)
                    self.assertEqual(cam.word(d.OUT_TRB + 12) & 1, 0)

    def test_wait_oracle_sensitivity_with_synthetic_return_mutation(self):
        # Not a proposed fix: force *all* HWO-clear returns to fail. This makes
        # both rejection oracles pass and deliberately breaks normal completion.
        mutated = bytearray(self.blob)
        begin, end = self.labels['wait_done'], self.labels['mem_refuse']
        pattern = struct.pack('<2I', 0xE3A00000, 0xE8BD8070)  # mov r0,0; pop
        self.assertEqual(mutated[begin:end].count(pattern), 1)
        site = mutated.index(pattern, begin, end)
        struct.pack_into('<I', mutated, site, 0xE3E00000)  # mvn r0,0
        for event in ('cancel', 'replace'):
            cam = Lifecycle(self, bytes(mutated), self.labels, event=event)
            self.assert_wait_rejected(cam.wait())
        cam = Lifecycle(self, bytes(mutated), self.labels)
        with self.assertRaises(AssertionError):
            self.assertEqual(cam.wait(), 0)
        with self.assertRaisesRegex(AssertionError, 'lost transfer reported success'):
            self.assert_wait_rejected(0)


if __name__ == '__main__':
    unittest.main()
