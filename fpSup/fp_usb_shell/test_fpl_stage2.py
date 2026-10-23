"""The fp L load chain under emulation, against the real fp L 3.02 image.

    FPSUP_FPL_MAIN=/path/to/FPL_V302/MAIN.bin python3 -B -m unittest -v test_fpl_stage2

Assembles the REAL loader.S and the REAL stage2.S with the fp L firmware
profile and the dir-body placement the live heap-probe trial proved
(docs/FPL_HEAP_PROBE.md), then runs them the way a boot would: the loader
spelled into the stock `dir` handler's verified extent, dispatched through the
untouched `dir` slot; stage2 running from the loader's staging allocation.

Firmware routines are stubbed at the profile's literal addresses (independent
oracles, not derived from the headers): file API, descriptor allocator,
channel allocator, power-off manager and cache maintenance. The payload entry
is stubbed. What this proves, per docs/FPL_PORT.md's stage2 milestone:

  - the chain completes: file read -> stage2 -> both passes -> entry -> return,
    with the loader freeing its staging and returning load status
  - both power-off registrations happen BEFORE any firmware word is patched
  - the journal holds the stock words of every firmware section, and with the
    fp L exclusion EMPTY (no cave) a destination inside the fp structural
    cave range is journaled too -- nothing is exempt on fp L
  - pool-offset sections land only after the entry publishes its pool, via
    the fp L publication word C37588BC
  - the power-off routine, called once per list, puts every patched word back
  - a missing file returns cleanly with no journal, no registration, no entry

It does NOT prove: the camera's live allocator, cache or power-off manager
behaviour (see docs/FPL_POFF_AUDIT.md for the static evidence), any USB
worker, or an installable fp L card.
"""
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

from armasm import assemble
from firmware import get_camera

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                                   UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                                   UC_ARM_REG_PC)
except ImportError:                                      # pragma: no cover
    Uc = None

HERE = pathlib.Path(__file__).resolve().parent
CAMERA = get_camera('fp-l-3.02')
IMAGE = pathlib.Path(os.environ.get(
    'FPSUP_FPL_MAIN',
    pathlib.Path.home() / '.local/share/fpsup/firmware/FPL_V302/MAIN.bin'))

# The placement the heap-probe trial proved, from docs/FPL_BOOTSTRAP_AUDIT.md:
# the loader is spelled into the stock `dir` handler's verified extent and
# dispatched through the untouched `dir` table slot.
DIR_ENTRY = 0xC03E2B98            # LOADER_BASE; also the stage2 build value
POOL_DESC = DIR_ENTRY + 0x200     # the loader's descriptor: dir body +512,
                                  # above the loader's 468 bytes, inside the
                                  # verified 896-byte extent, restored with
                                  # the dir body by the script that follows
# Independent literal oracles. Deliberately NOT imported from the headers:
# a wrong selected address must fail here, not move its stub with it.
FW = dict(F_MGR=0xC04408B8, F_VOL=0xC04408F8, F_CTOR=0xC03660A8,
          F_OPEN=0xC03661C8, F_READ=0xC0366278, F_CLOSE=0xC0366238,
          F_DTOR=0xC03660E8, DCACHE=0xC000E91C, ICACHE=0xC000EABC,
          H_GET=0xC001D740, H_ADDR=0xC001D7F0, H_FREE=0xC001D7A0,
          MEM_HEAP=0xC001CF78, MEM_GET=0xC001D038,
          POFF_MGR=0xC00239B8, POFF_ADD=0xC0024038,
          TICK=0xC0029320)
FRAMEBUF = 0xC37588BC             # the fp L pool publication word
DIR_SLOT = 0xC0BD24FC             # entry 14's handler slot: stays DIR_ENTRY

STAGING = 0x45000000              # the loader's staging allocation
JOURNAL = 0x45020000              # stage2's journal block (never freed)
POOL = 0x45100000                 # the entry's own published pool
STACK = 0x46000000
ENTRY = 0x47000000                # a stub entry address nothing else uses
DONE = 0x48000000

FW_DEST = 0xC1000000              # a firmware word to patch: inside the
                                  # mapped image, chosen for the test
IMU_RANGE_DEST = 0xC072C000       # inside the fp structural cave counterpart:
                                  # IMU-owned, and on fp L still JOURNALED --
                                  # the exclusion is empty by policy

BIN_PATH = '\\fpSup.BIN'


def fpl_defines(loader_base, extra=()):
    return list(CAMERA.loader_defines()) + [f'LOADER_BASE={loader_base:#010X}',
                                            f'POOL_DESC={POOL_DESC:#010X}',
                                            'BIN_PATH="\\\\fpSup.BIN"',
                                            *extra]


