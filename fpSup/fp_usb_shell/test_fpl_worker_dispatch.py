"""Offline fp L dispatch tests; no firmware image or camera is required.

Run from fp_usb_shell: python3 -B -m unittest -v test_fpl_worker_dispatch

Execute the current worker's relocated wbody from got_command until next_round,
including capture, frame/range checks, reply fragmentation, arm_in[_block], and
wait_done. Only firmware services are mocked, at independent fp L 3.02 literal
addresses. By default POOL and POOL+0x40000000 have independent backing RAM,
as the fallback MMU mapping
in docs/FPL_ALLOCATOR_AUDIT.md section 3 implies for these virtual addresses.
That alternate model is conditional: the audit does not establish the live MMU
table. coherent_alias=True retains the alternative shared-memory model.
Both models assume the DMA bus address +0x40000000 reaches POOL; neither
emulates caches, DWC3, IRQ delivery, or firmware service internals.
The callback mock supports literal strings only, enough to run the real capture.
All three TRB arming routines are checked for public-call stack alignment,
including arm_out's fault cleanup. This is ABI evidence, not a live diagnosis.
"""
import ctypes
import hashlib
from pathlib import Path
import struct
import unittest
import zlib

from armasm import assemble, symbols
from firmware import get_camera

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1,
                                   UC_ARM_REG_R2, UC_ARM_REG_R3,
                                   UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                                   UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                                   UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12,
                                   UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)
except ImportError:
    Uc = None

SOURCE = Path(__file__).resolve().parent / 'camera/worker.S'
POOL, POOL_SIZE, CODE, STACK = 0x45000000, 0x100000, 0x46000000, 0x47000000
PUBLICATION, SHELL_CTX = 0xC37588BC, 0xC3757744
TRB_TABLE, OUT_BUSY = 0xC31E1668, 0xC31E1D74
OUT_TRB, IN_TRB = 0x48000000, 0x48000010
STATE, CAP_LEN, CAP_PTR = POOL + 0x1000, POOL + 0x1040, POOL + 0x1100
FW = dict(START=0xC01E3400, END=0xC01E35C8, WAIT=0xC01E1700, DELAY=0xC01F5244,
          SHINIT=0xC03D9C28, SHPUSH=0xC03D9CD8, SHRUN=0xC03D9E38,
          SHPOP=0xC03D9D38, VSNPRINT=0xC0013F48, CRC=0xC06AC4D8,
          DCACHE=0xC000E91C)
SEQ = 0x193A57CD


def frame(command, payload=b'', flags=0):
    result = bytearray(struct.pack('<4sBBHIHHI', b'FPSH', 1, command,
                                   flags, SEQ, len(payload), 0, 0))
    result += payload.ljust(44, b'\0')
    assert len(result) == 64
    struct.pack_into('<I', result, 16, zlib.crc32(result))
    return bytes(result)


