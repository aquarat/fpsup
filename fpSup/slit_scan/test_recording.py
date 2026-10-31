"""Owned boot -> native keys -> native IRQ dispatch -> conditional restoration.

Mode getters are modeled here (separately proved on hardware); native GUI
registry and early-Vd dispatcher execute real instructions. MMIO progression,
allocators, scheduling, cache effects and unrelated IRQ services are modeled.
"""
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import test_boot as b
import test_adapter as a
import test_runtime as rt
from build_adapter import build
import bindings
import test_fpl_vd_probe as vd
from unicorn.arm_const import *

SLOT, T04, T20 = 0xC31D6DD8, 0x020B047B, 0x165B0000


class Machine(b.Machine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.restore_length = len(a.restore.restore_code(slit=True))
        self.mode = {bindings.GETTERS[k]: v for k, v in zip(('format','quality','size','rate'), (0,4,3,12))}
        for at in (0x30100000, 0x2D810000, 0x100000): self.u.mem_map(at, 0x10000)
        self.put(bindings.APP, 2); self.put(bindings.RECORDING, 0x10000)
        self.put(SLOT-4, 0, 0, 1, 0, 0)
        self.put(0x30100004, T04); self.put(0x30100020, T20)
        self.u.mem_write(0xC31AB0D0, bytes(36))

    def instruction(self, u, pc, size, data):
        # Native Subject/attach are separately executed by the GTAG fixture.
        if pc == 0xC0054E28: self.ret(0xC31AB0D0); return
        if pc == 0xC00CF208:
            subject, obj = (u.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1))
            self.test.assertEqual(subject, 0xC31AB0D0)
            for i in range(9):
                if not self.word(subject+4*i): self.put(subject+4*i,obj); break
            else: raise AssertionError('native attach called with full list')
            self.ret(); return
        if pc in self.mode: self.ret(self.mode[pc]); return
        if pc == bindings.SETTINGS: self.ret(0xC31AB114); return
        if pc in (0xC01256D0, 0xC0121FC8, 0xC0125DF0, 0xC0123DA8, 0xC01F555C, 0xC0016B9C):
            self.ret(); return
        if 0xC0121D18 <= pc < 0xC0121F00 or 0xC0121CD0 <= pc < 0xC0121CE8: return
        return super().instruction(u, pc, size, data)


