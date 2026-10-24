"""The live one-shot GTAG test observer, executed against native fp L code.

Runs the exact fpSup/fp_usb_shell/asm/fpl_gtag560.S bytes: its installer
calls native Subject/attach, and native notify dispatches to its observer,
which calls native insertion and sizing on the reconstructed real-DNG graph.
The graph is the FINAL one (after late population); live, the observer runs
at mode 0 before late population. That gap is accepted by the owner for this
experiment, not proved here. No camera transports.
"""
import struct
import sys
import unittest
from pathlib import Path

import build as G
import fsg2
import tag_capacity as C
import test_fpl_formatter_dng as D
import test_fpl_observer as T

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'fpSup/fp_usb_shell'))
import armasm  # noqa: E402

SOURCE = Path(__file__).resolve().parents[2] / 'fpSup/fp_usb_shell/asm/fpl_gtag560.S'
CODE, PARAM, SRC = 0x4B000000, 0x4B001000, 0x4B002000
OBJ, VT = PARAM + 0x100, PARAM + 0x110


def payload(n):
    head = b'FPL-GTAG-TEST\0' + struct.pack('<I', n)
    return (head + bytes((i * 7 + 3) & 255 for i in range(n)))[:n]


class GtagMachine(D.DngMachine):
    def hook(self, mu, addr, size, userdata):
        if CODE <= addr < CODE + 0x1000:
            return
        super().hook(mu, addr, size, userdata)


class Gtag560(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        D.RealDng.setUpClass.__func__(cls)

    def machine(self, n=560):
        import test_fpl_formatter as F
        import test_fpl_tag_capacity as N
        defines = [f'PARAM={PARAM:#x}', f'SRC={SRC:#x}', f'N={n}']
        code = armasm.assemble(SOURCE, defines)
        sym = armasm.symbols(SOURCE, defines)
        m = GtagMachine(N.NativeCapacity.image, F.NativeFormatter.data,
                        N.NativeCapacity.code, N.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        m.mu.mem_map(CODE, 0x4000)
        m.mu.mem_write(CODE, code)
        m.mu.mem_write(SRC, payload(n))
        m.write(OBJ, VT)
        for k in range(3):
            m.write(VT + 4 * k, CODE + sym['ret0'])
        m.write(VT + 12, CODE + sym['observer'])
        return m

    def var(self, m, off):
        return m.word(PARAM + off)

    def test_install_notify_adds_exact_tag_and_self_detaches(self):
        m = self.machine()
        self.assertEqual(m.call(CODE), 0)
        self.assertEqual(self.var(m, 0), 2)
        self.assertEqual(m.word(T.SUBJECT + 4 * self.var(m, 8)), OBJ)
        self.assertEqual(self.var(m, 12), 9)
        m.notify(3)                     # a frame event: ignored, stays attached
        self.assertEqual(m.word(T.SUBJECT), OBJ)
        self.assertEqual(self.var(m, 0x20), 0)
        m.notify(0)
        self.assertEqual(self.var(m, 0x20), 1)
        self.assertEqual(m.word(T.SUBJECT), 0)   # native dispatcher cleared it
        self.assertEqual((self.var(m, 0x28), self.var(m, 0x30)), (0x135C4, 0x13800))
        self.assertEqual(self.var(m, 0x34), 560)
        size, h, b = m.output()
        self.assertEqual((size, h), (0x13800, 0x13800))
        _, maker = fsg2.maker_note(b)
        ty, count, off = maker[fsg2.GTAG]
        self.assertEqual((ty, count, b[off:off + 560]), (7, 560, payload(560)))
        self.assertEqual(fsg2.ifd_entries(b, 8)[0x111], (4, 1, h))
        self.assertEqual(C.validate_header(b, serialized_bytes=h, owner_bytes=0x15400,
                                           raw_start=h, tag_bytes=560), fsg2.gtag_area(b))
        m.notify(0)                     # detached: a second take adds nothing
        self.assertEqual(self.var(m, 0x30), 0x13800)
        self.assertEqual(m.output()[1], 0x13800)

    def test_reinstall_refused_while_attached(self):
        m = self.machine()
        m.call(CODE)
        m.call(CODE)
        self.assertEqual(self.var(m, 0), 4)
        self.assertEqual(sum(m.word(T.SUBJECT + 4 * i) == OBJ for i in range(9)), 1)

    def test_full_subject_refused_without_overwrite(self):
        m = self.machine()
        slots = tuple(T.OBS + 4 * (i + 1) for i in range(9))
        m.mu.mem_write(T.SUBJECT, struct.pack('<9I', *slots))
        m.call(CODE)
        self.assertEqual(self.var(m, 0), 3)
        self.assertEqual(bytes(m.mu.mem_read(T.SUBJECT, 36)), struct.pack('<9I', *slots))

    def test_mutation_561_crosses_padding(self):
        m = self.machine(561)
        m.call(CODE)
        m.notify(0)
        self.assertEqual(m.output()[1], 0x13C00)


if __name__ == '__main__':
    unittest.main()