class Dispatch:
    def __init__(self, test, blob, labels, request, output=b'', start_result=0,
                 coherent_alias=False):
        self.t, self.labels = test, labels
        self.output, self.start_result = output, start_result
        self.calls, self.transfers, self.lines, self.alignments = [], [], [], []
        self.sink = None
        self.stopped = False
        self.entry = 'got_command'
        mu = self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        # Keep both buffers alive for Unicorn's mem_map_ptr lifetime. Separate
        # storage models genuinely different memory, not stale cache lines.
        self.ram = ctypes.create_string_buffer(POOL_SIZE)
        self.alias_ram = self.ram if coherent_alias else ctypes.create_string_buffer(POOL_SIZE)
        for base, backing in ((POOL, self.ram), (POOL + 0x40000000, self.alias_ram)):
            mu.mem_map_ptr(base, POOL_SIZE, 7, ctypes.addressof(backing))
        mu.mem_map(CODE, 0x10000)
        mu.mem_write(CODE, blob[labels['wbody']:labels['wbody_end']])
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(OUT_TRB, 0x1000)
        pages = {a & ~0xFFF for a in FW.values()}
        pages |= {a & ~0xFFF for a in (PUBLICATION, SHELL_CTX, TRB_TABLE, OUT_BUSY)}
        for page in pages:
            mu.mem_map(page, 0x1000)
        mu.mem_write(PUBLICATION, struct.pack('<3I', POOL, POOL_SIZE, CODE))
        mu.mem_write(TRB_TABLE, struct.pack('<2I', OUT_TRB, IN_TRB))
        mu.mem_write(POOL, request)
        self.word(STATE, 0x4C485356)
        self.word(STATE + 0x0C, 19)
        # Prove got_command clears stale results, and reply_done clears CAP_PTR.
        for offset in (0x10, 0x14, 0x18, 0x1C):
            self.word(STATE + offset, 0xDEADBEEF)
        self.word(CAP_PTR, POOL + 0x2000)
        mu.reg_write(UC_ARM_REG_SP, STACK + 0x8000)
        mu.reg_write(UC_ARM_REG_R4, STATE)
        mu.hook_add(UC_HOOK_CODE, self.hook)

    def at(self, label):
        return CODE + self.labels[label] - self.labels['wbody']

    def word(self, address, value=None):
        if value is not None:
            self.mu.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))
        return struct.unpack('<I', self.mu.mem_read(address, 4))[0]

    def cstr(self, address):
        return bytes(self.mu.mem_read(address, 512)).split(b'\0', 1)[0]

    def ret(self, value=0):
        # Do not accidentally promise caller-saved registers survive firmware.
        for reg in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12):
            self.mu.reg_write(reg, 0xBAD00000)
        self.mu.reg_write(UC_ARM_REG_R0, value & 0xFFFFFFFF)
        self.mu.reg_write(UC_ARM_REG_PC, self.mu.reg_read(UC_ARM_REG_LR))

    def hook(self, mu, address, size, _):
        if address == self.at('next_round') or address == STACK + 0xF000:
            self.stopped = True
            mu.emu_stop()
            return
        if CODE <= address < CODE + self.labels['wbody_end'] - self.labels['wbody']:
            return
        names = {v: k for k, v in FW.items()}
        self.t.assertIn(address, names, f'unmocked execution at {address:#x}')
        name = names[address]
        self.calls.append(name)
        self.alignments.append((name, mu.reg_read(UC_ARM_REG_SP) % 8))
        r0, r1, r2 = (mu.reg_read(r) for r in
                      (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2))
        if name == 'CRC':
            self.ret(zlib.crc32(mu.mem_read(r0, r1)))
        elif name == 'START':
            if self.entry == 'arm_out':
                self.t.assertEqual(r0, 2, 'command must use physical endpoint 2')
                self.t.assertEqual(struct.unpack('<4I', mu.mem_read(OUT_TRB, 16)),
                                   (POOL - 0x40000000, 0, 0x4000, 0x813))
                for offset in (0, 4, 20):
                    self.t.assertEqual(self.word(POOL + offset), 0)
                self.ret(self.start_result)
                return
            self.t.assertEqual(r0, 5, 'reply must use physical endpoint 5')
            bus, high, length, control = struct.unpack('<4I', mu.mem_read(IN_TRB, 16))
            self.t.assertEqual((high, control), (0, 0x813))
            self.t.assertEqual(self.word(OUT_BUSY), 1)
            cpu = bus + 0x40000000
            self.transfers.append((cpu, bytes(mu.mem_read(cpu, length))))
            self.ret(self.start_result)
        elif name == 'END':
            self.t.assertEqual(r0, 1, 'cleanup must use logical OUT endpoint 1')
            self.ret()
        elif name == 'WAIT':
            self.t.assertEqual((r0, r1), (2, 20))
            # Complete only during Wait, so wait_done must inspect HWO again.
            self.word(IN_TRB + 12, self.word(IN_TRB + 12) & ~1)
            self.ret(0xFFFFFFFF)  # stale/error event return does not own the TRB
        elif name == 'SHINIT':
            self.t.assertEqual(r0, SHELL_CTX)
            self.word(SHELL_CTX, 1)
            self.ret()
        elif name == 'SHPUSH':
            self.t.assertEqual(r0, SHELL_CTX)
            self.t.assertEqual(r1, self.at('capture'))
            self.sink = r1
            self.ret()
        elif name == 'SHRUN':
            self.t.assertEqual(r0, SHELL_CTX)
            self.lines.append(self.cstr(r1))
            self.t.assertIsNotNone(self.sink)
            # Tail-call the actual worker callback with one literal printf.
            mu.mem_write(POOL + 0x8000, self.output + b'\0')
            mu.reg_write(UC_ARM_REG_R0, POOL + 0x8000)
            mu.reg_write(UC_ARM_REG_PC, self.sink)
        elif name == 'VSNPRINT':
            text = self.cstr(r2)
            mu.mem_write(r0, text[:r1 - 1] + b'\0')
            self.ret(len(text))
        elif name == 'SHPOP':
            self.t.assertEqual(r0, SHELL_CTX)
            self.sink = None
            self.ret()
        else:
            self.ret()

    def run(self, entry='got_command'):
        self.entry = entry
        self.mu.reg_write(UC_ARM_REG_LR, STACK + 0xF000)
        self.mu.emu_start(self.at(entry), CODE + 0x10000, count=200000)
        self.t.assertTrue(self.stopped, 'instruction budget exhausted before next_round')
        self.t.assertEqual(self.mu.reg_read(UC_ARM_REG_SP), STACK + 0x8000)
        return self


