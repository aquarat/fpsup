"""Resident FPLS variant: native observer/tag/parser, simulated template DMA.

MMIO and private slit state are explicit test inputs, not sensor simulation.
"""
import struct
import unittest
import test_fpl_gtagpf as P
import test_fpl_formatter as F
import test_fpl_tag_capacity as N
import test_fpl_observer as T
from unicorn.arm_const import *
from unicorn import UC_HOOK_MEM_READ
from unittest.mock import patch

STATE = P.CODE+0x3000


class Slit(unittest.TestCase):
    setUpClass = classmethod(P.GtagPf.setUpClass.__func__)

    def machine(self, queue=False, lookup=False, producer=False):
        defs = ['SLIT=1','PARAM=0','SRC=0',f'N={640 if producer else 464 if lookup else 336 if queue else 64}']
        if queue:defs+=['SLIT_QUEUE=1']
        if lookup:defs+=['SLIT_LOOKUP=1']
        if producer:defs+=['SLIT_PRODUCER=1']
        code=P.armasm.assemble(P.SOURCE,defs)
        syms=P.armasm.symbols(P.SOURCE,defs)
        m=P.GtagMachine(N.NativeCapacity.image,F.NativeFormatter.data,
                       N.NativeCapacity.code,N.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        m.mu.mem_map(P.CODE,0x4000);m.mu.mem_map(P.TEMPLATE,0x40000)
        for at in (0x30100000,0x2D810000):m.mu.mem_map(at,0x10000)
        m.mu.mem_write(P.CODE,code)
        m.write(P.OBJ,P.VT)
        for i in range(3):m.write(P.VT+4*i,P.CODE+syms['ret0'])
        m.write(P.VT+12,P.CODE+syms['observer'])
        m.write(P.PARAM+0x120,STATE)
        self.assertEqual(m.call(P.CODE,P.PARAM),0)
        self.assertEqual(m.word(P.PARAM),2)
        return m,syms

    def frame(self,m):
        m.notify(3)
        data=bytes(m.mu.mem_read(P.TEMPLATE,m.word(P.TLEN)))
        _,maker=P.fsg2.maker_note(data)
        ty,count,off=maker[P.fsg2.GTAG]
        self.assertEqual((ty,count),(7,64))
        return struct.unpack_from('<16I',data,off)

    def start(self,m):
        m.notify(0);_,h,header=m.output()
        m.mu.mem_write(P.TEMPLATE,header);m.write(P.TPTR,P.TEMPLATE);m.write(P.TLEN,h)
        m.notify(2)
        self.assertEqual(m.word(P.PARAM+0x3C),1)

    def test_preroll_active_restored_are_observations_not_associations(self):
        m,_=self.machine();m.write(STATE+0x4c,1);self.start(m)
        for frame,active,timing in ((1,0,0x020b047b),(2,1,0x0c471ae7),(3,0,0x020b047b)):
            m.write(STATE+0x20c,active);m.write(STATE+0x218,frame*8)
            m.write(0x30100004,timing);m.write(0x30100020,0x165b0000)
            got=self.frame(m)
            self.assertEqual(got[:6],(0x534c5046,frame,~frame&0xffffffff,64,1,active))
            self.assertEqual(got[6],frame*8);self.assertEqual(got[8],timing)
            self.assertEqual(got[14:],(0,1))  # association explicitly UNKNOWN

    def test_off_new_take_clears_old_template_and_shutdown_is_inert(self):
        m,_=self.machine();m.write(STATE+0x4c,1);self.start(m);self.frame(m)
        before=m.word(P.PARAM+0x54)
        m.write(STATE+0x4c,0);m.notify(0);m.notify(3)
        self.assertEqual(m.word(P.PARAM+0x3c),0)
        self.assertEqual(m.word(P.PARAM+0x54),before)
        m.write(STATE+0x204,1);calls=m.word(P.PARAM+0x10);m.notify(0);m.notify(3)
        self.assertEqual(m.word(P.PARAM+0x10),calls)

    def test_transition_observation_mutation_is_detected(self):
        m,syms=self.machine();m.write(STATE+0x4c,1);self.start(m)
        # Alter the actual read of active to chosen, not a code-hash rejection.
        code=bytes(m.mu.mem_read(P.CODE+syms['slit_frame'],256))
        old=struct.pack('<I',0xe597000c) # ldr r0,[r7,#12]
        self.assertEqual(code.count(old),1)
        at=P.CODE+syms['slit_frame']+code.index(old)
        m.mu.mem_write(at,struct.pack('<I',0xe5970024));m.mu.ctl_remove_cache(at,at+4)
        m.write(STATE+0x20c,1)
        with self.assertRaises(AssertionError):self.assertEqual(self.frame(m)[5],1)

    def test_queue_snapshot_native_pool_field_ring_and_host_parser(self):
        import importlib.util
        path=P.SOURCE.parents[2]/'slit_scan/metadata.py'
        spec=importlib.util.spec_from_file_location('slit_metadata',path)
        reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
        m,syms=self.machine(queue=True);m.write(STATE+0x4c,1);self.start(m)
        m.write(0xC343B858,1);m.write(0xC343B6D4,79)
        # This is NOT the DNG ordinal (1) or native current counter (79).
        m.write(T.POOL+0x4004,72)
        m.write(STATE+0x2ec,19)
        for i in range(16):m.mu.mem_write(STATE+0x2f0+i*16,struct.pack('<4I',50+i,0x0c471ae7,100*i,i+1))
        m.notify(3)
        data=bytes(m.mu.mem_read(P.TEMPLATE,m.word(P.TLEN)))
        got=reader.observation(data)
        self.assertEqual(got['version'],2);self.assertEqual(got['association'],0)
        self.assertEqual(got['queue']['native_sequence'],72)
        self.assertEqual(got['queue']['current_counter'],79)
        self.assertEqual([r['native_counter'] for r in got['queue']['samples']],list(range(53,66))+[50,51,52])
        # The constructor guard is required; neither stale pool data nor a
        # valid-looking counter authorizes an observation when it is absent.
        m.write(0xC343B858,0);m.notify(3)
        got=reader.observation(bytes(m.mu.mem_read(P.TEMPLATE,m.word(P.TLEN))))
        self.assertFalse(got['queue']['valid']);self.assertEqual(got['queue']['native_sequence'],0)

    def test_queue_field_mutation_is_detected(self):
        m,syms=self.machine(queue=True);m.write(STATE+0x4c,1);self.start(m)
        m.write(0xC343B858,1);m.write(T.POOL+0x4004,72)
        code=bytes(m.mu.mem_read(P.CODE+syms['slit_frame'],512))
        old=struct.pack('<I',0xe304c004) # movw ip,#4004
        self.assertEqual(code.count(old),1)
        at=P.CODE+syms['slit_frame']+code.index(old)
        m.mu.mem_write(at,struct.pack('<I',0xe304c000));m.mu.ctl_remove_cache(at,at+4)
        m.notify(3);data=bytes(m.mu.mem_read(P.TEMPLATE,m.word(P.TLEN)))
        _,maker=P.fsg2.maker_note(data);off=maker[P.fsg2.GTAG][2]
        with self.assertRaises(AssertionError):self.assertEqual(struct.unpack_from('<I',data,off+64)[0],72)


class LookupMachine(P.GtagMachine):
    def hook(self,mu,addr,size,data):
        if addr in (0xC0310800,0xC031E210):
            self.ret(0xC343B6C4);return
        if any(a<=addr<a+n for a,n in ((0xC038C8BC,0x60),(0xC0053CB0,0x28),
                (0xC0310C58,0x24),(0xC031EBF8,0xD0))):return
        super().hook(mu,addr,size,data)


class Lookup(unittest.TestCase):
    setUpClass=classmethod(P.GtagPf.setUpClass.__func__)
    start=Slit.start

    def machine(self):
        with patch.object(P,'GtagMachine',LookupMachine):
            m,syms=Slit.machine(self,queue=True,lookup=True)
        m.write(STATE+0x4c,1);self.start(m)
        m.write(0xC343B858,1);m.write(0xC343B6D4,41)
        m.mu.mem_write(0xC343B800,bytes(84))  # native keys/values/cursor
        m.call(0xC031EBF8,0xC343B6C4,0x45008000)
        m.write(0xC330104c,0x45008000)
        tcb=0xC3000838+39*132
        m.write(0xC3000098,tcb);m.write(tcb+0x74,T.STACK+0x10000);m.write(tcb+0x18,0x10000)
        m.write(0xC30337EC,0x2D810000);m.write(0xC30337F8,0x2D810080)
        m.write(0xC2F09408,12000000);m.write(0xC3076D98,17)
        m.write(0x2D810054,123456);m.write(0x2D810084,0)
        return m,syms

    def frame(self,m,record=0xC3301000):
        # Execute the actual lookup -> native DataPool -> Subject -> observer
        # chain. Only singleton guards are modeled, not stack frames or lookup.
        sp=T.STACK+0xfe00
        m.mu.reg_write(UC_ARM_REG_SP,sp)
        for r,v in ((UC_ARM_REG_R4,T.POOL),(UC_ARM_REG_R5,record),(UC_ARM_REG_R7,1)):
            m.mu.reg_write(r,v)
        m.mu.emu_start(0xC038C8BC,0xC038C91C,count=10000)
        self.assertEqual(m.mu.reg_read(UC_ARM_REG_PC),0xC038C91C)
        self.assertEqual(m.mu.reg_read(UC_ARM_REG_SP),sp)
        self.assertEqual(m.mu.reg_read(UC_ARM_REG_R5),record)
        return self.read(m)

    def read(self,m):
        import importlib.util
        spec=importlib.util.spec_from_file_location('slit_metadata',P.SOURCE.parents[2]/'slit_scan/metadata.py')
        reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
        data=bytes(m.mu.mem_read(P.TEMPLATE,m.word(P.TLEN)))
        return reader.observation(data)

    def test_exact_native_consumer_key_hit_miss_zero_reuse_and_clock(self):
        m,_=self.machine();got=self.frame(m)
        snap=got['lookup']['at_notify']
        self.assertEqual((snap['key'],snap['status'],snap['result']),(0x45008000,'hit',42))
        self.assertTrue(snap['agrees_with_native_result'])
        self.assertIsNone(got['lookup']['producer_timestamp'])
        self.assertEqual(got['notify_clock']['seconds'],17)
        self.assertEqual(got['notify_clock']['ticks'],123456)
        m.write(0xC330104c,0x45009000)
        got=self.frame(m);self.assertEqual(got['lookup']['at_notify']['status'],'miss-fallback')
        self.assertEqual(got['queue']['native_sequence'],41)
        # A same-key zero value is distinct from a key miss, but both fall back.
        m.write(0xC330104c,0)
        self.assertEqual(self.frame(m)['lookup']['at_notify']['status'],'zero-value-fallback')
        # Repeated key: actual native maximum, not whichever slot is newest.
        m.write(0xC330104c,0x45008000);m.write(0xC343B6D4,7)
        m.call(0xC031EBF8,0xC343B6C4,0x45008000)
        self.assertEqual(self.frame(m)['lookup']['at_notify']['result'],42)
        m.write(0x2D810084,32)
        got=self.frame(m);self.assertEqual(got['notify_clock']['seconds'],18)
        self.assertTrue(got['notify_clock']['pending_rollover'])

    def test_snapshot_can_disagree_with_actual_lookup_and_is_never_promoted(self):
        from unicorn import UC_HOOK_CODE
        m,_=self.machine()
        # Modeled producer scheduling after native lookup, before notification.
        # Native ring/lookup/Subject instructions themselves execute unchanged.
        def change(u,pc,size,data):
            if pc==0xC038C8F0:m.write(0xC343B828,99)
        m.mu.hook_add(UC_HOOK_CODE,change)
        got=self.frame(m)
        self.assertEqual(got['queue']['native_sequence'],42)
        self.assertEqual(got['lookup']['at_notify']['result'],99)
        self.assertFalse(got['lookup']['at_notify']['agrees_with_native_result'])
        self.assertFalse(got['lookup']['capture_association'])

    def test_foreign_notify_stack_extent_and_record_refuse_without_dereference(self):
        m,_=self.machine();m.notify(3)
        self.assertFalse(self.read(m)['lookup']['key_valid'])
        # No native stack was guessed for the generic notify caller above.
        m.write(0xC3000838+39*132+0x74,T.STACK+0xfd00)
        self.assertFalse(self.frame(m)['lookup']['key_valid'])
        m.write(0xC3000838+39*132+0x74,T.STACK+0x10000)
        m.write(0xC343B858,0)
        got=self.frame(m)
        self.assertTrue(got['lookup']['key_valid']);self.assertFalse(got['lookup']['snapshot_valid'])

    def test_clock_rollover_refuses_and_key_load_mutation_is_detected(self):
        m,syms=self.machine();reads=[]
        def read(u,access,address,size,value,data):
            if address==0x2D810054:
                reads.append(address)
                # First is v1 raw observation; next two are coherent sampling.
                m.write(address,11999999 if len(reads)==2 else 1)
        handle=m.mu.hook_add(UC_HOOK_MEM_READ,read)
        self.assertFalse(self.frame(m)['notify_clock']['valid'])
        m.mu.hook_del(handle)
        code=bytes(m.mu.mem_read(P.CODE+syms['slit_frame'],1200))
        old=struct.pack('<I',0xe592004c)  # ldr r0,[r2,#4c]
        self.assertEqual(code.count(old),1)
        at=P.CODE+syms['slit_frame']+code.index(old)
        m.mu.mem_write(at,struct.pack('<I',0xe5920048));m.mu.ctl_remove_cache(at,at+4)
        with self.assertRaises(AssertionError):
            self.assertEqual(self.frame(m)['lookup']['key'],0x45008000)


TRACE=0x45100000
TRACE_STACK=0x45200000

class ProducerMachine(LookupMachine):
    def hook(self,mu,addr,size,data):
        if TRACE+0x1000<=addr<TRACE+0x4000:return
        super().hook(mu,addr,size,data)


class Producer(unittest.TestCase):
    setUpClass=classmethod(P.GtagPf.setUpClass.__func__)
    start=Slit.start
    read=Lookup.read

    def machine(self):
        import sys
        sys.path.insert(0,str(P.SOURCE.parents[2]/'slit_scan'))
        from build_producer_trace import build
        trace=build()
        with patch.object(P,'GtagMachine',ProducerMachine):
            m,syms=Slit.machine(self,queue=True,lookup=True,producer=True)
        m.mu.mem_map(TRACE,0x10000);m.mu.mem_map(TRACE_STACK,0x10000)
        m.mu.mem_map(STATE-0x8000,0x1000)
        m.mu.mem_write(TRACE+0x1000,trace.code)
        m.write(TRACE+0x8000,0x31545046)
        m.write(STATE-0x8000+0x24,TRACE)
        m.write(STATE-0x8000+0x28,TRACE+0x1000+trace.functions['pt_export'])
        for site,name in ((0xC031EBF8,'pt_writer'),(0xC031EC58,'pt_lookup')):
            m.write(site,0xE51FF004);m.write(site+4,TRACE+0x1000+trace.functions[name])
        m.write(STATE+0x4c,1);self.start(m)
        m.write(0xC343B858,1);m.write(0xC343B6D4,41)
        m.mu.mem_write(0xC343B800,bytes(84))
        tcb=0xC3000838+39*132
        m.write(0xC3000098,tcb);m.write(tcb+0x74,TRACE_STACK+0x10000);m.write(tcb+0x18,0x10000)
        m.write(0xC30337EC,0x2D810000);m.write(0xC30337F8,0x2D810080)
        m.write(0xC2F09408,12000000);m.write(0xC3076D98,17)
        m.write(0x2D810054,123456);m.write(0x2D810084,0)
        m.call(0xC031EBF8,0xC343B6C4,0x45008000)
        m.write(0xC330104c,0x45008000)
        return m,syms

    def frame(self,m):
        with patch.object(T,'STACK',TRACE_STACK):return Lookup.frame(self,m)

    def test_native_writer_lookup_subject_dng_join_survives_later_queue_change(self):
        from unicorn import UC_HOOK_CODE
        m,_=self.machine()
        def changed(u,pc,size,data):
            if pc==0xC038C8F0:m.write(0xC343B828,99)
        m.mu.hook_add(UC_HOOK_CODE,changed)
        got=self.frame(m)
        self.assertEqual(got['version'],4)
        self.assertTrue(got['producer_trace']['joined'])
        self.assertEqual(got['lookup']['at_notify']['result'],99)
        actual=got['lookup']['actual']
        self.assertEqual(actual['result'],42)
        self.assertEqual(actual['producer']['generation'],1)
        self.assertEqual(actual['producer']['before']['seconds'],17)
        self.assertFalse(got['lookup']['capture_association'])

    def test_fallback_and_stale_startup_do_not_manufacture_a_generation(self):
        m,_=self.machine();m.write(0xC330104c,0x45009000)
        got=self.frame(m)
        self.assertEqual(got['lookup']['actual']['status'],'miss-fallback')
        self.assertIsNone(got['lookup']['actual']['producer'])
        m.write(0xC343B800,0x45009000);m.write(0xC343B828,42)
        got=self.frame(m)
        self.assertEqual(got['lookup']['actual']['flags'],1|8)
        self.assertIsNone(got['lookup']['actual']['producer'])

    def test_consumer_handoff_is_consumed_and_refused_lookup_invalidates_it(self):
        m,_=self.machine();got=self.frame(m)
        self.assertTrue(got['producer_trace']['joined'])
        # Execute another actual lookup but refuse tracing. The preceding joined
        # record must never be recycled merely because key/result are equal.
        m.write(TRACE+0x8004,1)
        got=self.frame(m)
        self.assertFalse(got['producer_trace']['joined'])
        m.write(TRACE+0x8004,0)
        got=self.frame(m)
        self.assertTrue(got['producer_trace']['joined'])
        self.assertEqual(got['producer_trace']['rejected_events'],1)
        self.assertEqual(got['lookup']['actual']['flags'],1|8)


if __name__=='__main__':unittest.main()
