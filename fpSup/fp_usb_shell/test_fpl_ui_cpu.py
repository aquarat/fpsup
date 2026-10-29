"""Execute diagnostic instructions; CP15 inputs explicitly modeled."""
import struct
import unittest

import armasm
import fpl_ui_cpu as cpu
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *


class CPUProbe(unittest.TestCase):
    def run_probe(self, midr=0x410FC075, mpidr=0x80000000, l2=0, mutation=False):
        code, output, ret = 0x45000000, 0x45001000, 0x45002000
        body = armasm.assemble(cpu.SOURCE, [f'P={output}'])
        u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(code, 0x10000)
        u.mem_write(code, body)
        # MRC values are hardware inputs, not emulator CPU defaults.
        reads = []
        values = {0xEE100F10: midr, 0xEE101FB0: mpidr, 0xEE390F50: l2}
        def hook(mu, pc, size, _):
            insn = struct.unpack('<I', mu.mem_read(pc, 4))[0]
            if insn in values:
                reads.append(insn)
                reg = UC_ARM_REG_R1 if insn == 0xEE101FB0 else UC_ARM_REG_R0
                mu.reg_write(reg, values[insn])
                mu.reg_write(UC_ARM_REG_PC, pc+4)
            elif mutation and insn == 0xE5840010:  # lose L2CTLR output
                mu.reg_write(UC_ARM_REG_PC, pc+4)
            elif not code <= pc < code+len(body):
                raise AssertionError(f'unexpected execution {pc:#x}')
        u.hook_add(UC_HOOK_CODE, hook)
        u.reg_write(UC_ARM_REG_CPSR, 0x13)
        u.reg_write(UC_ARM_REG_R4, 0x12345678)
        u.reg_write(UC_ARM_REG_SP, code+0xF000)
        u.reg_write(UC_ARM_REG_LR, ret)
        u.emu_start(code, ret, count=1000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC), ret)
        self.assertEqual(u.reg_read(UC_ARM_REG_SP), code+0xF000)
        self.assertEqual(u.reg_read(UC_ARM_REG_R4), 0x12345678)
        return cpu.decode(bytes(u.mem_read(output, 1024))), reads

    def test_known_cpu_and_four_core_counts(self):
        for n in range(4):
            report, reads = self.run_probe(l2=n << 24)
            self.assertEqual(report['cluster_cpus'], n+1)
            self.assertEqual(len(reads), 3)

    def test_unknown_cpu_does_not_read_implementation_register(self):
        report, reads = self.run_probe(midr=0x410FC090)
        self.assertEqual(report['state'], 3)
        self.assertIsNone(report['cluster_cpus'])
        self.assertEqual(len(reads), 2)

    def test_mutation_detected(self):
        report, _ = self.run_probe(l2=1 << 24, mutation=True)
        with self.assertRaises(AssertionError):
            self.assertEqual(report['cluster_cpus'], 2)


if __name__ == '__main__':
    unittest.main()