class Recording(unittest.TestCase):
    queue_observation = False
    @classmethod
    def setUpClass(cls):
        cls.fp, cls.fpl = Path(os.environ['FP_MAIN']), Path(os.environ['FPL_MAIN'])
        cls.image = a.restore.CAMERA.verify_main(cls.fpl)
        b.c.registry.SEG0_SIZE = len(cls.image)
        cls.block, cls.info, cls.reference = b.product.menu.build(cls.fp, cls.fpl)
        lookup=getattr(cls,'lookup_observation',False)
        cls.text = build(runtime=True, boot=True, recording=True, queue_observation=cls.queue_observation,lookup_observation=lookup)
        cls.launch, cls.layout = b.product.payload(cls.fp, cls.fpl, recording=True, queue_observation=cls.queue_observation,lookup_observation=lookup)
        cls.sections = a.restore.stock_sections(cls.image)

    def machine(self, debug=False):
        with patch.object(a, 'Machine', Machine): m, p = rt.Runtime.machine(self)
        script, art = b.card.ordinary_card(self.fpl, stock_sections=self.sections,
            boot_bins=[(self.launch, 0)], shell=debug, ui_boot=True, slit_recording=True)
        m.bin, m.loader, m.script, m.image = art['binfile'], art['loader'], script, self.image
        return m, p, script

    booted = b.Boot.booted

    def irq(self, m, count=1):
        for _ in range(count):
            # The reused native-IRQ ABI checker verifies callee-saved registers,
            # stack alignment and exact incoming interrupt mask on return.
            vd.Probe.call(self, m.u, 0xC0121D19, irq=True)

    def active(self, index=1):
        m,p,o,_ = self.booted()
        for _ in range(index): p.press(1)
        m.draw()                        # selected while idle
        self.assertEqual(m.word(SLOT), 0)
        m.put(bindings.RECORDING, 0x10001); m.draw()
        self.assertEqual(m.word(SLOT), o+0x1800)
        self.irq(m,8)
        scale = (0,6,4,3,2)[index]
        self.assertEqual(m.word(0x30100004), ((524*scale-1)<<16)|(1148*scale-1))
        return m,p,o

    def test_four_rates_native_irq_stop_and_repeated_takes(self):
        for index in range(1,5):
            m,p,o = self.active(index)
            m.put(bindings.RECORDING,0x10000); self.irq(m)
            self.assertEqual(m.word(SLOT),0); self.assertEqual(m.word(0x30100004),T04)
            m.draw(); m.put(bindings.RECORDING,0x10001); m.draw(); self.irq(m,8)
            self.assertNotEqual(m.word(0x30100004),T04)

    def test_off_failure_disabled_mode_change_and_missing_heartbeat(self):
        for case in ('off','disabled','error','mode','status','heartbeat','foreign'):
            m,p,o = self.active()
            if case=='off': p.press(-1)
            if case=='disabled': m.put(o+0x8010,2)
            if case=='error': m.put(o+0x8008,0x123)
            if case=='mode': m.put(0x30100020,0x123)
            if case=='status': m.put(bindings.RECORDING,0x10000)
            if case=='heartbeat': m.put(0xC3076D98,3)
            if case=='foreign': m.put(SLOT,0x12345678)
            if case=='foreign': m.call(o+0x3000+self.text.functions['slit_vd'],o+0x8000)
            else: self.irq(m)
            self.assertEqual(m.word(SLOT),0x12345678 if case=='foreign' else 0)
            self.assertEqual(m.word(o+0x820C),0)
            if case!='mode': self.assertEqual(m.word(0x30100004),T04)
            else: self.assertEqual(m.word(0x30100020),0x123)

    def test_unsupported_and_late_selection_and_failed_start_inert(self):
        for case in ('format','quality','size','rate','app','late','failed'):
            m,p,o,_ = self.booted()
            if case=='late': m.put(bindings.RECORDING,0x10001); m.draw()
            if case in bindings.GETTERS: m.mode[bindings.GETTERS[case]]=99
            if case=='app': m.put(bindings.APP,1)
            p.press(1); m.draw()
            if case!='failed': m.put(bindings.RECORDING,0x10001)
            m.draw()
            self.assertEqual(m.word(SLOT),0)
            self.assertEqual(m.word(0x30100004),T04)
            if case in bindings.GETTERS or case=='app':
                self.assertEqual(p.posted_text(),'Refused')
                p.press(1);m.draw()
                self.assertEqual(p.posted_text(),'Refused')

    def test_menu_app_previews_supported_mode_but_cannot_activate(self):
        m,p,o,_ = self.booted()
        m.put(bindings.APP,5); p.press(1); m.draw()
        self.assertEqual(p.posted_text(),'4 fps')
        m.put(bindings.RECORDING,0x10001); m.draw()
        self.assertEqual(m.word(SLOT),0)
        m.put(bindings.APP,2); m.draw()
        self.assertEqual(m.word(SLOT),0)  # consume the impossible menu start
        m.put(bindings.RECORDING,0x10000);m.draw()
        m.put(bindings.RECORDING,0x10001);m.draw();self.irq(m,8)
        self.assertEqual(m.word(0x30100004),0x0c471ae7)

    def test_changed_native_mode_cleans_up_and_never_resumes_same_take(self):
        m,p,o = self.active()
        m.mode[bindings.GETTERS['rate']] = 99
        m.draw()
        self.assertEqual(m.word(0x30100004),T04)
        self.assertEqual(m.word(SLOT),0)
        self.assertEqual(p.posted_text(),'Refused')
        m.mode[bindings.GETTERS['rate']] = 12
        m.draw()
        self.assertEqual(m.word(SLOT),0)
        self.assertEqual(p.posted_text(),'4 fps')

    def test_foreign_vd_refuses_before_journal_and_admission_mutation_is_detected(self):
        for mutation in (False,True):
            m,p,_ = self.machine()
            m.put(SLOT,0xdeadbeef)
            if mutation:
                needle = struct.pack('<4I',SLOT,0,0,0)
                self.assertEqual(m.bin.count(needle),1)
                m.bin=m.bin.replace(needle,struct.pack('<4I',SLOT,0xdeadbeef,0,0))
            m.run()
            if mutation:
                with self.assertRaises(AssertionError): self.assertEqual(m.journal_calls,0)
            else:
                self.assertEqual(m.journal_calls,0)
                self.assertEqual(m.allocations,[])
                self.assertEqual(m.word(SLOT),0xdeadbeef)

    def test_shared_shutdown_restores_before_detach_both_reasons_and_foreign_mode(self):
        for index in range(1,5):
            for reason in (1,4):
                m,p,o=self.active(index)
                report=a.restore.inspect(lambda at,n:[m.word(at+i*4) for i in range(n)],self.image,draw=True,slit=True)
                self.assertTrue(report['complete'])
                obj=m.registrations[0][0]; m.call(m.word(obj+4),obj,reason)
                self.assertEqual(m.word(0x30100004),T04)
                self.assertEqual(m.word(SLOT),0)
                self.assertEqual(m.word(o+0x8204),1)
                self.assertEqual(m.word(b.DRAW),b.STOCK)
                self.assertNotIn(o+0x2500, [m.word(0xC31AB0D0+4*i) for i in range(9)])
                # A drawing call already in flight may finish in retained code.
                m.call(o+0x3000+self.text.functions['slit_tick'],o+0x8000)
                self.assertEqual(m.word(SLOT),0)
        m,p,o=self.active();m.put(0x30100004,0x123)
        obj=m.registrations[0][0];m.call(m.word(obj+4),obj,4)
        self.assertEqual(m.word(0x30100004),0x123)

    def test_observer_full_slot_refuses_without_retry_or_timing(self):
        m,p,o,_ = self.booted()
        m.put(0xC31AB0D0,*range(1,10));m.put(o+0x2400,0)
        m.draw()
        self.assertEqual(m.word(o+0x2400),3)
        m.put(0xC31AB0D0,0);m.draw()
        self.assertEqual(m.word(o+0x2400),3)
        self.assertEqual(m.word(SLOT),0)

    def test_idle_shutdown_detaches_only_owned_observer_and_mutation_fails(self):
        from unicorn import UC_HOOK_MEM_WRITE
        for mutation in (False,True):
            m,p,o,_=self.booted();obj=m.registrations[0][0]
            m.put(0xC31AB0D4,0x12345678) # foreign borrower survives
            writes=[]
            h=m.u.hook_add(UC_HOOK_MEM_WRITE,lambda u,a,at,n,v,d:
                writes.append(u.reg_read(UC_ARM_REG_PC)) if at==0xC31AB0D0 else None)
            m.call(m.word(obj+4),obj,1);m.u.hook_del(h)
            self.assertEqual(m.word(0xC31AB0D0),0)
            self.assertEqual(m.word(0xC31AB0D4),0x12345678)
            self.assertEqual(len(writes),1)
            if mutation:
                target=writes[0]
                m,p,o,_=self.booted();obj=m.registrations[0][0]
                m.u.mem_write(target,struct.pack('<I',0xE320F000));m.u.ctl_remove_cache(target,target+4)
                m.call(m.word(obj+4),obj,4)
                with self.assertRaises(AssertionError):self.assertEqual(m.word(0xC31AB0D0),0)

    def test_restore_mutations_detected_in_isolated_machine(self):
        # Independently remove MMIO stores, from runtime and shared shutdown.
        for shutdown in (False,True):
            m,p,o=self.active()
            if shutdown:
                obj=m.registrations[0][0];start=m.word(obj+4);size=m.restore_length
            else:
                start=o+0x3000+self.text.functions['slit_restore_timing'];size=152
            code=bytes(m.u.mem_read(start,size))
            import capstone
            dis=capstone.Cs(capstone.CS_ARCH_ARM,capstone.CS_MODE_ARM)
            stores=[x for x in dis.disasm(code,start) if x.mnemonic=='str' and x.op_str.endswith('[r0, #4]')]
            if not shutdown:
                # Compiler chooses the MMIO base register; identify the store
                # actually made to timing04 by a memory-write observation.
                from unicorn import UC_HOOK_MEM_WRITE
                pcs=[]
                h=m.u.hook_add(UC_HOOK_MEM_WRITE,lambda u,a,at,n,v,d:pcs.append(u.reg_read(UC_ARM_REG_PC)) if at==0x30100004 else None)
                m.put(bindings.RECORDING,0x10000);self.irq(m);m.u.hook_del(h)
                self.assertEqual(len(pcs),1)
                m,p,o=self.active();target=pcs[0]
            else:
                self.assertEqual(len(stores),1);target=stores[0].address
            m.u.mem_write(target,struct.pack('<I',0xE320F000));m.u.ctl_remove_cache(target,target+4)
            if shutdown: m.call(m.word(obj+4),obj,4)
            else: m.put(bindings.RECORDING,0x10000);self.irq(m)
            with self.assertRaises(AssertionError): self.assertEqual(m.word(0x30100004),T04)


