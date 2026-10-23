"""Offline fp L heap experiment tests, with independent firmware-call oracles.

Run from fp_usb_shell: python3 -B -m unittest -v test_heap_probe
Synthetic placements and allocator/cache stubs do not establish allocator
semantics, executable camera heaps, cache coherency, or a working card.
"""
import pathlib
import struct
import unittest

from armasm import assemble, symbols
from firmware import get_camera
from fpl_heap_probe import inspect_result

try:
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import arm_const as reg
except ImportError:
    Uc = None


SOURCE = pathlib.Path(__file__).resolve().parent / 'asm/heap_probe.S'
# Do not obtain these addresses from the selected profile or its C header.
FIRMWARE = {0xC001D740: 'GET', 0xC001D7F0: 'ADDR', 0xC001D7A0: 'FREE',
            0xC000E91C: 'D', 0xC000EABC: 'I'}
PLACEMENTS = ((0x41000100, 0x46000200), (0x52100340, 0x63000480))
STACK, DONE = 0x71001000, 0x72000000


class ProbeRun:
    def __init__(self, test, code, labels, base, heap, *, outcome='success', misaligned_sp=False):
        self.t, self.code, self.labels = test, code, labels
        self.base, self.heap, self.outcome = base, heap, outcome
        self.sp = STACK - (4 if misaligned_sp else 8)
        self.frame = (self.sp - 32) & ~7
        self.descriptor = self.frame - 16
        self.result = base + labels['heap_result']
        self.leaf_size = labels['heap_leaf_end'] - labels['heap_leaf']
        self.returned_address = {'success': heap, 'null': 0,
                                 'misaligned': heap + 2}[outcome]
        self.events, self.writes, self.heap_pcs = [], [], []
        self.allocated, self.freed, self.leaf_return = False, False, None
        self.error = None
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for page in {base & ~0xFFF, heap & ~0xFFF, (heap & ~0xFFF) + 0x1000,
                     STACK - 0x1000, DONE, *(address & ~0xFFF for address in FIRMWARE)}:
            self.mu.mem_map(page, 0x1000)
        self.mu.mem_write(base, code)
        # A successful run must initialise reserved fields, not inherit zeros.
        self.mu.mem_write(self.result, b'\xA5' * 64)
        self.mu.mem_write(heap & ~0xFFF, b'\xCC' * 0x2000)
        self.mu.mem_write(STACK - 0x1000, b'\xA5' * 0x1000)
        self.mu.hook_add(UC_HOOK_CODE, self.guarded(self.execute))
        self.mu.hook_add(UC_HOOK_MEM_WRITE, self.guarded(self.write))

    def guarded(self, callback):
        # Stop explicitly: some Unicorn versions otherwise continue after an
        # exception in a Python callback and hide the first oracle failure.
        def hook(*args):
            try:
                callback(*args)
            except Exception as error:
                self.error = error
                self.mu.emu_stop()
        return hook

    def r(self, register):
        return self.mu.reg_read(register)

    def words(self):
        return struct.unpack('<16I', self.mu.mem_read(self.result, 64))

    def write(self, mu, access, address, size, value, _):
        t = self.t
        ranges = [(self.descriptor, self.sp), (self.result, self.result + 64)]
        if self.allocated and not self.freed and self.outcome == 'success':
            ranges.append((self.heap, self.heap + self.leaf_size))
        t.assertTrue(any(start <= address and address + size <= end for start, end in ranges),
                     f'out-of-ownership write at {address:#x} size {size}')
        if self.heap <= address < self.heap + 0x1000:
            t.assertEqual(self.events, ['GET', 'ADDR'], 'leaf changed after cache publication')
        self.writes.append((address, size, value))

    def execute(self, mu, address, size, _):
        t = self.t
        t.assertEqual(self.r(reg.UC_ARM_REG_CPSR) & 0x20, 0, 'execution must be ARM')
        if self.heap <= address < self.heap + 0x1000:
            t.assertTrue(self.allocated and not self.freed, 'heap execution after free or before allocation')
            t.assertLess(address, self.heap + self.leaf_size, 'execution outside copied leaf')
            if not self.heap_pcs:
                t.assertEqual(address, self.heap)
                t.assertEqual(self.events, ['GET', 'ADDR', 'D', 'I'], 'cache publication order')
                t.assertEqual(self.r(reg.UC_ARM_REG_R0), self.result)
                t.assertEqual(self.r(reg.UC_ARM_REG_SP) % 8, 0)
                self.leaf_return = self.r(reg.UC_ARM_REG_LR)
                t.assertTrue(self.base <= self.leaf_return < self.base + self.labels['heap_leaf'])
                self.events.append('LEAF')
            self.heap_pcs.append(address)
            return  # Run the actual copied instructions, including bx lr.
        if self.base <= address < self.base + self.labels['heap_leaf']:
            if address == self.leaf_return:
                t.assertEqual(self.events[-1], 'LEAF')
                t.assertEqual(self.r(reg.UC_ARM_REG_R0), 0x21594B4F, 'leaf return marker')
                t.assertEqual(self.words()[9], 0x50454148, 'leaf result marker')
                self.events.append('RETURN')
            return
        t.assertIn(address, FIRMWARE, f'unexpected execution at {address:#x}')
        name = FIRMWARE[address]
        t.assertEqual(self.r(reg.UC_ARM_REG_SP), self.descriptor, name)
        t.assertEqual(self.r(reg.UC_ARM_REG_SP) % 8, 0, name)
        args = tuple(self.r(r) for r in (reg.UC_ARM_REG_R0, reg.UC_ARM_REG_R1,
                                        reg.UC_ARM_REG_R2, reg.UC_ARM_REG_R3))
        value = 0xBAD00000  # Unspecified firmware return values must not be used.
        if name == 'GET':
            t.assertEqual(self.events, [])
            t.assertEqual(args, (self.descriptor, 0, 4096, 0))
            t.assertEqual(bytes(mu.mem_read(self.descriptor, 16)), bytes(16))
            # Opaque fixture token, NOT a model of the real allocator layout.
            mu.mem_write(self.descriptor, struct.pack('<4I', 0x12345678, 0x87654321, 7, 9))
        elif name == 'ADDR':
            t.assertEqual(self.events, ['GET'])
            t.assertEqual(args[0], self.descriptor)
            t.assertEqual(struct.unpack('<4I', mu.mem_read(args[0], 16)),
                          (0x12345678, 0x87654321, 7, 9))
            value = self.returned_address
            self.allocated = value != 0
        elif name in ('D', 'I'):
            t.assertEqual(self.events, ['GET', 'ADDR'] + (['D'] if name == 'I' else []),
                          'cache publication order')
            t.assertTrue(self.allocated and not self.freed)
            t.assertEqual(bytes(mu.mem_read(self.heap, self.leaf_size)),
                          self.code[self.labels['heap_leaf']:self.labels['heap_leaf_end']])
            t.assertEqual(self.words()[7], self.heap)
            t.assertFalse(self.heap_pcs, 'cache maintenance came after execution')
        elif name == 'FREE':
            t.assertEqual(args[:2], (self.descriptor, 2))
            t.assertTrue(self.allocated and not self.freed)
            t.assertEqual(struct.unpack('<4I', mu.mem_read(args[0], 16)),
                          (0x12345678, 0x87654321, 7, 9))
            expected = ['GET', 'ADDR']
            if self.outcome == 'success':
                expected += ['D', 'I', 'LEAF', 'RETURN']
                t.assertEqual(self.words()[2], 3)
                t.assertEqual(self.words()[10], 0x21594B4F)
            else:
                t.assertEqual(self.outcome, 'misaligned')
                t.assertEqual(self.words()[2], 2)
            t.assertEqual(self.events, expected, 'free must follow leaf return')
            t.assertEqual(self.words()[11], 0, 'free-return marker set before free')
            self.freed = True
        self.events.append(name)
        # AAPCS permits all these registers and condition flags to be trashed.
        for register in (reg.UC_ARM_REG_R1, reg.UC_ARM_REG_R2,
                         reg.UC_ARM_REG_R3, reg.UC_ARM_REG_R12):
            mu.reg_write(register, 0xBAD00000 + register)
        mu.reg_write(reg.UC_ARM_REG_CPSR, (self.r(reg.UC_ARM_REG_CPSR) & 0x0FFFFFFF) | 0xA0000000)
        mu.reg_write(reg.UC_ARM_REG_R0, value)
        mu.reg_write(reg.UC_ARM_REG_PC, self.r(reg.UC_ARM_REG_LR))

    def run(self):
        saved = [getattr(reg, f'UC_ARM_REG_R{i}') for i in range(4, 12)]
        for register in saved:
            self.mu.reg_write(register, 0xABC00000 + register)
        self.mu.reg_write(reg.UC_ARM_REG_R0, self.base + self.labels['heap_probe'])
        self.mu.reg_write(reg.UC_ARM_REG_SP, self.sp)
        self.mu.reg_write(reg.UC_ARM_REG_LR, DONE)
        try:
            self.mu.emu_start(self.base + self.labels['heap_probe'], DONE, count=2000)
        finally:
            if self.error is not None:
                raise self.error
        self.t.assertEqual(self.r(reg.UC_ARM_REG_PC), DONE, 'probe did not return')
        self.t.assertEqual(self.r(reg.UC_ARM_REG_SP), self.sp, 'caller SP not restored')
        for register in saved:
            self.t.assertEqual(self.r(register), 0xABC00000 + register, 'callee-saved register')
        self.t.assertEqual(self.r(reg.UC_ARM_REG_R0), self.result)
        success = self.outcome == 'success'
        expected = (0x58455046, 1, {'null': 1, 'misaligned': 2, 'success': 3}[self.outcome],
                    self.returned_address, 4096, self.leaf_size,
                    self.heap if success else 0, self.heap if success else 0,
                    self.descriptor if success else 0, 0x50454148 if success else 0,
                    0x21594B4F if success else 0, int(self.outcome != 'null'), 0, 0, 0, 0)
        self.t.assertEqual(self.words(), expected, '16-word result ABI')
        events = ['GET', 'ADDR'] + (['D', 'I', 'LEAF', 'RETURN'] if success else [])
        if self.outcome != 'null':
            events.append('FREE')
        self.t.assertEqual(self.events, events)
        self.t.assertEqual(bool(self.heap_pcs), success)
        # Code outside the embedded result must remain byte-for-byte unchanged.
        offset = self.labels['heap_result']
        self.t.assertEqual(bytes(self.mu.mem_read(self.base, offset)), self.code[:offset])
        after = offset + 64
        self.t.assertEqual(bytes(self.mu.mem_read(self.base + after, len(self.code) - after)),
                           self.code[after:])
        heap_writes = [(a, n) for a, n, _ in self.writes if self.heap <= a < self.heap + 0x1000]
        self.t.assertEqual(heap_writes, [(self.heap + i, 4) for i in range(0, self.leaf_size, 4)]
                           if success else [])
        self.t.assertEqual(bytes(self.mu.mem_read(self.heap + self.leaf_size, 4096 - self.leaf_size)),
                           b'\xCC' * (4096 - self.leaf_size))
        return self


