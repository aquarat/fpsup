"""Headless fp L service profile through real shared boot and native allocation.

No transport. File I/O, directory backend, power-off registration and cache
effects are mocked; USER allocator and directory wrapper instructions are real.
"""
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm_const as ar
import card_build
import test_fpl_shell_card as fpl
import test_fpl_retained_launcher as native
from v3 import build_v3 as build
from v3 import test_v3 as old

FW = dict(old.F, F_MGR=0xC04408B8, F_VOL=0xC04408F8,
          F_CTOR=0xC03660A8, F_OPEN=0xC03661C8, F_READ=0xC0366278,
          F_CLOSE=0xC0366238, F_DTOR=0xC03660E8, F_WRITE=0xC0366300,
          TICK=0xC0029320, POFF_MGR=0xC00239B8, POFF_ADD=0xC0024038,
          DIR_CTOR=0xC0366B30, DIR_OPEN=0xC0366BA8,
          DIR_NEXT=0xC0366C10, DIR_DTOR=0xC0366B58)
NATIVE = ('MEM_HEAP', 'MEM_GET', 'MEM_FREE', 'DIR_CTOR', 'DIR_OPEN', 'DIR_NEXT', 'DIR_DTOR')
HEAP, HEAP_BYTES = 0x44400000, 0x100000


def envelope():
    core, info = build.loader_bin(splash=False, camera='fp-l-3.02')
    art = card_build.artifact()
    binary, entry, _ = card_build.build_vbin([(0, art['stage2']), (0, core)], [(1, 16)])
    assert len(binary) <= card_build.READ_CAP
    return art['loader'], binary, info


class Camera(old.Camera):
    def __init__(self, loader, binary, products=(), *, fail_poff=None, no_heap=False,
                 heap_bytes=HEAP_BYTES):
        files = {'\\fpSup.BIN': binary}
        entries = []
        for name, data in products:
            files['\\fpSup\\'+name] = data
            entries.append((name, 0x20, len(data)))
        constructor = old.Uc
        def cortex(*args, **kwargs):
            m = constructor(*args, **kwargs)
            m.ctl_set_cpu_model(ar.UC_CPU_ARM_CORTEX_A15)
            return m
        with patch.object(old, 'IMAGE', fpl.IMAGE), patch.dict(old.F, FW, clear=True), \
                patch.object(old, 'Uc', side_effect=cortex):
            super().__init__(files, {'\\fpSup': entries}, autorun=b'')
        self.mu.mem_write(card_build.DIR_ENTRY, loader)
        self.fail_poff, self.no_heap = fail_poff, no_heap
        self.poff_calls = 0
        # Remove only native service stubs and restore their instructions.
        for name in NATIVE:
            address = FW[name]
            self.by_addr.pop(address)
            self.mu.mem_write(address, self.img[address-0xC0000000:address-0xC0000000+4])
        self.mu.mem_map(HEAP, heap_bytes)
        a = native.allocator.Machine(self.img)
        if heap_bytes > 0x10000:
            a.mu.mem_map(HEAP+0x10000, heap_bytes-0x10000)
        a.stubs.update({0xC0013090: 1, 0xC00131E4: 0, 0xC001E328: 0, 0xC001E3C8: 0})
        a.put(0xC30739D8, native.allocator.CHANNEL)
        a.put(0xC3073A10, native.allocator.CHANNEL)
        a.put(native.allocator.CHANNEL, 0, 0)
        a.call(0xC0010310, native.allocator.CHANNEL+8)
        a.call(0xC00103A8, native.allocator.CHANNEL+8, HEAP)
        for address in (HEAP, HEAP+heap_bytes-0x40):
            a.put(native.allocator.DESC+0x100, address, 0x40)
            a.call(0xC00103E8, native.allocator.CHANNEL+8, native.allocator.DESC+0x100)
        self.mu.mem_write(HEAP, bytes(a.mu.mem_read(HEAP, heap_bytes)))
        self.mu.mem_write(0xC3070000, bytes(a.mu.mem_read(0xC3070000, 0x10000)))
        self.native_calls = []
        self.mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.memory)

    def memory(self, mu, access, address, size, value, unused):
        assert not 0xC072DE00 <= address < 0xC0730000, 'fp cave/global access'
        for start in self.freed:
            if start in self.allocs and self.allocs[start] == 0x10000:
                assert not start <= address < start+0x10000, 'freed staging reference'

    def _hook(self, mu, address, size, unused):
        if address in (0xC0011100, 0xC0011130):
            raise AssertionError('native firmware assertion')
        if address in (0xC0013090, 0xC00131E4, 0xC001E328, 0xC001E3C8):
            return self._ret(1 if address == 0xC0013090 else 0)
        if address == FW['MEM_HEAP'] and self.no_heap:
            return self._ret(0)
        if address in [FW[n] for n in NATIVE]:
            assert self.r(ar.UC_ARM_REG_SP) % 8 == 0, 'native service call alignment'
            self.native_calls.append(address)
        if address == 0xC0366AA0:  # native directory backend constructor boundary
            obj = self._alloc(0x40)
            self.put(obj+4, obj+0x10)
            for off, name in ((8, 'DIR_DTOR'), (12, 'DIR_OPEN'), (20, 'DIR_NEXT')):
                target = old.DONE+0x100+off
                self.put(obj+0x10+off, target)
                self.put(target, 0xE12FFF1E)
                self.by_addr[target] = name
            return self._ret(obj)
        if address == FW['POFF_ADD']:
            self.poff_calls += 1
            if self.poff_calls == self.fail_poff:
                return self._ret(0)
        super()._hook(mu, address, size, unused)

    def state(self):
        objs = [o-old.SVC_BYTES for o, _ in self.registered
                if self.w(o-old.SVC_BYTES) == 2]
        assert objs
        return objs[-1]

    def boot(self):
        result = self.call(card_build.DIR_ENTRY)
        assert self.r(ar.UC_ARM_REG_PC) == old.DONE
        return result


