"""The fp L shell bring-up trial, executed offline against the real image.

    FPSUP_FPL_MAIN=/path/to/FPL_V302/MAIN.bin python3 -B -m unittest -v test_fpl_shell_card

Drives the EMITTED AutoRun (the actual command lines from fpl_shell_card.py)
through the real fp L firmware image in Unicorn: the real loader spelled into
the dir body, dispatched via `dir`; the real stage2 journaling and calling the
real worker `spawn`, which really allocates, copies its body, publishes the
rendezvous and creates the task. Stubbed at literal fp L addresses: the file
API, both allocator forms (modelled faithfully, descriptor and all), the
power-off manager, task creation and the cache routines. What this proves:

  - one clean run: load, journal registration, spawn's two allocations and
    publication, wbody copied out of staging, ONE task with the exact
    descriptor fp L expects, staging freed, dir body and slots restored,
    IFACE left patched (deliberately, like fp)
  - the observed DOUBLE AutoRun run: run 2's spawn stands down through the
    publication word -- no second pool, no second task -- and everything
    restores again
  - a missing \\fpSup.BIN: the loader returns 0, nothing allocates or
    registers, the script still restores everything
  - mutations are caught: a dropped restore word leaves the dir body
    non-stock; a corrupted loader byte breaks the file-open oracle

It does NOT prove: USB enumeration, the serve loop (needs the DWC3), cache
effects, or anything live.
"""
import os
from pathlib import Path
import struct
import unittest

from armasm import symbols
from fpl_shell_card import (artifact, card, DIR_ENTRY, DIR_SLOT, POOL_DESC,
                            RESTORE_LEN, ECHO_SLOT, ECHO_STOCK, DCACHE,
                            ICACHE, TABLE, TABLE_LEN, IFACE, IFACE_PATCH,
                            PUBLICATION, BIN_NAME)
from firmware import get_camera

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC)
except ImportError:                                      # pragma: no cover
    Uc = None

CAMERA = get_camera('fp-l-3.02')
IMAGE = Path(os.environ.get(
    'FPSUP_FPL_MAIN',
    Path.home() / '.local/share/fpsup/firmware/FPL_V302/MAIN.bin'))

# Independent literal oracles, not the profile headers.
FW = dict(F_MGR=0xC04408B8, F_VOL=0xC04408F8, F_CTOR=0xC03660A8,
          F_OPEN=0xC03661C8, F_READ=0xC0366278, F_CLOSE=0xC0366238,
          F_DTOR=0xC03660E8, DCACHE=0xC000E91C, ICACHE=0xC000EABC,
          H_GET=0xC001D740, H_ADDR=0xC001D7F0, H_FREE=0xC001D7A0,
          MEM_HEAP=0xC001CF78, MEM_GET=0xC001D038,
          POFF_MGR=0xC00239B8, POFF_ADD=0xC0024038,
          CRETSK=0xC0016A58, STATSK=0xC0016BC0)
# The live allocator's addresses (both boots published these exactly; the
# diag card's hardcoded dumps read them, so the emulation must match).
STAGING, JOURNAL_A = 0x45000000, 0x45020000
POOL, CODE = 0x4533AEC0, 0x4543AF00
STAGING2, JOURNAL_B = 0x45300000, 0x45320000    # the second run's own blocks
STACK, DONE = 0x46000000, 0x47000000
NOPTP_SITES = {0xC003178C, 0xC01E3F84}