@unittest.skipIf(Uc is None, 'requires unicorn')
class HeapProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        defines = get_camera('fp-l-3.02').loader_defines()
        cls.code = assemble(SOURCE, defines)
        cls.labels = symbols(SOURCE, defines)

    def exercise(self, outcome='success', misaligned_sp=False):
        for base, heap in PLACEMENTS:
            with self.subTest(base=hex(base), heap=hex(heap), outcome=outcome):
                run = ProbeRun(self, self.code, self.labels, base, heap,
                               outcome=outcome, misaligned_sp=misaligned_sp).run()
                report = inspect_result(bytes(run.mu.mem_read(run.result, 64)))
                self.assertEqual(report['execution_evidence_passed'], outcome == 'success')
                self.assertFalse(report['restoration_verified'])

    def test_allocated_leaf_executes_and_returns_before_free_at_two_placements(self):
        self.exercise()

    def test_null_address_returns_without_execution_cache_or_free(self):
        self.exercise('null')

    def test_misaligned_address_freed_without_copy_cache_or_execution(self):
        self.exercise('misaligned')

    def test_misaligned_caller_stack_is_restored_on_all_paths(self):
        for outcome in ('success', 'null', 'misaligned'):
            self.exercise(outcome, misaligned_sp=True)

    def test_missing_dcache_call_mutation_is_rejected(self):
        code = bytearray(self.code)
        # CALL_FW's blx ip instructions: GET, ADDR, D, I, FREE. Delete only D.
        calls = [i for i in range(0, self.labels['heap_leaf'], 4)
                 if struct.unpack_from('<I', code, i)[0] == 0xE12FFF3C]
        self.assertEqual(len(calls), 5)
        struct.pack_into('<I', code, calls[2], 0xE320F000)  # ARM nop
        with self.assertRaisesRegex(AssertionError, 'cache publication order'):
            ProbeRun(self, bytes(code), self.labels, *PLACEMENTS[0]).run()

    def test_changed_leaf_marker_instruction_mutation_is_rejected(self):
        code = bytearray(self.code)
        # Literal ARM encoding of movw r1,#0x4148, not a source/header oracle.
        candidates = [i for i in range(self.labels['heap_leaf'], self.labels['heap_leaf_end'], 4)
                      if struct.unpack_from('<I', code, i)[0] == 0xE3041148]
        self.assertEqual(len(candidates), 1)
        struct.pack_into('<I', code, candidates[0], 0xE3041149)
        with self.assertRaisesRegex(AssertionError, 'leaf result marker'):
            ProbeRun(self, bytes(code), self.labels, *PLACEMENTS[1]).run()


