"""Real ordinary script/loader/stage2/launcher -> owned native menu runtime.

Native variable instructions and page/string adapter reuse their strict fixtures.
File IO, allocators, cache/CPU topology, scheduling and the original drawing
method are modeled. Staging is poisoned on free. No camera IO in these tests.
"""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import build_card as product
import test_runtime as runtime
import test_adapter as a
import test_controller as c
from build_adapter import build
import card_build as card
import test_fpl_shell_card as shell
from unicorn.arm_const import *

DRAW, STOCK, TCB = 0xC38D37CC, 0xC2E55A70, a.TCB+39*132
STAGING = a.CODE+0x90000


class Machine(a.Machine):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.freed = False
        self.bin = b''
        self.registrations, self.tasks = [], []
        self.journal_calls = 0
        self.fail_registration = 0
        self.boot_alloc_fail = False
        self.restore_length = len(a.restore.restore_code())
        self.firmware = {v: k for k, v in shell.FW.items()}
        self.unpublished = {}
        self.put(DRAW, STOCK, 0, a.APP, 1)
        self.put(TCB+8, 39); self.put(TCB+0x18, 0x4000)
        self.put(TCB+0x74, a.STACK)
        self.put(a.restore.MANAGER+12, 0); self.put(a.restore.MANAGER+52, 0)
        self.put(0xC3000098, TCB)
        self.u.mem_write(a.TCB+132, bytes(132))  # base fixture's old current task is absent
        self.u.mem_write(TCB+0x23, b'\x01')

    def instruction(self, u, pc, size, data):
        name = self.firmware.get(pc)
        if name:
            args = [u.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
            self.test.assertEqual(u.reg_read(UC_ARM_REG_SP) & 7, 0)
        if name == 'H_GET' and args[0] == card.POOL_DESC:
            self.freed = False
            self.put(args[0], STAGING, 0, STAGING, args[2]); self.ret(); return
        if name == 'H_GET' and self.boot_alloc_fail:
            self.put(args[0], 0, 0, 0, args[2]); self.ret(); return
        if name == 'H_FREE':
            self.test.assertEqual(args[:2], [card.POOL_DESC, 2])
            self.u.mem_write(STAGING, b'\xfe'*0x10000)
            self.freed = True; self.ret(); return
        if name == 'F_MGR': self.ret(0x12340000); return
        if name == 'F_VOL': self.ret(1); return
        if name == 'F_OPEN':
            self.test.assertEqual(bytes(u.mem_read(args[1], 11)), b'\\fpSup.BIN\0')
            self.ret(bool(self.bin)); return
        if name == 'F_READ':
            self.test.assertLessEqual(len(self.bin), args[2])
            u.mem_write(args[1], self.bin)
            u.ctl_remove_cache(args[1], args[1]+len(self.bin))
            self.ret(len(self.bin)); return
        if name in ('F_CTOR', 'F_DTOR', 'F_CLOSE', 'STATSK'): self.ret(); return
        if name == 'MEM_HEAP': self.ret(0x44000000); return
        if name == 'MEM_GET':
            self.journal_calls += 1
            self.ret(a.JOURNAL_OBJECT); return
        if name == 'POFF_MGR': self.ret(a.restore.MANAGER); return
        if name == 'POFF_ADD':
            if self.fail_registration == len(self.registrations)+1:
                self.ret(0); return
            self.registrations.append(tuple(args[1:3]))
            self.put(a.restore.MANAGER+(52 if args[2] else 12), args[1])
            self.ret(1); return
        if name == 'CRETSK':
            self.tasks.append(bytes(u.mem_read(args[0], 32))); self.ret(77); return
        if name == 'H_GET':
            super().instruction(u, pc, size, data)
            allocated = self.word(args[0])
            if allocated: self.unpublished[allocated] = len(self.cache)
            return
        if name in ('H_ADDR', 'DCACHE', 'ICACHE'):
            return super().instruction(u, pc, size, data)
        if pc == 0xC06CF498: self.ret(0x55); return
        if STAGING <= pc < STAGING+0x10000:
            if self.freed: raise AssertionError('execution in freed staging')
            return
        if card.DIR_ENTRY <= pc < card.DIR_ENTRY+len(self.loader): return
        if a.JOURNAL_OBJECT+12 <= pc < a.JOURNAL_OBJECT+12+self.restore_length: return
        if any(lo <= pc < lo+n for lo, n in self.allocations):
            for lo, n in self.allocations:
                if lo <= pc < lo+n and lo in self.unpublished:
                    since = self.unpublished.pop(lo)
                    self.test.assertGreaterEqual(len(self.cache)-since, 2)
                    self.test.assertEqual(self.cache[-2:], [card.DCACHE, card.ICACHE])
            cp = {0xEE100F10: 0x410FC075, 0xEE100FB0: 0x80000000, 0xEE390F50: 0}
            insn = self.word(pc)
            if insn in cp:
                u.reg_write(UC_ARM_REG_R0, cp[insn]); u.reg_write(UC_ARM_REG_PC, pc+4)
            return
        return super().instruction(u, pc, size, data)

    def write(self, u, access, address, size, value, data):
        if self.freed and STAGING <= address < STAGING+0x10000:
            raise AssertionError('write into freed staging')
        # stage2 writes stock declarations before installation, outside the
        # hook transaction. Runtime publication remains independently checked.
        if 0xC0000000 <= address < 0xC3000000:
            self.test.assertIn(address, [s+i for s in a.ui.STRING_SITES.values() for i in (0, 4)])
            self.writes.append((address, value))

    def run(self):
        bridge = shell.ShellTrial.__new__(shell.ShellTrial)
        bridge.t, bridge.mu, bridge.lines = self.test, self.u, self.script.splitlines()
        bridge.saved = {}
        bridge.word = self.word
        def dispatch(target):
            result = self.call(target)
            if target == card.DIR_ENTRY: self.load_result = result
            return result
        bridge.dispatch = dispatch
        bridge.run()
        self.test.assertEqual(bytes(self.u.mem_read(card.DIR_ENTRY, card.RESTORE_LEN)),
            self.image[card.DIR_ENTRY-card.BASE:card.DIR_ENTRY-card.BASE+card.RESTORE_LEN])
        self.test.assertEqual(self.word(card.ECHO_SLOT), card.ECHO_STOCK)
        return self.load_result

    def draw(self):
        return self.call(self.word(self.word(DRAW)+12), DRAW, 0, 0)


class Boot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp, cls.fpl = Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN'])
        cls.image = a.restore.CAMERA.verify_main(cls.fpl)
        c.registry.SEG0_SIZE = len(cls.image)
        cls.block, cls.info, cls.reference = product.menu.build(cls.fp, cls.fpl)
        cls.text = build(runtime=True, boot=True)
        cls.launch, cls.layout = product.payload(cls.fp, cls.fpl)
        cls.sections = a.restore.stock_sections(cls.image)

    def machine(self, debug=False):
        with patch.object(a, 'Machine', Machine):
            m, p = runtime.Runtime.machine(self)
        script, art = card.ordinary_card(self.fpl, stock_sections=self.sections,
                                        boot_bins=[(self.launch, 0)], shell=debug, ui_boot=True)
        m.bin, m.loader, m.script, m.image = art['binfile'], art['loader'], script, self.image
        return m, p, script

    def booted(self, debug=False):
        m, p, script = self.machine(debug)
        self.assertEqual(m.run(), 1)
        owner = m.word(DRAW)-0x2000
        self.assertIn((owner, 0x10000), m.allocations)
        self.assertEqual(m.word(owner+0x20), 2)
        self.assertEqual(m.word(owner+0x8004), 0)  # entry installs/returns; no GUI work yet
        self.assertTrue(m.freed)
        self.assertEqual(m.word(STAGING), 0xfefefefe)
        p.CODE, p.STATE = owner+0x3000, owner+0x8038
        # The native fixture's reader/writer accepts the USER retained blocks.
        old_string, old_write = p.string, p.write
        p.string = lambda addr: (bytes(m.u.mem_read(addr, 128)).split(b'\0')[0]
            if owner <= addr < owner+0x10000 else old_string(addr))
        p.write = lambda addr, data: (m.u.mem_write(addr, bytes(data))
            if owner <= addr <= addr+len(data) <= owner+0x10000 else old_write(addr, data))
        self.assertEqual(m.draw(), 0x55)
        self.assertEqual(m.word(owner+0x8004), 2)
        self.assertEqual(m.word(owner+0x8008), 0)
        return m, p, owner, script

    def test_owned_boot_native_keys_poisoned_staging_and_both_shutdown_reasons(self):
        for debug in (False, True):
            m, p, owner, script = self.booted(debug)
            self.assertEqual(len(m.tasks), int(debug))
            self.assertEqual('0xC003178C' in script, debug)
            self.assertEqual('0xC0D03A24' in script, debug)
            report = a.restore.inspect(lambda at, n: [m.word(at+4*i) for i in range(n)], self.image, draw=True)
            self.assertTrue(report['complete'])
            for direction, label in ((-1,'12 fps'), (1,'Off'), (1,'4 fps'), (1,'6 fps')):
                self.assertEqual(p.press(direction), 0)
                self.assertEqual(m.draw(), 0x55)
                self.assertEqual(p.posted_text(), label)
            self.assertEqual(bytes(m.u.mem_read(m.word(owner+0x8030), len(self.reference['page']))), self.reference['page'])
            for reason in (1, 4):
                m.put(DRAW, owner+0x2000)
                for at, _ in self.sections: m.put(at, 0xbadbad)
                obj = m.registrations[0][0]
                m.call(m.word(obj+4), obj, reason)
                self.assertEqual(m.word(DRAW), STOCK)
                for at, value in self.sections:
                    self.assertEqual(bytes(m.u.mem_read(at, 4)), value)

    def test_duplicate_fresh_staging_never_places_or_allocates_again(self):
        m, p, owner, _ = self.booted()
        before = (list(m.allocations), list(m.registrations), list(m.writes))
        self.assertEqual(m.run(), 1)  # shared loader reports stage2 returned, not product success
        self.assertEqual((m.allocations, m.registrations, m.writes), before)
        self.assertEqual(m.journal_calls, 1)
        self.assertEqual(m.word(DRAW), owner+0x2000)
        p.press(1); m.draw(); self.assertEqual(p.posted_text(), '4 fps')

    def test_foreign_or_stale_sites_refuse_before_journal(self):
        for at in (DRAW, *(a for a, _ in self.sections)):
            m, _, _ = self.machine(); m.put(at, 0xdeadbeef)
            m.run()
            self.assertEqual(m.word(at), 0xdeadbeef)
            self.assertEqual(m.journal_calls, 0)
            self.assertEqual(m.allocations, [])

    def test_failed_allocation_registration_or_ui_leave_no_active_product(self):
        for failure in ('allocation', 'ordinary', 'forced', 'ui'):
            m, _, _ = self.machine()
            if failure == 'allocation': m.boot_alloc_fail = True
            if failure == 'ordinary': m.fail_registration = 1
            if failure == 'forced': m.fail_registration = 2
            if failure == 'ui': m.put(a.READER+0x24, 0)
            m.run()
            self.assertEqual(m.word(DRAW), STOCK)
            self.assertEqual(m.word(a.TABLE+8), a.ui.PAGES['MainB2'])
            for at, data in self.sections: self.assertEqual(bytes(m.u.mem_read(at,4)), data)

    def test_mutation_admission_bypass_is_detected(self):
        m, _, _, _ = self.booted()
        # Isolated copy of emitted BIN: change the first conditional refusal to
        # NOP in the new stage2 prefix. Never mutate the working assembly.
        blob = bytearray(m.bin)
        count = struct.unpack_from('<I', blob, 4)[0]
        start = 16+count*8
        words = list(struct.unpack_from('<20I', blob, start))
        at = next(i for i, w in enumerate(words) if w >> 24 == 0x1a)
        struct.pack_into('<I', blob, start+4*at, 0xe320f000)
        m.bin = bytes(blob)
        before = list(m.writes)
        m.run()
        with self.assertRaises(AssertionError): self.assertEqual(m.writes, before)

    def test_mutation_missing_first_owned_icache_publication_is_detected(self):
        m, _, _ = self.machine()
        blob = bytearray(m.bin)
        entry = struct.unpack_from('<I', blob, 8)[0]  # single no-shell entry
        at = blob.index(struct.pack('<I', card.ICACHE), entry,
                        entry+self.layout['launch_symbols']['embedded'])
        struct.pack_into('<I', blob, at, card.DCACHE)
        m.bin = bytes(blob)
        with self.assertRaises(AssertionError): m.run()

    def test_missing_file_and_missing_draw_journal_refuse(self):
        m, _, _ = self.machine(); m.bin = b''
        self.assertEqual(m.run(), 0)
        self.assertEqual(m.word(DRAW), STOCK)
        self.assertEqual(m.registrations, [])
        m, _, _ = self.machine()
        # Remove only the draw declaration, leaving its pre-placement guard.
        blob = bytearray(m.bin)
        count = struct.unpack_from('<I', blob, 4)[0]
        for i in range(count):
            if struct.unpack_from('<I', blob, 16+8*i)[0] == DRAW:
                struct.pack_into('<I', blob, 16+8*i, 0)
                break
        else: self.fail('draw declaration absent from candidate')
        m.bin = bytes(blob); m.run()
        self.assertEqual(m.word(DRAW), STOCK)
        owner = m.allocations[0][0]
        self.assertEqual(m.word(owner+0x20), 0x301)

    def test_payload_change_keeps_autorun_and_default_chain_bytes(self):
        plain, art = card.ordinary_card(self.fpl)
        script, boot = card.ordinary_card(self.fpl, stock_sections=self.sections,
            boot_bins=[(self.launch, 0)], ui_boot=True)
        self.assertEqual(script, plain)
        self.assertEqual(boot['loader'], art['loader'])
        self.assertEqual(boot['worker'], art['worker'])
        other, _ = card.ordinary_card(self.fpl, stock_sections=self.sections,
            boot_bins=[(self.launch+bytes(4), 0)], ui_boot=True)
        self.assertEqual(other, script)


if __name__ == '__main__': unittest.main()
