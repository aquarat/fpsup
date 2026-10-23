"""Offline diagnostic VBIN: real loader/stage2/entries and retained kernels.

File APIs, loader/worker allocations, journal and worker task backend reuse the
shell-card fixture. Retained allocation and task kernels use the native fixture.
No AutoRun, public builder switch, transport or card write is provided here.
"""
import hashlib
import struct
import unittest
from unittest.mock import patch

import armasm
import card_build as card
import test_fpl_shell_card as shell
import test_fpl_retained_launcher as launcher
from unicorn import UC_MEM_WRITE
from unicorn import arm_const as ar

base = launcher.base
SENTINEL = b'PASS'
PASS2 = 0x9000


def composition(built):
    art = card.artifact()
    defs = list(card.CAMERA.loader_defines()) + ['FPSUP_PONG_ACK=1']
    worker = armasm.assemble(card.HERE/'camera/worker.S', defs)
    ws = armasm.symbols(card.HERE/'camera/worker.S', defs)
    assert hashlib.sha256(worker[ws['wbody']:ws['wbody_end']]).hexdigest() == (
        'e2b94aeb67938dbb05f581ca6f8ec5aff1e84dfe7dd34de11a1b76e0c7f2b342')
    # A real, returning ARM entry is a continuation witness. It publishes no pool.
    witness = struct.pack('<I', 0xE12FFF1E)  # bx lr
    sections = [(0, art['stage2']), (0, worker), (0, built[0]),
                (0, witness), (PASS2, SENTINEL)]
    binary, entry, sections = card.build_vbin(sections, [(1, 0), (2, 0), (3, 0)])
    offsets, cursor = [], 16+8*len(sections)
    for _, data in sections:
        offsets.append(cursor)
        cursor += len(data)
    assert len(binary) <= card.READ_CAP
    return art, worker, ws, binary, entry, offsets


class BootMachine(launcher.Machine):
    booting = False

    def prepare(self, test, fixture):
        art, self.worker, self.ws, binary, entry, offsets = fixture
        # Reuse the shell-card mock's disjoint loader/journal/worker blocks.
        for start, length in ((shell.STAGING, 0x10000), (shell.JOURNAL_A, 0x10000),
                              (shell.POOL & ~4095, 0x102000),
                              (shell.CODE & ~4095, 0x4000),
                              (0xC3000000, 0x1000000)):
            cursor = start
            for lo, hi, _ in sorted(self.m.mem_regions()):
                if hi < cursor or lo >= start+length:
                    continue
                if lo > cursor:
                    self.m.mem_map(cursor, lo-cursor)
                cursor = max(cursor, hi+1)
            if cursor < start+length:
                self.m.mem_map(cursor, start+length-cursor)
        self.m.mem_write(card.DIR_ENTRY, art['loader'])
        self.filebase = shell.STAGING+0x1000
        self.stage = self.filebase+offsets[2]
        self.wrapper_stage = self.stage+self.ls['embedded_image']
        self.targets = {self.filebase+offsets[0]: 'stage2',
                        self.filebase+entry: 'entries',
                        self.filebase+offsets[1]: 'worker',
                        self.stage: 'launcher',
                        self.filebase+offsets[3]: 'continuation'}
        self.code = launcher.launch.runtime.initialize(self.artifact, self.wrapper_stage, self.owner)
        self.trace, self.in_launcher, self.freed = [], False, False
        s2defs = list(card.CAMERA.loader_defines()) + [
            'LH_RESTORE=1', f'LOADER_BASE={card.DIR_ENTRY:#010X}']
        ss = armasm.symbols(card.HERE/'asm/stage2.S', s2defs)
        self.pass_pc = self.filebase+offsets[0]+ss['s2_pass']
        self.passes = []
        bridge = self.bridge = shell.ShellTrial.__new__(shell.ShellTrial)
        bridge.t, bridge.mu, bridge.bin = test, self.m, binary
        bridge.have_file, bridge.current = True, -1
        bridge.by_addr = {v: k for k, v in shell.FW.items()}
        bridge.timeline, bridge.allocations, bridge.registered, bridge.tasks = [], [], [], []
        self.booting = True

    def memory(self, m, access, address, size, value, unused):
        if getattr(self, 'freed', False):
            assert not shell.STAGING <= address < shell.STAGING+0x10000, 'freed loader reference'
        if self.booting:
            if access == UC_MEM_WRITE and address == shell.POOL+PASS2:
                assert self.trace[-1] == 'continuation', 'pass 2 before entry chain returned'
                self.trace.append('pass2-write')
            if not self.in_launcher:
                return
        super().memory(m, access, address, size, value, unused)

    def execute(self, m, pc, size, unused):
        if getattr(self, 'freed', False):
            assert not shell.STAGING <= pc < shell.STAGING+0x10000, 'freed loader execution'
        if not self.booting:
            return super().execute(m, pc, size, unused)
        if self.in_launcher and pc == self.launch_return:
            self.in_launcher = False
        if pc == self.pass_pc:
            self.passes.append(m.reg_read(ar.UC_ARM_REG_R8))
        target = self.targets.get(pc)
        if target:
            self.trace.append(target)
            if target == 'stage2':
                assert self.reg(0) == self.filebase
            if target != 'stage2':
                assert self.reg(0) == pc, 'resolved entry r0'
                assert m.reg_read(ar.UC_ARM_REG_SP) % 8 == 0
            if target == 'entries':
                assert [n for _, n in self.bridge.timeline][-2:] == ['DCACHE', 'ICACHE']
            if target == 'launcher':
                self.in_launcher = True
                self.launch_return = m.reg_read(ar.UC_ARM_REG_LR)
                self.fullcache, self.cache = [], []
            if target == 'continuation':
                self.in_launcher = False
                self.entry_returned = True
                self.result = bytes(m.mem_read(self.stage+self.ls['result'], 32))
                assert bytes(m.mem_read(shell.POOL+PASS2, 4)) == bytes(4)
        if self.in_launcher:
            return super().execute(m, pc, size, unused)
        if pc == shell.FW['H_FREE']:
            assert self.reg(0) == card.POOL_DESC
            assert self.trace[-1] == 'pass2-write'
            assert [n for _, n in self.bridge.timeline][-2:] == ['DCACHE', 'ICACHE']
            self.trace.append('staging-free')
            self.freed = True
            m.mem_write(shell.STAGING, b'\xFE'*0x10000)
        self.bridge._hook(m, pc, size, unused)

    def boot(self, alignment):
        sp = base.HOST_STACK-alignment
        self.m.reg_write(ar.UC_ARM_REG_CPSR, 0x13)
        self.m.reg_write(ar.UC_ARM_REG_SP, sp)
        self.m.reg_write(ar.UC_ARM_REG_LR, base.STOP)
        self.m.emu_start(card.DIR_ENTRY, base.STOP, count=3000000)
        assert self.m.reg_read(ar.UC_ARM_REG_PC) == base.STOP
        assert self.m.reg_read(ar.UC_ARM_REG_SP) == sp
        self.booting = False


