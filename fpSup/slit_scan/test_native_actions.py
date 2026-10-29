"""Execute fp L controlAppVariable literal actions from the emitted row.

Component property access is modeled from the decoded NBU record (not its
manifest); the action handler, atoi, registry setter, notifications and private
controller are actual ARM instructions. Rendering/event scheduling stay outside
this fixture. In particular, this reproduces the old dst +/- 1 failure.
"""
import os
from pathlib import Path
import unittest

import menu
import test_controller as c
from unicorn.arm_const import *


class ActionProbe(c.Probe):
    COMPONENT = c.Probe.RAM+0x31000
    DEST = COMPONENT+0x100
    VALUE = COMPONENT+0x200

    def __init__(self, image, text):
        super().__init__(image, text)
        self.uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF00000)
        self.uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)

    def _instruction(self, uc, address, size, data):
        args = [uc.reg_read(r) for r in c.registry.REGS]
        if address == 0xC05D32C8:  # component -> owning app
            assert args[0] == self.COMPONENT
            self.write_words(args[1], self.APP)
            self._return(0); return
        if address == 0xC05D2DC0:  # string properties: destination / literal
            assert args[0] == self.COMPONENT and args[1] in (0, 7)
            self.write_words(args[2], self.DEST if args[1] == 0 else self.VALUE)
            self._return(0); return
        if address == 0xC05D25E0:  # modeled literal donor source-type: Value (3)
            assert args[0] == self.COMPONENT and args[1] == 1
            self.write_words(args[2], 3)
            self._return(0); return
        for lo, hi in ((0xC05ED7C0, 0xC05EE0D8),  # native action handler
                       (0xC0015808, 0xC00158B0),  # zero memory
                       (0xC01F2284, 0xC01F2414),  # decimal conversion
                       (0xC0015938, 0xC00159FC)): # unsigned division
            if lo <= address < hi: return
        super()._instruction(uc, address, size, data)

    def action(self, rec, resolve, value=None):
        assert rec.tag == 0x10009 and resolve(rec.word(8)) == 'controlAppVariable'
        assert len(rec.data) == 46 and rec.word(32) == 0x81
        assert rec.data[40] == rec.data[45] == 0  # literal string flags
        self.write(self.DEST, resolve(rec.word(36)).encode()+b'\0')
        self.write(self.VALUE, (resolve(rec.word(41)) if value is None else value).encode()+b'\0')
        return self.run(0xC05ED7C0, self.COMPONENT, 0)


class NativeActions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = c.get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        c.registry.SEG0_SIZE = len(cls.image)
        cls.text = c.build()
        _, cls.info, cls.data = menu.build(Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN']))

    def probe(self):
        p = ActionProbe(self.image, self.text)
        self.addCleanup(p.close)
        self.assertEqual(p.init(), 0)
        return p

    def actions(self, event):
        resolve = self.data['strings'].text
        records = menu.validate_page(self.data['page'], resolve)
        root = self.info['first_local_id']+1
        return [r for r in records if r.tag == 0x10009 and
                (r.word(20), r.word(24)) == (root, event)]

    def press(self, p, event, reset=True):
        actions = self.actions(event)
        self.assertEqual([r.word(28) for r in actions], [1, 2])
        for r in actions if reset else actions[1:]:
            self.assertEqual(p.action(r, self.data['strings'].text), 0)

    def test_literal_formula_reproduces_old_silent_failure(self):
        p = self.probe()
        for value in ('dst + 1', 'dst - 1'):
            self.assertEqual(p.action(self.actions(6)[1], self.data['strings'].text, value), 0)
            self.assertEqual(p.requested(), 0)
            self.assertEqual(p.words(p.STATE+28)[0], 0)

    def test_emitted_keys_repeated_right_ok_left_and_both_wraps(self):
        p = self.probe()
        for event, index in ((6,1), (6,2), (7,3), (7,4), (6,0), (21,4), (21,3)):
            self.press(p, event)
            self.assertEqual(p.requested(), index)
            self.assertEqual(p.call('pump', p.STATE), 0)
            self.assertEqual(p.posted_text(), menu.LABELS[index])
        self.assertEqual(p.words(p.STATE+28)[0], 7)

    def test_mutation_without_reset_loses_repeated_key(self):
        p = self.probe()
        self.press(p, 6, reset=False)
        self.press(p, 6, reset=False)
        with self.assertRaises(AssertionError):
            self.assertEqual(p.requested(), 2)
        self.assertEqual(p.requested(), 1)


if __name__ == '__main__': unittest.main()
