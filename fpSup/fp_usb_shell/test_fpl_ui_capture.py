"""Uncertain menu-key replies must retain evidence and release without retry."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fpl_ui_capture as capture


class Capture(unittest.TestCase):
    def test_timeout_reply_and_transport_exception_retain_key_release(self):
        for response in ('ERR timeout', TimeoutError('transport')):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as td:
                out = Path(td)/'screen.jpg'
                calls = []
                class IO:
                    def words(self, *args): return [0, 0, 0]
                    def sh(self, text, retries):
                        calls.append(text)
                        self_check = json.loads(out.with_suffix('.json').read_text())
                        assert self_check['commands'][-1]['command'] == text
                        assert retries == 0
                        if text == 'version': return 'w91c1 3.02.0.V90'
                        if text == 'dir \\DCIM': return '<DIR> 100SIGMA\n'
                        if text == 'key RIGHTON':
                            if isinstance(response, Exception): raise response
                            return response
                        return ''
                with patch.object(capture.gf, 'Backend', IO), \
                     patch.object(capture.gf, 'staging_lock', nullcontext):
                    with self.assertRaises((RuntimeError, TimeoutError)):
                        capture.capture(out, 'RIGHT')
                self.assertEqual(calls[-2:], ['key RIGHTON', 'key RIGHTOFF'])
                self.assertFalse(out.exists())
                report = json.loads(out.with_suffix('.json').read_text())
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['commands'][-1]['command'], 'key RIGHTOFF')
                self.assertTrue('reply' in report['commands'][-2] or 'error' in report['commands'][-2])


if __name__ == '__main__': unittest.main()