class WorkerImageTests(unittest.TestCase):
    def test_reviewed_same_size_ack_and_legacy_images(self):
        # Frozen pre-PONG resident bodies, not hashes of a freshly assembled
        # comparison alone: disabling the option must retain those exact bytes.
        for camera, length, digest in (
                ('fp-l-3.02', 3572, '48d3b2f4fec039c0c6141c61d4e496ea443e9685468f43366cbfd667271c8668'),
                ('fp-5.02', 3476, '488e016fb270c83f4208144a4ca7aaab6c616c79e14c1fd5bfe64faa45fd4495')):
            with self.subTest(camera=camera):
                defines = get_camera(camera).loader_defines()
                legacy_defines = defines + ['FPSUP_PONG_ACK=0']
                old = assemble(SOURCE, legacy_defines)
                labels = symbols(SOURCE, legacy_defines)
                body = old[labels['wbody']:labels['wbody_end']]
                self.assertEqual(len(body), length)
                self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
                new = assemble(SOURCE, defines)
                self.assertEqual(symbols(SOURCE, defines), labels)
                self.assertEqual(len(new), len(old))
                if camera == 'fp-5.02':
                    self.assertEqual(new, old)
                    continue
                start, end = labels['reply_nothing'], labels['reply_upload_caps']
                self.assertEqual(end - start, 24)
                self.assertEqual(new[:start], old[:start])
                self.assertEqual(new[end:], old[end:])
                self.assertEqual(struct.unpack('<6I', new[start:end]),
                                 (0xE2868014, 0xE3040F50, 0xE344074E,
                                  0xE5880000, 0xE3A09004, 0xEA0001D2))


