"""One owned ARM far transfer; actual shared boot, claim, native allocator.

The installation interval and restoration are modelled quiescent. This suite
does not supply live admission or prove absence of unknown indirect entries.
"""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from unicorn import UC_HOOK_CODE, UC_MEM_WRITE
from unicorn import arm_const as ar
from v3 import fpl_owned_hook as hook
from v3 import test_fpl_v3 as boot


class Camera(boot.Camera):
    def __init__(self, *args, **kwargs):
        self.arm_writes = []
        self.check_arming = True
        super().__init__(*args, **kwargs)

    def memory(self, mu, access, address, size, value, unused):
        super().memory(mu, access, address, size, value, unused)
        if access == UC_MEM_WRITE and hook.SITE <= address < hook.SITE+8 and self.check_arming:
            assert self.journal() == [(hook.SITE, 8, hook.STOCK)], 'both words must already be journaled'
            assert self.calls[-2:] == ['DCACHE', 'ICACHE'], 'veneer must be published before arming'
            self.arm_writes.append((address, size, value))


class OwnedHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = boot.fpl.IMAGE.read_bytes()
        cls.product, cls.syms, cls.evidence = hook.build(cls.image, offline_quiescent_model=True)
        cls.loader, cls.binary, _ = boot.envelope()

    def machine(self, *, padding=0, products=None):
        m = Camera(self.loader, self.binary,
                   products if products is not None else [('10LEVEL.BIN', self.product)])
        if padding:
            # Reserve through the same actual USER allocator, no address alias.
            m.mu.reg_write(ar.UC_ARM_REG_R3, 0)
            sp = boot.old.STACK-0x1000
            m.put(sp, 0)
            m.call(boot.FW['MEM_GET'], r0=boot.native.allocator.CHANNEL,
                   r1=padding, sp=sp)
        return m

    def replay(self, m, *, patched, flags):
        # Run both displaced instructions and the actual native epilogue. Seed
        # the stack exactly as the C05094B8 push/sub prologue left it.
        sp = boot.old.STACK-0x2000
        saved = [0xA1000000+i for i in range(6)] + [boot.old.DONE]
        m.mu.mem_write(sp+0x20, struct.pack('<7I', *saved))
        regs = [getattr(ar, 'UC_ARM_REG_R'+str(i)) for i in range(13)]
        for i, r in enumerate(regs):
            m.mu.reg_write(r, 0xB1000000+i)
        m.mu.reg_write(ar.UC_ARM_REG_LR, 0xC0509730)  # native unlock BL returned here
        m.mu.reg_write(ar.UC_ARM_REG_SP, sp)
        m.mu.reg_write(ar.UC_ARM_REG_CPSR, flags | 0x13)
        # Stop on RESUME with a code hook: unicorn's `until` check is skipped
        # when the stock direct `b` chains straight into the RESUME block.
        def stop(mu, address, size, unused):
            if address == hook.RESUME:
                mu.emu_stop()
        h = m.mu.hook_add(UC_HOOK_CODE, stop, begin=hook.RESUME, end=hook.RESUME)
        try:
            m.mu.emu_start(hook.SITE, hook.RESUME, count=100)
        finally:
            m.mu.hook_del(h)
        self.assertEqual(m.mu.reg_read(ar.UC_ARM_REG_PC), hook.RESUME)
        before_epilogue = tuple(m.mu.reg_read(r) for r in regs) + (
            m.mu.reg_read(ar.UC_ARM_REG_LR), m.mu.reg_read(ar.UC_ARM_REG_SP),
            m.mu.reg_read(ar.UC_ARM_REG_CPSR))
        self.assertEqual(before_epilogue[2], 0)
        self.assertEqual(before_epilogue[-3], hook.SITE)
        self.assertEqual(before_epilogue[-2], sp)
        self.assertEqual(before_epilogue[-1], flags | 0x13)
        m.mu.emu_start(hook.RESUME, boot.old.DONE, count=100)
        self.assertEqual(m.mu.reg_read(ar.UC_ARM_REG_PC), boot.old.DONE)
        self.assertEqual(m.mu.reg_read(ar.UC_ARM_REG_SP), sp+0x3C)
        self.assertEqual(m.mu.reg_read(ar.UC_ARM_REG_R0), 0)
        return before_epilogue, tuple(m.mu.reg_read(r) for r in regs)

    def test_replay_two_native_owned_addresses_flags_and_shared_restore(self):
        targets = []
        for padding in (0, 0x20000):
            m = self.machine(padding=padding)
            stock = {}
            for flags in (0, 0xF0000000, 0xA8000000):
                stock[flags] = self.replay(m, patched=False, flags=flags)
            m.boot()
            target = m.w(hook.SITE+4)
            targets.append(target)
            self.assertEqual(m.w(hook.SITE), 0xE51FF004)
            self.assertFalse(hook.bl_reachable(hook.SITE, target))
            block = m.w(m.state()+boot.old.O_SUPS+44)
            self.assertEqual(target, block+self.syms['veneer'])
            self.assertEqual(m.w(block+self.syms['result']), 2)
            self.assertEqual([(a, n) for a, n, _ in m.arm_writes],
                             [(hook.SITE+4, 4), (hook.SITE, 4)])
            self.assertEqual(bytes(m.mu.mem_read(target, 12)),
                             struct.pack('<III', 0xE3A02000, 0xE51FF004, hook.RESUME))
            for flags in stock:
                self.assertEqual(self.replay(m, patched=True, flags=flags), stock[flags])
            m.check_arming = False
            m.power_off()
            self.assertEqual(bytes(m.mu.mem_read(hook.SITE, 8)), hook.STOCK)
        self.assertNotEqual(*targets)

    def test_stock_guard_both_words_before_claim_and_no_repair(self):
        for index in (0, 1):
            m = self.machine()
            word = struct.unpack_from('<I', hook.STOCK, index*4)[0] ^ 1
            m.put(hook.SITE+index*4, word)
            before = bytes(m.mu.mem_read(hook.SITE, 8))
            m.boot()
            self.assertFalse(m.arm_writes)
            self.assertEqual(m.journal(), [])
            self.assertEqual(bytes(m.mu.mem_read(hook.SITE, 8)), before)

    def test_overlap_second_word_claim_refuses_without_partial_patch(self):
        # An existing claim of only the second word blocks the complete claim;
        # its data stays stock, so refusal is genuinely in svc_claim.
        blocker = boot.old.test_sup('BUSY', [(hook.SITE+4, 0xEA000003, 2, 0xEA000003)])
        m = self.machine(products=[('00BUSY.BIN', blocker), ('10LEVEL.BIN', self.product)])
        m.check_arming = False  # the first diagnostic performs its stock store
        m.boot()
        self.assertEqual(m.journal(), [(hook.SITE+4, 4, hook.STOCK[4:])])
        self.assertEqual(bytes(m.mu.mem_read(hook.SITE, 8)), hook.STOCK)
        self.assertIn('CONFLICT', [r[0] for r in m.log()])

    def test_fingerprint_site_live_gate_and_reach_boundaries(self):
        with self.assertRaises(ValueError):
            hook.build(self.image)
        with self.assertRaises(ValueError):
            hook.build(self.image, site=hook.SITE+4, offline_quiescent_model=True)
        bad = bytearray(self.image); bad[hook.SITE-hook.BASE+4] ^= 1
        with self.assertRaises(ValueError):
            hook.build(bytes(bad), offline_quiescent_model=True)
        for delta, accepted in ((-(1 << 25), True), ((1 << 25)-4, True),
                                (1 << 25, False), (-(1 << 25)-4, False)):
            self.assertEqual(hook.bl_reachable(hook.SITE, (hook.SITE+8+delta)&0xffffffff), accepted)
        self.assertFalse(hook.bl_reachable(hook.SITE, 0x44500001))
        self.assertFalse(hook.bl_reachable(hook.SITE, 0x44500000))
        self.assertEqual(len(self.evidence['mode_exclusions']), 2)

    def test_direct_branch_scanner_detects_an_interior_entry(self):
        # A real ARM branch to the literal word cannot be silently classified
        # as safe; check decoder independently of the fingerprint rejection.
        site = 0x1000
        word = 0xEA000000 | (((site+4-(site-8)-8)//4)&0xffffff)
        hits = hook.direct_candidates(struct.pack('<4I', word, 0, 0, 0), site-8, site, site+8)
        self.assertIn(('ARM', site-8, site+4), hits)

    def test_mutation_missing_first_replay_instruction_fails(self):
        text = hook.SOURCE.read_text()
        old = 'mov r2, #0                      @ exact first displaced instruction (no S)'
        self.assertIn(old, text)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'mutant.S'
            source.write_text(text.replace(old, 'nop'))
            with patch.object(hook, 'SOURCE', source):
                product, _, _ = hook.build(self.image, offline_quiescent_model=True)
            m = self.machine(products=[('10LEVEL.BIN', product)])
            m.boot()
            with self.assertRaises(AssertionError):
                self.replay(m, patched=True, flags=0xA0000000)


if __name__ == '__main__':
    unittest.main()
