"""Offline exact-candidate rollback; no camera/backend/allocator calls.

Real forward-candidate and reviewed old worker instructions, simulated firmware
USB/CRC/cache services. Completion is an actual old-worker reply_done + frame,
not a trampoline status. Ownership of the two retained mappings is a precondition
established separately by test_fpl_allocated_handoff's real-allocator proof.
"""
import hashlib
from pathlib import Path
import struct
import unittest
import zlib

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
from armasm import assemble, symbols
from firmware import get_camera
import fpl_swapworker as sw
import test_fpl_worker_dispatch as d
from test_fpl_allocated_handoff import candidate, COOKIE

OLD, NEW = 0x46000000, 0x46100000
POOL, STACK = d.POOL, d.STACK + 0x8000
STUB, STATUS = POOL + 0x10000, POOL + 0x10400
EXPECTED_NEW, EXPECTED_OLD = POOL + 0x11000, POOL + 0x13000
REQUEST = 0xAD529731
ASM = Path(__file__).parent / 'asm/fpl_allocated_reverse_prototype.S'
CANDIDATE_SHA = 'bb7919787b96abf8d6ac0828d08f8ea6ea2a815880d742c146e4b0e81eeffe5f'


class ReverseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body, cls.labels = candidate()
        assert (len(cls.body), hashlib.sha256(cls.body).hexdigest()) == (3884, CANDIDATE_SHA)
        assert {k: cls.labels[k] for k in ('serve', 'next_round', 'no_swap',
                                          'guard_pins', 'handoff_record')} == dict(
            serve=120, next_round=200, no_swap=316, guard_pins=3844, handoff_record=3852)
        labels = symbols(d.SOURCE, get_camera('fp-l-3.02').loader_defines())
        cls.old_labels = {k: v - labels['wbody'] for k, v in labels.items()}

    def trial(self, *, fail=None, mutation=None, pause=None, fault=0, pong=True, command=9):
        old = sw.reviewed_body(pong)
        image = bytearray(self.body)
        record, pins = self.labels['handoff_record'], self.labels['guard_pins']
        struct.pack_into('<8I', image, record, NEW, 0, NEW, len(image), COOKIE, OLD, 2, 0)
        expected = bytes(image)
        # Live mutable pins differ from the upload template: neither is identity.
        struct.pack_into('<2I', image, pins, 0x12345670, 0x76543210)
        initial_image = bytes(image)
        defs = dict(POOL=POOL, OLD=OLD, NEW=NEW, STUB=STUB, STATUS=STATUS,
                    REQUEST=REQUEST, TOKEN=COOKIE, PINS=pins, RECORD=record,
                    EXPECTED_NEW=EXPECTED_NEW, EXPECTED_OLD=EXPECTED_OLD)
        args = [f'{k}={v}' for k, v in defs.items()]
        labels = symbols(ASM, args)
        code = bytearray(assemble(ASM, args))
        if mutation in ('unwind', 'publication', 'old_mismatch'):
            label = {'publication': 'publish'}.get(mutation, mutation)
            struct.pack_into('<I', code, labels[label], 0xE1A00000)
        if mutation == 'cache':
            code[:] = code.replace(struct.pack('<I', sw.gf.ICACHE), struct.pack('<I', sw.gf.DCACHE))
        self.assertLess(len(code), 1024)
        mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        regions = [(POOL, 0x100000), (OLD, 0x10000), (NEW, 0x10000),
                   (d.STACK, 0x10000), (d.OUT_TRB, 0x1000)]
        for base, size in regions:
            mu.mem_map(base, size)
        pages = {v & ~0xFFF for v in d.FW.values()}
        pages |= {a & ~0xFFF for a in (d.PUBLICATION, d.SHELL_CTX, d.TRB_TABLE,
                    d.OUT_BUSY, 0x2100C720, 0xC3077794, 0xC31E1D6C, 0xC3032A92,
                    0xC001D740, 0xC001D7A0)}
        for page in pages:
            mu.mem_map(page, 0x1000)
        def put(a, *values):
            mu.mem_write(a, struct.pack('<' + 'I' * len(values), *values))
        def get(a):
            return struct.unpack('<I', mu.mem_read(a, 4))[0]
        def ret(value=0):
            for reg in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12):
                mu.reg_write(reg, 0xBAD00000)
            mu.reg_write(UC_ARM_REG_R0, value)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))
        mu.mem_write(OLD, old)
        mu.mem_write(NEW, initial_image)
        mu.mem_write(STUB, bytes(code))
        mu.mem_write(EXPECTED_NEW, expected)
        mu.mem_write(EXPECTED_OLD, old)
        put(d.PUBLICATION, POOL, 0x100000, NEW)
        put(d.TRB_TABLE, d.OUT_TRB, d.IN_TRB)
        put(d.STATE, 0x4C485356, 79, fault, 19)
        put(d.STATE + 0x20, 7, 11)
        put(STATUS, REQUEST, 0)
        put(0x2100C720, 0x24)
        put(0x2100C704, 0x80000000)
        put(0xC3077794, 5)
        mu.mem_write(0xC31E1D6C, b'\x01')
        mu.mem_write(0xC3032A92, b'\x01')
        windows = struct.pack('<24I', *range(1, 25))
        upload = b'\xA5' * 16
        events, replies, pubwrites = [], [], []
        armed = False
        stopped = None
        def hook(uc, a, size, _):
            nonlocal armed, stopped
            if 'old-serve' in events and STUB <= a < STUB + len(code):
                self.fail('old worker returned into scratch after handoff')
            if a in (0xC001D740, 0xC001D7A0, 0xC001D7F0):
                self.fail('reverse must never allocate, query or free a descriptor')
            if a == NEW + self.labels['next_round'] and not armed:
                # Actual candidate serve frame exists; simulate a queued request
                # at the next boundary of a responsive candidate.
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK - 32)
                armed = True
                put(d.STATE + 0xC0, STUB)
                put(d.STATE + 0x80, 0x50415753)
                uc.mem_write(POOL + 0x6A00, windows)
                uc.mem_write(POOL + 0x6900, upload)
            if a == STUB:
                self.assertEqual(get(d.STATE + 0x80), 0)
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK - 32)
                if fail == 'publication':
                    put(d.PUBLICATION + 8, OLD)
                elif fail == 'request':
                    put(STATUS, REQUEST + 1)
                elif fail == 'old':
                    put(EXPECTED_OLD + 100, get(EXPECTED_OLD + 100) ^ 1)
                elif isinstance(fail, int):
                    # Corrupt actual identity/state, outside executing instructions.
                    put(NEW + fail, get(NEW + fail) ^ 1)
            checkpoints = dict(prepublication=STUB + labels['publish'],
                               postpublication=STUB + labels['publish'] + 4,
                               entering_old=OLD + 120)
            if pause and a == checkpoints[pause]:
                stopped = pause
                uc.emu_stop()
                return
            if a == NEW + self.labels['no_swap']:
                self.assertTrue(fail is not None, 'unexpected reverse abort')
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK - 32)
                self.assertEqual(uc.reg_read(UC_ARM_REG_R4), d.STATE)
                self.assertEqual(get(d.STATE + 8), fault)
                self.assertEqual(bytes(uc.mem_read(POOL + 0x6A00, 96)), windows)
                self.assertEqual(bytes(uc.mem_read(POOL + 0x6900, 16)), upload)
                stopped = 'candidate-resumed'
                uc.emu_stop()
                return
            if a == OLD + 120:
                self.assertIsNone(fail, 'mismatch accepted by reverse verifier')
                self.assertEqual(events, ['D', 'I'])
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK)
                self.assertEqual(uc.reg_read(UC_ARM_REG_LR), d.STACK + 0xF000)
                self.assertEqual(get(d.PUBLICATION + 8), OLD)
                self.assertEqual(get(d.STATE + 8), fault)
                events.append('old-serve')
            if a == OLD + self.old_labels['next_round']:
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP), STACK - 32)
                self.assertEqual(bytes(uc.mem_read(POOL + 0x6A00, 96)), bytes(96))
                self.assertEqual(bytes(uc.mem_read(POOL + 0x6900, 16)), bytes(16))
                if get(d.STATE + 0x20) == 8:
                    stopped = 'old-completed'
                    uc.emu_stop()
                    return
                self.assertEqual(get(d.STATE + 0x20), 7)
                self.assertEqual(get(d.STATE + 8), fault)
            if a in (sw.gf.DCACHE, sw.gf.ICACHE):
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP) % 8, 0)
                events.append('D' if a == sw.gf.DCACHE else 'I')
                ret()
                return
            if a in d.FW.values():
                self.assertEqual(uc.reg_read(UC_ARM_REG_SP) % 8, 0)
                r0, r1 = uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1)
                self.assertIn('old-serve', events)
                if a == d.FW['END']:
                    self.assertEqual((fault, r0), (1, 1))
                    events.append('END')
                    ret()
                elif a == d.FW['START']:
                    if r0 == 2:
                        events.append('OUT')
                        self.assertEqual(get(d.OUT_TRB), POOL - 0x40000000)
                    else:
                        self.assertEqual(r0, 5)
                        self.assertEqual(get(d.IN_TRB + 8), 64)
                        replies.append(bytes(uc.mem_read(get(d.IN_TRB) + 0x40000000, 64)))
                    ret()
                elif a == d.FW['WAIT']:
                    self.assertEqual(r1, 20)
                    trb = d.OUT_TRB if r0 == 1 else d.IN_TRB
                    if r0 == 1:
                        uc.mem_write(POOL, d.frame(command))
                    else:
                        self.assertEqual(r0, 2)
                    put(trb + 12, get(trb + 12) & ~1)
                    ret()
                elif a == d.FW['CRC']:
                    ret(zlib.crc32(uc.mem_read(r0, r1)))
                else:
                    self.fail(f'unexpected firmware call {a:#x}')
        def store(uc, access, a, size, value, _):
            self.assertFalse(OLD <= a < OLD + len(old), 'retained old image written')
            if NEW <= a < NEW + len(image):
                self.assertEqual((a, size, value), (NEW + record + 24, 4, 2))
            if a == d.PUBLICATION + 8:
                self.assertEqual((size, value, get(a)), (4, OLD, NEW))
                self.assertEqual(events, ['D', 'I'])
                pubwrites.append(value)
        mu.hook_add(UC_HOOK_CODE, hook)
        mu.hook_add(UC_HOOK_MEM_WRITE, store)
        mu.reg_write(UC_ARM_REG_SP, STACK)
        mu.reg_write(UC_ARM_REG_LR, d.STACK + 0xF000)
        mu.emu_start(NEW + self.labels['serve'], 0, count=150000)
        self.assertIsNotNone(stopped, 'instruction budget exhausted')
        self.assertEqual(bytes(mu.mem_read(OLD, len(old))), old)
        self.assertEqual(get(d.STATE + 4), 79)
        self.assertEqual(get(d.STATE + 0x24), 11)
        self.assertEqual(get(d.PUBLICATION), POOL)
        self.assertEqual(get(d.PUBLICATION + 4), 0x100000)
        if pause:
            self.assertEqual(stopped, pause)
            self.assertEqual(get(d.STATE + 0x20), 7)
            self.assertEqual(replies, [])
            self.assertEqual(get(d.PUBLICATION + 8), NEW if pause == 'prepublication' else OLD)
            self.assertEqual(get(STATUS + 4), OLD if pause == 'entering_old' else 0)
            # Original candidate acknowledgement stays 2 in ALL these states.
            self.assertEqual(get(NEW + record + 24), 2)
        elif fail is not None:
            self.assertEqual(stopped, 'candidate-resumed')
            self.assertEqual((pubwrites, replies), ([], []))
            self.assertEqual(get(d.STATE + 0x20), 7)
            self.assertEqual(get(d.PUBLICATION + 8), OLD if fail == 'publication' else NEW)
        else:
            self.assertEqual(stopped, 'old-completed')
            self.assertEqual(pubwrites, [OLD])
            self.assertEqual(get(d.STATE + 0x20), 8)
            self.assertEqual(get(d.STATE + 8), 0)  # old reply_done, not trampoline
            self.assertEqual(events, ['D', 'I', 'old-serve'] + (['END'] if fault else []) + ['OUT'])
            payload = b''
            for i, data in enumerate(replies):
                magic, version, cmd, flags, seq, length, status, crc = struct.unpack('<4sBBHIHHI', data[:20])
                self.assertEqual((magic, version, cmd, seq, status), (b'FPSH', 1, command, d.SEQ, 0))
                self.assertEqual(flags, int(i < len(replies) - 1))
                self.assertEqual(crc, zlib.crc32(data[:16] + bytes(4) + data[20:]))
                payload += data[20:20 + length]
            self.assertEqual(payload, struct.pack('<4I', 0x314D454D, 0xFFFC00, POOL, 0x100000) + bytes(96)
                             if command == 9 else (b'PONG' if pong else b''))
            self.assertEqual(bytes(mu.mem_read(NEW, len(image))), initial_image)
        return stopped

    def test_old_worker_completes_mcaps_and_ping_for_both_reviewed_images(self):
        for pong in (False, True):
            for command in (9, 1):
                with self.subTest(pong=pong, command=command):
                    self.trial(pong=pong, command=command)

    def test_fault_is_preserved_until_old_worker_cleanup_and_reply(self):
        self.trial(fault=1)

    def test_mismatches_resume_exact_candidate_no_swap(self):
        record, pins = self.labels['handoff_record'], self.labels['guard_pins']
        for fail in ('publication', 'request', 'old', 100, pins - 4,
                     record, record + 4, record + 8, record + 12,
                     record + 16, record + 20, record + 24, record + 28):
            with self.subTest(fail=fail):
                self.trial(fail=fail, fault=1)

    def test_interrupted_reverse_is_not_old_operation_completion(self):
        for pause in ('prepublication', 'postpublication', 'entering_old'):
            with self.subTest(pause=pause):
                self.trial(pause=pause, fault=1)

    def test_mutations_are_detected(self):
        for mutation in ('unwind', 'publication', 'cache', 'old_mismatch'):
            with self.subTest(mutation=mutation), self.assertRaises(AssertionError):
                self.trial(mutation=mutation, fail='old' if mutation == 'old_mismatch' else None)


if __name__ == '__main__':
    unittest.main()
