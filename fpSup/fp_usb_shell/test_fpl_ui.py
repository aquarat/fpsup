"""Actual fp L UI instructions and shared string-layer ABI; no device IO.

This proves call shapes, not registration, rendering, queue consumption or
safe installation. Layers are invoked directly: no hypothetical veneer/cave.
"""
import os
from pathlib import Path
import struct
import unittest

import armasm
import fpl_ui as ui
from firmware import get_camera
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *

HERE = Path(__file__).resolve().parent
CODE, RAM, RET = 0x45000000, 0x46000000, 0x100000
REGS = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]


class NativeUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        source = HERE.parent/'uishare/ui_strings.S'
        cls.layer = armasm.assemble(source)
        cls.sym = armasm.symbols(source)

    def machine(self, allowed, stubs=None):
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a, n in [(0xC0000000, 0x4000000), (CODE, 0x10000), (RAM, 0x20000), (RET, 0x1000)]:
            u.mem_map(a, n)
        u.mem_write(0xC0000000, self.image)
        u.mem_write(CODE, self.layer)
        def hook(mu, pc, size, _):
            if pc in (stubs or {}):
                stubs[pc](mu)
                mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
            elif not any(a <= pc < b for a, b in allowed):
                raise AssertionError(f'unmodelled firmware execution: {pc:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        return u

    @staticmethod
    def put(u, address, *values):
        u.mem_write(address, struct.pack('<%dI' % len(values), *values))

    @staticmethod
    def word(u, address):
        return struct.unpack('<I', u.mem_read(address, 4))[0]

    def call(self, u, fn, *args, skew=0):
        u.reg_write(UC_ARM_REG_CPSR, 0x13)
        for r, value in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
            u.reg_write(r, value)
        for i, r in enumerate(REGS):
            u.reg_write(r, 0x12340000+i)
        u.reg_write(UC_ARM_REG_R12, 0x1234CCCC)
        u.reg_write(UC_ARM_REG_SP, RAM+0x1F000-skew)
        u.reg_write(UC_ARM_REG_LR, RET)
        u.emu_start(fn, RET, count=20000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), RET)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), RAM+0x1F000-skew)
        self.assertEqual([u.reg_read(r) for r in REGS], [0x12340000+i for i in range(8)])
        return u.reg_read(UC_ARM_REG_R0)

    def test_initialized_gui_and_registry_getters(self):
        guards = []
        def guarded(mu):
            guards.append(mu.reg_read(UC_ARM_REG_R0))
            mu.reg_write(UC_ARM_REG_R0, 0)  # initialized singleton, no constructor
        u = self.machine([(ui.GUI_GET, ui.GUI_GET+0x98), (ui.APP_REGISTRY & ~1, ui.APP_REGISTRY+8)],
                         {0xC0013090: guarded})
        self.assertEqual(self.call(u, ui.GUI_GET), ui.GUI_OBJECT)
        self.assertEqual(guards, [0xC37B6CB4, 0xC37B6CBC])
        self.put(u, RAM+0x888, RAM+0x1000)
        self.assertEqual(self.call(u, ui.APP_REGISTRY, RAM), RAM+0x1060)

    def test_native_registry_lookup_found_and_missing(self):
        def strcmp(mu):
            def text(p):
                return bytes(mu.mem_read(p, 64)).split(b'\0', 1)[0]
            a, b = (text(mu.reg_read(r)) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1))
            mu.reg_write(UC_ARM_REG_R0, (a > b)-(a < b))
        u = self.machine([(0xC05D75F8, 0xC05D760E), (0xC05E9598, 0xC05E963A),
                          (0xC05E5FC8, 0xC05E5FEA)], {0xC0013E2C: strcmp})
        names = [b'SLIT_ENABLE', b'SLIT_RATE']
        def fnv(name):
            h = 2166136261
            for c in name: h = ((h ^ c)*16777619) & 0xFFFFFFFF
            return h
        mapping, table, order, output = RAM+0x14, RAM+0x100, RAM+0x200, RAM+0x300
        self.put(u, mapping+8, 2, table, order, 1)
        hashes = [fnv(n) for n in names]
        self.put(u, order, *sorted(range(2), key=lambda i: hashes[i]))
        for i, name in enumerate(names):
            at, desc = RAM+0x400+i*64, RAM+0x800+i*32
            u.mem_write(at, name+b'\0')
            self.put(u, table+i*12, hashes[i], at, desc)
            self.put(u, desc, 0, at, i, i)
        for i, name in enumerate(names):
            at, desc = RAM+0x400+i*64, RAM+0x800+i*32
            self.assertEqual(self.call(u, ui.REGISTRY_LOOKUP, RAM, at, output), 0)
            self.assertEqual(self.word(u, output), desc)
        u.mem_write(RAM+0x500, b'SLIT_MISSING\0')
        self.assertEqual(self.call(u, ui.REGISTRY_LOOKUP, RAM, RAM+0x500, output), 0)
        self.assertEqual(self.word(u, output), 0)

    def test_post_integer_builds_native_event(self):
        events = []
        def memset(mu):
            a, c, n = (mu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
            mu.mem_write(a, bytes([c & 255])*n)
        def queue(mu):
            self.assertEqual(mu.reg_read(UC_ARM_REG_SP) & 7, 0)
            self.assertEqual(mu.reg_read(UC_ARM_REG_R0), RAM+0x1000)
            events.append(bytes(mu.mem_read(mu.reg_read(UC_ARM_REG_R1), 0x38)))
        u = self.machine([(ui.POST_INT, ui.POST_INT+0x50), (0xC0559E28, 0xC0559E60)],
                         {0xC0015058: memset,
                          0xC055A208: lambda mu: mu.reg_write(UC_ARM_REG_R0, RAM+0x1000),
                          0xC055A300: queue})
        self.call(u, ui.POST_INT, 0, RAM+0x200, 7)
        self.assertEqual(events, [struct.pack('<14I', 2, 0, RAM+0x200, 7, *([0]*10))])

    def string_machine(self):
        ranges = [(CODE, CODE+0x2000), (0xC05E1D38, 0xC05E1D4C),
                  (0xC05E23A8, 0xC05E23CA)]
        u = self.machine(ranges)
        self.put(u, RAM+0x10, ui.POOL_LEN, ui.POOL)
        return u

    def layer_at(self, u, base, index, inner=0):
        u.mem_write(base, self.layer)
        text = base+0x800
        table = base+0x700
        u.mem_write(text, b'Slit scan\0')
        self.put(u, table, text)
        self.put(u, base, 0x4C445346, 0, 5, 0x40000000+index, 1, text, text+10,
                 *[inner+self.sym[k] if inner else 0 for k in ('resolve','owns','remain')], table)
        return text

    def test_shared_layers_match_actual_fpl_leaves(self):
        u = self.string_machine()
        for k, site in ui.STRING_SITES.items():
            for skew in (0, 4):
                args = ((0, 1, ui.POOL_LEN-1, ui.POOL_LEN, 0xFFFFFFFF) if k == 'resolve' else
                        (ui.POOL-1, ui.POOL, ui.POOL+ui.POOL_LEN-1, ui.POOL+ui.POOL_LEN))
                for value in args:
                    want = self.call(u, site | 1, RAM, value, skew=skew)
                    got = self.call(u, CODE+self.sym[k], RAM, value, skew=skew)
                    self.assertEqual(got, want, (k, value, skew))
                    self.assertEqual(u.reg_read(UC_ARM_REG_R1), value)
                    self.assertEqual(u.reg_read(UC_ARM_REG_R12), 0x1234CCCC)

    def test_two_shared_layers_resolve_and_borrow_private_strings(self):
        u = self.string_machine()
        a = self.layer_at(u, CODE, 0)
        b = self.layer_at(u, CODE+0x1000, 1, CODE)
        for skew in (0, 4):
            for i, text in enumerate((a, b)):
                self.assertEqual(self.call(u, CODE+0x1000+self.sym['resolve'], RAM, 0x40000000+i, skew=skew), text)
                self.assertEqual(self.call(u, CODE+0x1000+self.sym['owns'], RAM, text+2, skew=skew), 1)
                self.assertEqual(self.call(u, CODE+0x1000+self.sym['remain'], RAM, text+2, skew=skew), 8)

    def test_mutation_losing_private_range_is_detected(self):
        u = self.string_machine()
        text = self.layer_at(u, CODE, 0)
        at = self.sym['resolve_range']
        # Force the range miss in a private emulator image, leaving sources intact.
        import capstone
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        branch = next(i for i in md.disasm(self.layer[at:at+32], at) if i.mnemonic == 'bhs')
        word = struct.unpack('<I', branch.bytes)[0]
        self.put(u, CODE+branch.address, (word & 0x0FFFFFFF) | 0xE0000000)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.call(u, CODE+self.sym['resolve'], RAM, 0x40000000), text)


if __name__ == '__main__':
    unittest.main()
