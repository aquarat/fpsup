"""Coordinator + actual controller/native registry + shared ARM page adapter.

Reuses their bounded native-service fixtures. Scheduling, Lua and rendering are
not simulated; this test proves initialization ordering and failure behavior.
"""
import os
from pathlib import Path
import unittest

import menu
from build_adapter import build
import test_adapter as a
import test_controller as c

STATE = a.CODE+0x80000


class Runtime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = a.restore.CAMERA.verify_main(os.environ['FPL_MAIN'])
        c.registry.SEG0_SIZE = len(cls.image)
        cls.block, cls.info, cls.reference = menu.build(Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN']))
        cls.text = build(runtime=True)

    def machine(self):
        m = a.Machine(self, self.image, self.text, self.block)
        p = c.Probe(self.image, self.text)
        # Carry the registry fixture's modeled allocator into the adapter's
        # machine. The actual app is cached; its registry is synthetic RAM.
        m.u.mem_map(p.RAM, p.RAM_SIZE)
        m.u.mem_write(p.RAM, bytes(p.uc.mem_read(p.RAM, p.RAM_SIZE)))
        m.u.mem_map(p.SERVICES, 0x1000)
        m.u.mem_write(p.SERVICES, bytes(p.uc.mem_read(p.SERVICES, 0x1000)))
        p.uc = m.u
        p.APP, p.CODE, p.STATE = a.APP, a.CODE, STATE+56
        m.put(a.APP+0x888, p.ROOT); m.put(a.APP+8, p.ALLOCATOR)
        old_string = p.string
        def string(address):
            if a.CODE <= address < a.CODE+0x100000:
                return bytes(m.u.mem_read(address, 128)).split(b'\0')[0]
            return old_string(address)
        p.string = string
        old_write = p.write
        def write(address, data):
            if a.CODE <= address <= address+len(data) <= a.CODE+0x100000:
                return m.u.mem_write(address, bytes(data))
            return old_write(address, data)
        p.write = write
        m.fallback = p._instruction
        m.put(STATE, 0x534C4954, 0, 0, 0, 1, a.APP,
              a.CODE+self.text.functions['slit_key'], a.BLOCK, len(self.block),
              a.TCB+132, a.TABLE, a.ui.PAGES['MainB2'], 0, 0)
        return m, p

    def tick(self, m): return m.call(a.CODE+self.text.functions['slit_tick'], STATE)

    def test_register_before_page_and_keys_drive_summary(self):
        m, p = self.machine()
        self.assertEqual(self.tick(m), 2)
        self.assertEqual(m.word(STATE+56+36), 5)
        self.assertEqual(m.word(STATE+48), (a.ui.NBU+m.word(a.TABLE+8)) & 0xFFFFFFFF)
        self.assertEqual(bytes(m.u.mem_read(m.word(STATE+48), len(self.reference['page']))), self.reference['page'])
        self.assertEqual(p.key(1), 0)
        self.assertEqual(self.tick(m), 2)
        self.assertEqual(p.posted_text(), '4 fps')
        self.assertEqual(p.requested(), 1)
        m.put(STATE+16, 2)
        self.assertEqual(self.tick(m), 3)
        self.assertEqual(p.key(2), 0)
        self.assertEqual(p.requested(), 1)

    def test_wrong_task_app_and_reentry_never_initialize(self):
        for address, value in ((0xC3000098, a.TCB+264), (a.ui.GUI_OBJECT, a.APP+4), (STATE+12, 1)):
            m, p = self.machine(); m.put(address, value)
            self.assertEqual(self.tick(m), 0)
            self.assertEqual(m.word(STATE+4), 0)
            self.assertEqual(m.word(STATE+56+36), 0)
            self.assertEqual(m.writes, [])

    def test_registration_failure_never_installs_page_or_strings(self):
        m, p = self.machine()
        p.fail_allocation = {p.allocation_calls+1}
        self.assertEqual(self.tick(m), 4)
        self.assertEqual(m.word(STATE+8), 0x102)
        self.assertEqual(m.word(a.TABLE+8), a.ui.PAGES['MainB2'])
        self.assertEqual(m.writes, [])
        self.assertEqual(self.tick(m), 4)

    def test_page_failure_disables_registered_controller_and_is_sticky(self):
        m, p = self.machine(); m.put(m.journal, 0)
        self.assertEqual(self.tick(m), 4)
        self.assertEqual(m.word(STATE+8), 6)
        self.assertEqual(m.word(STATE+56), 3)
        self.assertEqual(m.word(STATE+56+36), 5)
        self.assertEqual(m.writes, [])
        self.assertEqual(p.key(1), 0)
        self.assertEqual(p.requested(), 0)


if __name__ == '__main__': unittest.main()
