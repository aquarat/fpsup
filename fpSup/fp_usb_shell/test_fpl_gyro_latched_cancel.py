"""Offline actual ARM cancellation, profile and mutation tests; no transport."""
from pathlib import Path
from dataclasses import replace
import io
import struct
import tempfile
import unittest
from unittest.mock import patch

import fpl_gyro_latched as lat
import test_fpl_gyro_latched as fixture


class Cancellation(unittest.TestCase):
    def setUp(self):
        self.plan = lat.layout(fixture.CAPS, fixture.PUB, 1200)
        self.code, self.syms = lat.code_for(self.plan, 1200, runtime=True, cancel=True)

    def run_capture(self, event=None, *, code=None, **kwargs):
        fired = []
        def inject(m, kind, at, batch):
            if event and not fired and event(kind, at, batch):
                m.mem_write(self.plan.code+self.syms['g_cancel_request'], struct.pack('<I', 7))
                fired.append(True)
        result = fixture.emulate(code or self.code, self.syms, self.plan, inject=inject, **kwargs)
        state, output, actual, _, delays, _ = result
        lat.verify_code(code or self.code, actual, self.syms, cancel=True)
        report = lat.decode(state, output, 1200, cancel=True)
        if event:
            self.assertTrue(fired)
            self.assertEqual(struct.unpack_from('<I', actual, self.syms['g_cancel_request'])[0], 7)
        self.assertEqual(report['delay_calls'], len(delays))
        cursor = report['batches'][-1]['consumed_cursor'] if report['batches'] else lat.UNARMED
        self.assertEqual(struct.unpack_from('<I', actual, self.syms['g_ghead'])[0], cursor)
        self.assertEqual(output[:report['appended_records']*8], b''.join(v for _, v in result[3]))
        return report, result

    def at(self, symbol):
        return self.plan.code+self.syms[symbol]

    def test_preentry_zero_rows_and_default_decoder_refuses(self):
        report, result = self.run_capture(lambda k, a, b: k == 'execute' and a == self.plan.code)
        self.assertEqual((report['status_code'], len(report['batches']), report['appended_records']), (101, 0, 0))
        with self.assertRaises(RuntimeError):
            lat.decode(result[0], result[1], 1200)

    def test_every_prebatch_and_postledger_boundary(self):
        for row in range(20):
            for symbol in ('loop', 'cancel_after_ledger'):
                with self.subTest(row=row, symbol=symbol):
                    # fixture increments batch after the injection callback at loop.
                    target_batch = row-1 if symbol == 'loop' else row
                    report, _ = self.run_capture(lambda k, a, b: k == 'execute' and
                                                a == self.at(symbol) and b == target_batch)
                    n = row if symbol == 'loop' else row+1
                    self.assertEqual(report['status_code'], 101)
                    self.assertEqual(len(report['batches']), n)
                    self.assertEqual(report['delay_calls'], row)
                    self.assertEqual(report['proven_valid_records'], 0)

    def test_during_drain_keeps_whole_batch_and_during_delay_checks_next_boundary(self):
        report, _ = self.run_capture(lambda k, a, b: k == 'read' and b == 1 and
                                    fixture.R+4 <= a < fixture.R+4804)
        self.assertEqual(len(report['batches']), 2)
        self.assertEqual(report['appended_records'], 50)
        self.assertEqual(report['conditional_prefix_records'], 50)
        for row in (0, 1, 18, 19):
            report, _ = self.run_capture(lambda k, a, b: k == 'execute' and a == fixture.DELAY and b == row)
            self.assertEqual(len(report['batches']), row+1)
            self.assertEqual(report['status_code'], 100 if row == 19 else 101)

    def test_errors_win_and_no_cancel_runs_twenty_batches(self):
        report, _ = self.run_capture(lambda k, a, b: k == 'execute' and a == self.at('row_done'),
                                    descriptor=0)
        self.assertEqual(report['status_code'], 10)
        report, _ = self.run_capture(lambda k, a, b: k == 'execute' and a == self.at('row_done') and b == 1,
                                    advance=550)
        self.assertEqual(report['status_code'], 4)
        report, _ = self.run_capture()
        self.assertEqual((report['status_code'], len(report['batches'])), (100, 20))
        report, _ = self.run_capture(lambda k, a, b: k == 'execute' and
                                    a == self.at('row_done') and b == 3, step=500, advance=0)
        self.assertEqual(report['status_code'], 5)

    def test_request_after_result_publication_does_not_restart(self):
        # Initial state clearing also writes this address: inject specifically
        # at final batch to distinguish a late request from a pre-entry request.
        report, _ = self.run_capture(lambda k, a, b: k == 'write' and a == self.plan.state and b == 19)
        self.assertEqual(report['status_code'], 100)
        self.assertEqual(len(report['batches']), 20)

    def test_mask_is_exact_and_cancel_requires_optin(self):
        actual = bytearray(self.code)
        struct.pack_into('<I', actual, self.syms['g_cancel_request'], 1)
        with self.assertRaises(RuntimeError):
            lat.verify_code(self.code, actual, self.syms)
        lat.verify_code(self.code, actual, self.syms, cancel=True)
        mutable = {self.syms[n]+i for n in (*lat.MUTABLE, 'g_cancel_request') for i in range(4)}
        for offset in range(4096):
            bad = bytearray(actual); bad[offset] ^= 1
            if offset in mutable:
                lat.verify_code(self.code, bad, self.syms, cancel=True)
            else:
                with self.assertRaises(RuntimeError):
                    lat.verify_code(self.code, bad, self.syms, cancel=True)

    def test_alternate_profile_and_missing_inputs(self):
        core = Path(__file__).resolve().parents[1]/'gyro/latched_capture.inc.S'
        inputs = ['LAT_DESC_SLOT=0xC31E23CC', 'LAT_DESC_ROOT=0x2E006004',
                  'LAT_RING_BASE=0x2E00644C', 'LAT_DELAY=0xC01F5244']
        for missing in inputs:
            with self.subTest(missing=missing), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    lat.armasm.assemble(core, ['RUNTIME_REFS=1']+[v for v in inputs if v != missing])
        defs = ['RUNTIME_REFS=1', 'LAT_CANCEL=1', 'LAT_DESC_SLOT=0xC31E13CC',
                'LAT_DESC_ROOT=0x2E003004', 'LAT_RING_BASE=0x2E00444C', 'LAT_DELAY=0xC01F4244']
        code = bytearray(lat.armasm.assemble(core, defs))
        syms = lat.armasm.symbols(core, defs)
        struct.pack_into('<5I', code, syms['runtime_refs'], self.plan.state, 2048,
                         self.plan.output, self.plan.output_room, 1200)
        with patch.multiple(fixture, P=0x2E003004, R=0x2E00444C, GLOBAL=0xC31E13CC, DELAY=0xC01F4244):
            # The existing strict access oracle traps old profile reads/calls.
            state, output, actual, _, delays, _ = fixture.emulate(bytes(code).ljust(4096, b'\0'), syms,
                                                                self.plan, descriptor=fixture.P, ring=fixture.R)
        self.assertEqual(struct.unpack_from('<I', state, 4)[0], 100)
        self.assertEqual(len(delays), 20)

    def test_mutated_stop_checks_fail_boundary_oracle(self):
        for symbol in ('loop', 'cancel_after_ledger'):
            code = bytearray(self.code)
            # BNE finish -> NOP: request no longer stops at the required boundary.
            struct.pack_into('<I', code, self.syms[symbol]+12, 0xE320F000)
            event = lambda k, a, b: k == 'execute' and a == self.at(symbol)
            with self.assertRaises((AssertionError, RuntimeError)):
                report, _ = self.run_capture(event, code=bytes(code))
                self.assertEqual(len(report['batches']), 0 if symbol == 'loop' else 1)
                self.assertEqual(report['delay_calls'], 0)

    def test_mutated_clear_request_and_reset_cursor_fail_ownership_and_ledger(self):
        text = fixture.mutation_source().replace('"../../gyro/gyro_drain.S"',
                    f'"{Path(__file__).resolve().parents[1]}/gyro/gyro_drain.S"')
        mutations = [
            ('str r0, g_gcount', 'str r0, g_gcount\n    str r0, g_cancel_request'),
            ('finish:\n', 'finish:\n    mvn r1, #0\n    str r1, g_ghead\n'),
        ]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'mutant.S'
            for old, new in mutations:
                self.assertIn(old, text)
                source.write_text(text.replace(old, new))
                with patch.object(lat, 'SOURCE', source):
                    code, self.syms = lat.code_for(self.plan, 1200, runtime=True, cancel=True)
                with self.assertRaises(AssertionError):
                    self.run_capture(lambda k, a, b: k == 'execute' and
                                     a == self.at('cancel_after_ledger') and b == 1, code=code)

    def test_fixed_variant_relocation_invalid_refs_and_tail_rejection(self):
        for address in (0x46020000, 0x53070000):
            self.plan = replace(self.plan, code=address, state=address+0x4000, output=address+0x8000)
            for runtime in (False, True):
                self.code, self.syms = lat.code_for(self.plan, 1200, runtime=runtime, cancel=True)
                report, result = self.run_capture(lambda k, a, b: k == 'execute' and
                                                  a == self.at('cancel_after_ledger') and b == 1,
                                                  poison_old=True)
                bad = bytearray(result[1]); bad[-1] ^= 1
                with self.assertRaisesRegex(RuntimeError, 'sentinel'):
                    lat.decode(result[0], bad, 1200, cancel=True)
        fixture.emulate(self.code, self.syms, self.plan, runtime_refs=[0]*5, rejected=True)

    def test_cancelled_header_cannot_hide_error_or_impossible_delay_count(self):
        report, result = self.run_capture(descriptor=0)
        state = bytearray(result[0]); struct.pack_into('<I', state, 4, 101)
        with self.assertRaises(RuntimeError):
            lat.decode(state, result[1], 1200, cancel=True)
        report, result = self.run_capture()
        state = bytearray(result[0]); struct.pack_into('<I', state, 4, 101)
        with self.assertRaises(RuntimeError):
            lat.decode(state, result[1], 1200, cancel=True)


if __name__ == '__main__':
    unittest.main()