def build_bin(stage2, sections, entry):
    """A VBIN like build_autorun's: header, table, then 4-aligned data.

    Section zero is destination zero (stage2 runs where it lands); a
    destination below 0x40000000 is a pool offset (pass 2); anything else is
    a firmware word (pass 1, journaled on fp L).
    """
    table, data = b'', b''
    for dest, blob in sections:
        pad = -len(blob) % 4
        table += struct.pack('<II', dest, len(blob))
        data += blob + b'\0' * pad
    header = struct.pack('<4sIII', b'VBIN', len(sections), entry, len(data))
    return header + table + data


class Stage2Chain:
    """Drives the real assembled fp L loader and stage2 under Unicorn."""

    def __init__(self, test, loader_words, binfile, have_file=True,
                 journal_refused=False):
        self.t, self.bin, self.have_file = test, binfile, have_file
        self.journal_refused = journal_refused
        self.stock = CAMERA.verify_main(IMAGE)
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        mu.mem_map(0xC0000000, 0x03000000)               # the image
        mu.mem_write(0xC0000000, self.stock[:0x03000000])
        mu.mem_map(0xC3000000, 0x01000000)               # BSS: zero, as at boot
        mu.mem_map(0x40000000, 0x10000000)               # the USER heap window:
        #                                                   staging, journal, pool,
        #                                                   stack, entry and DONE
        mu.mem_write(ENTRY, struct.pack('<I', 0xE12FFF1E))  # bx lr: the stub entry
        mu.mem_write(DIR_ENTRY, b''.join(struct.pack('<I', w)
                                         for w in loader_words))
        self.by_addr = {v: k for k, v in FW.items()}     # address -> name
        self.calls, self.registered = [], []
        self.pool_published = None
        self.fw_stock_at_poff = None
        mu.hook_add(UC_HOOK_CODE, self._hook)

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
        if addr == ENTRY:
            self.calls.append('ENTRY')
            # The payload's entry allocates and publishes its pool; publish
            # one so pass 2 has something to place against.
            mu.mem_write(FRAMEBUF, struct.pack('<I', POOL))
            self.pool_published = True
            return self._ret(0)
        name = self.by_addr.get(addr)
        if name is None:
            return
        self.calls.append(name)
        r0, r1, r2, r3 = (self.r(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                              UC_ARM_REG_R2, UC_ARM_REG_R3))
        if name == 'H_ADDR':
            self._ret(STAGING)
        elif name == 'H_FREE':
            self._ret(0)
        elif name == 'F_MGR':
            self._ret(0x12340000)
        elif name == 'F_VOL':
            self.t.assertEqual((r0, r1), (0x12340000, 0))
            self._ret(1)                              # the card volume
        elif name == 'F_CTOR':
            self.t.assertEqual(r1, 1)
            self._ret(r0)
        elif name == 'F_OPEN':
            self.t.assertEqual(self.cstr(r1), BIN_PATH)
            self._ret(1 if self.have_file else 0)
        elif name == 'F_READ':
            # The loader asks for MAXLEN (0xF000); the stub hands back the
            # whole file wherever it fits, like the real reader would.
            mu.mem_write(r1, self.bin[:r2])
            self._ret(len(self.bin[:r2]))
        elif name == 'F_CLOSE':
            self._ret(0)
        elif name == 'F_DTOR':
            self.t.assertEqual(r1, 2)
            self._ret(0)
        elif name == 'MEM_HEAP':
            self.t.assertEqual(r0, 0)                 # class 0, USER
            self._ret(0x44000000)                     # a channel handle
        elif name == 'MEM_GET':
            self.t.assertEqual((r1, r3), (r1, 0))
            self.t.assertEqual(self.word(self.r(UC_ARM_REG_SP)), 0)
            self._ret(0 if self.journal_refused else JOURNAL)
        elif name == 'POFF_MGR':
            self._ret(0xC3000100)
        elif name == 'POFF_ADD':
            self.t.assertEqual((r0, r2), (0xC3000100, len(self.registered)))
            if self.fw_stock_at_poff is None:
                # Nothing patched yet: every registration precedes placement.
                self.fw_stock_at_poff = self.word(FW_DEST)
                self.t.assertEqual(self.fw_stock_at_poff,
                                  struct.unpack('<I', self.stock[
                                      FW_DEST - 0xC0000000:FW_DEST - 0xC0000000 + 4])[0])
            self.registered.append((r1, r2))
            self._ret(1)
        else:
            self._ret(0)                              # DCACHE, ICACHE, TICK

    def call_loader(self, r0=0xC0BAC000, r1=0, sp=STACK - 0x1004):
        """Dispatch like the shell would `dir`: (ctx, argc, argv)."""
        mu = self.mu
        mu.reg_write(UC_ARM_REG_SP, sp)               # 4 off, like the caller
        mu.reg_write(UC_ARM_REG_R0, r0)
        mu.reg_write(UC_ARM_REG_R1, r1)
        mu.reg_write(UC_ARM_REG_LR, DONE)
        mu.emu_start(DIR_ENTRY, DONE, count=5_000_000)
        return self.r(UC_ARM_REG_R0), self.r(UC_ARM_REG_SP)

    def sections(self):
        n = struct.unpack_from('<I', self.bin, 4)[0]
        return [struct.unpack_from('<II', self.bin, 16 + 8 * i) for i in range(n)]

    def fw_sections(self):
        """Every section pass 1 must journal: on fp L that is every firmware
        destination -- the cave exclusion is empty by policy."""
        return [(d, (n + 3) & ~3) for d, n in self.sections() if d >= 0x40000000]

    def journal_entries(self):
        block = JOURNAL
        j = self.word(block + 8)
        if j == 0:                       # no journal block was ever allocated
            return []
        got = []
        while self.word(j):
            a, n = self.word(j), self.word(j + 4)
            got.append((a, n, bytes(self.mu.mem_read(j + 8, n))))
            j += 8 + n
        return got


