"""Execute native buffer association and save ordering; hardware is not modeled."""
import os
import struct
import unittest
import test_bindings as b
import queue_binding as q
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *


class QueueBinding(b.Bindings):
    # Keep this suite's cases distinct from the existing binding suite.
    test_status_accessor_is_byte_and_app_is_word = None
    test_finite_probe_executes_native_leaf_and_preserves_abi = None
    test_exposure_probe_structure_return_and_setter_arguments = None

    def put(self,u,at,*words):u.mem_write(at,struct.pack('<'+'I'*len(words),*words))
    def word(self,u,at):return struct.unpack('<I',u.mem_read(at,4))[0]

    def test_native_buffer_reuse_wrap_and_ambiguous_miss(self):
        u=self.machine();owner=q.COUNTER_OWNER
        u.mem_write(owner,bytes(0x198))
        for i in range(13):
            self.put(u,q.COUNTER,i)
            self.call(u,0xC031EBF8,owner,0x46000000+0x1000*(i%3))
        self.assertEqual(self.word(u,owner+0x18c),3)
        for i,expected in enumerate((13,11,12)):
            self.assertEqual(self.call(u,0xC031EC58,owner,0x46000000+0x1000*i),expected)
        # A miss returns current counter 12, indistinguishable from valid key 2.
        self.assertEqual(self.call(u,0xC031EC58,owner,0xdeadbeef),12)
        self.put(u,0xC031ECB0,0xE3A02000)  # mutate fallback to zero
        u.ctl_remove_cache(0xC031ECB0,0xC031ECB4)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.call(u,0xC031EC58,owner,0xdeadbeef),12)

    def test_native_lookup_reaches_datapool_before_notify(self):
        u=self.machine();pool=0x45002000;record=0x45001000;out=0x45000100
        self.put(u,pool,q.POOL_VTABLE)
        self.call(u,0xC0053CB0,out,pool)
        self.assertEqual((self.word(u,out),self.word(u,out+4)),(pool+4,pool+q.POOL_SEQUENCE))
        self.put(u,q.COUNTER,41);self.put(u,q.COUNTER_OWNER+0x18c,0)
        self.call(u,0xC031EBF8,q.COUNTER_OWNER,0x46004000)
        self.put(u,record+0x4c,0x46004000)
        calls=[]
        def hook(u,pc,size,data):
            if pc==0xC0310800:value=0xC343A320
            elif pc==0xC031E210:value=q.COUNTER_OWNER
            elif pc==0xC0054E28:value=0xC31AB0D0
            elif pc==0xC0053028:
                calls.append((u.reg_read(UC_ARM_REG_R1),u.reg_read(UC_ARM_REG_R2),
                              u.reg_read(UC_ARM_REG_R3),self.word(u,pool+q.POOL_SEQUENCE)))
                value=1
            else:return
            u.reg_write(UC_ARM_REG_R0,value);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,hook)
        for r,v in ((UC_ARM_REG_SP,0x4500F000),(UC_ARM_REG_R4,pool),
                    (UC_ARM_REG_R5,record),(UC_ARM_REG_R7,1)):u.reg_write(r,v)
        u.emu_start(0xC038C8BC,0xC038C91C,count=2000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0xC038C91C)
        self.assertEqual(calls,[(3,3,pool,42)])

    def test_native_ordinary_save_precedes_later_shared_restore(self):
        u=self.machine();mgr=0xC3075684;obj=0xC31AB174;shared=0x45001000
        self.put(u,mgr+0x60,1);self.put(u,mgr+0xc,obj,shared,0)
        self.put(u,obj,0xC0733A30)
        self.put(u,shared,shared+0x10);self.put(u,shared+0x1c,0x45002000)
        events=[]
        def hook(u,pc,size,data):
            if pc==0xC0055120:value=0xC31AB114
            elif pc==0xC0055588:events.append('prepare-save');value=0
            elif pc==0xC0055320:events.append('save');value=0
            elif pc==0x45002000:events.append('shared-restore');value=0
            elif pc in (0xC0023DD8,0xC0019DC0,0xC001A048):value=0
            else:return
            u.reg_write(UC_ARM_REG_R0,value);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,hook)
        u.reg_write(UC_ARM_REG_SP,0x4500f004) # firmware's caller alignment
        u.reg_write(UC_ARM_REG_R0,mgr)
        u.emu_start(0xC0023B70,0xC0023BF4,count=2000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0xC0023BF4)
        self.assertEqual(events,['prepare-save','save','shared-restore'])

    def test_image_seams_and_structural_mutations(self):
        image=b.get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        q.audit(image)
        for at in (0xC031EC24,0xC031ECB0,0xC038C8EC,0xC0076000,
                   0xC0320D00,0xC03210E8,0xC005302C,0xC0053618,0xC0029178):
            changed=bytearray(image);struct.pack_into('<I',changed,at-q.BASE,0xE320F000)
            with self.assertRaises(ValueError):q.audit(changed)

    def test_both_native_producer_arguments_reach_writer_unchanged(self):
        u=self.machine();owner=q.COUNTER_OWNER;descriptor=0x45004000;key=0x45008000
        self.put(u,owner+0x18c,0);self.put(u,q.COUNTER,55)
        self.put(u,descriptor+0x38,key)
        u.reg_write(UC_ARM_REG_SP,0x4500f000)
        self.put(u,0x4500f028,owner)
        u.reg_write(UC_ARM_REG_R6,descriptor)
        u.emu_start(0xC0320D00,0xC0320D0C,count=1000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0xC0320D0C)
        self.assertEqual((self.word(u,owner+0x13c),self.word(u,owner+0x164)),(key,56))
        u.reg_write(UC_ARM_REG_R4,key+0x1000);u.reg_write(UC_ARM_REG_R6,owner)
        self.put(u,q.COUNTER,56)
        u.emu_start(0xC03210E8,0xC03210F4,count=1000)
        self.assertEqual((self.word(u,owner+0x140),self.word(u,owner+0x168)),(key+0x1000,57))
        self.assertEqual(u.reg_read(UC_ARM_REG_SP),0x4500f000)

    def test_native_clock_pending_correction_and_same_counter_semantics(self):
        # Execute native C0029120; timer peripheral reads are explicit modeled
        # inputs. This is not an assertion about hardware interrupt phase.
        for pending in (0,1):
            u=self.machine();self.put(u,0xC3076D98,17);self.put(u,0xC2F09408,12000000)
            def hook(u,pc,size,data):
                out=u.reg_read(UC_ARM_REG_R1)
                if pc==0xC00165E8:self.put(u,out,123456)
                elif pc==0xC00164C0:u.mem_write(out,bytes([pending]))
                else:return
                u.reg_write(UC_ARM_REG_R0,0);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
            u.hook_add(UC_HOOK_CODE,hook)
            self.call(u,0xC0029120,0x45000100)
            self.assertEqual((self.word(u,0x45000100),self.word(u,0x45000104)),(123456,17+pending))

    def test_native_buffer_programmer_alias_stride_and_software_toggle(self):
        for key in (0x45008000,0xC5008000,0x05008000):
            for flags in (0,1,16,17):
                u=self.machine();u.mem_map(0x30182000,0x1000);u.mem_map(0x30002000,0x1000)
                self.put(u,0xC37CF3F4,0);self.put(u,0x30182320,flags)
                self.put(u,0x30182310,5,64)
                self.assertEqual(self.call(u,0xC062E4C1,key),0)
                self.assertEqual(self.word(u,0x30182380),0x05008000//4+(64 if flags&1 else 0)+(256 if flags&16 else 0))
                self.assertEqual(self.word(u,0xC37CF420),key)
                self.assertEqual(self.word(u,0xC37CF3F4),1)
        image=b.get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        q.audit_producer(image)
        for at in (0xC031EBF8,0xC031EC5C,0xC062E4E8):
            changed=bytearray(image);struct.pack_into('<I',changed,at-q.BASE,0xE320F000)
            with self.assertRaises(ValueError):q.audit_producer(changed)


if __name__=='__main__':unittest.main()
