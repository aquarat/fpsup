"""The persistent per-frame GTAG test observer, against native fp L code.

Runs the exact fpSup/fp_usb_shell/asm/fpl_gtagpf.S bytes: install calls
native Subject/attach; native notify dispatches to its observer; mode 0
calls the native builder size/add-tag pair; mode 2 parses the serialized
template with the shared parser algorithm; mode 3 rewrites the tag's value
bytes in that template.  The graph is the FINAL one (after late population);
live, mode 0 runs before late population -- the same accepted gap as
test_fpl_gtag560.  The frame DMA is simulated by copying the template after
each mode-3 notify.  No camera transports.
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

SOURCE = Path(__file__).resolve().parents[2] / 'fpSup/fp_usb_shell/asm/fpl_gtagpf.S'
CODE, PARAM, SRC = 0x4B000000, 0x4B001000, 0x4B002000
TEMPLATE = 0x4B100000
OBJ, VT = PARAM + 0x100, PARAM + 0x110
N = 560
TPTR, TLEN = 0xC358E9E8, 0xC358E9E4
MAGIC = 0x504C5046


def payload(counter):
    """The per-frame value: magic, counter, ~counter, N, then (i*7+3)&255."""
    head = struct.pack('<4I', MAGIC, counter, ~counter & 0xFFFFFFFF, N)
    return head + bytes((i * 7 + 3) & 255 for i in range(16, N))


class GtagMachine(D.DngMachine):
    def hook(self, mu, addr, size, userdata):
        if CODE <= addr < CODE + 0x1000:
            return
        super().hook(mu, addr, size, userdata)


class GtagPf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        D.RealDng.setUpClass.__func__(cls)

    def machine(self, code=None):
        import test_fpl_formatter as F
        import test_fpl_tag_capacity as Ncap
        if code is None:
            defines = [f'PARAM={PARAM:#x}', f'SRC={SRC:#x}', f'N={N}']
            code = armasm.assemble(SOURCE, defines)
            sym = armasm.symbols(SOURCE, defines)
        else:
            sym = armasm.symbols(SOURCE, [f'PARAM={PARAM:#x}', f'SRC={SRC:#x}', f'N={N}'])
        m = GtagMachine(Ncap.NativeCapacity.image, F.NativeFormatter.data,
                        Ncap.NativeCapacity.code, Ncap.NativeCapacity.offsets)
        m.reconstruct(self.prefix)
        m.mu.mem_map(CODE, 0x4000)
        m.mu.mem_map(TEMPLATE, 0x40000)   # a serialized header is 0x13800 bytes
        m.mu.mem_write(CODE, code)
        m.mu.mem_write(SRC, payload(0))
        m.write(OBJ, VT)
        for k in range(3):
            m.write(VT + 4 * k, CODE + sym['ret0'])
        m.write(VT + 12, CODE + sym['observer'])
        self.assertTrue(m.call(CODE) == 0)
        self.assertEqual(self.var(m, 0), 2)
        self.assertEqual(m.word(T.SUBJECT + 4 * self.var(m, 8)), OBJ)
        return m

    def var(self, m, off):
        return m.word(PARAM + off)

    def gtag(self, data):
        _, maker = fsg2.maker_note(data)
        ty, count, off = maker[fsg2.GTAG]
        return ty, count, off

    def take(self, m, frames=1):
        """A whole take: build, serialize, locate, `frames` frame notifies."""
        m.notify(0)
        size, h, header = m.output()
        ty, count, off = self.gtag(header)
        self.assertEqual((ty, count), (7, N))
        self.assertEqual(header[off:off + N], payload(0))   # uploaded initial value
        m.mu.mem_write(TEMPLATE, header)
        m.write(TPTR, TEMPLATE)
        m.write(TLEN, h)
        m.notify(2)
        self.assertEqual(self.var(m, 0x3C), 1)
        self.assertEqual(self.var(m, 0x48), off)            # the parser found it
        self.assertEqual(self.var(m, 0x4C), N)
        out = []
        for _ in range(frames):
            m.notify(3)
            out.append(bytes(m.mu.mem_read(TEMPLATE, h)))  # the frame's DMA copy
        return (size, h, header), out

    def test_frame_notifies_rewrite_template_and_stay_attached(self):
        m = self.machine()
        m.notify(3)                     # a frame with no take: skipped, no write
        self.assertEqual((self.var(m, 0x50), self.var(m, 0x54), self.var(m, 0x68)),
                         (1, 0, 1))
        self.assertEqual(m.word(T.SUBJECT + 4 * self.var(m, 8)), OBJ)
        (size, h, header), frames = self.take(m, frames=3)
        self.assertEqual(self.var(m, 0x1C), 1)
        self.assertEqual((self.var(m, 0x28), self.var(m, 0x30)), (0x135C4, h))
        self.assertEqual(self.var(m, 0x20), 1)             # one add, and it stayed
        self.assertEqual(self.var(m, 0x50), 4)             # 1 skip + 3 frames
        self.assertEqual(self.var(m, 0x54), 3)
        for k, frame in enumerate(frames, start=1):
            ty, count, off = self.gtag(frame)
            self.assertEqual((ty, count), (7, N))
            self.assertEqual(frame[off:off + N], payload(k))
        self.assertEqual(self.var(m, 0x58), 3)
        ring = [tuple(self.var(m, 0x6C + 16 * i + 4 * j) for j in range(4))
                for i in range(4)]
        self.assertEqual(ring, [(1, 0, 0, 0)]                    # pre-take skip
                         + [(k, TEMPLATE, h, 1) for k in (1, 2, 3)])
        self.assertEqual(m.word(T.SUBJECT + 4 * self.var(m, 8)), OBJ)
        self.assertEqual(m.mu.mem_read(TEMPLATE, 4), b'II\x2a\x00')  # header intact

    def test_template_pointer_change_is_a_mismatch_not_a_write(self):
        m = self.machine()
        (_, h, _), frames = self.take(m, frames=1)
        self.assertEqual(frames[0][self.gtag(frames[0])[2]:][:4], b'FPLP')
        m.write(TPTR, TEMPLATE + 0x1000)
        m.notify(3)
        self.assertEqual(self.var(m, 0x64), 1)
        self.assertEqual(self.var(m, 0x54), 1)             # no new write
        after = bytes(m.mu.mem_read(TEMPLATE, h))
        self.assertEqual(after[self.gtag(after)[2]:][:N], payload(1))  # untouched

    def test_malformed_template_is_not_located_and_frames_skip(self):
        m = self.machine()
        m.notify(0)
        _, h, _ = m.output()
        m.mu.mem_write(TEMPLATE, b'\xa5' * h)
        m.write(TPTR, TEMPLATE)
        m.write(TLEN, h)
        m.notify(2)
        self.assertEqual((self.var(m, 0x3C), self.var(m, 0x48)), (0, 0))
        m.notify(3)
        self.assertEqual((self.var(m, 0x54), self.var(m, 0x68)), (0, 1))
        self.assertEqual(m.mu.mem_read(TEMPLATE, 2), b'\xa5\xa5')

    def test_short_template_refuses_the_write(self):
        m = self.machine()
        (_, _, _), _ = self.take(m, frames=1)
        off = self.var(m, 0x48)
        m.write(TLEN, off + N - 1)        # mode 3 re-reads the length: no room
        m.notify(3)
        self.assertEqual((self.var(m, 0x54), self.var(m, 0x68)), (1, 1))

    def test_second_take_readds_and_native_replaces_the_tag(self):
        m = self.machine()
        (_, h, _), _ = self.take(m, frames=2)
        m.notify(0)                       # a second take's build event
        self.assertEqual((self.var(m, 0x1C), self.var(m, 0x20)), (2, 2))
        self.assertEqual(self.var(m, 0x30), h)             # no net size growth
        size, h2, header = m.output()
        self.assertEqual(h2, h)
        seen = [t for t in fsg2.maker_note(header)[1] if t == fsg2.GTAG]
        self.assertEqual(len(seen), 1)    # one 0x4653 entry, not two
        m.mu.mem_write(TEMPLATE, header)
        m.write(TPTR, TEMPLATE)
        m.write(TLEN, h2)
        m.notify(2)
        m.notify(3)
        frame = bytes(m.mu.mem_read(TEMPLATE, h2))
        self.assertEqual(frame[self.gtag(frame)[2]:][:N], payload(1))  # index restarts

    def located(self, m, header, h):
        m.mu.mem_write(TEMPLATE, header)
        m.write(TPTR, TEMPLATE)
        m.write(TLEN, h)
        m.notify(2)
        return self.var(m, 0x3C)

    def test_tag_smaller_than_n_refuses_the_write(self):
        # A GTAG already present with a smaller count (another sup's) must not
        # be overrun: the 544 bytes after a 16-byte tag stay untouched.
        m = self.machine()
        m.notify(0)
        _, h, header = m.output()
        _, _, off = self.gtag(header)
        hdr = bytearray(header)
        entry = hdr.find(struct.pack('<HHI', fsg2.GTAG, 7, N))
        self.assertGreater(entry, 0)
        struct.pack_into('<I', hdr, entry + 4, 16)
        hdr[off + 16:off + N] = b'\xee' * (N - 16)
        self.assertEqual(self.located(m, bytes(hdr), h), 1)
        self.assertEqual(self.var(m, 0x4C), 16)
        m.notify(3)
        self.assertEqual((self.var(m, 0x54), self.var(m, 0x68)), (0, 1))
        self.assertEqual(bytes(m.mu.mem_read(TEMPLATE + off, N)), bytes(hdr[off:off + N]))

    def test_skip_mid_take_does_not_shift_later_counters(self):
        m = self.machine()
        (_, h, _), _ = self.take(m, frames=1)
        m.write(TLEN, self.var(m, 0x48) + N - 1)          # frame 2: refused
        m.notify(3)
        m.write(TLEN, h)
        m.notify(3)                                        # frame 3
        frame = bytes(m.mu.mem_read(TEMPLATE, h))
        self.assertEqual((self.var(m, 0x54), self.var(m, 0x68)), (2, 1))
        self.assertEqual(frame[self.gtag(frame)[2]:][:N], payload(3))
        ring = [tuple(self.var(m, 0x6C + 16 * i + 4 * j) for j in (0, 3)) for i in range(3)]
        self.assertEqual(ring, [(1, 1), (2, 0), (3, 1)])

    def test_wrapping_offsets_are_not_located(self):
        m = self.machine()
        m.notify(0)
        _, h, header = m.output()
        exif = header.find(struct.pack('<HH', 0x8769, 4))
        maker = header.find(struct.pack('<HH', 0x927C, 7))
        self.assertGreater(exif, 0)
        self.assertGreater(maker, 0)
        for entry, value in ((exif + 8, 0xFFFFFFFE),       # IFD offset + 2 wraps
                             (maker + 8, 0xFFFFFF00),      # MakerNote offset
                             (maker + 4, 0xFFFFFF00)):     # MakerNote length
            hdr = bytearray(header)
            struct.pack_into('<I', hdr, entry, value)
            self.assertEqual(self.located(m, bytes(hdr), h), 0, hex(entry))
        self.assertEqual(self.located(m, header, h), 1)   # the intact one does

    def test_mutated_mode3_dispatch_leaves_frames_unwritten(self):
        # The unmutated build asserts frame k carries payload(k); prove that
        # can fail: break the mode-3 compare and every frame keeps payload(0).
        defines = [f'PARAM={PARAM:#x}', f'SRC={SRC:#x}', f'N={N}']
        code = armasm.assemble(SOURCE, defines)
        needle = struct.pack('<I', 0xE3510003)             # cmp r1, #3
        self.assertEqual(code.count(needle), 1)
        broken = code.replace(needle, struct.pack('<I', 0xE3510009))
        m = self.machine(code=broken)
        (_, h, _), frames = self.take(m, frames=2)
        self.assertEqual(self.var(m, 0x54), 0)             # no write happened
        for frame in frames:
            self.assertEqual(frame[self.gtag(frame)[2]:][:N], payload(0))


if __name__ == '__main__':
    unittest.main()
