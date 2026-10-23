"""Offline binding dispatch tests; real fp L services behind synthetic bridges.

Alternate addresses test linkage, not another camera's native ABI.
"""
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from unicorn import arm_const as ar
import test_fpl_gyro_task_retained as retained

base = retained.base
CORE = Path(__file__).resolve().parents[1]/'gyro/retained_task.inc.S'
BINDINGS = dict(RT_CREATE=base.CREATE, RT_ATTACH=base.ATTACH,
                RT_REF_TSK=retained.audit.REF_TASK, RT_REF_FLG=retained.audit.REF_FLAG,
                RT_DCACHE=0xC000E91C, RT_ICACHE=0xC000EABC)
ALTERNATE = {name: base.STOP+0x800+i*16 for i, name in enumerate(BINDINGS)}


def build(bindings):
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory)/'bindings.S'
        source.write_text(''.join(f'#define {k} {v}\n' for k, v in bindings.items())+
                          f'#include "{CORE}"\n')
        return retained.build(source)


class BoundMachine(retained.Machine):
    def __init__(self, image, artifact):
        self.dispatches = []
        self.bridged = None
        super().__init__(image, artifact)

    def execute(self, m, pc, size, unused):
        if pc in ALTERNATE.values():
            name = next(k for k, v in ALTERNATE.items() if v == pc)
            self.dispatches.append(name)
            self.bridged = BINDINGS[name]
            m.reg_write(ar.UC_ARM_REG_PC, self.bridged)
            return
        if pc in BINDINGS.values():
            lr = m.reg_read(ar.UC_ARM_REG_LR)
            from_wrapper = (base.STAGING <= lr < base.STAGING+0x1000 or
                            base.OWNED+0x1000 <= lr < base.OWNED+0x2000)
            if from_wrapper:
                assert self.bridged == pc, 'direct old binding reached'
                self.bridged = None
        super().execute(m, pc, size, unused)


class Bindings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = base.MAIN.read_bytes()
        retained.audit.fingerprint(cls.image)

    def test_each_missing_binding_fails_assembly(self):
        for missing in BINDINGS:
            with self.subTest(missing=missing), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    build({k: v for k, v in BINDINGS.items() if k != missing})

    def test_explicit_default_core_matches_adapter_bytes_and_symbols(self):
        actual, expected = build(BINDINGS), retained.build()
        self.assertEqual(actual[0], expected[0])
        self.assertEqual(actual[1], expected[1])

    def test_alternate_dispatches_all_services_and_retains_native_behavior(self):
        m = BoundMachine(self.image, build(ALTERNATE))
        m.call('entry')
        self.assertEqual(m.dispatches, ['RT_DCACHE', 'RT_ICACHE', 'RT_CREATE'])
        m.poison_staging()
        self.assertEqual(m.observe(), 7)
        m.call('activate')
        m.wakes += 1
        m.run_task()
        self.assertEqual(m.observe(), 15)
        self.assertEqual(m.capture_calls, 1)
        self.assertEqual(m.body_calls, 2)
        m.retained_readback()
        self.assertEqual(m.dispatches.count('RT_ATTACH'), 1)
        self.assertEqual(m.dispatches.count('RT_REF_TSK'), 4)
        self.assertEqual(m.dispatches.count('RT_REF_FLG'), 4)
        self.assertEqual(set(m.dispatches), set(BINDINGS))

    def test_each_hardcoded_old_binding_mutation_is_trapped(self):
        for name in BINDINGS:
            with self.subTest(name=name):
                bindings = dict(ALTERNATE, **{name: BINDINGS[name]})
                m = BoundMachine(self.image, build(bindings))
                with self.assertRaisesRegex(AssertionError, 'direct old binding'):
                    m.call('entry')
                    m.poison_staging()
                    m.call('activate')
                    m.observe()


if __name__ == '__main__':
    unittest.main()
