"""Real ARM core + native walkers/snapshot/save paths; modeled OS/notifications.

No camera I/O. Tests deliberately demonstrate why the profiled interception is
NOT admitted as a native hook. Compile-time modeled admission is test-only.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import test_bindings as b
import exposure_boundary as profile
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *

HERE = Path(__file__).resolve().parent
CODE, STATE, WRAP, RET = 0x45000000, 0x45008000, 0x45004000, 0x4500FF00
TASK, SETTINGS = 0xC3001C00, 0xC31AB114
P = profile.PROVIDER
# Synthetic tuple in the serialized block for controller/ordering tests. This
# is NOT the native exposure-field layout. A separate test below executes the
# actual mode/shutter pointer functions and native current-profile snapshot.
TUPLE = P+0x100
FIELDS = 'task busy closing dirty valid work phase error'.split()
OK, UNQUALIFIED, CONTEXT, BUSY, CLOSING, MODE, ARGUMENT, VERIFY = range(8)


def compile_core(model=False, mutate=None):
    # Same freestanding ARM compiler/resolver as build_adapter; no card builder.
    with tempfile.TemporaryDirectory(prefix='slit-exposure-') as tmp:
        tree = Path(tmp); text = (HERE/'exposure.c').read_text()
        if mutate:
            old, new = mutate
            assert old in text
            text = text.replace(old,new)
        source = tree/'core.c'; source.write_text(text)
        assembly = tree/'core.S'
        subprocess.run([shutil.which('clang') or 'clang', '-target','armv7-none-eabi',
            '-marm','-mfloat-abi=soft','-mfpu=none','-fno-vectorize','-fno-slp-vectorize',
            '-std=c11','-O2','-ffreestanding','-fno-builtin','-fno-jump-tables','-fno-addrsig',
            '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-fno-optimize-sibling-calls',
            '-Wall','-Wextra','-Werror',
            '-Wno-unused-command-line-argument',f'-DFPL_EXPOSURE_MODEL={int(model)}',
            '-I',str(HERE),'-S',str(source),'-o',str(assembly)], check=True,capture_output=True)
        _,_,sections = b.armasm._parse(b.armasm._compile(assembly))
        for name,(_,section) in sections.items():
            if section[2]&2 and section[5] and name not in ('.text','.ARM.exidx'):
                raise AssertionError('unexpected allocated section '+name)
        return SimpleNamespace(code=b.armasm.assemble(assembly),functions=b.armasm.symbols(assembly))


class Machine:
    def __init__(self, test, text, image):
        self.test, self.text = test,text
        self.u = b.Uc(b.UC_ARCH_ARM,b.UC_MODE_ARM)
        self.u.mem_map(profile.BASE,0x4000000); self.u.mem_write(profile.BASE,image)
        self.u.mem_map(CODE,0x10000); self.u.mem_write(CODE,text.code)
        self.events=[]; self.interrupt=None; self.fail_restore=False
        self.mode_values={0xC00594C8:0,0xC0059560:4,0xC0059690:3,0xC0059728:12}
        self.refuse_save=False
        self.late_write=False
        self.persist_reentry=False
        self.put(STATE,TASK); self.put(0xC3000098,TASK)
        self.put(0xC3033A40,2); self.put(0xC30338CC,0)
        self.put(P+8,profile.VTABLE); self.put(P+0x5930,1)
        self.put(TUPLE,3,0,0,0)
        self.put(P+0xb268+0x592c,0)
        self.put(0x45006048,0x45006100)
        self.put(0x45006100,0x45006200,0xC3400000)
        self.put(0x45006208,14);self.put(0x45006210,0x4f48)
        self.u.reg_write(UC_ARM_REG_CPSR,0x13)
        self.u.hook_add(UC_HOOK_CODE,self.hook)

    def put(self,at,*values):self.u.mem_write(at,struct.pack('<'+'I'*len(values),*values))
    def words(self,at,n=1):return list(struct.unpack('<'+'I'*n,self.u.mem_read(at,4*n)))
    def state(self,name):return self.words(STATE+4*FIELDS.index(name))[0]
    def tuple(self):return self.words(TUPLE,4)
    def call(self,fn,*args,sp=0x4500F000,cpsr=0x13):
        u=self.u;u.reg_write(UC_ARM_REG_CPSR,cpsr);u.reg_write(UC_ARM_REG_SP,sp)
        u.reg_write(UC_ARM_REG_LR,RET)
        for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),args):u.reg_write(r,v)
        u.emu_start(CODE+self.text.functions[fn] if isinstance(fn,str) else fn,RET,count=40000)
        self.test.assertEqual(u.reg_read(UC_ARM_REG_PC),RET)
        self.test.assertEqual(u.reg_read(UC_ARM_REG_SP),sp)
        return u.reg_read(UC_ARM_REG_R0)

    def boundary_during_call(self):
        # Synchronous nested request on this same task: a spin/wait would deadlock.
        u=self.u;ctx=u.context_save()
        result=self.call('slit_exposure_before_persist',STATE,sp=0x4500D000)
        u.context_restore(ctx);self.events.append(('nested',result))

    def hook(self,u,pc,size,data):
        args=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if pc==0xC0055320 and self.late_write:
            self.late_write=False;self.put(TUPLE,1,1,6400,800)
            self.events.append(('foreign-write-after-verification',))
        value=0
        if pc in (b.bindings.SETTINGS,0xC0089D00,0xC00882F0):value=SETTINGS if pc==b.bindings.SETTINGS else P
        elif pc==0xC0055320 and self.refuse_save:self.events.append(('save-refused',));value=0
        elif pc in (0xC00594C8,0xC0059560,0xC0059690,0xC0059728):
            value=self.mode_values[pc]
        elif pc in (0xC0055A10,0xC0055BE8,0xC0056190):
            v=self.tuple()
            if pc==0xC0055BE8:self.put(args[0],*v[1:3])
            else:value=v[0 if pc==0xC0055A10 else 3]
        elif pc in (0xC00559D8,0xC0055BA0,0xC0056158):
            self.test.assertEqual(u.reg_read(UC_ARM_REG_SP)&7,0)
            self.test.assertEqual(u.reg_read(UC_ARM_REG_CPSR)&0xff,0x13)
            v=self.tuple();self.events.append(('setter',pc,args[1:]))
            if pc==0xC00559D8:
                v[0]=args[1]
                if self.fail_restore and args[1]==3:v[1:3]=[1,25]
            elif pc==0xC0055BA0:v[1:3]=args[1:3]
            else:v[3]=args[1]
            self.put(TUPLE,*v)
            if self.interrupt==pc:
                self.interrupt=None;self.boundary_during_call()
        elif pc==0xC0014DAC:
            self.events.append(('copy',args[0],args[1],args[2]))
            u.mem_write(args[0],bytes(u.mem_read(args[1],args[2])));value=args[0]
            if args[0]==0xC3400000:
                self.events.append(('persist',self.words(0xC3400000+0xf4,4)))
                if self.persist_reentry:
                    self.persist_reentry=False;self.boundary_during_call()
        elif pc==0xC00871B0:self.events.append(('snapshot-imported',self.tuple()))
        elif pc==0xC0055760:self.events.append(('refresh',self.tuple()))
        elif pc==0xC0021398:value=0x45006000
        elif pc==0xC0086410:self.events.append(('header',))
        elif pc==0xC00227F0:value=0x1234
        elif pc==0xC0010298:self.events.append(('mutex-enter',args[1]))
        elif pc==0xC00102D0:self.events.append(('mutex-exit',))
        elif pc==0x45005000:self.events.append(('shared',args[:2]));value=0xfeed
        elif pc==0x45005004:self.events.append(('shell-reply',bytes(u.mem_read(args[0],8)).split(b'\0')[0]))
        elif pc==0xC00B0D18:value=1  # model CINE resolver; pointer arithmetic is native
        elif pc in (0xC0019DC0,0xC001A048,0xC001A450,0xC001A288,
                    0xC0023DD8):pass
        else:
            # Native instruction ranges deliberately under test. Unknown calls fail.
            allowed=((CODE,CODE+len(self.text.code)),(WRAP,WRAP+0x100),
                     (0xC0023B70,0xC0023BF4),(0xC0023E58,0xC0023ECC),
                     (0xC0075FE8,0xC0076008),(0xC0055320,0xC0055348),
                     (0xC0055588,0xC0055600),(0xC0086228,0xC0086374),
                     (0xC0086508,0xC0086588),(0xC0086CC0,0xC0086E74),
                     (0xC0086E78,0xC0086EDC),(0xC00B12D0,0xC00B1320),(0xC00B1398,0xC00B13E8),
                     (0xC03FAC08,0xC03FAC34),
                     (0xC009C99C,0xC009C9B0),
                     (0xC0089DD0,0xC0089DF8),(0xC008A408,0xC008A430),
                     (0xC0089FD8,0xC008A000),
                     (0xC0085CD8,0xC0085D84),(0xC0064A70,0xC0064B30))
            if not any(lo<=pc<hi for lo,hi in allowed):raise AssertionError(f'unmodeled execution {pc:08x}')
            return
        u.reg_write(UC_ARM_REG_R0,value);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))

    def wrapper(self,original):
        # Owned-memory only. A candidate callback to exercise native walkers;
        # deliberately returns a refusal status to show that they IGNORE it.
        src=f'''.syntax unified
.arm
.text
.global entry
entry:
push {{r4-r6,lr}}
mov r4,sp
bic sp,sp,#7
mov r3,r1
mov r2,r0
movw r1,#{original&65535}
movt r1,#{original>>16}
movw r0,#{STATE&65535}
movt r0,#{STATE>>16}
mov r5,r0
movw ip,#{(CODE+self.text.functions['slit_exposure_dispatch'])&65535}
movt ip,#{(CODE+self.text.functions['slit_exposure_dispatch'])>>16}
blx ip
cmp r0,#0
ldreq r0,[r5,#64]
mov sp,r4
pop {{r4-r6,pc}}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'wrapper.S';p.write_text(src);self.u.mem_write(WRAP,b.armasm.assemble(p))

    def walker(self,forced=False,stock_callback=False):
        mgr=0xC3075684;obj=profile.CALLBACK_OBJECT;shared=0x45005800
        self.put(mgr+0x60,4 if forced else 1)
        self.put(mgr+(0x34 if forced else 0xc),obj,shared,0)
        self.put(obj,profile.CALLBACK_VTABLE if stock_callback else 0x45005900)
        self.put(0x4500590c,WRAP)
        self.put(shared,0x45005a00);self.put(0x45005a0c,0x45005000)
        u=self.u;u.reg_write(UC_ARM_REG_CPSR,0x13)
        u.reg_write(UC_ARM_REG_SP,0x4500F000 if forced else 0x4500F004)
        u.reg_write(UC_ARM_REG_R0,mgr);u.reg_write(UC_ARM_REG_R1,4)
        end=0xC0023ECC if forced else 0xC0023BF4
        u.emu_start(0xC0023E58 if forced else 0xC0023B70,end,count=40000)
        self.test.assertEqual(u.reg_read(UC_ARM_REG_PC),end)


class Exposure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image=b.get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        cls.text=compile_core(True);cls.refused=compile_core(False)
    def machine(self,text=None):return Machine(self,text or self.text,self.image)
    def borrow(self,m,index=1):return m.call('slit_exposure_borrow',STATE,index,1000,800)

    def test_production_and_card_admission_refuse_before_effects(self):
        m=self.machine(self.refused)
        self.assertEqual(self.borrow(m),UNQUALIFIED);self.assertEqual(m.events,[])
        from build_card import build_card
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'card'
            with self.assertRaisesRegex(ValueError,'not admitted'):
                build_card(Path('absent'),Path('absent'),out,exposure=True)
            self.assertFalse(out.exists())

    def test_supported_mode_context_and_arguments(self):
        for index in (1,2,3,4):
            m=self.machine();self.assertEqual(self.borrow(m,index),OK)
            self.assertEqual(m.tuple(),[1,1,{1:6400,2:4000,3:3200,4:2000}[index],800])
        for at,v in ((0xC3033A40,1),(0xC30338CC,1),(0xC3000098,TASK+132)):
            m=self.machine();m.put(at,v);self.assertIn(self.borrow(m),(MODE,CONTEXT))
            self.assertEqual(m.tuple(),[3,0,0,0])
        for cpsr in (0x12,0x11,0x93,0xd3):
            m=self.machine();self.assertEqual(m.call('slit_exposure_borrow',STATE,1,1000,800,cpsr=cpsr),CONTEXT)
        m=self.machine();self.assertEqual(self.borrow(m,5),ARGUMENT)
        for fn in self.machine().mode_values:
            m=self.machine();m.mode_values[fn]=99
            self.assertEqual(self.borrow(m),MODE);self.assertEqual(m.tuple(),[3,0,0,0])

    def test_full_tuple_restored_before_native_save_and_return_preserved(self):
        m=self.machine();self.assertEqual(self.borrow(m),OK)
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0xabc),OK)
        self.assertEqual(m.words(STATE+64),[1])  # original native save return
        self.assertIn(('persist',[3,0,0,0]),m.events)
        self.assertEqual((m.state('dirty'),m.state('work'),m.state('busy')),(0,0,0))
        self.assertEqual(self.borrow(m),CLOSING)

    def test_clean_dispatch_preserves_original_arguments_and_result(self):
        m=self.machine()
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0x45005000,0x1234,0x5678),OK)
        self.assertEqual(m.events,[('shared',[0x1234,0x5678])])
        self.assertEqual(m.words(STATE+64),[0xfeed])

    def test_native_save_keeps_private_admission_closed_until_return(self):
        m=self.machine();self.borrow(m);m.persist_reentry=True
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),OK)
        self.assertIn(('nested',BUSY),m.events)
        self.assertEqual(sum(e[0]=='persist' for e in m.events),1)
        self.assertEqual((m.state('busy'),m.state('dirty'),m.state('work')),(0,0,0))

    def test_foreign_request_closes_but_never_runs_setters_on_wrong_task(self):
        m=self.machine();self.borrow(m);n=len(m.events)
        m.put(0xC3000098,TASK+132)
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),CONTEXT)
        self.assertEqual(m.events[n:],[]);self.assertEqual(m.state('closing'),1)
        self.assertEqual(m.state('dirty'),1)
        m.put(0xC3000098,TASK)
        self.assertEqual(m.call('slit_exposure_before_persist',STATE),OK)

    def test_coupled_failure_retains_dirty_tuple_and_refuses_save(self):
        m=self.machine();self.borrow(m);m.fail_restore=True
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),VERIFY)
        self.assertEqual(m.state('dirty'),1);self.assertEqual(m.words(STATE+32,4),[3,0,0,0])
        self.assertFalse(any(e[0]=='persist' for e in m.events))
        m.fail_restore=False
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),OK)

    def test_nested_request_cancels_work_and_owner_drains_without_wait(self):
        for setter in (0xC00559D8,0xC0055BA0,0xC0056158):
            m=self.machine();m.interrupt=setter
            self.assertEqual(self.borrow(m),CLOSING)
            self.assertIn(('nested',BUSY),m.events)
            self.assertEqual(m.tuple(),[3,0,0,0])
            self.assertEqual((m.state('busy'),m.state('work'),m.state('dirty')),(0,0,0))
            self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),OK)

    def test_ordinary_walker_order_when_quiescent_and_no_old_snapshot(self):
        m=self.machine();self.borrow(m);m.wrapper(0xC0075FE8);m.walker()
        names=[e[0] for e in m.events]
        self.assertLess(names.index('persist'),names.index('shared'))
        self.assertIn(('refresh',[3,0,0,0]),m.events)
        self.assertIn(('persist',[3,0,0,0]),m.events)

    def test_native_snapshot_import_defeats_callback_only_restoration(self):
        m=self.machine();self.borrow(m)
        # Execute actual snapshot/export before hypothetical shutdown wrapper.
        self.assertEqual(m.call(0xC0086DA8,P,P+0xb268,sp=0x4500f004),1)
        m.wrapper(0xC0075FE8);m.walker()
        self.assertIn(('persist',[1,1,6400,800]),m.events)
        self.assertNotEqual(m.tuple(),[3,0,0,0])
        with self.assertRaises(ValueError):profile.require_admitted()

    def test_native_current_profile_mode_shutter_replaced_by_snapshot(self):
        m=self.machine();m.put(P+0xb264,0)
        # These are native property-table 3/6 resolvers, not synthetic tuple ABI.
        mode=m.call(0xC00B12D0,0xffff,0x45007000)
        shutter=m.call(0xC00B1398,0xffff,0x45007000,sp=0x4500f004)
        self.assertEqual(mode,P+0x4f54+0x98c);self.assertEqual(shutter,mode+4)
        m.put(mode,1,1,6400)
        self.assertEqual(m.call(0xC0086DA8,P,P+0xb268,sp=0x4500f004),1)
        m.put(mode,3,0,0)  # model completed native setters restoring live fields
        self.assertEqual(m.call(0xC0086CC0,P,P+0xb268,sp=0x4500f004),1)
        self.assertEqual(m.words(mode,3),[1,1,6400])
        # Actual getter releases the provider mutex BEFORE returning the pointer.
        # Holding that mutex in a save hook therefore cannot exclude later writes
        # through a pointer already obtained by a preempted setter.
        m.events=[]
        returned=m.call(0xC0086E78,P)
        self.assertEqual(returned,P+0x4f54)
        self.assertEqual([e[0] for e in m.events],['mutex-enter','mutex-exit'])
        # Resume the actual pair-write instructions AFTER hypothetical restore.
        m.put(shutter,0,0);m.put(0x4500f004,1,6400)
        m.u.reg_write(UC_ARM_REG_SP,0x4500f000);m.u.reg_write(UC_ARM_REG_R0,shutter)
        m.u.emu_start(0xC009C99C,0xC009C9B0,count=10)
        self.assertEqual(m.words(shutter,2),[1,6400])

    def test_owned_provider_save_slot_restores_after_prepare_when_quiescent(self):
        for ordinary in (False,True):
            m=self.machine();self.borrow(m)
            m.call(0xC0086DA8,P,P+0xb268,sp=0x4500f004)
            # Clone the exact 0x90-byte table in owned test memory. No new
            # power-off object, cave, loader, or runtime code patch.
            owned=WRAP+0x100
            m.u.mem_write(owned,self.image[profile.VTABLE-profile.BASE:profile.VTABLE-profile.BASE+0x90])
            m.wrapper(0xC0086228);m.put(owned+0x10,WRAP);m.put(P+8,owned)
            if ordinary:m.walker(stock_callback=True)
            else:
                self.assertEqual(m.call(0xC0055320,SETTINGS),1)
            self.assertIn(('persist',[3,0,0,0]),m.events)
            self.assertEqual(m.state('dirty'),0)
            if ordinary:
                events=[e[0] for e in m.events]
                self.assertLess(events.index('snapshot-imported'),events.index('persist'))
            # An actual installation would declare provider+8 with its stock
            # value in the existing shared journal BEFORE publishing this table.
            # This test does not claim that declaration/boot admission exists.

    def test_native_shell_prints_success_even_if_save_returns_refusal(self):
        m=self.machine();m.refuse_save=True;m.put(0x45007000,0x45005004)
        m.call(0xC03FAC08,0x45007000,0,0)
        self.assertEqual(m.events[0],('save-refused',))
        self.assertEqual(m.events[1][0],'shell-reply')
        self.assertIn(b'OK',m.events[1][1])

    def test_private_gate_cannot_exclude_foreign_notification_after_readback(self):
        m=self.machine();self.borrow(m);m.late_write=True
        self.assertEqual(m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0),OK)
        self.assertIn(('persist',[1,1,6400,800]),m.events)
        # A negative design result: own work is clear but a foreign publisher
        # can still race. Passing this test is NOT admission of the candidate.
        self.assertEqual(m.state('work'),0)
        with self.assertRaises(ValueError):profile.require_admitted()

    def test_native_walkers_ignore_refusal_and_continue_shutdown(self):
        for forced in (False,True):
            m=self.machine();self.borrow(m);m.put(STATE+4,1)
            m.wrapper(0xC0075FE8);m.walker(forced)
            self.assertTrue(any(e[0]=='shared' for e in m.events))
            self.assertFalse(any(e[0]=='persist' for e in m.events))
            self.assertEqual(m.state('dirty'),1)
        # Forced list has NO settings object in stock; this synthetic inclusion
        # tests walker refusal semantics, not a proposed new registration.

    def test_real_native_busy_setter_returns_without_restoration(self):
        m=self.machine();prop=0x45007000;m.put(prop+0x10,1)
        before=bytes(m.u.mem_read(prop,0x20))
        m.call(0xC0064A70,prop,0,0,0xffff,sp=0x4500f004)
        self.assertEqual(bytes(m.u.mem_read(prop,0x20)),before)
        self.assertEqual(m.events,[])

    def test_structural_mutations_are_not_hidden_by_fingerprint(self):
        profile.audit(self.image)
        for at in (0xC00555E8,0xC0086D0C,0xC0064A94,0xC0023BE8,profile.VTABLE+0x10):
            changed=bytearray(self.image);struct.pack_into('<I',changed,at-profile.BASE,0xE320F000)
            with self.assertRaises(ValueError):profile.audit(changed)

    def test_core_mutations_break_order_or_quiescence_assertions(self):
        mutations=(
            ('if (rc != EXP_OK) return rc;', '(void)rc; s->dirty = 0; /* falsely discard failed restoration */'),
            ('s->closing = 1; s->work = 0; unmask(m);', 's->work = 0; unmask(m);'),
            ('s->work = 0;\n    if (s->closing ||', 's->work = 99;\n    if (s->closing ||'),
            ('if (!equal(&actual, &s->original))', 'if (0)'),
        )
        for i,mutation in enumerate(mutations):
            m=self.machine(compile_core(True,mutation));self.borrow(m)
            if i in (0,3):m.fail_restore=True
            if i==2:
                with self.assertRaises(AssertionError):self.assertEqual(m.state('work'),0)
                continue
            rc=m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0)
            with self.assertRaises(AssertionError):
                if i in (0,3):self.assertFalse(any(e[0]=='persist' for e in m.events))
                else:self.assertEqual(self.borrow(m),CLOSING)

    def test_wrong_order_mutation_persists_borrowed_values(self):
        old='''uint32_t rc = slit_exposure_before_persist(s);
    if (rc != EXP_OK) return rc;'''
        new='''s->native_result = ((uint32_t (*)(uint32_t,uint32_t))fn)(a,b);
    uint32_t rc = slit_exposure_before_persist(s);
    if (rc != EXP_OK) return rc;'''
        m=self.machine(compile_core(True,(old,new)));self.borrow(m)
        m.call('slit_exposure_dispatch',STATE,0xC0055320,SETTINGS,0)
        with self.assertRaises(AssertionError):
            self.assertTrue(all(e[1]==[3,0,0,0] for e in m.events if e[0]=='persist'))


if __name__=='__main__':unittest.main()