class HeapResultTests(unittest.TestCase):
    # Independent wire fixture: neither FIELDS nor assembly constants determine
    # its values or positions. In particular a forged all-zero PC chain fails.
    VALID = (0x58455046, 1, 3, 0x46000200, 4096, 40, 0x46000200, 0x46000200,
             0x71000FC0, 0x50454148, 0x21594B4F, 1, 0, 0, 0, 0)

    def test_literal_result_is_execution_evidence_only(self):
        report = inspect_result(struct.pack('<16I', *self.VALID))
        self.assertTrue(report['execution_evidence_passed'])
        self.assertTrue(all(report['checks'].values()))
        self.assertFalse(report['restoration_verified'])
        self.assertEqual(report['words']['leaf_marker'], '0x50454148')
        self.assertEqual(report['words']['leaf_return'], '0x21594b4f')

    def test_every_corrupted_result_word_is_rejected(self):
        for index in range(16):
            with self.subTest(word=index):
                words = list(self.VALID)
                words[index] ^= 1
                report = inspect_result(struct.pack('<16I', *words))
                self.assertFalse(report['execution_evidence_passed'])
        for indices in ((3, 6, 7), (8,)):
            with self.subTest(zero_words=indices):
                words = list(self.VALID)
                for index in indices:
                    words[index] = 0
                self.assertFalse(inspect_result(struct.pack('<16I', *words))['execution_evidence_passed'])

    def test_missing_truncated_or_oversized_result_is_rejected(self):
        raw = struct.pack('<16I', *self.VALID)
        for size in (0, 1, 4, 60, 63, 65, 68, 128):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, 'expected 64 result bytes'):
                    inspect_result((raw + bytes(128))[:size])


if __name__ == '__main__':
    unittest.main()
