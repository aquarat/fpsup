"""Host delivery timelines must not manufacture capture identity or cadence."""
import struct
import unittest
import metadata as m
import queue_binding as q


def obs(frame, seconds=10, tick=0, valid=True, version=3, active=1):
    result=dict(frame=frame,requested=1,active=active,timing04=123 if active else 456,reason=0)
    if version==3:
        result['notify_clock']=dict(valid=valid,seconds=seconds,ticks=tick)
    return result


class Metadata(unittest.TestCase):
    def report(self,*observations):
        return m.timeline([(str(o['frame']),o,dict(frame_rate=[24000,1000],timecodes='stock'))
                           for o in observations])['frames']

    def test_delivery_rollover_transition_and_missing_files_are_explicit(self):
        rows=self.report(obs(1,10,11000000,active=0),obs(2,11,2000000),obs(4,11,8000000))
        self.assertEqual([r['notify_elapsed_ticks'] for r in rows],[0,3000000,9000000])
        self.assertEqual(rows[1]['notify_rate_hz'],4)
        self.assertIsNone(rows[2]['notify_rate_hz'])
        self.assertEqual(rows[2]['missing_frames_before'],1)
        self.assertEqual([r['observed_state_segment'] for r in rows],[0,1,1])
        self.assertTrue(all(r['capture_time'] is None for r in rows))
        self.assertTrue(all(r['nominal']['frame_rate']==[24000,1000] for r in rows))

    def test_raw_v2_clock_never_promoted_and_missing_clock_breaks_elapsed(self):
        old=obs(1,version=2);old.update(seconds=10,timer5=123)
        self.assertIsNone(self.report(old)[0]['notify_elapsed_ticks'])
        rows=self.report(obs(1),obs(2,tick=100,valid=False),obs(3,tick=200),obs(4,tick=300))
        self.assertEqual([r['notify_elapsed_ticks'] for r in rows],[0,None,None,None])
        self.assertEqual([r['notify_interval_ticks'] for r in rows],[None,None,None,100])

    def test_duplicate_reset_reverse_and_clock_backwards(self):
        for a,b in ((2,2),(2,1),(100,1)):
            with self.assertRaises(ValueError):self.report(obs(a),obs(b))
        rows=self.report(obs(1,10,100),obs(2,9,200))
        self.assertIsNone(rows[1]['notify_rate_hz'])
        self.assertIsNone(rows[1]['notify_elapsed_ticks'])
        # Explicit unsigned seconds wrap, not timer5-only guessed unwrapping.
        rows=self.report(obs(1,0xffffffff,11000000),obs(2,0,2000000))
        self.assertEqual(rows[1]['notify_interval_ticks'],3000000)

    def test_native_maximum_is_not_newest_generation_and_zero_is_fallback(self):
        keys=[0x123]*10;values=[0xfffffff0,1,0,0,0,0,0,0,0,0]
        r=q.lookup_snapshot(0x123,keys,values,1,2)
        self.assertEqual((r['result'],r['selected_slots']),(0xfffffff0,[0]))
        self.assertIn('unproved',r['key_generation'])
        self.assertEqual(q.lookup_snapshot(0x123,keys,[0]*10,42,0)['status'],'zero-value-fallback')
        self.assertEqual(q.lookup_snapshot(0x124,keys,values,42,0)['status'],'miss-fallback')
        with self.assertRaises(ValueError):q.lookup_snapshot(0,keys,values,42,10)

    def test_nominal_metadata_is_read_not_assumed_or_rewritten(self):
        data=bytearray(128)
        struct.pack_into('<2sHIH',data,0,b'II',42,8,2)
        struct.pack_into('<HHII',data,10,51044,10,1,64)
        struct.pack_into('<HHII',data,22,51043,1,8,72)
        struct.pack_into('<ii',data,64,60000,1001)
        data[72:80]=bytes.fromhex('1234560100000000')
        before=bytes(data);got=m.nominal_metadata(data)
        self.assertEqual(got['frame_rate'],[60000,1001])
        self.assertEqual(got['timecodes'],'1234560100000000')
        self.assertEqual(bytes(data),before)
        struct.pack_into('<i',data,68,0)
        with self.assertRaises(ValueError):m.nominal_metadata(data)


if __name__=='__main__':unittest.main()
