"""M1 bounded refusal, NOT a working synchronized transport or hardware test.

Legacy lifecycle tests retain their three expected failures. This separate
profile admits no submissions; normal mode5 transport is intentionally refused.
"""
import hashlib
import struct
import unittest

import test_fpl_worker_dispatch as d
from test_fpl_worker_lifecycle import Lifecycle, REPLACEMENT

if d.Uc is not None:
    from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_SP, UC_ARM_REG_LR


@unittest.skipIf(d.Uc is None, 'needs unicorn')
class ClosedAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.defines = d.get_camera('fp-l-3.02').loader_defines()
        candidate = cls.defines + ['FPSUP_USB_CLOSED_ADMISSION=1']
        cls.blob = d.assemble(d.SOURCE, candidate)
        cls.labels = d.symbols(d.SOURCE, candidate)

    def trial(self, *, mutation=None, **kwargs):
        blob = bytearray(self.blob)
        if mutation:
            # Remove exactly the refusal branch, leaving the actual legacy body.
            site = self.labels[mutation]
            self.assertEqual(struct.unpack_from('<I', blob, site)[0] >> 24, 0xEA)
            struct.pack_into('<I', blob, site, 0xE320F000)  # ARM NOP
        cam = Lifecycle(self, bytes(blob), self.labels, **kwargs)
        cam.transport_access = []

        def access(mu, kind, address, size, value, user):
            # Neither tables/driver state nor descriptors may be read or written.
            if (0xC31E1000 <= address < 0xC31E2000 or
                    d.OUT_TRB <= address < d.OUT_TRB + 0x1000):
                cam.transport_access.append((kind, address, size))
        cam.mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, access)
        return cam

    def excluded(self, cam):
        self.assertEqual(cam.transport_access, [])
        self.assertEqual(cam.lines, [])
        self.assertEqual(cam.transfers, [])
        self.assertFalse(set(cam.calls) & {'END', 'START', 'START_OUT',
                                          'WAIT', 'WAIT_OUT', 'SHRUN'})

    def test_all_modes_closed_even_with_ready_state_and_pending_cleanup(self):
        for mode in (0, 4, 5, 8, 12, 13, 18):
            with self.subTest(mode=mode):
                cam = self.trial(mode=mode)
                cam.word(d.STATE + 8, 1)
                cam.run('next_round')
                self.excluded(cam)
                self.assertEqual(cam.word(d.STATE + 8), 0)
                self.assertEqual(cam.word(d.STATE + 0x38), 0x534F4C43)
                self.assertEqual(cam.calls, ['DELAY'])
                self.assertEqual(cam.word(d.STATE + 0x28), 1)

    def test_no_reopen_after_delay_with_same_address_reconfiguration(self):
        cam = self.trial()
        cam.run('next_round')
        # Synthetic reconfiguration while the worker yields: ready again, same
        # descriptor address, new contents and a legacy cleanup marker. These
        # are not a ticket or permission to reopen, including after many rounds.
        for _ in range(3):
            cam.word(d.OUT_TRB + 12, 0x812)
            cam.word(d.STATE + 8, 1)
            cam.round_entries = 0
            cam.stopped = False
            cam.run('next_round')
        self.excluded(cam)
        self.assertEqual(cam.word(d.STATE + 0x28), 4)

    def test_unowned_wait_never_calls_stock_wait_or_reads_replacement(self):
        for event in ('complete', 'cancel', 'replace'):
            for clear in (False, True):
                with self.subTest(event=event, clear=clear):
                    cam = self.trial(event=event)
                    if clear:
                        cam.word(d.TRB_TABLE, REPLACEMENT)
                    self.assertEqual(cam.wait(), 0xFFFFFFFF)
                    self.excluded(cam)
                    self.assertEqual(cam.out_waits, 0)

    def test_arm_and_claim_primitives_refuse_without_transport_access(self):
        for entry in ('arm_out', 'arm_in', 'arm_in_block', 'out_owned'):
            with self.subTest(entry=entry):
                cam = self.trial()
                cam.word(d.STATE + 8, 1)
                cam.run(entry)
                self.excluded(cam)
                self.assertEqual(cam.mu.reg_read(UC_ARM_REG_R0), 0xFFFFFFFF)

    def test_closed_round_does_not_consume_legacy_swap_request(self):
        cam = self.trial()
        cam.word(d.POOL + 0x1080, 0x50415753)
        cam.word(d.POOL + 0x10C0, 0xDEADBEEF)
        cam.run('next_round')
        self.excluded(cam)
        self.assertEqual(cam.word(d.POOL + 0x1080), 0x50415753)
        self.assertEqual(cam.word(d.POOL + 0x10C0), 0xDEADBEEF)

    def test_stale_dispatch_memw_and_cleanup_paths_have_no_rights(self):
        for entry in ('got_command', 'mem_write', 'mem_write_abort', 'mem_write_lost'):
            with self.subTest(entry=entry):
                cam = self.trial()
                cam.word(d.STATE + 8, 1)
                cam.word(d.TRB_TABLE, REPLACEMENT)
                cam.run(entry)
                self.excluded(cam)
                self.assertEqual(cam.word(d.STATE + 8), 0)

    def test_spawn_refuses_without_allocating_publishing_or_starting(self):
        cam = self.trial()
        cam.mu.mem_write(d.CODE, self.blob)  # spawn is outside relocated wbody
        publication = bytes(cam.mu.mem_read(d.PUBLICATION, 12))
        cam.mu.reg_write(UC_ARM_REG_LR, d.STACK + 0xF000)
        cam.mu.emu_start(d.CODE + self.labels['spawn'], d.CODE + len(self.blob), count=10)
        self.assertTrue(cam.stopped)
        self.assertEqual(cam.calls, [])
        self.assertEqual(bytes(cam.mu.mem_read(d.PUBLICATION, 12)), publication)
        self.assertEqual(cam.mu.reg_read(UC_ARM_REG_SP), d.STACK + 0x8000)

    def test_mutations_expose_real_legacy_cancellation_and_replacement(self):
        for event in ('cancel', 'replace'):
            with self.subTest(event=event):
                cam = self.trial(mutation='wait_done', event=event)
                self.assertEqual(cam.wait(), 0)  # the actual old false success
                self.assertEqual(cam.out_waits, 1)
                with self.assertRaises(AssertionError):
                    self.excluded(cam)

    def test_cleanup_branch_mutation_ends_current_replacement(self):
        cam = self.trial(mutation='mem_write_abort')
        cam.word(d.TRB_TABLE, REPLACEMENT)
        cam.run('mem_write_abort')
        self.assertIn('END', cam.calls)
        with self.assertRaises(AssertionError):
            self.excluded(cam)

    def test_admission_branch_mutation_exposes_legacy_driver_reads(self):
        cam = self.trial(mutation='next_round', mode=4)
        cam.run('next_round')
        self.assertTrue(cam.transport_access)
        with self.assertRaises(AssertionError):
            self.excluded(cam)

    def test_legacy_pong_fingerprint_and_explicit_zero_are_unchanged(self):
        legacy = d.assemble(d.SOURCE, self.defines)
        labels = d.symbols(d.SOURCE, self.defines)
        body = legacy[labels['wbody']:labels['wbody_end']]
        self.assertEqual(len(body), 3572)
        self.assertEqual(legacy, d.assemble(
            d.SOURCE, self.defines + ['FPSUP_USB_CLOSED_ADMISSION=0']))
        # Compare to the independent reviewed live allowlist; never replace it
        # with the candidate's hash or teach the updater to accept this profile.
        from fpl_swapworker import supported_hashes, reviewed_body
        self.assertIn(hashlib.sha256(body).hexdigest(), supported_hashes())
        self.assertEqual(body, reviewed_body(True))
        self.assertEqual(len(reviewed_body(False)), 3572)
        candidate = self.blob[self.labels['wbody']:self.labels['wbody_end']]
        self.assertNotIn(hashlib.sha256(candidate).hexdigest(), supported_hashes())


if __name__ == '__main__':
    unittest.main()