class RetainedBoot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        launcher.Launcher.setUpClass()
        cls.fixture = composition(launcher.Launcher.built)

    def run_case(self, refusal=False):
        factory = launcher.Launcher()
        for owner in launcher.OWNERS:
            for alignment in (0, 4):
                with self.subTest(owner=hex(owner), alignment=alignment), \
                        patch.object(launcher, 'Machine', BootMachine), \
                        factory.machine(owner, refusal=refusal) as m:
                    m.prepare(self, self.fixture)
                    m.boot(alignment)
                    self.assertEqual(m.trace, ['stage2', 'entries', 'worker', 'launcher',
                                               'continuation', 'pass2-write', 'staging-free'])
                    self.assertEqual(m.passes, [1, 0])
                    self.assertEqual(m.bridge.allocations[0],
                                     (card.POOL_DESC, 0x10000, shell.STAGING))
                    self.assertEqual(bytes(m.m.mem_read(shell.POOL+PASS2, 4)), SENTINEL)
                    self.assertEqual(len(m.bridge.tasks), 1)
                    self.assertEqual(len(m.bridge.registered), 2)
                    self.assertEqual(bytes(m.m.mem_read(shell.CODE, self.ws_length())),
                                     m.worker[m.ws['wbody']:m.ws['wbody_end']])
                    self.assertEqual(m.get_calls, 1)
                    self.assertNotIn(base.ATTACH, m.events)
                    self.assertEqual(m.capture_calls, 0)
                    self.assertEqual(struct.unpack('<I', m.result[:4])[0], 3 if refusal else 6)
                    if refusal:
                        self.assertFalse(m.events or m.launch_writes)
                    else:
                        self.assertEqual(m.fullcache, [card.DCACHE, card.ICACHE]*2)
                        self.assertEqual(bytes(m.m.mem_read(owner+0x400, 32)), m.result)
                        self.assertEqual(m.events.count(base.CREATE), 1)
                        self.assertEqual(m.observe(), 7)
                        # Independent external action, only AFTER loader return/free.
                        m.call('activate')
                        m.run_task()
                        self.assertEqual(m.observe(), 15)
                        m.retained_readback()

    def ws_length(self):
        ws = self.fixture[2]
        return ws['wbody_end']-ws['wbody']

    def test_actual_chain_created_unattached_survives_staging_release(self):
        self.run_case()

    def test_refusal_returns_and_continues_chain_and_pass2(self):
        self.run_case(refusal=True)


if __name__ == '__main__':
    unittest.main()
