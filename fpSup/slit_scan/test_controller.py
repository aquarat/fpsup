"""Actual controller + fp L registration/lookup/subscription/set/notify instructions.

Native heap, Lua, locks, string-sharing lookup and final event queue are bounded
services. This is not native rendering, live scheduling or a timing backend.
"""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest

from build_controller import build, HERE
sys.path.insert(0, str(HERE.parent/'fp_usb_shell'))
from firmware import get_camera
from unicorn import UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
from unicorn.arm_const import *

# A private module instance: no global modification of the fp test harness.
spec = importlib.util.spec_from_file_location('slit_binding_probe',
    HERE.parents[1]/'research/ui/tools/native_variable_probe/binding_probe.py')
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)
registry = binding.registry
FP_NATIVE = dict(registry.NATIVE, **binding.EXTRA_NATIVE)
for module, keys in ((registry, ('REGISTER', 'LOOKUP', 'LOOKUP_APP', 'MAP_APPEND', 'LUA_WRAPPER')),
                     (binding, ('SUBSCRIBE', 'UNSUBSCRIBE', 'NOTIFY', 'SET_NOTIFY', 'SET_SILENT', 'SET_INDEX'))):
    for name in keys:
        setattr(module, name, getattr(module, name)-0x3E20)
registry.NATIVE = {k: (a-0x3E20, b-0x3E20) for k, (a, b) in registry.NATIVE.items()}
binding.EXTRA_NATIVE = {k: (a-0x3E20, b-0x3E20) for k, (a, b) in binding.EXTRA_NATIVE.items()}
registry.SEG0_SHA256 = get_camera('fp-l-3.02').main_sha256
SAVED = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
         UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]