class QueueRecording(unittest.TestCase):
    queue_observation = True
    setUpClass = classmethod(Recording.setUpClass.__func__)
    machine = Recording.machine
    booted = Recording.booted
    irq = Recording.irq
    active = Recording.active

    def test_debug_and_plain_queue_card_boot_and_idle_shutdown(self):
        for debug in (False,True):
            m,p,o,_=self.booted(debug)
            self.assertEqual(len(m.tasks),int(debug))
            self.assertEqual(m.word(o+0x2434),336)
            self.assertLessEqual(len(m.bin),61440)
            self.assertEqual(bytes(m.u.mem_read(o+0x2600,336)),bytes(336))
            obj=m.registrations[0][0];m.call(m.word(obj+4),obj,1)
            self.assertEqual(m.word(b.DRAW),b.STOCK)
            self.assertNotIn(o+0x2500,[m.word(0xC31AB0D0+i*4) for i in range(9)])

    def test_ring_records_before_timing_write_wraps_and_resets(self):
        m,p,o = self.active()
        self.assertEqual(m.word(o+0x82ec),8)
        self.assertEqual(m.word(o+0x82f0+7*16+4),T04) # eighth IRQ changed timing AFTER sample
        m.put(0xC343B858,1)
        for i in range(20):
            m.put(0xC343B6D4,100+i);self.irq(m)
        self.assertEqual(m.word(o+0x82ec),28)
        for i in range(12,28):
            at=o+0x82f0+(i&15)*16
            self.assertEqual(m.word(at),100+i-8)
            self.assertEqual(m.word(at+4),0x0c471ae7)
            self.assertEqual(m.word(at+12),i+1)
        m.put(bindings.RECORDING,0x10000);self.irq(m);m.draw()
        m.put(bindings.RECORDING,0x10001);m.draw()
        self.assertEqual(bytes(m.u.mem_read(o+0x82ec,260)),bytes(260))

    def test_queue_load_mutation_detected_and_shutdown_still_restores(self):
        from unicorn import UC_HOOK_MEM_READ
        m,p,o=self.active();m.put(0xC343B858,1);m.put(0xC343B6D4,123)
        pcs=[]
        h=m.u.hook_add(UC_HOOK_MEM_READ,lambda u,a,at,n,v,d:
            pcs.append(u.reg_read(UC_ARM_REG_PC)) if at==0xC343B6D4 else None)
        self.irq(m);m.u.hook_del(h)
        self.assertEqual(len(pcs),1)
        m.u.mem_write(pcs[0],struct.pack('<I',0xE320F000));m.u.ctl_remove_cache(pcs[0],pcs[0]+4)
        self.irq(m)
        with self.assertRaises(AssertionError):self.assertEqual(m.word(o+0x82f0+9*16),123)
        obj=m.registrations[0][0];m.call(m.word(obj+4),obj,4)
        self.assertEqual(m.word(SLOT),0);self.assertEqual(m.word(0x30100004),T04)
        self.assertNotIn(o+0x2500,[m.word(0xC31AB0D0+i*4) for i in range(9)])


