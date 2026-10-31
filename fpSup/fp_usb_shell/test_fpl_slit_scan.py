"""Host export and teardown invariants; no camera IO."""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fpl_slit_scan as S


class SlitScan(unittest.TestCase):
    def test_framerate_edit_changes_only_rational_bytes(self):
        data = bytearray(b'II*\0'+struct.pack('<I', 8))
        data += struct.pack('<H', 1)+struct.pack('<HHII', 51044, 10, 1, 32)+bytes(10)
        data += struct.pack('<ii', 24000, 1000)+bytes(range(256))
        result = S.patch_frame_rate(bytes(data), 4)
        self.assertEqual(struct.unpack_from('<ii', result, 32), (4, 1))
        self.assertEqual(result[:32], data[:32])
        self.assertEqual(result[40:], data[40:])
        struct.pack_into('<I', data, 18, len(data)-4)
        with self.assertRaises(ValueError):
            S.patch_frame_rate(data, 4)

    def test_restore_attempts_all_settings_and_reports_failures(self):
        seen = []
        def setter(io, name, value):
            seen.append(name)
            if name == 'SetShutterSpeed':
                raise RuntimeError('transport failed')
        with patch.object(S, 'set_menu', setter):
            with self.assertRaises(RuntimeError):
                S.restore_exposure(None, {k:'0' for k in S.EXPOSURE}, lambda *a: None)
        self.assertEqual(seen, ['SetShutterSpeed', 'SetIso', 'SetExpMode'])

    def test_timecode_is_renumbered_at_export_rate(self):
        data = bytearray(80)
        data[:8] = b'II*\0'+struct.pack('<I',8)
        struct.pack_into('<H',data,8,2)
        struct.pack_into('<HHII',data,10,51044,10,1,40)
        struct.pack_into('<HHII',data,22,51043,1,8,48)
        struct.pack_into('<ii',data,40,24,1)
        data[48:56] = b'\x23\x59\x59\x12'+bytes(4)
        result = S.patch_frame_rate(bytes(data),4.0000001,4*61+3)
        self.assertEqual(result[48:56], b'\x03\x01\x01\x00'+bytes(4))
        self.assertEqual(result[56:],data[56:])

    def test_coupled_final_mode_change_cannot_falsely_verify_restoration(self):
        saved=dict(SetExpMode='3',SetShutterSpeed='0/0',SetIso='0')
        for coupled in (False,True):
            state={};events=[]
            def setter(io,name,value):
                state[name]=value
                if coupled and name=='SetExpMode':state['SetShutterSpeed']='1/25'
            with patch.object(S,'set_menu',setter),patch.object(S,'menu',lambda io,k:state[k]):
                if coupled:
                    with self.assertRaisesRegex(RuntimeError,'final value'):
                        S.restore_exposure(None,saved,lambda *e:events.append(e))
                else:S.restore_exposure(None,saved,lambda *e:events.append(e))
            self.assertEqual(events[0][1]['actual'],state)
            self.assertEqual(bool(events[0][1]['errors']),coupled)

    def test_teardown_marker_retained_until_exposure_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory)/'pending'
            marker.write_text('owned')
            record = dict(schema=S.SCHEMA, publication=[1,2,3], callback=123,
                          obj=456, exposure={})
            def words(io, address, count=1):
                return record['publication'] if address == S.gf.PUBLICATION else [0]
            with patch.object(S.vd, 'MARKER', marker), patch.object(S.vd, 'words', words), \
                 patch.object(S, 'stop_recording'), patch.object(S.tag, 'detach', return_value=True), \
                 patch.object(S, 'restore_exposure', side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):
                    S.cleanup(None, lambda *a: None, record)
                self.assertTrue(marker.exists())

    def test_export_resume_verifies_existing_content(self):
        result = dict(frames=[30],folder='A001_013',pattern='A001_013_20261026',measured_fps=4)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with patch.object(S.gr, 'download', return_value=b'original') as download, \
                 patch.object(S.tag, 'parse_gtag', return_value=(30,True)), \
                 patch.object(S, 'patch_frame_rate', return_value=b'export'):
                dest = S.export(out,result)
                S.export(out,result)
                self.assertEqual(download.call_count,1)
                (dest/'photo.DNG').write_bytes(b'changed by user')
                with self.assertRaises(RuntimeError):
                    S.export(out,result)
                self.assertEqual((dest/'photo.DNG').read_bytes(),b'changed by user')


if __name__ == '__main__':
    unittest.main()
