"""Owned producer allocation, real shared journal, native guard and restoration."""
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
import test_recording as r
import test_boot as b
import test_adapter as a
import test_runtime as rt
import test_fpl_ui_guard as g
from build_adapter import build, armasm
from unicorn.arm_const import UC_ARM_REG_CPSR

SITES=(0xC031EBF8,0xC031EC58)


class Machine(r.Machine):
    def write(self,u,access,address,size,value,data):
        if address in (*SITES,*(x+4 for x in SITES)):
            if value not in (0xE92D0030,0xE92D0070,0xE1A0C000):
                self.test.assertEqual(u.reg_read(UC_ARM_REG_CPSR)&0xc0,0xc0)
            self.writes.append((address,value));return
        return super().write(u,access,address,size,value,data)


class ProducerBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fp,cls.fpl=Path(os.environ['FP_MAIN']),Path(os.environ['FPL_MAIN'])
        cls.image=a.restore.CAMERA.verify_main(cls.fpl)
        b.c.registry.SEG0_SIZE=len(cls.image)
        cls.block,cls.info,cls.reference=b.product.menu.build(cls.fp,cls.fpl)
        cls.text=build(runtime=True,boot=True,recording=True,queue_observation=True,
                       lookup_observation=True,producer_observation=True)
        cls.launch,cls.layout=b.product.payload(cls.fp,cls.fpl,True,True,True,True)
        cls.sections=a.restore.stock_sections(cls.image)+[
            (at,cls.image[at-0xc0000000:at-0xc0000000+4]) for s in SITES for at in (s,s+4)]

    def machine(self,debug=False):
        with patch.object(a,'Machine',Machine):m,p=rt.Runtime.machine(self)
        script,art=b.card.ordinary_card(self.fpl,stock_sections=self.sections,
            boot_bins=[(self.launch,0)],shell=debug,ui_boot=True,slit_recording=True)
        m.bin,m.loader,m.script,m.image=art['binfile'],art['loader'],script,self.image
        return m,p,script

    booted=b.Boot.booted

    def test_owned_decode_caps_journal_and_both_shutdown_lists(self):
        for debug in (False,True):
            m,p,o,script=self.booted(debug)
            trace=m.word(o+0x24)
            self.assertIn((trace,65536),m.allocations)
            self.assertNotEqual(trace,o)
            self.assertEqual(bytes(m.u.mem_read(o+0x8400,len(self.block))),self.block)
            self.assertEqual(m.word(trace+0x8000),0x31545046)
            self.assertEqual(m.word(o+0x2434),640)
            self.assertLessEqual(len(m.bin),61440)
            self.assertLessEqual(len(self.text.code),0x5000)
            self.assertEqual(len(m.tasks),int(debug))
            self.assertEqual(len(m.registrations),2)
            journal=a.restore.inspect(lambda at,n:[m.word(at+4*i) for i in range(n)],
                                      self.image,draw=True,slit=True,producer=True)
            self.assertTrue(journal['complete']);self.assertEqual(len(journal['sites']),12)
            for site in SITES:
                self.assertEqual(m.word(site),0xE51FF004)
                self.assertTrue(trace+0x1000<=m.word(site+4)<trace+0x4000)
            for reason in (1,4):
                for site in SITES:m.put(site,0xdeadbeef);m.put(site+4,0xdeadbeef)
                obj=m.registrations[0][0];m.call(m.word(obj+4),obj,reason)
                for at,stock in self.sections:self.assertEqual(bytes(m.u.mem_read(at,4)),stock)

    def test_missing_journal_word_refuses_before_any_hook(self):
        for missing in (s+i for s in SITES for i in (0,4)):
            m,p,_=self.machine();blob=bytearray(m.bin)
            n=struct.unpack_from('<I',blob,4)[0]
            for i in range(n):
                if struct.unpack_from('<I',blob,16+8*i)[0]==missing:
                    struct.pack_into('<I',blob,16+8*i,0);break
            else:self.fail('declaration missing before mutation')
            m.bin=bytes(blob);m.run()
            self.assertEqual(m.word(b.DRAW),b.STOCK)
            self.assertEqual(m.word(m.allocations[0][0]+0x20),0x301)
            for at,stock in self.sections:self.assertEqual(bytes(m.u.mem_read(at,4)),stock)

    def test_foreign_entry_and_second_word_refuse_before_allocation(self):
        for at in (s+i for s in SITES for i in (0,4)):
            m,_,_=self.machine();m.put(at,0xdeadbeef);m.run()
            self.assertEqual(m.word(at),0xdeadbeef)
            self.assertEqual(m.allocations,[])
            self.assertEqual(m.registrations,[])

    def test_invalid_compressed_backreference_refuses_before_trace_install(self):
        m,_,_=self.machine()
        at=m.bin.index(self.launch)+self.layout['launch_symbols']['embedded']+self.layout['wrapper_bytes']+self.layout['runtime_bytes']
        blob=bytearray(m.bin);blob[at:at+3]=b'\x80\0\0';m.bin=bytes(blob)
        m.run()
        self.assertEqual(m.word(b.DRAW),b.STOCK)
        self.assertEqual(len(m.allocations),1)
        for site in SITES:
            self.assertEqual(bytes(m.u.mem_read(site,8)),self.image[site-0xc0000000:site-0xc0000000+8])


class ProducerGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=a.restore.CAMERA.verify_main(os.environ['FPL_MAIN'])
        defs=[f'P={g.P}',f'B={g.B}','PRODUCER_TRACE=1']
        cls.body=armasm.assemble(g.SOURCE,defs);cls.sym=armasm.symbols(g.SOURCE,defs)
    machine=g.Guard.machine
    task=g.Guard.task
    call=g.Guard.call
    stock=g.Guard.stock

    def test_whole_native_leaves_not_only_displaced_prologues(self):
        with patch.object(g,'SITES',SITES):
            for pc in range(SITES[0],0xC031ECC8,4):
                u=self.machine();self.task(u,500,pc=pc)
                self.assertEqual(self.call(u,1),0x13)
                self.assertEqual(self.writes,[]);self.stock(u)
            u=self.machine();self.assertEqual(self.call(u,1),2)
            self.assertEqual(len(self.writes),4)
            self.assertEqual(self.cache,[0xC000E91C,0xC000EABC])

    def test_entry_only_guard_mutation_fails_and_bad_context_refuses(self):
        with patch.object(g,'SITES',SITES):
            original=self.body
            self.assertEqual(original.count(struct.pack('<I',0xE35000D0)),1)
            self.body=original.replace(struct.pack('<I',0xE35000D0),struct.pack('<I',0xE3500008))
            try:
                u=self.machine();self.task(u,500,pc=0xC031EC28)
                with self.assertRaises(AssertionError):self.assertEqual(self.call(u,1),0x13)
            finally:self.body=original
            u=self.machine(cpus=2);self.assertEqual(self.call(u,1),0x10);self.stock(u)
            u=self.machine();self.assertEqual(self.call(u,3),0x15);self.stock(u)


if __name__=='__main__':unittest.main()