class ShellTrial:
    """Applies the emitted script to the image; models the allocator."""

    def __init__(self, test, image, lines, binfile, have_file=True):
        self.t, self.image, self.lines = test, image, lines
        self.bin, self.have_file = binfile, have_file
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)               # the image
        mu.mem_write(0xC0000000, image[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)               # BSS: zero, as at boot
        mu.mem_map(0x40000000, 0x10000000)               # the USER heap window:
        #                                                   staging, journal,
        #                                                   pool, code, stack, DONE
        mu.mem_map(0x21000000, 0x10000)                  # the DWC3 MMIO window
        #                                                   (DALEPENA is read by
        #                                                   the diag dumps)
        self.by_addr = {v: k for k, v in FW.items()}
        self.saved, self.timeline = {}, []
        self.slept_ms = 0
        self.registered = []
        self.tasks = []                                  # captured descriptors
        self.allocations = []                            # (desc, size, addr)
        self.staging = STAGING
        mu.hook_add(UC_HOOK_CODE, self._hook)
        self.current = -1

    def r(self, reg):
        return self.mu.reg_read(reg)

    def word(self, a):
        return struct.unpack('<I', self.mu.mem_read(a, 4))[0]

    def cstr(self, a):
        return bytes(self.mu.mem_read(a, 64)).split(b'\0')[0].decode()

    def _ret(self, value=None):
        if value is not None:
            self.mu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.mu.reg_write(UC_ARM_REG_PC, self.r(UC_ARM_REG_LR))

    def _hook(self, mu, addr, size, _):
        if addr == DONE:
            mu.emu_stop()
            return
        name = self.by_addr.get(addr)
        if name is None:
            return
        self.timeline.append((self.current, name))
        r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                              UC_ARM_REG_R2, UC_ARM_REG_R3))
        if name == 'H_GET':
            # The real H_GET writes {addr, class, addr, size} at the
            # descriptor; the callers read the address back through H_ADDR.
            if self._caller(r0) == 'loader':
                again = any(d == POOL_DESC for d, s, a in self.allocations)
                block = STAGING2 if again else STAGING
            else:
                block = POOL if self._caller(r0) == 'pool' else CODE
            mu.mem_write(r0, struct.pack('<4I', block, r1, block, r2))
            self.allocations.append((r0, r2, block))
            self._ret(r0)
        elif name == 'H_ADDR':
            self._ret(self.word(r0))
        elif name == 'H_FREE':
            self.t.assertEqual(r1, 2)
            self._ret(0)
        elif name == 'F_MGR':
            self._ret(0x12340000)
        elif name == 'F_VOL':
            self.t.assertEqual((r0, r1), (0x12340000, 0))
            self._ret(1)
        elif name == 'F_CTOR':
            self.t.assertEqual(r1, 1)
            self._ret(r0)
        elif name == 'F_OPEN':
            self.t.assertEqual(self.cstr(r1), f'\\{BIN_NAME}')
            self._ret(1 if self.have_file else 0)
        elif name == 'F_READ':
            mu.mem_write(r1, self.bin[:r2])
            self._ret(len(self.bin))
        elif name == 'F_CLOSE':
            self._ret(0)
        elif name == 'F_DTOR':
            self.t.assertEqual(r1, 2)
            self._ret(0)
        elif name == 'MEM_HEAP':
            self.t.assertEqual(r0, 0)
            self._ret(0x44000000)
        elif name == 'MEM_GET':
            self.t.assertEqual(self.word(self.r(UC_ARM_REG_SP)), 0)
            used = [a for d, s, a in self.allocations]
            self._ret(JOURNAL_B if JOURNAL_A in used else JOURNAL_A)
        elif name == 'POFF_MGR':
            self._ret(0xC3000100)
        elif name == 'POFF_ADD':
            self.t.assertEqual((r0, r2), (0xC3000100, len(self.registered) % 2))
            self.registered.append((r1, r2))
            self._ret(1)
        elif name == 'CRETSK':
            d = bytes(mu.mem_read(r0, 32))
            self.tasks.append(d)
            self._ret(5)
        else:
            self._ret(0)          # STATSK, DCACHE, ICACHE

    def _caller(self, desc):
        if desc == POOL_DESC:
            return 'loader'
        # spawn keeps both descriptors on its stack, 16 bytes apart; the size
        # argument says which is which.
        size = self.r(UC_ARM_REG_R2)
        if size == 0x100000:
            return 'pool'
        if size < 0x2000:                      # wbody_len is under 8 KiB
            return 'code'
        raise AssertionError(f'unexpected H_GET size {size:#x}')

    def run(self):
        for index, line in enumerate(self.lines):
            self.current = index
            line = line.strip()
            if line.startswith('mem save'):
                _, _, path, spec = line.split()
                start, size = (int(p, 16) for p in spec.split(',,'))
                self.saved[path] = bytes(self.mu.mem_read(start, size))
            elif line.startswith('mem set'):
                _, _, address, value = line.split()
                address, value = int(address, 16), int(value, 16)
                allowed = (DIR_ENTRY <= address and
                           address + 4 <= DIR_ENTRY + RESTORE_LEN or
                           address == ECHO_SLOT or address == IFACE or
                           address in NOPTP_SITES)
                self.t.assertTrue(allowed, f'script writes at {address:#x}')
                self.mu.mem_write(address, struct.pack('<I', value))
            elif line == 'echo':
                slot = self.word(ECHO_SLOT)
                self.dispatch(slot)
            elif line.startswith('ctrl sleep'):
                self.slept_ms = int(line.split()[-1])   # modelled as a no-op
            elif line == 'dir':
                slot = self.word(DIR_SLOT)
                self.t.assertEqual(slot, DIR_ENTRY)
                self.dispatch(slot)
            elif line.startswith('#'):
                continue
            else:
                raise AssertionError(f'unmodelled line: {line!r}')
        self.current = -1
        return self

    def dispatch(self, target, r0=0xC0BAC000, r1=0):
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, STACK - 0x1004)     # 4 off, like the caller
        mu.reg_write(UC_ARM_REG_R0, r0)
        mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_LR, DONE)
        mu.emu_start(target, DONE, count=20_000_000)


