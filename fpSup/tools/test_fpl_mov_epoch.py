"""Diagnostic state-machine tests; handcrafted cases are not hardware evidence."""
from copy import deepcopy
from pathlib import Path
import os
import unittest

from fpl_mov_epoch import classify, _classify, replay_audit


def fixture():
    return [dict(seq=i, owner='owner', writer='writer', **e) for i, e in enumerate([
        dict(kind='start'), dict(kind='message2'),
        dict(kind='finalizer_return', r0=0, flags=0), dict(kind='raw_status', status=1)])]


class EpochTests(unittest.TestCase):
    def synthetic(self, events):
        # Exercise transitions independently of the proof boundary. This private
        # entry point asserts a model assumption, not hardware authenticity.
        return _classify(events, synthetic_association=True)

    def test_positive_model_and_raw_preservation(self):
        events = fixture()
        result = self.synthetic(events)
        self.assertEqual(result['classification'], 'local_finalization_observed')
        self.assertEqual(result['raw_events'], events)
        events[0]['owner'] = 'changed'
        self.assertEqual(result['raw_events'][0]['owner'], 'owner')
        self.assertFalse(result['hardware_certified'])
        self.assertFalse(any(result['claims'].values()))

    def test_invented_epoch_and_proof_fields_never_authorize_import(self):
        events = fixture()
        for e in events:
            e.update(epoch='trusted-42', proof=True, causal_association='verified',
                     evidence_scope='bounded_synthetic_execution')
        result = classify(events)
        self.assertEqual(result['classification'], 'inconclusive')
        self.assertIn('causal_association_unproven', result['reasons'])
        self.assertEqual(result['raw_events'], events)

    def test_event30_is_not_raw_status(self):
        events = fixture()
        events[-1] = dict(events[-1], kind='event30', result=1)
        self.assertIn('incomplete_epoch', self.synthetic(events)['reasons'])
        result_only = [events[0], dict(events[-1], seq=1)]
        self.assertEqual(self.synthetic(result_only)['classification'], 'inconclusive')

    def test_errors_missing_fields_and_raw2(self):
        for field, value in [('r0', 1), ('flags', 8), ('flags', 2), ('flags', None), ('r0', True)]:
            with self.subTest(field=field, value=value):
                events = fixture()
                events[2][field] = value
                self.assertEqual(self.synthetic(events)['classification'], 'inconclusive')
        events = fixture()
        events[-1]['status'] = 2
        events.insert(3, dict(seq=3, kind='event30', result=1, owner='owner', writer='writer'))
        events[-1]['seq'] = 4
        self.assertIn('raw2_is_not_clean_completion', self.synthetic(events)['reasons'])

    def test_nonerror_flag_bits(self):
        events = fixture()
        events[2]['flags'] = 0x20
        self.assertEqual(self.synthetic(events)['classification'], 'local_finalization_observed')

    def test_missing_and_out_of_order_evidence(self):
        base = fixture()
        variants = [base[:1]+base[2:], base[:2]+base[3:], base[:-1],
                    [base[0], base[2], base[1], base[3]],
                    [base[0], base[1], base[3], base[2]]]
        for events in variants:
            # Renumber too: semantics must catch loss even without a seq gap.
            with self.subTest(events=events):
                events = [dict(e, seq=i) for i, e in enumerate(events)]
                self.assertEqual(self.synthetic(events)['classification'], 'inconclusive')

    def test_duplicates_gaps_overlap_and_late_events(self):
        for position in range(4):
            events = fixture()
            events.insert(position+1, deepcopy(events[position]))
            for renumber in (False, True):
                with self.subTest(position=position, renumber=renumber):
                    trial = [dict(e, seq=i) if renumber else e for i, e in enumerate(events)]
                    self.assertEqual(self.synthetic(trial)['classification'], 'inconclusive')
        for kind in ('start', 'gap', 'association_unknown'):
            events = fixture()
            events.insert(2, dict(kind=kind, owner='owner', writer='writer'))
            events = [dict(e, seq=i) for i, e in enumerate(events)]
            self.assertEqual(self.synthetic(events)['classification'], 'inconclusive')
        events = fixture() + [dict(fixture()[0], seq=4, epoch='new-epoch')]
        self.assertIn('overlapping_or_reused_epoch', self.synthetic(events)['reasons'])

    def test_stale_identity_and_unobservable_staleness(self):
        for key in ('owner', 'writer'):
            events = fixture()
            events[-1][key] = 'previous'
            self.assertIn('owner_or_writer_unassociated', self.synthetic(events)['reasons'])
        # A stale callback with the same numerical identity cannot be detected
        # from tags. Even a perfect-looking imported sequence must be refused.
        self.assertEqual(classify(fixture())['classification'], 'inconclusive')

    def test_unknown_and_malformed_events(self):
        for event in (None, {}, dict(kind='guess'), dict(seq=True, kind='start')):
            self.assertEqual(self.synthetic([event])['classification'], 'inconclusive')


class AuditReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get('FPSUP_FPL_MAIN', Path.home()/
            '.local/share/fpsup/firmware/FPL_V302/MAIN.bin'))
        if not path.exists():
            raise unittest.SkipTest('set FPSUP_FPL_MAIN to official fp L 3.02 MAIN; bounded replay tests not run')
        cls.data = path.read_bytes()

    def test_real_bounded_pipeline_with_mocked_io(self):
        cases = [({}, 'local_finalization_observed'),
                 (dict(pools=(1,0,1)), 'inconclusive'),
                 (dict(writer_send_errors=(-1,0)), 'inconclusive'),
                 (dict(finalize_error=True), 'inconclusive'),
                 (dict(remainder_error=True), 'inconclusive'),
                 (dict(pools=(1,1,0)), 'inconclusive'),
                 (dict(writer_send_errors=(0,-1)), 'inconclusive'),
                 (dict(send_error=-1), 'inconclusive'),
                 (dict(started=False), 'inconclusive')]
        for case, expected in cases:
            with self.subTest(case=case):
                result = replay_audit(self.data, **case)
                self.assertEqual(result['classification'], expected)
                self.assertEqual(result['evidence_scope'], 'bounded_synthetic_execution')
                self.assertIn('log', result['audit_trace'])
                self.assertFalse(result['hardware_certified'])
                # Export/reimport cannot launder synthetic association as proof.
                self.assertEqual(classify(result['raw_events'])['classification'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
