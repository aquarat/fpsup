"""Additive recipe semantics and corruption tests against pinned official images."""
import os
from pathlib import Path
import struct
import unittest

import menu
from ui import fpui


class Menu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.info, cls.data = menu.build(Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN']))
        cls.audit = menu.donor.load_audit(menu.donor.DEFAULT_AUDIT)

    def records(self):
        return menu.validate_page(self.data['page'], self.data['strings'].text, self.audit)

    def test_inline_keys_and_summary_are_private(self):
        resolve = self.data['strings'].text
        root = self.info['first_local_id']+1
        records = self.records()
        actions = [r for r in records if r.tag == 0x10009 and r.word(20) == root and r.word(24) in (6, 7, 21)]
        self.assertEqual(len(actions), 6)
        events = [r for r in records if r.tag == 0x10006 and r.word(24) == root
                  and r.word(28) in (6, 7, 21)]
        self.assertEqual([r.word(16) for r in events], [2, 2, 2])
        for r in actions:
            self.assertEqual(resolve(r.word(8)), 'controlAppVariable')
            self.assertEqual(resolve(r.word(36)), 'MV_fpSlitKey')
            self.assertEqual(r.word(32), 0x81)  # destination + literal value
            self.assertEqual(resolve(r.word(41)), '0' if r.word(28) == 1 else
                             '-1' if r.word(24) == 21 else '1')
        bindings = [r for r in records if r.tag == 0x10006 and
                    resolve(r.word(8)) == 'appVariableEvent' and resolve(r.word(40)) == 'MV_fpSlitText']
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0].word(45), 1)
        self.assertEqual(resolve(bindings[0].word(49)), 'text')
        # No cloned row field retains the Audio setting (including hidden donor children).
        fields = self.data['manifest']['typed_string_fields']
        self.assertFalse(any(f['text'] in ('MV_AudioRecord', 'SUB_MV_AudioRecord', 'EXCL_AudioRecord') for f in fields))
        self.assertNotIn('fpLossless_Row_GATED', self.info['strings'])

    def test_two_additions_relocate_ids_rows_and_strings(self):
        stock = self.data['stock_page']
        pages = {'MainB2': fpui.PageCopy(stock, len(stock), 1)}
        pool = fpui.Strings(self.data['strings'].stock)
        first = fpui.apply(self.blob, pages, pool)
        second = fpui.apply(self.blob, pages, pool)
        self.assertEqual(second['MainB2']-first['MainB2'], 23)
        self.assertEqual(first['slots'], [243])
        self.assertEqual(second['slots'], [324])
        menu.validate_page(bytes(pages['MainB2'].data), pool.text)

    def test_mutations_of_native_graph_are_detected(self):
        records = self.records()
        root = self.info['first_local_id']+1
        left = next(r for r in records if r.tag == 0x10006 and r.word(24) == root and r.word(28) == 21)
        obj = next(r for r in records if r.tag == 0x10003 and r.word(20) == root)
        for at, value, message in ((left.offset+28, 6, 'duplicate'),
                                   (left.offset+16, 4, 'action count'),
                                   (left.offset+24, 65535, 'owner'),
                                   (obj.offset+8, 0, 'budget'),
                                   (obj.offset+16, 0, 'child counts'),
                                   (8, 0, 'budget')):
            with self.subTest(at=at):
                corrupt = bytearray(self.data['page'])
                struct.pack_into('>I', corrupt, at, value)
                with self.assertRaisesRegex(ValueError, message):
                    menu.validate_page(corrupt, self.data['strings'].text)


if __name__ == '__main__':
    unittest.main()
