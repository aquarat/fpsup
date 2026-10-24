"""Offline attach feasibility and refusal evidence; not a live installer.

Executes native fp L Subject attach/notify, shared observer, native insertion
and reconstructed real-DNG serialization. Guard/lock/context/heap/copy stubs
are inherited explicitly from the earlier harness. No camera transports.
"""
import struct
import unittest

import build as G
import fsg2
import tag_capacity as C
import test_fpl_observer as T
import test_fpl_tag_capacity as N
import test_fpl_formatter as F
import test_fpl_formatter_dng as D


class AttachRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        D.RealDng.setUpClass.__func__(cls)

    def route(self, n):
        code, offsets, _ = G.observer_probe(N.NativeCapacity.fp,
            N.NativeCapacity.fpl, sample_hz=1234, tag_capacity=n,
            frame_callback=T.CALLBACK)
        m = D.DngMachine(N.NativeCapacity.image, F.NativeFormatter.data, code, offsets)
        m.reconstruct(self.prefix)
        m.attach()
        return m

    def test_exact_observer_add_560_561_then_native_header(self):
        for n, expected_h in ((560, 0x13800), (561, 0x13C00)):
            with self.subTest(n=n):
                m = self.route(n)
                m.notify(0)
                self.assertEqual(m.var(172), n)
                size, h, b = m.output()
                self.assertEqual((size, h), (0x135C4+12+((n+1) & ~1), expected_h))
                _, maker = fsg2.maker_note(b)
                ty, count, off = maker[fsg2.GTAG]
                self.assertEqual((ty, count, b[off:off+n]), (7, n, bytes(n)))
                self.assertEqual(fsg2.ifd_entries(b, 8)[0x111], (4, 1, h))
                self.assertEqual(C.validate_header(b, serialized_bytes=h,
                    owner_bytes=0x15400, raw_start=h, tag_bytes=n), fsg2.gtag_area(b))

    def test_failed_value_storage_does_not_stop_observer_or_native_writer(self):
        m = self.route(561)
        m.fail_at = len(m.allocations)+1  # value-object succeeds, payload fails
        m.notify(0)
        self.assertEqual(m.var(172), 561)  # bookkeeping is not admission
        self.assertEqual(m.word(T.SUBJECT), T.OBS)  # still attached
        _, h, b = m.output()  # writer still returns, despite missing data
        with self.assertRaises(C.CapacityError):
            C.validate_header(b, serialized_bytes=h, owner_bytes=0x15400,
                              raw_start=h, tag_bytes=561)

    def test_mutated_zero_return_detaches_but_does_not_undo_tag_or_cancel(self):
        m = self.route(561)
        start = T.CODE+m.offsets['tag_observer']
        code = bytes(m.mu.mem_read(start, m.size-(start-T.CODE)))
        epilogue = struct.pack('<II', 0xE3A00001, 0xE28DD018)
        self.assertEqual(code.count(epilogue), 1)
        at = start+code.index(epilogue)
        m.write(at, 0xE3A00000)
        m.mu.ctl_remove_cache(at, at+4)
        m.notify(0)
        self.assertEqual(m.word(T.SUBJECT), 0)  # native dispatcher clears slot
        self.assertEqual(m.var(172), 561)
        _, h, b = m.output()
        self.assertEqual(h, 0x13C00)
        self.assertIsNotNone(fsg2.gtag_area(b))  # detaching is not rollback

    def test_full_subject_refuses_attach_without_overwrite(self):
        m = self.route(560)
        slots = tuple(T.OBS+4*(i+1) for i in range(9))
        m.mu.mem_write(T.SUBJECT, struct.pack('<9I', *slots))
        with self.assertRaises(N.NativeAssert):
            m.call(T.ATTACH, T.SUBJECT, T.OBS)
        self.assertEqual(bytes(m.mu.mem_read(T.SUBJECT, 36)), struct.pack('<9I', *slots))


if __name__ == '__main__':
    unittest.main()
