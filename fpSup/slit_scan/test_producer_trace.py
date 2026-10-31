"""Execute original writer/lookup instructions through owned trace trampolines.

Emulated timers/task state are explicit inputs, not hardware phase evidence.
These tests do not install anything on a camera or constitute admission proof.
"""
import os
import struct
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fp_usb_shell'))
from firmware import get_camera
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *
from build_producer_trace import build

BASE=0x45000000
CODE=BASE+0x1000
STATE=BASE+0x8000
OWNER=0xC343B6C4
WRITER=0xC031EBF8
LOOKUP=0xC031EC58
MAGIC=0x31545046
TCB=0xC3000838+40*132
POOL=0x45100000
RECORD=0x45105000
STACK=0x4520f000
STOP=0x4520ff00
REGS=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,
      UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,UC_ARM_REG_R7,
      UC_ARM_REG_R8,UC_ARM_REG_R9,UC_ARM_REG_R10,UC_ARM_REG_R11,UC_ARM_REG_R12]


class Trace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        cls.text=build()

    def words(self,u,p,n=1):return struct.unpack('<'+'I'*n,u.mem_read(p,n*4))
    def put(self,u,p,*v):u.mem_write(p,struct.pack('<'+'I'*len(v),*v))
    def machine(self,patched=True):
        u=Uc(UC_ARCH_ARM,UC_MODE_ARM)
        u.mem_map(0xC0000000,0x4000000);u.mem_write(0xC0000000,self.image)
        u.mem_map(BASE,0x10000);u.mem_map(POOL,0x10000);u.mem_map(0x45200000,0x10000)
        u.mem_map(0x2d810000,0x1000)
        u.mem_write(CODE,self.text.code)
        self.put(u,STATE,MAGIC)
        u.mem_write(OWNER,bytes(0x198));self.put(u,OWNER+0x194,1)
        self.put(u,0xC3000098,TCB);self.put(u,TCB+8,40)
        self.put(u,TCB+0x18,0x10000);self.put(u,TCB+0x74,0x45210000)
        self.put(u,0xC30337EC,0x2d810000);self.put(u,0xC30337F8,0x2d810080)
        self.put(u,0xC2F09408,12000000);self.put(u,0xC3076D98,17)
        self.put(u,0x2d810054,1234);self.put(u,POOL,0xC07333D4)
        if patched:
            for at,name in ((WRITER,'pt_writer'),(LOOKUP,'pt_lookup')):
                self.put(u,at,0xE51FF004,CODE+self.text.functions[name])
        u.reg_write(UC_ARM_REG_CPSR,0x13)
        def strict(u,pc,size,data):
            allowed=(CODE<=pc<CODE+len(self.text.code) or WRITER<=pc<0xC031ECC8 or
                     0xC0310C58<=pc<0xC0310C7C or 0xC038C8BC<=pc<0xC038C91C or
                     0xC0053CB0<=pc<0xC0053CD8)
            if pc in (0xC0310800,0xC031E210):
                u.reg_write(UC_ARM_REG_R0,OWNER)
                u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR));return
            if not allowed:raise AssertionError(f'unmodeled execution {pc:08x}')
            if pc in [CODE+self.text.functions[n] for n in ('pt_before','pt_after')]:
                self.assertEqual(u.reg_read(UC_ARM_REG_SP)&7,0)
                self.assertEqual(u.reg_read(UC_ARM_REG_CPSR)&0xc0,0xc0)
        u.hook_add(UC_HOOK_CODE,strict)
        return u

    def call(self,u,pc,key,sp=STACK):
        mask=u.reg_read(UC_ARM_REG_CPSR)&0xff
        for i,r in enumerate(REGS):u.reg_write(r,0x10000+i)
        u.reg_write(UC_ARM_REG_R0,OWNER);u.reg_write(UC_ARM_REG_R1,key)
        u.reg_write(UC_ARM_REG_SP,sp);u.reg_write(UC_ARM_REG_LR,STOP)
        u.emu_start(pc,STOP,count=10000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),STOP)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP),sp)
        self.assertEqual(u.reg_read(UC_ARM_REG_CPSR)&0xff,mask)
        for i in range(4,12):self.assertEqual(u.reg_read(REGS[i]),0x10000+i)
        return u.reg_read(UC_ARM_REG_R0)

    def producer(self,u,slot):return self.words(u,STATE+40+64*slot,16)
    def lookup(self,u,slot):return self.words(u,STATE+680+144*slot,36)

    def test_replay_matches_native_registers_memory_and_stack_alignment(self):
        for sp in (STACK,STACK+4):
            stock=self.machine(False);trace=self.machine()
            for u in (stock,trace):
                self.put(u,OWNER+0x10,42)
                self.call(u,WRITER,0x46001000,sp)
            self.assertEqual(stock.mem_read(OWNER,0x198),trace.mem_read(OWNER,0x198))
            self.assertEqual([stock.reg_read(r) for r in REGS],[trace.reg_read(r) for r in REGS])
            self.assertEqual(stock.reg_read(UC_ARM_REG_CPSR),trace.reg_read(UC_ARM_REG_CPSR))
            for u in (stock,trace):self.assertEqual(self.call(u,LOOKUP,0x46001000,sp),43)
            self.assertEqual([stock.reg_read(r) for r in REGS],[trace.reg_read(r) for r in REGS])
            p=self.producer(trace,0)
            self.assertEqual(p[:6],(MAGIC,1,0,0x46001000,43,0))
            self.assertEqual(p[6:12],(1,17,1234,1,17,1234))
            l=self.lookup(trace,0)
            self.assertEqual(l[3:6],(0x46001000,43,17)) # hit, nonconsumer context
            self.assertEqual(l[20:],p)

    def test_consumer_stack_is_captured_at_actual_lookup(self):
        u=self.machine();key=0x46001000
        self.put(u,OWNER+0x10,41);self.call(u,WRITER,key)
        self.put(u,RECORD+0x4c,key)
        u.reg_write(UC_ARM_REG_SP,STACK);u.reg_write(UC_ARM_REG_R4,POOL)
        u.reg_write(UC_ARM_REG_R5,RECORD)
        u.emu_start(0xC038C8BC,0xC038C8F0,count=10000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0xC038C8F0)
        self.assertEqual(self.words(u,POOL+0x4004),(42,))
        l=self.lookup(u,0)
        self.assertEqual(l[3:11],(key,42,1,POOL,RECORD,TCB,1,0))
        # Later mutable ring overwrite cannot alter the retained lookup copy.
        saved=u.mem_read(STATE+680,144)
        for i in range(20):
            self.put(u,OWNER+0x10,100+i);self.call(u,WRITER,key)
        self.assertEqual(u.mem_read(STATE+680,144),saved)

    def test_wrap_duplicates_stale_and_fallbacks(self):
        u=self.machine();key=0x46001000
        for counter in (0xfffffffe,0xffffffff,0,0):
            self.put(u,OWNER+0x10,counter);self.call(u,WRITER,key)
        self.assertEqual(self.call(u,LOOKUP,key),0xffffffff)
        l=self.lookup(u,0)
        self.assertEqual((l[9],l[10],l[21]),(15,0,1)) # first strict maximum, generation1
        self.call(u,LOOKUP,key+4)
        self.assertEqual(self.lookup(u,1)[5],4|16)
        # A native ring entry predating arming has no invented generation.
        self.put(u,OWNER+0x140,key+8);self.put(u,OWNER+0x168,90)
        self.call(u,LOOKUP,key+8)
        self.assertEqual(self.lookup(u,2)[5],1|8|16)
        self.assertEqual(self.lookup(u,2)[20],0)
        self.put(u,OWNER+0x168,0);self.call(u,LOOKUP,key+8)
        self.assertEqual(self.lookup(u,3)[5],2|16)

    def test_bounded_retention_generation_carry_and_exhaustion(self):
        u=self.machine();self.put(u,STATE+8,0xffffffff,8)
        self.call(u,WRITER,0x46001000)
        self.assertEqual(self.producer(u,0)[1:3],(0,9))
        for i in range(67):self.call(u,LOOKUP,0x46001000)
        self.assertEqual(self.words(u,STATE+24,2),(3,3))
        self.put(u,STATE+8,0xffffffff,0xffffffff)
        self.call(u,WRITER,0x46002000)
        self.assertEqual(self.producer(u,1)[0],0)
        self.assertEqual(self.words(u,STATE+36),(1,))

    def test_commit_is_last_and_displaced_replay_mutation_is_detected(self):
        u=self.machine();writes=[]
        def write(u,access,at,size,value,data):
            if STATE+40<=at<STATE+104:writes.append((at,value))
        u.hook_add(UC_HOOK_MEM_WRITE,write)
        self.call(u,WRITER,0x46001000)
        self.assertEqual(writes[0],(STATE+40,0))
        self.assertEqual(writes[-1],(STATE+40,MAGIC))
        # Mutate only emulator bytes: replay ip from the wrong register.
        entry=CODE+self.text.functions['pt_writer']
        raw=bytes(u.mem_read(entry,140));needle=struct.pack('<I',0xE1A0C000)
        at=entry+raw.index(needle)
        self.put(u,at,0xE1A0C001);u.ctl_remove_cache(at,at+4)
        with self.assertRaises(UcError):self.call(u,WRITER,0x46002000)

    def test_pre_mask_preemption_orders_generations_and_reentry_invalidates(self):
        for before_mask in (True,False):
            u=self.machine();key=0x46001000
            for i,r in enumerate(REGS):u.reg_write(r,0x10000+i)
            u.reg_write(UC_ARM_REG_R0,OWNER);u.reg_write(UC_ARM_REG_R1,key)
            u.reg_write(UC_ARM_REG_SP,STACK);u.reg_write(UC_ARM_REG_LR,STOP)
            at=CODE+self.text.functions['pt_writer']+12 if before_mask else 0xC031EC10
            u.emu_start(WRITER,at,count=10000)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC),at)
            self.assertEqual(u.reg_read(UC_ARM_REG_CPSR)&0xc0,0 if before_mask else 0xc0)
            saved=u.context_save()
            # Only the first case is an admitted interrupt. The second injects
            # an impossible-under-I/F reentry to exercise explicit loss handling.
            self.call(u,WRITER,key+0x1000,STACK-0x1000)
            u.context_restore(saved);u.emu_start(at,STOP,count=10000)
            self.assertEqual(u.reg_read(UC_ARM_REG_PC),STOP)
            self.assertEqual(self.words(u,STATE+4),(0,))
            if before_mask:
                self.assertEqual(self.producer(u,0)[1:4],(1,0,key+0x1000))
                self.assertEqual(self.producer(u,1)[1:4],(2,0,key))
            else:
                self.assertEqual(self.words(u,STATE+32),(2,))
                self.assertTrue(all(self.producer(u,i)[0]==0 for i in range(10)))

    def test_mask_mutation_is_caught_before_native_queue_stores(self):
        u=self.machine();at=CODE+self.text.functions['pt_writer']+12
        self.assertEqual(self.words(u,at),(0xF10C00C0,))
        self.put(u,at,0xE320F000);u.ctl_remove_cache(at,at+4)
        with self.assertRaises(AssertionError):self.call(u,WRITER,0x46001000)
        self.assertEqual(self.words(u,OWNER+0x18c),(0,))


if __name__=='__main__':unittest.main()
