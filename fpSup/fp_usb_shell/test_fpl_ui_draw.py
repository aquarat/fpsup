"""Actual ARM BSS interposition/observer, with native drawing modeled explicitly.

This proves the observer ABI and pointer transaction, not GUI serialization.
"""
import os
from pathlib import Path
import struct
import tempfile
import unittest

import armasm
from firmware import get_camera
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

SOURCE = Path(__file__).parent/'asm/fpl_ui_draw.S'
OWNER, RET, STACK = 0x45600000, 0x48000000, 0x4560F000
OBJECT, STOCK, LISTENER = 0xC38D37CC, 0xC2E55A70, 0xC3785524
TCB = 0xC3000838+132*42


def put(u, a, *v): u.mem_write(a, struct.pack('<%dI' % len(v), *v))
def word(u, a): return struct.unpack('<I', u.mem_read(a, 4))[0]


class Draw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = get_camera('fp-l-3.02').verify_main(Path(os.environ['FPL_MAIN']))
        cls.code = armasm.assemble(SOURCE, [f'OWNED={OWNER}'])
        cls.syms = armasm.symbols(SOURCE, [f'OWNED={OWNER}'])

    def machine(self, code=None, recursive=False, callback=False):
        if callback:
            code = armasm.assemble(SOURCE, [f'OWNED={OWNER}', 'CALLBACK=1'])
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(0xC0000000, 0x4000000); u.mem_write(0xC0000000, self.image)
        u.mem_map(OWNER, 0x10000); u.mem_map(RET, 0x1000)
        u.mem_write(OWNER+0x1000, code or self.code)
        u.mem_write(OWNER+0x2000, self.image[STOCK-0xC0000000:STOCK-0xC0000000+40])
        put(u, OWNER+0x200c, OWNER+0x1000+self.syms['observe'])
        put(u, OBJECT, STOCK, 0, LISTENER, 1)
        put(u, OWNER+0x408, LISTENER)
        if callback:
            put(u, OWNER+0x40c, OWNER+0x3000, OWNER+0x8000, TCB)
        put(u, 0xC3000098, TCB)
        put(u, TCB+8, 42); put(u, TCB+0x18, 0x10000); put(u, TCB+0x74, OWNER+0x10000)
        self.native_calls, self.stores, self.outer_lr, self.callbacks = [], [], None, []

        def write(u, access, a, n, v, data):
            if 0xC0000000 <= a < 0xC4000000:
                self.assertEqual((a, n), (OBJECT, 4))
                self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xC0, 0xC0)
                self.stores.append(v)

        def instruction(u, pc, size, data):
            if pc == 0xC000E91C:
                self.assertEqual(u.reg_read(UC_ARM_REG_SP) & 7, 0)
                u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR)); return
            if pc == 0xC06CF498:
                self.assertEqual(u.reg_read(UC_ARM_REG_SP) & 7, 0)
                self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, 0x13)
                args = [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
                self.assertEqual(args, [OBJECT, 0x12345678, 0x23456780])
                self.native_calls.append(args)
                if recursive and len(self.native_calls) == 1:
                    self.outer_lr = u.reg_read(UC_ARM_REG_LR)
                    u.reg_write(UC_ARM_REG_LR, RET+4)
                    u.reg_write(UC_ARM_REG_PC, OWNER+0x1000+self.syms['observe']); return
                u.reg_write(UC_ARM_REG_R0, 0x87654321)
                u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR)); return
            if pc == RET+4:
                u.reg_write(UC_ARM_REG_PC, self.outer_lr); return
            if pc == OWNER+0x3000 and callback:
                self.assertEqual(u.reg_read(UC_ARM_REG_R0), OWNER+0x8000)
                self.assertEqual(u.reg_read(UC_ARM_REG_SP) & 7, 0)
                self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, 0x13)
                self.callbacks.append(pc)
                u.reg_write(UC_ARM_REG_R0, 2)
                u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR)); return
            if OWNER+0x1000 <= pc < OWNER+0x1000+len(code or self.code):
                cp = {0xEE100FB0: 0x80000000, 0xEE390F50: 0}
                insn = word(u, pc)
                if insn in cp:
                    u.reg_write(UC_ARM_REG_R0, cp[insn]); u.reg_write(UC_ARM_REG_PC, pc+4)
                return
            raise AssertionError(f'unmodeled instruction {pc:#x}')
        u.hook_add(UC_HOOK_CODE, instruction)
        u.hook_add(UC_HOOK_MEM_WRITE, write)
        return u

    def call(self, u, name='entry', skew=0):
        u.reg_write(UC_ARM_REG_CPSR, 0x13)
        regs = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
        for i, r in enumerate(regs): u.reg_write(r, 0xABCD0000+i)
        for r, v in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2),
                        (OBJECT, 0x12345678, 0x23456780)): u.reg_write(r, v)
        u.reg_write(UC_ARM_REG_SP, STACK-skew); u.reg_write(UC_ARM_REG_LR, RET)
        u.emu_start(OWNER+0x1000+self.syms[name], RET, count=10000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), RET)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), STACK-skew)
        self.assertEqual([u.reg_read(r) for r in regs], [0xABCD0000+i for i in range(8)])
        self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, 0x13)
        return u.reg_read(UC_ARM_REG_R0)

    def test_atomic_install_remove_and_abi_aligned_or_skewed(self):
        for skew in (0, 4):
            u = self.machine(); put(u, OWNER+0x400, 1)
            self.assertEqual(self.call(u, skew=skew), 2)
            self.assertEqual(word(u, OBJECT), OWNER+0x2000)
            self.assertEqual(self.call(u, 'observe', skew), 0x87654321)
            self.assertEqual(word(u, OWNER+0x420), 1)
            self.assertEqual(word(u, OWNER+0x424), 1)
            self.assertEqual(word(u, OWNER+0x428), 0)
            self.assertEqual(word(u, OWNER+0x42c), 1)
            self.assertEqual(word(u, OWNER+0x430), TCB)
            self.assertEqual(word(u, OWNER+0x438), 0)
            self.assertEqual(word(u, OWNER+0x440), STACK-skew)
            self.assertEqual(word(u, OWNER+0x484), 1 << 10)
            put(u, OWNER+0x400, 2)
            self.assertEqual(self.call(u), 2)
            self.assertEqual(self.stores, [OWNER+0x2000, STOCK])
            self.assertEqual(len(self.native_calls), 1)

    def test_foreign_pointer_listener_and_table_are_never_overwritten(self):
        for a in (OBJECT, OBJECT+8, OBJECT+12, OWNER+0x2000, OWNER+0x200c, OWNER+0x2024):
            u = self.machine(); put(u, OWNER+0x400, 1); put(u, a, 0xDEADBEEF)
            self.assertEqual(self.call(u), 0x10)
            self.assertEqual(self.stores, [])

    def test_recursion_is_observed_and_native_return_is_preserved(self):
        u = self.machine(recursive=True)
        self.assertEqual(self.call(u, 'observe'), 0x87654321)
        self.assertEqual(word(u, OWNER+0x420), 2)
        self.assertEqual(word(u, OWNER+0x424), 2)
        self.assertEqual(word(u, OWNER+0x428), 0)
        self.assertEqual(word(u, OWNER+0x42c), 2)

    def test_task_change_is_recorded(self):
        u = self.machine(); self.call(u, 'observe')
        put(u, 0xC3000098, TCB+132); put(u, TCB+132+8, 43)
        self.call(u, 'observe')
        self.assertEqual(word(u, OWNER+0x438), 1)
        self.assertEqual(word(u, OWNER+0x484), (1 << 10) | (1 << 11))

    def test_callback_only_on_outer_observed_task_with_owned_arguments(self):
        u = self.machine(recursive=True, callback=True)
        self.assertEqual(self.call(u, 'observe', 4), 0x87654321)
        self.assertEqual(len(self.native_calls), 2)
        self.assertEqual(len(self.callbacks), 1)
        for at, value in ((OWNER+0x414, TCB+132), (OWNER+0x410, OWNER),
                          (OWNER+0x40c, 0xC06CF498), (OWNER+0x40c, OWNER+0x8000)):
            u = self.machine(callback=True); put(u, at, value)
            self.assertEqual(self.call(u, 'observe'), 0x87654321)
            self.assertEqual(self.callbacks, [])

    def test_mutation_omitting_native_call_is_detected(self):
        source = SOURCE.read_text().replace('blx ip                        @ original method',
                                          'nop                           @ original method')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'mutant.S'; p.write_text(source)
            mutant = armasm.assemble(p, [f'OWNED={OWNER}'])
        u = self.machine(mutant)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.call(u, 'observe'), 0x87654321)


if __name__ == '__main__': unittest.main()
