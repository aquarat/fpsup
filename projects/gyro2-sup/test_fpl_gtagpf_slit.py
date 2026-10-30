"""Resident FPLS variant: native observer/tag/parser, simulated template DMA.

MMIO and private slit state are explicit test inputs, not sensor simulation.
"""
import struct
import unittest
import test_fpl_gtagpf as P
import test_fpl_formatter as F
import test_fpl_tag_capacity as N
import test_fpl_observer as T
from unicorn.arm_const import UC_ARM_REG_R0

STATE = P.CODE+0x3000


class Slit(unittest.TestCase):
    setUpClass = classmethod(P.GtagPf.setUpClass.__func__)

    def machine(self):
        defs = ['SLIT=1','PARAM=0','SRC=0','N=64']
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


if __name__=='__main__':unittest.main()
