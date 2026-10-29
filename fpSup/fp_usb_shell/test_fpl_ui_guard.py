"""Actual guard and kernel save/restore instructions. No device IO.

CP15 register inputs/cache side effects are modeled explicitly; ordinary RAM,
the six code writes, CPSR masking and native kernel frames execute in Unicorn.
"""
import os
from pathlib import Path
import struct
import unittest

import armasm
from firmware import get_camera
import fpl_ui as ui
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

SOURCE = Path(__file__).parent/'asm/fpl_ui_guard.S'
CODE, P, B, OWNER = 0x45000000, 0x45002000, 0x45004000, 0x46000000
RET, STACK = 0x48000000, 0x4500F000
TCB, CURRENT, FRAME = 0xC3000838, 0xC3000098, 0xC3B01000
ENTRIES = [OWNER+0x1100, OWNER+0x1200, OWNER+0x1300]
SITES = list(ui.STRING_SITES.values())


def put(u, at, *values):
    u.mem_write(at, struct.pack('<%dI' % len(values), *values))


def word(u, at):
    return struct.unpack('<I', u.mem_read(at, 4))[0]


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        cls.body = armasm.assemble(SOURCE, [f'P={P}', f'B={B}'])
        cls.sym = armasm.symbols(SOURCE, [f'P={P}', f'B={B}'])

    def machine(self, cpus=1, mutate=None):
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for a, n in [(0xC0000000, 0x4000000), (CODE, 0x10000),
                     (OWNER, 0x10000), (RET, 0x1000)]:
            u.mem_map(a, n)
        u.mem_write(0xC0000000, self.image)
        body = bytearray(self.body)
        if mutate == 'skip-pc':
            # Replace PC comparison with one that can never take the refusal.
            at = self.sym['pc_loop']+8
            struct.pack_into('<I', body, at, 0xE3520000)  # cmp r2,#0
        if mutate == 'skip-restore':
            struct.pack_into('<I', body, self.sym['roundtrip_restore'], 0xE3A05000)
        u.mem_write(CODE, bytes(body))
        put(u, CURRENT, TCB+132)
        self.task(u, 1, current=True)
        self.task(u, 2)
        self.writes, self.cache, self.hook_entries = [], [], []
        self.allow_owned = False
        cp = {0xEE100F10: 0x410FC075, 0xEE100FB0: 0x80000000,
              0xEE390F50: (cpus-1) << 24}
        def hook(mu, pc, size, _):
            if self.allow_owned and (OWNER+0x1000 <= pc < OWNER+0x2000 or
                                     OWNER+0x3000 <= pc < OWNER+0x3400 or
                                     any(site <= pc < site+8 for site in SITES)):
                self.assertEqual(mu.reg_read(UC_ARM_REG_CPSR) & 0xC0, 0xC0)
                if pc in SITES:
                    self.hook_entries.append(pc)
                return
            if pc in (0xC000E91C, 0xC000EABC):
                self.assertEqual(mu.reg_read(UC_ARM_REG_SP) & 7, 0)
                self.assertEqual(mu.reg_read(UC_ARM_REG_CPSR) & 0xC0, 0xC0)
                self.cache.append(pc)
                mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
                return
            if not CODE <= pc < CODE+len(body):
                raise AssertionError(f'unmodeled native execution {pc:#x}')
            insn = word(mu, pc)
            if insn in cp:
                mu.reg_write(UC_ARM_REG_R0, cp[insn])
                mu.reg_write(UC_ARM_REG_PC, pc+4)
        def write(mu, access, at, size, value, _):
            if any(site <= at < site+8 for site in SITES):
                self.assertEqual(mu.reg_read(UC_ARM_REG_CPSR) & 0xC0, 0xC0)
                self.assertEqual(word(mu, P+24), 500)
                self.writes.append((at, size, value))
        u.hook_add(UC_HOOK_CODE, hook)
        u.hook_add(UC_HOOK_MEM_WRITE, write)
        put(u, P+64, *ENTRIES, OWNER)
        return u

    def task(self, u, tid, current=False, state=4, pc=0xC0012340, cpsr=0x13):
        at = TCB+132*tid
        frame = FRAME+tid*0x100
        put(u, at+8, tid)
        put(u, at+0x18, 0x1000)
        u.mem_write(at+0x23, bytes([1 if current else state]))
        put(u, at+0x74, frame+0xD0, frame)
        put(u, frame+0xC4, cpsr, 0x12345678, pc)

    def call(self, u, command, cpsr=0x13, skew=0):
        put(u, P, command)
        u.reg_write(UC_ARM_REG_CPSR, cpsr)
        regs = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]
        for n, reg in enumerate(regs):
            u.reg_write(reg, 0x12340000+n)
        u.reg_write(UC_ARM_REG_SP, STACK-skew)
        u.reg_write(UC_ARM_REG_LR, RET)
        u.emu_start(CODE, RET, count=100000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), RET)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), STACK-skew)
        self.assertEqual(u.reg_read(UC_ARM_REG_CPSR) & 0xDF, cpsr & 0xDF)
        self.assertEqual([u.reg_read(r) for r in regs], [0x12340000+n for n in range(8)])
        return word(u, P+4)

    def stock(self, u):
        for site in SITES:
            self.assertEqual(bytes(u.mem_read(site, 8)), self.image[site-0xC0000000:site-0xC0000000+8])

    def test_inspect_install_remove_and_masks(self):
        for mask in (0, 0x40, 0x80, 0xC0):
            for skew in (0, 4):
                u = self.machine()
                self.assertEqual(self.call(u, 0, cpsr=0x13|mask, skew=skew), 2)
                self.stock(u)
                self.assertEqual(self.writes, [])
                self.assertEqual(self.call(u, 1, cpsr=0x13|mask, skew=skew), 2)
                for site, target in zip(SITES, ENTRIES):
                    self.assertEqual(bytes(u.mem_read(site, 8)), struct.pack('<2I', 0xF000F8DF, target))
                self.assertEqual(len(self.writes), 6)
                self.assertEqual(self.cache, [0xC000E91C, 0xC000EABC])
                self.assertEqual(self.call(u, 2, cpsr=0x13|mask, skew=skew), 2)
                self.stock(u)
                self.assertEqual(len(self.writes), 12)

    def test_all_displaced_halfwords_including_last_task_refuse(self):
        for site in SITES:
            for off in (0, 2, 4, 6):
                u = self.machine()
                self.task(u, 500, pc=site+off, cpsr=0x33)
                self.assertEqual(self.call(u, 1), 0x13)
                self.assertEqual(word(u, P+32), 500)
                self.assertEqual(self.writes, [])
                self.stock(u)

    def test_foreign_second_words_refuse_without_partial_install(self):
        for site in SITES:
            u = self.machine()
            put(u, site+4, 0xDEADBEEF)
            self.assertEqual(self.call(u, 1), 0x14)
            self.assertEqual(self.writes, [])
            self.assertEqual(word(u, site+4), 0xDEADBEEF)

    def test_refuse_bad_context_topology_request_and_frames(self):
        cases = [(CURRENT, 0), (0xC3033268, 1), (0xC3000094, 1),
                 (TCB+264+0x18, 16), (TCB+264+0x78, FRAME-0x2000),
                 (TCB+264+0x78, 0xFFFFFF00), (TCB+264+8, 99),
                 (P+64, OWNER+4)]
        for at, value in cases:
            u = self.machine()
            put(u, at, value)
            self.assertNotEqual(self.call(u, 1), 2)
            self.assertEqual(self.writes, [])
            self.stock(u)
        u = self.machine(cpus=2)
        self.assertEqual(self.call(u, 1), 0x10)
        self.stock(u)

    def test_dormant_current_and_owned_layer_pc(self):
        u = self.machine()
        self.task(u, 3, state=8, pc=SITES[0]+4, cpsr=0x33)
        self.task(u, 2, pc=OWNER+0x1120)
        self.assertEqual(self.call(u, 1), 2)
        self.assertEqual(self.call(u, 2), 2)
        self.stock(u)

    def test_pc_guard_mutation_is_detected(self):
        u = self.machine(mutate='skip-pc')
        self.task(u, 2, pc=SITES[0]+4, cpsr=0x33)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.call(u, 1), 0x13)

    def test_finite_roundtrip_actual_far_jumps_and_shared_layers(self):
        import fpl_ui_hook_trial as trial
        for layers in (1, 2):
            u = self.machine()
            self.allow_owned = True
            reader = OWNER+0x6000
            body, entries = trial.build_owned(OWNER, reader, layers,
                                              [OWNER, 0, OWNER, 0x10000], '01'*16)
            u.mem_write(OWNER, body)
            put(u, reader+0x10, ui.POOL_LEN, ui.POOL)
            put(u, P+64, *entries, OWNER)
            self.assertEqual(self.call(u, 3), 2)
            self.stock(u)
            values = trial.check_results(bytes(u.mem_read(OWNER+0x4000, 1024)), OWNER, reader, layers)
            self.assertEqual(len(values), (layers+1)*3)
            self.assertEqual(self.hook_entries, SITES*(layers+1))
            self.assertEqual(self.cache, [0xC000E91C, 0xC000EABC]*2)
            self.assertEqual(len(self.writes), 12)

    def test_finite_checker_result_mutation_is_detected(self):
        import fpl_ui_hook_trial as trial
        u = self.machine()
        self.allow_owned = True
        reader = OWNER+0x6000
        body, entries = trial.build_owned(OWNER, reader, 1,
                                          [OWNER, 0, OWNER, 0x10000], '01'*16)
        u.mem_write(OWNER, body)
        put(u, reader+0x10, ui.POOL_LEN, ui.POOL)
        put(u, OWNER+0x2000, OWNER+0x2104)  # corrupt private pointer, not code
        put(u, P+64, *entries, OWNER)
        self.assertEqual(self.call(u, 3), 2)
        self.stock(u)
        with self.assertRaises(RuntimeError):
            trial.check_results(bytes(u.mem_read(OWNER+0x4000, 1024)), OWNER, reader, 1)

    def test_roundtrip_restoration_mutation_is_detected(self):
        import fpl_ui_hook_trial as trial
        u = self.machine(mutate='skip-restore')
        self.allow_owned = True
        reader = OWNER+0x6000
        body, entries = trial.build_owned(OWNER, reader, 1,
                                          [OWNER, 0, OWNER, 0x10000], '01'*16)
        u.mem_write(OWNER, body)
        put(u, reader+0x10, ui.POOL_LEN, ui.POOL)
        put(u, P+64, *entries, OWNER)
        self.assertEqual(self.call(u, 3), 2)
        with self.assertRaises(AssertionError):
            self.stock(u)


class NativeContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])

    def test_irq_and_voluntary_frames_restore_actual_pc_and_cpsr(self):
        for irq, thumb in ((False, False), (True, False), (True, True)):
            u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
            u.mem_map(0xC0000000, 0x4000000)
            u.mem_write(0xC0000000, self.image)
            u.mem_map(CODE, 0x10000)
            u.reg_write(UC_ARM_REG_C1_C0_2, 0xF << 20)
            u.reg_write(UC_ARM_REG_FPEXC, 1 << 30)
            top, irqtop = CODE+0x8000, CODE+0xC000
            resume = SITES[0]+4 if thumb else 0xC0012340
            saved_cpsr = 0x60000013 | (0x20 if thumb else 0)
            put(u, CURRENT, TCB+132)
            put(u, 0xC30000A0, TCB+264)
            put(u, 0xC3000094, 0)
            put(u, 0xC3033268, 0)
            u.reg_write(UC_ARM_REG_CPSR, 0x13)
            u.reg_write(UC_ARM_REG_SP, top)
            if irq:
                # Exact four-word IRQ-return input consumed at FC0/FC8.
                u.reg_write(UC_ARM_REG_CPSR, 0xD2)
                u.reg_write(UC_ARM_REG_SP, irqtop-16)
                put(u, irqtop-16, 0x5555, saved_cpsr, 0x12345678, resume)
                entry = 0xC0000F88
            else:
                # Execute the actual voluntary ARM frame construction.
                u.reg_write(UC_ARM_REG_CPSR, saved_cpsr)
                u.reg_write(UC_ARM_REG_R12, 0x12345678)
                u.reg_write(UC_ARM_REG_LR, resume)
                entry = 0xC0000CFC
            u.emu_start(entry, 0xC0000D60, count=1000)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC), 0xC0000D60)
            saved = word(u, TCB+132+0x78)
            self.assertEqual(saved, top-0xD0)
            self.assertEqual(word(u, saved+0xC4), saved_cpsr)
            self.assertEqual(word(u, saved+0xCC), resume)
            u.reg_write(UC_ARM_REG_CPSR, 0xD3)
            u.reg_write(UC_ARM_REG_SP, saved)
            u.emu_start(0xC0000DA0, resume, count=1000)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC), resume)
            self.assertEqual(u.reg_read(UC_ARM_REG_CPSR), saved_cpsr)
            self.assertEqual(u.reg_read(UC_ARM_REG_SP), top)


if __name__ == '__main__':
    unittest.main()