class LookupRecording(unittest.TestCase):
    queue_observation=True
    lookup_observation=True
    setUpClass=classmethod(Recording.setUpClass.__func__)
    machine=Recording.machine
    booted=Recording.booted
    test_foreign_vd_refuses_before_journal_and_admission_mutation_is_detected=Recording.test_foreign_vd_refuses_before_journal_and_admission_mutation_is_detected

    def test_owned_lookup_debug_plain_boot_caps_journal_and_shutdown(self):
        for debug in (False,True):
            m,p,o,_=self.booted(debug)
            self.assertEqual(len(m.tasks),int(debug))
            self.assertEqual(m.word(o+0x2434),464)
            self.assertEqual(bytes(m.u.mem_read(o+0x2600,464)),bytes(464))
            self.assertLessEqual(len(m.bin),61440)
            self.assertLessEqual(len(self.text.code),0x5000)
            self.assertTrue(a.restore.inspect(lambda at,n:[m.word(at+i*4) for i in range(n)],
                self.image,draw=True,slit=True)['complete'])
            obj=m.registrations[0][0];m.call(m.word(obj+4),obj,1)
            self.assertEqual(m.word(b.DRAW),b.STOCK)
            self.assertNotIn(o+0x2500,[m.word(0xC31AB0D0+i*4) for i in range(9)])


if __name__=='__main__': unittest.main()