class Headless(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        card_build.CAMERA.verify_main(fpl.IMAGE)
        cls.loader, cls.binary, cls.info = envelope()

    def camera(self, products=(), **kwargs):
        return Camera(self.loader, self.binary, products, **kwargs)

    def test_native_services_kept_books_duplicate_and_staging_release(self):
        product = old.test_sup('TEST', [])
        m = self.camera([('10A.BIN', product), ('20B.BIN', product)])
        _, sp = m.boot()
        self.assertEqual(sp, old.STACK-0x1004)
        st = m.state()
        self.assertEqual(m.w(st+old.O_NSUPS), 1)
        self.assertIn('DUP_ID', [r[0] for r in m.log()])
        self.assertEqual(len(m.registered), 4)  # real shared stage2 + resident v3
        self.assertTrue(all(FW[n] in m.native_calls for n in NATIVE))
        self.assertIn('\\fpSup\\LOAD.LOG', m.written)
        # Owned service called through the captured in-lifetime table, never a
        # global lookup. No cave allocation is advertised or synthesized.
        r, _ = m.call(m.w(st+20), r0=st, r1=8)
        self.assertEqual(r, 0)
        self.assertEqual(m.w(st), 2)

    def test_bad_missing_and_version3_products_fail_cleanly(self):
        good = old.test_sup('GOOD', [])
        bad_version = bytearray(good); struct.pack_into('<I', bad_version, 28, 3)
        m = self.camera([('10BAD.BIN', bytes(bad_version)), ('20SHORT.BIN', b'bad'),
                         ('30MISS.BIN', good), ('40GOOD.BIN', good)])
        del m.files['\\fpSup\\30MISS.BIN']
        m.boot()
        self.assertEqual(m.w(m.state()+old.O_NSUPS), 1)
        codes = [r[0] for r in m.log()]
        self.assertIn('BAD_HEADER', codes)
        self.assertIn('OPEN_FAIL', codes)

    def test_registration_and_heap_failures_do_not_enter_products(self):
        for kwargs in ({'no_heap': True}, {'fail_poff': 1}, {'fail_poff': 2},
                       {'fail_poff': 3}, {'fail_poff': 4}, {'heap_bytes': 0xC000}):
            with self.subTest(kwargs=kwargs):
                m = self.camera([('10TEST.BIN', old.test_sup('TEST', []))], **kwargs)
                m.boot()
                self.assertNotIn('\\fpSup\\10TEST.BIN', m.opened)

    def check_claim_restore(self, loader, binary):
        image = fpl.IMAGE.read_bytes()
        site = card_build.IFACE
        stock = struct.unpack_from('<I', image, site-0xC0000000)[0]
        first = old.test_sup('ONE', [(site, stock, 2, 0x12345678)])
        conflict = old.test_sup('TWO', [(site, stock, 2, 0xBAD00000)])
        m = Camera(loader, binary, [('10ONE.BIN', first), ('20TWO.BIN', conflict)])
        m.boot()
        self.assertEqual(m.w(site), 0x12345678)
        self.assertIn('CONFLICT', [r[0] for r in m.log()])
        self.assertEqual(m.journal(), [(site, 4, struct.pack('<I', stock))])
        m.power_off()  # execute the resident ARM write-back, not a restoration mock
        self.assertEqual(m.w(site), stock)

    def test_claim_collision_and_resident_journal_restore(self):
        self.check_claim_restore(self.loader, self.binary)

    def test_mutation_missing_stock_journal_copy_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('sloader.c', 'sloader.h', 'sloader_entry.S', 'services_fpl_302.h'):
                shutil.copyfile(build.HERE/name, root/name)
            path = root/'sloader.c'
            text = path.read_text()
            original = 'copy((void *)(e + 2), stock, len);'
            self.assertIn(original, text)
            path.write_text(text.replace(original, '(void)stock;'))
            with patch.object(build, 'HERE', root):
                loader, binary, _ = envelope()
            with self.assertRaises(AssertionError):
                self.check_claim_restore(loader, binary)

    def test_fresh_loader_has_new_books_not_boot_identity(self):
        m = self.camera([('10TEST.BIN', old.test_sup('TEST', []))])
        m.boot(); first = m.state()
        m.boot(); second = m.state()
        self.assertNotEqual(first, second)
        self.assertEqual(m.w(first+old.O_NSUPS), 1)
        self.assertEqual(m.w(second+old.O_NSUPS), 1)
        # This is precisely why kept-ID exclusion cannot be promoted to a
        # cross-loader or cross-reboot retained admission provider.
        self.assertNotIn('DUP_ID', [r[0] for r in m.log()])

    def test_profile_rejects_unimplemented_ui(self):
        with self.assertRaises(build.BuildError):
            build.loader_bin(camera='fp-l-3.02')
        with self.assertRaises(build.BuildError):
            build.loader_bin(camera='fp-l-3.02', splash=False, allsups=True)


if __name__ == '__main__':
    unittest.main()