class Probe(binding.BindingProbe):
    CODE = 0x30000000
    STATE = binding.BindingProbe.RAM+0x3B00

    def __init__(self, image, text):
        self.text = text
        self.queue = []
        # The shared permission probe documents Unicorn's IT-state corruption
        # with a Python memory-read hook. Use its code/write guards only; these
        # tests retain subscriptions and never exercise unsubscribe/free races.
        self.events, self.callback_results, self.freed = [], {}, {}
        self.private_callback_action = self.pause_at = self.pause_context = None
        self.paused, self.lock_depth = False, 0
        registry.RegistryProbe.__init__(self, image)
        self.write_words(self.APP+8, self.ALLOCATOR)
        self.write_words(self.ROOT+0x130, self.ALLOCATOR, self.RAM+0x2100)
        self.write_words(self.ALLOCATOR+0x2C, self.LOCK | 1, self.UNLOCK | 1)
        self.uc.mem_map(self.CODE, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_write(self.CODE, text.code)
        self.uc.mem_protect(self.CODE, 0x10000, UC_PROT_READ | UC_PROT_EXEC)

    def _instruction(self, uc, address, size, data):
        if self.CODE <= address < self.CODE+len(self.text.code):
            return
        args = [uc.reg_read(r) for r in registry.REGS]
        if address == 0xC05E51C8:  # string-sharing domain not initialized in this fixture
            self._return(0); return
        if address == 0xC0013DBC:
            self._return(len(self.string(args[0]))); return
        if address == 0xC0015058:
            self.write(args[0], bytes([args[1] & 255])*args[2])
            self._return(args[0]); return
        if address == 0xC055A208:
            self._return(self.RAM+0x2200); return
        if address == 0xC055A300:
            if args[0] != self.RAM+0x2200 or uc.reg_read(UC_ARM_REG_SP) & 7:
                raise AssertionError('bad queue context/stack')
            self.queue.append(self.words(args[1], 14))
            self._return(0); return
        for lo, hi in ((0xC0013DD4, 0xC0013E2C), (0xC05D5CF8, 0xC05D5D5E), (0xC0590078, 0xC05900C8),
                       (0xC0559E28, 0xC0559E60), (0xC0590128, 0xC0590178),
                       (0xC0559EA0, 0xC0559ED8)):
            if lo <= address < hi:
                return
        super()._instruction(uc, address, size, data)

    def call(self, name, *args):
        values = [0xA0001000+i for i in range(8)]
        for r, v in zip(SAVED, values): self.uc.reg_write(r, v)
        for r, value in zip(registry.REGS, (*args, 0, 0, 0, 0)):
            self.uc.reg_write(r, value)
        self.uc.reg_write(UC_ARM_REG_CPSR, 0x13)
        self.uc.reg_write(UC_ARM_REG_SP, self.STACK)
        self.uc.reg_write(UC_ARM_REG_LR, self.STOP | 1)
        self.stopped = False
        self.uc.emu_start(self.CODE+self.text.functions['slit_'+name], self.STOP+2,
                          timeout=self.TIMEOUT_US, count=self.MAX_INSTRUCTIONS)
        if not self.stopped or self.uc.reg_read(UC_ARM_REG_SP) != self.STACK:
            raise AssertionError('controller did not return within bounds/restore SP')
        answer = self.uc.reg_read(UC_ARM_REG_R0)
        if [self.uc.reg_read(r) for r in SAVED] != values:
            raise AssertionError('callee-saved registers changed')
        return answer

    def init(self):
        return self.call('init', self.STATE, self.APP, self.CODE+self.text.functions['slit_key'])

    def key(self, value):
        return self.set_integer(value, name='MV_fpSlitKey')

    def press(self, direction):
        reset = self.key(0)
        if reset: return reset
        return self.key(direction)

    def requested(self):
        return self.words(self.STATE+20)[0]

    def posted_text(self):
        return self.string(self.queue[-1][3]).decode()


class Controller(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = get_camera('fp-l-3.02').verify_main(os.environ['FPL_MAIN'])
        registry.SEG0_SIZE = len(cls.image)
        cls.text = build()

    def probe(self, text=None):
        p = Probe(self.image, text or self.text)
        self.addCleanup(p.close)
        return p

    def test_full_native_ranges_match_reviewed_fp_shapes(self):
        # Verify every instruction in reused ranges, not just a prologue/delta.
        import capstone
        sys.path.insert(0, str(HERE.parent/'tools'))
        from fpl_ui_audit import shape
        import re
        def normalized(i):
            mnemonic, operands = shape(i)
            if mnemonic.startswith(('movw', 'movt')):
                operands = re.sub(r'#(?:0x[0-9a-f]+|\d+)', '#ADDR', operands)
            return mnemonic, operands
        fp = get_camera('fp-5.02').verify_main(os.environ['FP_MAIN'])
        md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB)
        for name, (lo, hi) in FP_NATIVE.items():
            a = list(md.disasm(fp[lo-0xC0000000:hi-0xC0000000], lo))
            b = list(md.disasm(self.image[lo-0xC0000000-0x3E20:hi-0xC0000000-0x3E20], lo-0x3E20))
            self.assertEqual([normalized(i) for i in a], [normalized(i) for i in b], name)

    def test_registration_borrows_owned_names_and_copies_string_value(self):
        p = self.probe()
        self.assertEqual(p.init(), 0)
        self.assertEqual(p.words(p.STATE, 2), (2, 0))
        from menu import VARIABLES
        for i, name in enumerate(VARIABLES):
            status, desc = p.lookup(name)
            self.assertEqual(status, 0)
            self.assertEqual(p.words(desc+4)[0], p.STATE+60+i*24)
            self.assertEqual(p.words(desc)[0], 2 if i == 2 else 0)
            if i == 2:
                value = p.words(desc+8)[0]
                self.assertEqual(p.string(value), b'Off')
                self.assertNotEqual(value, p.STATE+180)
        self.assertEqual(p.call('pump', p.STATE), 0)
        self.assertEqual(p.queue, [])
        self.assertEqual(p.init(), 0x100)

    def cycle(self, p):
        self.assertEqual(p.init(), 0)
        for direction, requested, label in ((1,1,'4 fps'), (1,2,'6 fps'), (1,3,'8 fps'),
                                            (1,4,'12 fps'), (1,0,'Off'), (-1,4,'12 fps')):
            self.assertEqual(p.press(direction), 0)
            self.assertEqual(p.requested(), requested)
            self.assertEqual(p.call('pump', p.STATE), 0)
            self.assertEqual(p.posted_text(), label)
            self.assertEqual(p.queue[-2][:4], (2,0,p.STATE+60,requested))
            self.assertEqual(p.queue[-1][:3], (2,2,p.STATE+108))

    def test_repeated_right_ok_left_and_wrap(self):
        self.cycle(self.probe())

    def test_fast_keys_coalesce_display_without_losing_selection(self):
        p = self.probe(); self.assertEqual(p.init(), 0)
        for _ in range(9): self.assertEqual(p.press(1), 0)
        self.assertEqual(p.requested(), 4)
        self.assertEqual(p.words(p.STATE+28)[0], 9)
        self.assertEqual(p.call('pump', p.STATE), 0)
        self.assertEqual(len(p.queue), 2)
        self.assertEqual(p.posted_text(), '12 fps')
        self.assertEqual(p.key(1), 0)  # native unchanged-value suppression
        self.assertEqual(p.words(p.STATE+28)[0], 9)

    def test_left_from_off_uses_signed_counter_and_wraps_back(self):
        p = self.probe(); self.assertEqual(p.init(), 0)
        self.assertEqual(p.key(-1), 0)
        self.assertEqual(p.requested(), 4)
        self.assertEqual(p.call('pump', p.STATE), 0)
        self.assertEqual(p.posted_text(), '12 fps')
        self.assertEqual(p.press(1), 0)
        self.assertEqual(p.requested(), 0)
        self.assertEqual(p.call('pump', p.STATE), 0)
        self.assertEqual(p.posted_text(), 'Off')

    def test_collision_preflight_and_allocator_failure_are_sticky(self):
        p = self.probe()
        self.assertEqual(p.register('MV_fpSlitText'), 0)
        self.assertEqual(p.init(), 0x101)
        self.assertEqual(p.words(p.STATE+36)[0], 0)
        p = self.probe(); p.fail_allocation = {p.allocation_calls+1}
        self.assertEqual(p.init(), 0x102)
        self.assertEqual(p.init(), 0x100)

    def test_foreign_subscription_and_invalid_delta_stop_updates(self):
        p = self.probe(); self.assertEqual(p.init(), 0)
        self.assertEqual(p.key(7), 0)  # native setter does not propagate callback error
        self.assertEqual(p.words(p.STATE, 2), (4, 0x104))
        self.assertEqual(p.call('pump', p.STATE), 0x100)
        self.assertEqual(p.queue, [])
        p = self.probe(); self.assertEqual(p.init(), 0)
        _, desc = p.lookup('MV_fpSlitKey')
        pair = p.words(desc+24)[0]
        p.write_words(pair+4, p.CONTEXT)
        self.assertEqual(p.call('pump', p.STATE), 0x103)
        self.assertEqual(p.words(pair+4)[0], p.CONTEXT)

    def test_disable_keeps_borrowed_storage_and_callback_inert(self):
        p = self.probe(); self.assertEqual(p.init(), 0)
        p.call('disable', p.STATE)
        self.assertEqual(p.key(1), 0)
        self.assertEqual(p.requested(), 0)
        self.assertEqual(p.call('pump', p.STATE), 0x100)
        self.assertEqual(p.words(p.STATE)[0], 3)

    def test_mutation_wrong_wrap_is_detected(self):
        source = (HERE/'controller.c').read_text().replace('value == 4 ? 0 : value + 1', 'value == 4 ? 1 : value + 1')
        with self.assertRaises(AssertionError):
            self.cycle(self.probe(build(source)))


if __name__ == '__main__':
    unittest.main()