@unittest.skipIf(Uc is None or not IMAGE.exists(),
                 'needs unicorn and the private fp L 3.02 MAIN image')
class ShellCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = CAMERA.verify_main(IMAGE)
        cls.lines, cls.manifest, cls.art = card(cls.image)
        # The script carries exactly the freshly assembled chain.
        from armasm import assemble
        camera = CAMERA.loader_defines()
        loader = assemble(Path(__file__).resolve().parent / 'asm/loader.S',
                          camera + [f'LOADER_BASE={DIR_ENTRY:#010X}',
                                    f'POOL_DESC={POOL_DESC:#010X}',
                                    f'BIN_PATH="\\\\{BIN_NAME}"'])
        assert loader == cls.art['loader']

    def stock(self, start, length):
        return self.image[start - 0xC0000000:start - 0xC0000000 + length]

    def trial(self, **kw):
        return ShellTrial(self, self.image, self.lines, self.art['binfile'],
                          **kw).run()

    def assert_worker_installed(self, cam, pool=POOL, code=CODE, tasks=1):
        t = self
        t.assertEqual(struct.unpack('<4I', cam.mu.mem_read(PUBLICATION, 16)),
                     (pool, 0x100000, code, 0))
        t.assertEqual(cam.word(pool + 0x1000), 0x4C485356)      # 'VSHL'
        t.assertEqual(cam.word(pool + 0x1004), 5)                # task id
        w = self.art['symbols']
        body = w['wbody_end'] - w['wbody']
        t.assertEqual(bytes(cam.mu.mem_read(code, body)),
                     self.art['worker'][w['wbody']:w['wbody_end']])
        t.assertEqual(len(cam.tasks), tasks)
        d = struct.unpack('<IIIIIIII', cam.tasks[0])
        t.assertEqual(d[0], 0)                                   # exinf
        t.assertEqual(d[1], 0x41)                                # tskatr
        t.assertEqual(d[2], code + (w['serve'] - w['wbody']))    # entry
        t.assertEqual(d[3], 28)                                  # priority
        t.assertEqual(d[4], 0x2000)                              # stack
        t.assertEqual(d[5], 0x4853565F)                          # '_VSH'
        t.assertEqual(d[6], 0x004C)                              # 'L'

    def assert_restored(self, cam):
        t = self
        t.assertEqual(bytes(cam.mu.mem_read(DIR_ENTRY, RESTORE_LEN)),
                     self.stock(DIR_ENTRY, RESTORE_LEN))
        t.assertEqual(cam.word(ECHO_SLOT), ECHO_STOCK)
        t.assertEqual(cam.word(DIR_SLOT), DIR_ENTRY)
        t.assertEqual(cam.saved['\\FPLPROBE\\SHELL-PRE.BIN'],
                     self.stock(DIR_ENTRY, RESTORE_LEN))
        t.assertEqual(cam.saved['\\FPLPROBE\\SHELL-RESTORED.BIN'],
                     self.stock(DIR_ENTRY, RESTORE_LEN))
        t.assertEqual(cam.saved['\\FPLPROBE\\SHELL-SLOTS.BIN'],
                     self.stock(TABLE, TABLE_LEN))
        t.assertEqual(cam.word(IFACE), IFACE_PATCH)   # deliberately kept

    def test_one_run_loads_spawns_restores_and_evidences(self):
        cam = self.trial()
        self.assert_worker_installed(cam)
        self.assert_restored(cam)
        wrote = bytearray(self.stock(DIR_ENTRY, RESTORE_LEN))
        wrote[:len(self.art['loader'])] = self.art['loader']
        self.assertEqual(cam.saved['\\FPLPROBE\\SHELL-WROTE.BIN'], bytes(wrote))
        kinds = [n for _, n in cam.timeline]
        # loader staging, journal, spawn's two, then the free of the staging
        self.assertEqual(kinds.count('H_GET'), 3)
        self.assertEqual([a for d, s, a in cam.allocations],
                         [STAGING, POOL, CODE])
        self.assertEqual(kinds.count('H_FREE'), 1)
        self.assertEqual([f for _, f in cam.registered], [0, 1])
        self.assertIn('CRETSK', kinds)
        self.assertIn('STATSK', kinds)
        # the chain published before running the entry, twice around it
        cache = [n for n in kinds if n in ('DCACHE', 'ICACHE')]
        self.assertEqual(cache[:2], ['DCACHE', 'ICACHE'])       # loader
        self.assertGreaterEqual(len(cache), 6)                  # + lh_setup,
        #   pass-1 publish, spawn's copy publish, pass-2 publish

    def test_second_execution_stands_the_worker_down(self):
        cam = self.trial()
        cam.run()                                   # the observed double run
        # ONE task, ONE pool: run 2's spawn stood down via the publication
        self.assert_worker_installed(cam, tasks=1)
        self.assert_restored(cam)
        kinds = [n for _, n in cam.timeline]
        self.assertEqual(kinds.count('CRETSK'), 1)
        # run 2 still loaded its own staging and its own journal block...
        self.assertEqual([a for d, s, a in cam.allocations],
                         [STAGING, POOL, CODE, STAGING2])
        self.assertEqual(kinds.count('H_FREE'), 2)
        # ...and registered a second (empty) journal, harmlessly
        self.assertEqual([f for _, f in cam.registered], [0, 1, 0, 1])

    def test_missing_file_refuses_and_still_restores(self):
        cam = self.trial(have_file=False)
        self.assertEqual(len(cam.tasks), 0)
        self.assertEqual(cam.word(PUBLICATION), 0)
        self.assertEqual(cam.saved['\\FPLPROBE\\SHELL-POOL.BIN'], bytes(16))
        self.assertEqual([a for d, s, a in cam.allocations], [STAGING])
        self.assertEqual(cam.registered, [])
        self.assert_restored(cam)                    # IFACE still patched

    def test_diag_card_patches_noptp_waits_and_dumps_state(self):
        from fpl_shell_card import (card as card_fn, NOPTP1, NOPTP1_PATCH,
                                    NOPTP2, NOPTP2_PATCH, DIAG_POOL,
                                    DIAG_SLEEP_MS, FW_PTPBUF, FW_USBSTATE,
                                    FW_OUTBUSY, FW_DALEPENA)
        lines, manifest, art = card_fn(self.image, diag=True)
        cam = ShellTrial(self, self.image, lines, art['binfile']).run()
        self.assert_worker_installed(cam)
        self.assert_restored(cam)
        # NOPTP patched, left in place after the restore phase
        self.assertEqual(cam.word(NOPTP1), NOPTP1_PATCH)
        self.assertEqual(cam.word(NOPTP2), NOPTP2_PATCH)
        # the wait window is modelled and recorded
        self.assertEqual(cam.slept_ms, DIAG_SLEEP_MS)
        # the dumps landed in the saves, with the right content
        state = cam.saved[f'\\FPLPROBE\\DIAG-STATE.BIN']
        self.assertEqual(struct.unpack_from('<I', state, 0)[0], 0x4C485356)
        self.assertEqual(struct.unpack_from('<I', state, 4)[0], 5)  # task id
        self.assertEqual(len(state), 0x40)
        self.assertEqual(cam.saved['\\FPLPROBE\\DIAG-FRAME.BIN'],
                         bytes(cam.mu.mem_read(DIAG_POOL, 0x40)))
        self.assertEqual(cam.saved['\\FPLPROBE\\DIAG-PTP.BIN'],
                         bytes(cam.mu.mem_read(FW_PTPBUF, 0x40)))
        self.assertEqual(len(cam.saved['\\FPLPROBE\\DIAG-FAULTS.BIN']), 0x210)
        self.assertEqual(cam.saved['\\FPLPROBE\\DIAG-USBSTATE.BIN'],
                         bytes(cam.mu.mem_read(FW_USBSTATE, 4)))
        self.assertEqual(cam.saved['\\FPLPROBE\\DIAG-OUTBUSY.BIN'],
                         bytes(cam.mu.mem_read(FW_OUTBUSY, 4)))
        self.assertEqual(cam.saved['\\FPLPROBE\\DIAG-DALEPENA.BIN'],
                         bytes(cam.mu.mem_read(FW_DALEPENA, 8)))

    def test_dropped_restore_word_leaves_the_body_non_stock(self):
        damaged = list(self.lines)
        restore = [i for i, l in enumerate(damaged)
                   if l.startswith(f'mem set 0x{DIR_ENTRY:08X}') and i >
                   damaged.index('dir')]
        damaged.remove(damaged[restore[-1]])
        cam = ShellTrial(self, self.image, damaged, self.art['binfile']).run()
        self.assertNotEqual(bytes(cam.mu.mem_read(DIR_ENTRY, RESTORE_LEN)),
                            self.stock(DIR_ENTRY, RESTORE_LEN))

    def test_corrupted_loader_path_breaks_the_open_oracle(self):
        # The loader's last bytes are the BIN path string; break its first
        # word, and the F_OPEN stub must refuse the name it is handed.
        first_path_word = struct.unpack('<I', b'\\' + BIN_NAME.encode()[:3])[0]
        target = f'0x{first_path_word:08X}'
        hits = [l for l in self.lines if l.endswith(target)]
        self.assertEqual(len(hits), 1)
        damaged = [l.replace(target, f'0x{first_path_word + 1:08X}')
                   for l in self.lines]
        self.assertNotEqual(damaged, self.lines)
        with self.assertRaises(AssertionError):
            ShellTrial(self, self.image, damaged, self.art['binfile']).run()


if __name__ == '__main__':
    unittest.main()