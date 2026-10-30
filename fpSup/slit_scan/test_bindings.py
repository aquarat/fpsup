"""Actual native status accessors and finite call ABI, not a recorder model."""
import os
import struct
import tempfile
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'fp_usb_shell'))
import armasm
from firmware import get_camera
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R4
from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_R3
import bindings


class Bindings(unittest.TestCase):
    def machine(self):
        image = get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(0xC0000000, 0x4000000)
        u.mem_write(0xC0000000, image)
        u.mem_map(0x45000000, 0x10000)
        return u

    def call(self, u, pc, r0=0, r1=0):
        u.reg_write(UC_ARM_REG_SP, 0x4500F000)
        u.reg_write(UC_ARM_REG_LR, 0x4500FF00)
        u.reg_write(UC_ARM_REG_R0, r0); u.reg_write(UC_ARM_REG_R1, r1)
        u.emu_start(pc, 0x4500FF00, count=1000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), 0x4500FF00)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), 0x4500F000)
        return u.reg_read(UC_ARM_REG_R0)

    def test_status_accessor_is_byte_and_app_is_word(self):
        u = self.machine()
        self.assertEqual(self.call(u, 0xC0017AC8, 0xC3033830), 0xC3033848)
        for value in (0, 1):
            u.mem_write(bindings.RECORDING, bytes((value, 0, 1, 0)))
            u.mem_write(0x45001000, struct.pack('<4I', 0, bindings.RECORDING, 1, 0xC0BEA924))
            self.assertEqual(self.call(u, 0xC040FD50, 0x45001000), value)
        # Mutation: the nearby word getter is not an equivalent binding.
        u.mem_write(0x4500100C, struct.pack('<I', 0xC0BEA934))
        self.assertNotEqual(self.call(u, 0xC040FD50, 0x45001000), 1)
        u.mem_write(bindings.APP, struct.pack('<I', 2))
        u.mem_write(0x45001004, struct.pack('<I', bindings.APP))
        self.assertEqual(self.call(u, 0xC040FD50, 0x45001000), 2)

    def test_finite_probe_executes_native_leaf_and_preserves_abi(self):
        u = self.machine()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'probe.S'
            source.write_text(bindings.probe_source(0x45001000))
            u.mem_write(0x45000000, armasm.assemble(source))
        u.reg_write(UC_ARM_REG_R4, 0x12345678)
        self.call(u, 0x45000000)
        self.assertEqual(u.reg_read(UC_ARM_REG_R4), 0x12345678)
        self.assertEqual(struct.unpack('<3I', u.mem_read(0x45001000, 12)), (2, 0, 0xC3033848))

    def test_exposure_probe_structure_return_and_setter_arguments(self):
        # Native command edges/ABI independently checked against the official
        # image by ettr.audit_firmware; task/notification machinery modeled here.
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
        from fpSup.ettr.audit_firmware import audit, fingerprint
        image=Path(os.environ['FPL_MAIN']).read_bytes();fingerprint(image);audit(image)
        for field,values in ((None,()),('mode',(1,)),('shutter',(1,6400)),('iso',(800,))):
            u=self.machine();settings=0xC31AB114;seen=[]
            def hook(u,pc,size,data):
                args=[u.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
                value=0
                if pc==bindings.SETTINGS:value=settings
                elif pc==bindings.EXPOSURE['shutter'][1]:
                    self.assertEqual(args[:2],[0x4500100c,settings])
                    u.mem_write(args[0],struct.pack('<2I',1,6400))
                elif pc in [v[1] for v in bindings.EXPOSURE.values()]:
                    self.assertEqual(args[0],settings);value=3 if pc==bindings.EXPOSURE['mode'][1] else 800
                elif pc in [v[0] for v in bindings.EXPOSURE.values()]:
                    self.assertEqual(args[:len(values)+2],[settings,*values,1]);seen.append(pc)
                else:return
                self.assertEqual(u.reg_read(UC_ARM_REG_SP)&7,0)
                u.reg_write(UC_ARM_REG_R0,value);u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
            u.hook_add(UC_HOOK_CODE,hook)
            with tempfile.TemporaryDirectory() as tmp:
                source=Path(tmp)/'exposure.S';source.write_text(bindings.exposure_probe_source(0x45001000,field,values))
                u.mem_write(0x45000000,armasm.assemble(source))
            self.call(u,0x45000000)
            self.assertEqual(struct.unpack('<6I',u.mem_read(0x45001000,24)),(2,settings,3,1,6400,800))
            self.assertEqual(len(seen),int(field is not None))


if __name__ == '__main__': unittest.main()