@unittest.skipIf(Uc is None, 'needs unicorn')
class WorkerDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defines = get_camera('fp-l-3.02').loader_defines()
        cls.blob = assemble(SOURCE, defines)
        cls.labels = symbols(SOURCE, defines)

    def trial(self, request, **kwargs):
        return Dispatch(self, self.blob, self.labels, request, **kwargs)

    def replies(self, cam, command, lengths, status=0):
        self.assertEqual(len(cam.transfers), len(lengths))
        payload = b''
        for i, ((address, data), length) in enumerate(zip(cam.transfers, lengths)):
            self.assertEqual(address, POOL)
            self.assertEqual(len(data), 64)
            magic, version, cmd, flags, seq, size, code, crc = struct.unpack('<4sBBHIHHI', data[:20])
            self.assertEqual((magic, version, cmd, seq, size, code),
                             (b'FPSH', 1, command, SEQ, length, status))
            self.assertEqual(flags, int(i < len(lengths) - 1))
            self.assertEqual(crc, zlib.crc32(data[:16] + bytes(4) + data[20:]))
            payload += data[20:20 + size]
        self.assertEqual(cam.word(STATE + 0x20), 1)
        self.assertEqual(cam.word(STATE + 0x24), 0)
        self.assertEqual(cam.word(CAP_PTR), 0)
        self.assertEqual(cam.word(STATE + 8), 0)
        return payload

    def assert_shell(self, cam):
        cam.run()
        self.assertEqual(cam.lines, [b'echo dispatch'])
        self.assertEqual(self.replies(cam, 3, [15]), b'worker says hi\n')
        self.assertEqual([c for c in cam.calls if c.startswith('SH')],
                         ['SHINIT', 'SHPUSH', 'SHRUN', 'SHPOP'])
        self.assertEqual(cam.word(CAP_LEN), 15)

    def test_actual_ascii_shl_prefix_and_capture_callback(self):
        # Independent ASCII input: never construct it from the worker constant.
        self.assert_shell(self.trial(frame(3, b'shl echo dispatch\0'),
                                     output=b'worker says hi\n'))

    def test_wrong_prefix_does_not_dispatch(self):
        for prefix in (b'slh ', b'SHL ', b'shl\0'):
            with self.subTest(prefix=prefix):
                cam = self.trial(frame(3, prefix + b'echo dispatch\0')).run()
                self.assertEqual(cam.lines, [])
                self.assertEqual(self.replies(cam, 3, [4]), b'PONG')

    def test_ping_is_pong_framed_ack(self):
        request = frame(1)
        cam = self.trial(request).run()
        self.assertEqual(self.replies(cam, 1, [4]), b'PONG')
        self.assertNotEqual(cam.transfers, [(POOL, request)])
        self.assertEqual(cam.calls, ['CRC', 'START', 'WAIT'])
        self.assertEqual(cam.word(STATE + 0x34), 1)
        self.assertEqual(bytes(cam.mu.mem_read(POOL + 20, 44)), b'PONG' + bytes(40))

    def test_unknown_commands_use_fallback_pong_ack(self):
        for command in (0, 2, 10, 255):
            with self.subTest(command=command):
                request = frame(command)
                cam = self.trial(request).run()
                self.assertEqual(self.replies(cam, command, [4]), b'PONG')
                self.assertNotEqual(cam.transfers, [(POOL, request)])
                self.assertEqual(cam.lines, [])

    def test_legacy_option_retains_empty_ping(self):
        defines = get_camera('fp-l-3.02').loader_defines() + ['FPSUP_PONG_ACK=0']
        cam = Dispatch(self, assemble(SOURCE, defines), symbols(SOURCE, defines), frame(1)).run()
        self.assertEqual(self.replies(cam, 1, [0]), b'')
        # Negative control: the old ack is an unchanged empty request and must
        # fail both new response oracles.
        with self.assertRaises(AssertionError):
            self.replies(cam, 1, [4])
        with self.assertRaises(AssertionError):
            self.assertNotEqual(cam.transfers, [(POOL, frame(1))])

    def test_fixed_cpu_view_dispatches_with_independent_memory(self):
        source = POOL + 0x10000
        requests = [('SHL', frame(3, b'shl echo dispatch\0')),
                    ('MCAPS', frame(9)),
                    ('MEMR64', frame(7, struct.pack('<3I', source, 64, 0))),
                    ('MEMR4', frame(7, struct.pack('<3I', source, 4, 0)))]
        for name, request in requests:
            with self.subTest(command=name):
                cam = self.trial(request, output=b'worker says hi\n')
                self.assertIsNot(cam.ram, cam.alias_ram)
                cam.mu.mem_write(source, b'\xA5' * 64)
                if name == 'SHL':
                    self.assert_shell(cam)
                else:
                    cam.run()
                    if name == 'MCAPS':
                        expected = struct.pack('<4sIII', b'MEM1', 0xFFFC00,
                                               POOL, POOL_SIZE) + bytes(96)
                        self.assertEqual(self.replies(cam, 9, [44, 44, 24]), expected)
                    else:
                        length = 64 if name == 'MEMR64' else 4
                        self.assertEqual(cam.transfers, [(source, b'\xA5' * length)])
                        self.assertEqual(cam.word(STATE + 0x34), 5)
                self.assertEqual(cam.word(STATE + 0x20), 1)
                self.assertEqual(cam.word(STATE + 0x24), 0)
                self.assertEqual(bytes(cam.mu.mem_read(POOL + 0x40000000, 64)), bytes(64))
                self.assertNotEqual(cam.transfers, [(POOL, request)])

    def test_mutated_old_cpu_offset_reproduces_unchanged_request_echoes(self):
        # Conditional reproduction, NOT proof of the camera's active MMU/DMA
        # mapping. Restore the old CPU offset in all three emitted instructions,
        # without changing the current source or its DMA translation. OUT DMA
        # lands in POOL, while got_command reads zero-filled
        # *different* RAM at POOL+0x40000000. It falls through reply_nothing,
        # writes a fallback PONG reply there, then arms IN at the original POOL.
        # Even MEMR asking for four bytes therefore arms the untouched 64-byte
        # request. We observe the TRB bytes, not host short-read/overflow policy.
        mutated = bytearray(self.blob)
        # Match each zero-offset MOV together with its consuming ADD; this
        # avoids mistaking unrelated mov #0 instructions for frame addressing.
        for label, end_label, mov, add in (
                ('got_command', 'shell_ready', 0xE3A00000, 0xE0866000),
                ('fault', 'hold', 0xE3A02000, 0xE0800002),
                ('arm_out', 'reply_raw', 0xE3A00000, 0xE0860000)):
            start, end = self.labels[label], self.labels[end_label]
            pattern = struct.pack('<2I', mov, add)
            self.assertEqual(mutated[start:end].count(pattern), 1)
            site = mutated.index(pattern, start, end)
            # ARM immediate 1 rotated right by 2 encodes 0x40000000.
            struct.pack_into('<I', mutated, site, mov | 0x101)
        source = POOL + 0x10000
        requests = [('SHL', frame(3, b'shl echo dispatch\0')),
                    ('MCAPS', frame(9)),
                    ('MEMR64', frame(7, struct.pack('<3I', source, 64, 0))),
                    ('MEMR4', frame(7, struct.pack('<3I', source, 4, 0)))]
        for name, request in requests:
            with self.subTest(command=name):
                cam = Dispatch(self, bytes(mutated), self.labels, request,
                               output=b'worker says hi\n')
                cam.mu.mem_write(source, b'\xA5' * 64)
                wrong_view = POOL + 0x40000000
                self.assertEqual(bytes(cam.mu.mem_read(wrong_view, 64)), bytes(64))
                cam.run()
                self.assertEqual(cam.lines, [])
                self.assertNotIn('SHRUN', cam.calls)
                self.assertEqual(cam.calls, ['CRC', 'START', 'WAIT'])
                self.assertEqual(cam.transfers, [(POOL, request)])
                with self.assertRaises(AssertionError):
                    self.assertNotEqual(cam.transfers, [(POOL, request)],
                                        'CPU mapping regression echoes request')
                self.assertEqual(bytes(cam.mu.mem_read(POOL, 64)), request)
                self.assertEqual(bytes(cam.mu.mem_read(source, 64)), b'\xA5' * 64)
                bogus_reply = bytearray(64)
                struct.pack_into('<H', bogus_reply, 12, 4)
                bogus_reply[20:24] = b'PONG'
                struct.pack_into('<I', bogus_reply, 16, zlib.crc32(bogus_reply))
                self.assertEqual(bytes(cam.mu.mem_read(wrong_view, 64)), bytes(bogus_reply))
                self.assertEqual(cam.word(STATE + 0x34), 1)  # never MEMR phase 5
                self.assertEqual(cam.word(STATE + 0x20), 1)  # incorrectly 'served'
                self.assertEqual(cam.word(STATE + 0x24), 0)

    def test_memcaps_fragments_and_reports_all_windows(self):
        cam = self.trial(frame(9, flags=1))  # caps must clear the raw-request flag
        windows = b''.join(struct.pack('<3I', 0x50000000 + i * 0x1000,
                                      0x1000, 1 + i % 3) for i in range(8))
        cam.mu.mem_write(POOL + 0x6A00, windows)
        cam.run()
        expected = struct.pack('<4sIII', b'MEM1', 0xFFFC00, POOL, POOL_SIZE) + windows
        self.assertEqual(self.replies(cam, 9, [44, 44, 24]), expected)
        self.assertEqual(cam.calls, ['CRC', 'START', 'WAIT'] * 3)

    def test_memr_direct_pool_bytes_with_optional_sync(self):
        for sync in (0, 1):
            with self.subTest(sync=sync):
                source = POOL + 0x10000
                data = bytes(range(256)) * 133
                cam = self.trial(frame(7, struct.pack('<3I', source, len(data), sync)))
                cam.mu.mem_write(source, data)
                cam.run()
                self.assertEqual(cam.transfers, [(source, data)])
                self.assertEqual(cam.calls, ['CRC'] + ['DCACHE'] * sync + ['START', 'WAIT'])
                self.assertEqual(cam.word(STATE + 0x34), 5)
                self.assertEqual(cam.word(STATE + 0x20), 1)
                self.assertEqual(cam.word(STATE + 0x24), 0)
                self.assertEqual(cam.word(CAP_PTR), 0)

    def test_memr_explicit_window_permission_and_boundary(self):
        source = POOL + POOL_SIZE  # just beyond implicit pool, in separate RAM
        for permission, length, status in ((1, 32, 0), (2, 32, 4), (1, 33, 4)):
            with self.subTest(permission=permission, length=length):
                cam = self.trial(frame(7, struct.pack('<3I', source, length, 0)))
                cam.mu.mem_map(source, 0x1000)
                cam.mu.mem_write(source, b'x' * 32)
                cam.mu.mem_write(POOL + 0x6A00, struct.pack('<3I', source, 32, permission))
                cam.run()
                if status:
                    self.assertEqual(self.replies(cam, 7, [4], status), struct.pack('<I', status))
                else:
                    self.assertEqual(cam.transfers, [(source, b'x' * 32)])

    def test_memr_refuses_bad_frame_and_invalid_ranges(self):
        valid = frame(7, struct.pack('<3I', POOL + 0x10000, 32, 0))
        corrupt = bytearray(valid)
        corrupt[16] ^= 1
        requests = [(bytes(corrupt), 1)]
        for address, length, status in ((POOL, 0, 2), (0xFFFFFFF0, 32, 2),
                                        (POOL, 0xFFFC01, 2),
                                        (POOL + POOL_SIZE - 16, 32, 4)):
            requests.append((frame(7, struct.pack('<3I', address, length, 0)), status))
        for request, status in requests:
            with self.subTest(request=request.hex(), status=status):
                cam = self.trial(request).run()
                self.assertEqual(self.replies(cam, 7, [4], status), struct.pack('<I', status))
                self.assertEqual(cam.word(STATE + 0x34), 1)
                self.assertNotIn('DCACHE', cam.calls)

    def test_start_failure_records_fault_instead_of_served(self):
        cam = self.trial(frame(1), start_result=7).run()
        self.assertEqual(cam.calls, ['CRC', 'START', 'DELAY'])
        self.assertEqual(cam.word(STATE + 0x20), 0)
        self.assertEqual(cam.word(STATE + 0x24), 1)
        self.assertEqual(cam.word(STATE + 8), 1)
        self.assertEqual(cam.word(POOL + 0x6C00), 1)
        self.assertEqual(struct.unpack('<8I', cam.mu.mem_read(POOL + 0x6C10, 32)),
                         (19, 1, 1, SEQ, 0, 0, 7, 0))

    def test_firmware_calls_keep_aapcs_stack_alignment(self):
        # PING reaches arm_in; MEMR reaches arm_in_block via real dispatch.
        cam = self.trial(frame(1)).run()
        self.assertEqual(cam.alignments, [('CRC', 0), ('START', 0), ('WAIT', 0)])
        cam = self.trial(frame(7, struct.pack('<3I', POOL + 0x10000, 32, 1))).run()
        self.assertEqual(cam.alignments,
                         [('CRC', 0), ('DCACHE', 0), ('START', 0), ('WAIT', 0)])

    def assert_arm_out(self, cam, fault):
        cam.word(STATE + 8, fault)
        registers = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
                     UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                     UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12)
        for i, register in enumerate(registers[1:]):
            cam.mu.reg_write(register, 0x12340000 + i)
        before = [cam.mu.reg_read(r) for r in registers]
        cam.run('arm_out')
        self.assertEqual(cam.alignments, [('END', 0)] * fault + [('START', 0)])
        self.assertEqual([cam.mu.reg_read(r) for r in registers], before)
        self.assertEqual(cam.mu.reg_read(UC_ARM_REG_R0), cam.start_result)

    def test_arm_out_clean_and_fault_cleanup_calls_are_aligned(self):
        for fault in (0, 1):
            for start_result in (0, 7):
                with self.subTest(fault=fault, start_result=start_result):
                    self.assert_arm_out(self.trial(frame(1), start_result=start_result), fault)

    def test_alignment_oracle_detects_old_push_pop_pairs(self):
        # Restore the old five-register pair in memory, independently for each
        # routine. Balanced mutations return normally but fail the ABI oracle.
        for routine, request in (('arm_out', frame(1)), ('arm_in', frame(1)),
                                 ('arm_in_block', frame(7, struct.pack(
                                     '<3I', POOL + 0x10000, 32, 0)))):
            with self.subTest(routine=routine):
                mutated = bytearray(self.blob)
                start = self.labels[routine]
                self.assertEqual(struct.unpack_from('<I', mutated, start)[0], 0xE92D50F0)
                end = mutated.index(struct.pack('<I', 0xE8BD90F0), start)
                struct.pack_into('<I', mutated, start, 0xE92D40F0)
                struct.pack_into('<I', mutated, end, 0xE8BD80F0)
                cam = Dispatch(self, bytes(mutated), self.labels, request)
                if routine == 'arm_out':
                    cam.word(STATE + 8, 1)
                    cam.run('arm_out')
                    self.assertEqual(cam.alignments, [('END', 4), ('START', 4)])
                else:
                    cam.run()
                    self.assertIn(('START', 4), cam.alignments)
                with self.assertRaises(AssertionError):
                    self.assertTrue(all(alignment == 0 for _, alignment in cam.alignments),
                                    cam.alignments)

    def test_mutated_prefix_fails_real_shell_oracle(self):
        mutated = bytearray(self.blob)
        # movw r1,#0x6873 (low half of 'shl ') -> #0x6872 ('rhl ').
        instruction = struct.pack('<I', 0xE3061873)
        start, end = self.labels['got_command'], self.labels['shell_ready']
        site = mutated.index(instruction, start, end)
        mutated[site] ^= 1
        cam = Dispatch(self, bytes(mutated), self.labels,
                       frame(3, b'shl echo dispatch\0'), output=b'worker says hi\n')
        with self.assertRaises(AssertionError):
            self.assert_shell(cam)

    def test_mutated_reply_endpoint_is_detected(self):
        mutated = bytearray(self.blob)
        # One instruction changes physical IN 5 to OUT 4 in the emitted body.
        site = mutated.index(struct.pack('<I', 0xE3A00005), self.labels['arm_in'])
        mutated[site] ^= 1
        cam = Dispatch(self, bytes(mutated), self.labels, frame(1))
        with self.assertRaisesRegex(AssertionError, 'physical endpoint 5'):
            cam.run()


if __name__ == '__main__':
    unittest.main()