@unittest.skipIf(Uc is None or not IMAGE.exists(),
                 'needs unicorn and the private fp L 3.02 MAIN image')
class FplStage2ChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = CAMERA.verify_main(IMAGE)
        # The real loader at the dir-body placement the trial proved, and the
        # real stage2 with the fp L profile: journal + registrations only,
        # no cave arena, no profiling word, no store, no hook, no banner.
        cls.loader_words = struct.unpack(
            f'<{len(assemble(HERE / "asm/loader.S", fpl_defines(DIR_ENTRY))) // 4}I',
            assemble(HERE / 'asm/loader.S', fpl_defines(DIR_ENTRY)))
        cls.stage2 = assemble(HERE / 'asm/stage2.S',
                              fpl_defines(DIR_ENTRY, ['LH_RESTORE=1']))

    def shared_publish_oracle(self):
        """Run the SAME structural check every fp card build runs, from
        build_autorun.py without importing it (its module level is a script:
        it parses argv and emits a card, so give it a plain fp loader build)."""
        with tempfile.TemporaryDirectory() as tmp:
            script = (
                'import sys, pathlib, json;'
                'sys.argv = ["build_autorun.py", "--loader",'
                ' "--no-four-box-bar", "--out",'
                f' {str(pathlib.Path(tmp) / "AutoRun.txt")!r}];'
                'sys.path.insert(0, ".");'
                'import build_autorun;'
                'from armasm import assemble;'
                f'defines = json.loads({json.dumps(fpl_defines(DIR_ENTRY, ["LH_RESTORE=1"]))!r});'
                'code = assemble(pathlib.Path("asm/stage2.S"), defines);'
                'build_autorun.verify_stage2_cache_publish(code);'
                'print("ORACLE OK")')
            r = subprocess.run([sys.executable, '-B', '-c', script],
                              capture_output=True, text=True, cwd=HERE)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('ORACLE OK', r.stdout)

    def chain(self, **kw):
        stage2 = self.stage2
        sections = [(0, stage2),
                    (FW_DEST, b'\x11\x22\x33\x44' * 4),
                    (IMU_RANGE_DEST, b'\xAA' * 8),
                    (0x40, b'\x55' * 12)]      # a pool offset: pass 2
        binfile = build_bin(stage2, sections, ENTRY)
        return Stage2Chain(self, self.loader_words, binfile, **kw)

    def test_stage2_passes_the_shared_cache_publish_oracle(self):
        # The same structural check every fp card build runs, on the fp L
        # stage2: exactly the two cache routines, D before I, published
        # before the entry and again after the pass that follows it.
        self.shared_publish_oracle()

    def test_chain_loads_journals_registers_calls_entry_and_returns(self):
        cam = self.chain()
        r0, sp = cam.call_loader()
        self.assertEqual((r0, sp), (1, STACK - 0x1004))
        self.assertEqual(cam.calls, [
            'H_GET', 'H_ADDR', 'F_MGR', 'F_VOL', 'F_CTOR', 'F_OPEN',
            'F_READ', 'F_CLOSE', 'F_DTOR',
            'DCACHE', 'ICACHE',                    # the loader publishes stage2
            'MEM_HEAP', 'MEM_GET',                 # the journal block
            'DCACHE', 'ICACHE',                    # lh_setup publishes its routine
            'POFF_MGR', 'POFF_ADD', 'POFF_MGR', 'POFF_ADD',
            'DCACHE', 'ICACHE',                    # pass 1 published
            'ENTRY',
            'DCACHE', 'ICACHE',                    # pass 2 published
            'H_FREE'])                             # the loader frees staging
        self.assertEqual(cam.pool_published, True)
        self.assertEqual([f for _, f in cam.registered], [0, 1])  # both lists
        self.assertEqual(len({o for o, _ in cam.registered}), 1)
        # The dir slot was never touched: the load ran through it as-is.
        self.assertEqual(cam.word(DIR_SLOT), DIR_ENTRY)

    def test_journal_holds_stock_words_and_the_exclusion_is_empty(self):
        cam = self.chain()
        cam.call_loader()
        got = cam.journal_entries()
        want = cam.fw_sections()
        self.assertEqual([(a, n) for a, n, _ in got], want)
        for a, n, orig in got:
            self.assertEqual(orig, cam.stock[a - 0xC0000000:a - 0xC0000000 + n],
                             hex(a))
        # The destination inside the fp structural cave range is journaled
        # too: on fp that range is excluded (hook bodies live there); on fp L
        # it is IMU-owned image space and nothing is exempt.
        self.assertIn((IMU_RANGE_DEST, 8), [(a, n) for a, n, _ in got])
        # Pass 2 placed the pool section against the published pool.
        self.assertEqual(cam.word(POOL + 0x40), 0x55555555)
        self.assertEqual(bytes(cam.mu.mem_read(POOL + 0x40, 12)), b'\x55' * 12)

    def test_power_off_routine_restores_every_patched_word(self):
        cam = self.chain()
        cam.call_loader()
        want = cam.fw_sections()
        self.assertTrue(any(bytes(cam.mu.mem_read(d, n)) !=
                            cam.stock[d - 0xC0000000:d - 0xC0000000 + n]
                            for d, n in want), 'nothing was patched to begin with')
        block = JOURNAL
        routine = cam.word(block + 4)
        self.assertEqual(cam.word(block), block - 8)      # the vtable pointer
        for _ in range(2):                               # once per list
            cam.mu.reg_write(UC_ARM_REG_SP, STACK - 0x1004)
            cam.mu.reg_write(UC_ARM_REG_R0, block)
            cam.mu.reg_write(UC_ARM_REG_R1, 4)
            cam.mu.reg_write(UC_ARM_REG_LR, DONE)
            cam.mu.emu_start(routine, DONE, count=1_000_000)
            self.assertEqual(cam.r(UC_ARM_REG_PC), DONE)
        for d, n in want:
            self.assertEqual(bytes(cam.mu.mem_read(d, n)),
                             cam.stock[d - 0xC0000000:d - 0xC0000000 + n], hex(d))

    def test_missing_file_returns_with_no_journal_or_registration(self):
        cam = self.chain(have_file=False)
        r0, _ = cam.call_loader()
        self.assertEqual(r0, 0)
        self.assertEqual(cam.calls, ['H_GET', 'H_ADDR', 'F_MGR', 'F_VOL',
                                     'F_CTOR', 'F_OPEN', 'F_DTOR', 'H_FREE'])
        self.assertEqual(cam.registered, [])
        self.assertEqual(cam.journal_entries(), [])
        self.assertNotIn('ENTRY', cam.calls)
        self.assertIsNone(cam.pool_published)

    def test_journal_refusal_stands_down_completely(self):
        # lh_setup's own failure gate: a refused journal block must leave the
        # camera stock -- no section placed, no registration, no entry -- and
        # the loader still completes and hands its staging back.
        cam = self.chain(journal_refused=True)
        r0, _ = cam.call_loader()
        self.assertEqual(r0, 1)                 # the stage2 did run, and refused
        self.assertEqual(cam.calls, [
            'H_GET', 'H_ADDR', 'F_MGR', 'F_VOL', 'F_CTOR', 'F_OPEN',
            'F_READ', 'F_CLOSE', 'F_DTOR',
            'DCACHE', 'ICACHE',                # the loader publishes stage2
            'MEM_HEAP', 'MEM_GET',             # refused: no journal, no hook
            'H_FREE'])                        # the loader still frees staging
        self.assertEqual(cam.registered, [])
        self.assertNotIn('ENTRY', cam.calls)
        self.assertIsNone(cam.pool_published)
        for d, n in [(FW_DEST, 16), (IMU_RANGE_DEST, 8)]:
            self.assertEqual(bytes(cam.mu.mem_read(d, n)),
                             cam.stock[d - 0xC0000000:d - 0xC0000000 + n],
                             f'{d:#x} was placed despite the refusal')


if __name__ == '__main__':
    unittest.main()