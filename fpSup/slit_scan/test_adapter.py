"""Execute the shared applier/provider/guard/layer against official fp L bytes.

Allocator, cache effects and CP15 inputs are modeled; page composition, journal
inspection, IRQ masking, stores and string leaves execute as ARM instructions.
This fixture does not simulate the GUI scheduler, registry or renderer.
"""
import os
from pathlib import Path
import struct
import unittest

import menu
from build_adapter import build, HERE
import fpl_ui as ui
import fpl_ui_restore as restore
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ
from unicorn.arm_const import *

CODE, BLOCK, OUT, STACK, RET = 0x45000000, 0x45010000, 0x45040000, 0x450FF000, 0x48000000
APP, SCREENS, SCREEN, READER, TABLE = (0xC3B00000+i*0x1000 for i in range(5))
JOURNAL_OBJECT = 0x45400000
TCB = 0xC3000838


class Machine:
    def __init__(self, test, image, text, block, fail_alloc=0):
        self.test, self.text = test, text
        self.fallback = None
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a, n in ((0xC0000000, 0x4000000), (CODE, 0x100000),
                     (JOURNAL_OBJECT, 0x800000), (RET, 0x1000)):
            u.mem_map(a, n)
        u.mem_write(0xC0000000, image)
        u.mem_write(CODE, text.code)
        u.mem_write(BLOCK, block)
        self.block = block
        self.put(ui.GUI_OBJECT, APP)
        self.put(APP+0x80, 1); self.put(APP+0x8C, SCREENS)
        self.put(SCREENS, SCREEN); self.put(SCREEN+4, APP); self.put(SCREEN+0x24, READER)
        self.put(READER, 0x01090000)
        self.put(READER+0x10, ui.POOL_LEN, ui.POOL); self.put(READER+0x24, ui.NBU)
        self.put(READER+0xA8, 1, TABLE)
        name = ui.POOL+image[ui.POOL-0xC0000000:ui.POOL-0xC0000000+ui.POOL_LEN].index(b'MainB2\0')
        self.put(TABLE+4, name, ui.PAGES['MainB2'])
        self.put(restore.MANAGER, 0xC0726CEC)
        for off in (12, 52): self.put(restore.MANAGER+off, JOURNAL_OBJECT)
        code = restore.restore_code()
        self.journal = JOURNAL_OBJECT+12+len(code)
        self.put(JOURNAL_OBJECT, JOURNAL_OBJECT-8, JOURNAL_OBJECT+12, self.journal)
        u.mem_write(JOURNAL_OBJECT+12, code)
        p = self.journal
        for address, data in restore.stock_sections(image):
            self.put(p, address, 4, struct.unpack('<I', data)[0]); p += 12
        self.put(p, 0)
        self.put(0xC3000098, TCB+132)
        self.put(TCB+132+8, 1)
        u.mem_write(TCB+132+0x23, b'\x01')
        self.allocations, self.writes, self.cache = [], [], []
        self.cursor = JOURNAL_OBJECT+0x10000
        self.fail_alloc, self.alloc_calls = fail_alloc, 0
        u.hook_add(UC_HOOK_CODE, self.instruction)
        u.hook_add(UC_HOOK_MEM_WRITE, self.write)
        # fp cave is IMU firmware on fp L: no reads or writes allowed.
        u.hook_add(UC_HOOK_MEM_READ, self.forbidden, begin=0xC072D000, end=0xC0735000)

    def put(self, a, *v): self.u.mem_write(a, struct.pack('<%dI' % len(v), *v))
    def word(self, a): return struct.unpack('<I', self.u.mem_read(a, 4))[0]
    def ret(self, v=0):
        self.u.reg_write(UC_ARM_REG_R0, v)
        self.u.reg_write(UC_ARM_REG_PC, self.u.reg_read(UC_ARM_REG_LR))

    def forbidden(self, *args): raise AssertionError('fp cave was accessed')

    def instruction(self, u, pc, size, data):
        if pc in (0xC001D740, 0xC001D7F0, 0xC000E91C, 0xC000EABC):
            self.test.assertEqual(u.reg_read(UC_ARM_REG_SP) & 7, 0)
            a = [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
            if pc == 0xC001D740:
                self.test.assertEqual(a[1], 0)
                self.alloc_calls += 1
                owner = (self.cursor+0xFFFF) & ~0xFFFF
                if self.alloc_calls == self.fail_alloc: owner = 0
                else:
                    self.cursor = owner+a[2]
                    self.allocations.append((owner, a[2]))
                self.put(a[0], owner, 0, owner, a[2]); self.ret(); return
            if pc == 0xC001D7F0: self.ret(self.word(a[0])); return
            self.cache.append(pc); self.ret(); return
        if CODE <= pc < CODE+len(self.text.code):
            cp = {0xEE100F10: 0x410FC075, 0xEE100FB0: 0x80000000, 0xEE390F50: 0}
            insn = self.word(pc)
            if insn in cp:
                u.reg_write(UC_ARM_REG_R0, cp[insn]); u.reg_write(UC_ARM_REG_PC, pc+4)
            return
        if any(a <= pc < a+n for a, n in self.allocations): return
        if any(s <= pc < s+8 for s in ui.STRING_SITES.values()): return
        if self.fallback is not None:
            return self.fallback(u, pc, size, data)
        raise AssertionError(f'unmodeled native execution {pc:#x}')

    def write(self, u, access, a, n, value, data):
        if 0xC0000000 <= a < 0xC3000000:
            self.test.assertIn(a, [s+i for s in ui.STRING_SITES.values() for i in (0, 4)])
            self.test.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xC0, 0xC0)
            self.writes.append((a, value))
        if a == TABLE+8:
            self.test.assertEqual(len(self.writes), 6)
            self.test.assertGreaterEqual(len(self.cache), 5)

    def call(self, pc, *args):
        u = self.u
        u.reg_write(UC_ARM_REG_CPSR, 0x13)
        regs = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
        for i, r in enumerate(regs): u.reg_write(r, 0xABCD0000+i)
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args): u.reg_write(r, v)
        u.reg_write(UC_ARM_REG_SP, STACK); u.reg_write(UC_ARM_REG_LR, RET)
        u.emu_start(pc, RET, count=4000000, timeout=10000000)
        self.test.assertEqual(u.reg_read(UC_ARM_REG_PC), RET)
        self.test.assertEqual(u.reg_read(UC_ARM_REG_SP), STACK)
        self.test.assertEqual([u.reg_read(r) for r in regs], [0xABCD0000+i for i in range(8)])
        self.test.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, 0x13)
        return u.reg_read(UC_ARM_REG_R0)

    def apply(self): return self.call(CODE+self.text.functions['slit_apply'], BLOCK, len(self.block), OUT)


class Adapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = restore.CAMERA.verify_main(os.environ['FPL_MAIN'])
        cls.block, cls.info, cls.reference = menu.build(Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN']))
        cls.text = build()

    def machine(self, text=None, **kwargs):
        return Machine(self, self.image, text or self.text, self.block, **kwargs)

    def unchanged(self, m):
        self.assertEqual(m.word(TABLE+8), ui.PAGES['MainB2'])
        self.assertEqual(m.writes, [])

    def test_page_matches_python_and_real_shared_leaves_resolve_all_strings(self):
        m = self.machine()
        self.assertEqual(m.apply(), 0)
        page = (ui.NBU+m.word(TABLE+8)) & 0xFFFFFFFF
        self.assertEqual(bytes(m.u.mem_read(page, len(self.reference['page']))), self.reference['page'])
        layer = m.allocations[-1][0]+0x1000
        count, table = m.word(layer+16), m.word(layer+40)
        for i in range(count):
            p = m.call(ui.STRING_SITES['resolve']|1, READER, 0x40000000+i)
            self.assertEqual(p, m.word(table+4*i))
            actual = bytes(m.u.mem_read(p, 64)).split(b'\0')[0].decode()
            self.assertEqual(actual, self.reference['strings'].text(0x40000000+i))
            self.assertEqual(m.call(ui.STRING_SITES['owns']|1, READER, p), 1)
            # Native remain reports the enclosing pool's remaining capacity,
            # not strlen: every string in this layer shares the same end.
            self.assertEqual(m.call(ui.STRING_SITES['remain']|1, READER, p), m.word(layer+24)-p)
        self.assertEqual(m.call(ui.STRING_SITES['resolve']|1, READER, 0), ui.POOL)
        self.assertEqual(bytes(m.u.mem_read(ui.NBU+ui.PAGES['MainB2'], len(self.reference['stock_page']))), self.reference['stock_page'])

    def test_missing_wrong_duplicate_journal_or_forced_registration_refuses(self):
        for kind in ('missing', 'wrong', 'duplicate', 'forced', 'forced-after-end', 'code'):
            with self.subTest(kind=kind):
                m = self.machine()
                if kind == 'missing': m.put(m.journal+5*12, 0)
                if kind == 'wrong': m.put(m.journal+8, 0)
                if kind == 'duplicate':
                    a, data = restore.stock_sections(self.image)[0]
                    m.put(m.journal+6*12, a, 4, struct.unpack('<I', data)[0], 0)
                if kind == 'forced': m.put(restore.MANAGER+52, 0)
                if kind == 'forced-after-end': m.put(restore.MANAGER+52, 0, JOURNAL_OBJECT)
                if kind == 'code': m.put(JOURNAL_OBJECT+12, 0)
                self.assertEqual(m.apply(), 6)
                self.unchanged(m)
                self.assertEqual(m.allocations, [])

    def test_allocation_failure_and_busy_saved_pc_leave_page_stock(self):
        for fail in (1, 2):
            m = self.machine(fail_alloc=fail)
            self.assertNotEqual(m.apply(), 0)
            self.unchanged(m)
        m = self.machine()
        tcb, frame = TCB+500*132, 0xC3B10000
        m.put(tcb+8, 500); m.put(tcb+0x18, 0x1000)
        m.u.mem_write(tcb+0x23, b'\x04')
        m.put(tcb+0x74, frame+0xD0, frame)
        m.put(frame+0xC4, 0x33, 0, ui.STRING_SITES['resolve']+4)
        self.assertEqual(m.apply(), 6)
        self.unchanged(m)

    def test_existing_foreign_hook_is_not_overwritten(self):
        m = self.machine(); m.put(ui.STRING_SITES['remain']+4, 0xDEADBEEF)
        self.assertEqual(m.apply(), 6); self.unchanged(m)
        self.assertEqual(m.word(ui.STRING_SITES['remain']+4), 0xDEADBEEF)

    def test_fp_only_operations_are_rejected_before_publication(self):
        from ui import fpui
        for code in range(8, 19):
            with self.subTest(opcode=code):
                b = fpui.Block()
                b.op(code)
                m = Machine(self, self.image, self.text, b.encode())
                self.assertEqual(m.apply(), 7)
                self.unchanged(m)
                self.assertEqual(m.allocations, [])

    def test_mutation_missing_sixth_word_check_is_detected(self):
        source = (HERE/'fpl_pool.c').read_text().replace('coverage == 63', 'coverage == 31')
        m = self.machine(build(source)); m.put(m.journal+5*12, 0)
        with self.assertRaises(AssertionError): self.assertEqual(m.apply(), 6)


if __name__ == '__main__': unittest.main()
