"""Offline relocation: one assembled body, separately initialized local refs.

No Backend, allocation/free, firmware stores or camera invocation. Run from
fp_usb_shell with the configured ARM assembler and Unicorn available.
"""
from contextlib import nullcontext
from dataclasses import replace
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fpl_gyro_latched as lat
import test_fpl_gyro_latched as fixture
from test_fpl_gyro_latched import CAPS, PUB, Fake, emulate


class RuntimeSemantics(fixture.Payload):
    """Run the existing ARM ledger/window/hidden-lap/ABI cases in runtime mode."""
    @classmethod
    def setUpClass(cls):
        cls.plan = lat.layout(CAPS, PUB, 1200)
        cls.code, cls.syms = lat.code_for(cls.plan, 1200, runtime=True)


class Relocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.body, cls.syms = lat.runtime_body()
        cls.template = cls.body.ljust(lat.CODE_ROOM, b'\0')
        old = lat.layout(CAPS, PUB, 1200)
        cls.plans = [replace(old, code=base, state=base+0x4000, output=base+0x8000)
                     for base in (0x46020000, 0x53070000)]

    def refs(self, plan, capacity=1200):
        return [plan.state, lat.STATE_ROOM, plan.output, plan.output_room, capacity]

    def run_body(self, plan, **kwargs):
        # Exactly the same bytes are copied at each base. Only the data table
        # is initialized afterward by the caller, never instructions/fixups.
        return emulate(self.template, self.syms, plan,
                       runtime_refs=self.refs(plan), poison_old=True, **kwargs)

    def test_identical_body_two_unrelated_bases_and_poisoned_old_placement(self):
        results = []
        for plan in self.plans:
            result = self.run_body(plan)
            report = lat.decode(*result[:2], 1200)
            self.assertEqual(report['status_code'], 100)
            self.assertEqual(report['proven_valid_records'], 0)
            self.assertEqual(result[1][:report['appended_records']*8],
                             b''.join(data for _, data in result[3]))
            expected, syms = lat.code_for(plan, 1200, runtime=True)
            lat.verify_code(expected, result[2], syms)
            canonical = bytearray(expected[:len(self.body)])
            canonical[syms['runtime_refs']:syms['runtime_refs_end']] = bytes(20)
            self.assertEqual(bytes(canonical), self.body)
            results.append(result[:2])
        self.assertEqual(results[0], results[1])

    def test_local_slot_seams_match_absolute_drain(self):
        for plan in self.plans:
            fixed, syms = lat.code_for(plan, 1200)
            absolute = emulate(fixed, syms, plan, poison_old=True, start=598, step=3, pad=7)
            local = self.run_body(plan, start=598, step=3, pad=7)
            self.assertEqual(local[:2], absolute[:2])
            self.assertEqual(lat.decode(*local[:2], 1200), lat.decode(*absolute[:2], 1200))

    def test_conflicting_slots_rejected_and_no_macro_pollution(self):
        for conflicting in ('GYRO_DESC_PTR=0x45000000', 'GYRO_LATCHED_HEAD_PTR=0x45000004'):
            with self.subTest(option=conflicting), patch('sys.stderr', new=io.StringIO()):
                with self.assertRaises(SystemExit):
                    lat.armasm.assemble(lat.SOURCE, ['RUNTIME_REFS=1', conflicting])
        shared = lat.SOURCE.parent.parent.parent/'gyro/gyro_drain.S'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'clean-options.S'
            source.write_text(fixture.mutation_source().replace('"../../gyro/gyro_drain.S"', f'"{shared}"') + '''
#if defined(GYRO_DESC_LOCAL) || defined(GYRO_LATCH_LOCAL) || defined(movw) || defined(movt)
#error "local options or mnemonics leaked from include"
#endif
    movw r0, #0x1234
    movt r0, #0x5678
''')
            body = lat.armasm.assemble(source, ['RUNTIME_REFS=1'])
            self.assertEqual(body[:-8], self.body)
            self.assertEqual(body[-8:], bytes.fromhex('340201e3780645e3'))

    def test_wrong_local_slot_mutations_fail_ledger(self):
        shared = lat.SOURCE.parent.parent.parent/'gyro/gyro_drain.S'
        with tempfile.TemporaryDirectory() as directory:
            drain = Path(directory)/'drain.S'
            source = Path(directory)/'latched.S'
            source.write_text(fixture.mutation_source().replace('"../../gyro/gyro_drain.S"', f'"{drain}"'))
            for old, new in (('adr     r0, GYRO_DESC_LOCAL', 'adr     r0, descriptor'),
                             ('adr     r5, GYRO_LATCH_LOCAL', 'adr     r5, g_gcount')):
                text = shared.read_text()
                self.assertEqual(text.count(old), 1)
                drain.write_text(text.replace(old, new).replace(
                    '"imu_stream.inc.S"', f'"{shared.parent}/imu_stream.inc.S"'))
                with patch.object(lat, 'SOURCE', source):
                    body, syms = lat.runtime_body()
                result = emulate(body.ljust(lat.CODE_ROOM, b'\0'), syms, self.plans[0],
                                 runtime_refs=self.refs(self.plans[0]), poison_old=True)
                with self.assertRaisesRegex(RuntimeError, 'unlatched cursor'):
                    lat.decode(*result[:2], 1200)

    def test_runtime_invalid_refs_no_stores_no_source_reads(self):
        p = self.plans[0]
        good = self.refs(p)
        changes = [(0, 0), (0, p.state+1), (0, p.code), (0, p.output),
                   (0, 0xfffffc00), (0, 0xc31e23cc), (0, 0x7ffffc00),
                   (1, 0), (1, 2047), (1, 2049), (1, 0xffffffff),
                   (2, p.code), (2, p.state), (2, p.output+1),
                   (2, 0xfffffff8), (2, 0x2e00644c), (2, 0x7ffff800),
                   (3, 0), (3, 1200*8+1023), (3, 0xffffffff),
                   (4, 0), (4, 12001), (4, 0xffffffff)]
        for index, value in changes:
            refs = good.copy()
            refs[index] = value
            with self.subTest(index=index, value=hex(value)):
                emulate(self.template, self.syms, p, runtime_refs=refs,
                        rejected=True, poison_old=True)
        emulate(self.template, self.syms, p, runtime_refs=[0]*5,
                rejected=True, poison_old=True)

    def test_dynamic_capacity_same_body(self):
        p = self.plans[1]
        for capacity in (1, 55, 12000):
            plan = replace(p, output_room=((capacity*8+1023)//1024+1)*1024)
            result = emulate(self.template, self.syms, plan, capacity,
                             runtime_refs=self.refs(plan, capacity), poison_old=True)
            report = lat.decode(*result[:2], capacity)
            self.assertEqual(report['proven_valid_records'], 0)
            if capacity < 1200:
                self.assertEqual(report['status_code'], 5)
                self.assertEqual(report['appended_records'], capacity)

    def test_reference_table_is_immutable_and_mask_is_exact(self):
        expected, syms = lat.code_for(self.plans[0], 1200, runtime=True)
        mutable = {syms[k]+i for k in lat.MUTABLE for i in range(4)}
        for at in range(len(expected)):
            changed = bytearray(expected)
            changed[at] ^= 1
            if at in mutable:
                lat.verify_code(expected, changed, syms)
            else:
                with self.assertRaises(RuntimeError):
                    lat.verify_code(expected, changed, syms)

    def test_mutated_reference_load_and_validation_fail_independent_oracles(self):
        shared = lat.SOURCE.parent.parent.parent/'gyro/gyro_drain.S'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'latched.S'
            text = fixture.mutation_source().replace('"../../gyro/gyro_drain.S"', f'"{shared}"')
            # Mutations are temporary source copies; production files stay intact.
            for old, new, invalid in (
                ('ldr r4, runtime_state', 'ldr r4, =0x45014000', False),
                ('cmp r6, #1\n    bxlo lr', 'cmp r6, #1\n    nop', True)):
                source.write_text(text.replace(old, new))
                with patch.object(lat, 'SOURCE', source):
                    body, syms = lat.runtime_body()
                refs = self.refs(self.plans[0])
                if invalid:
                    refs[4] = 0
                with self.assertRaises(AssertionError):
                    emulate(body.ljust(lat.CODE_ROOM, b'\0'), syms, self.plans[0],
                            runtime_refs=refs, rejected=invalid, poison_old=True)

    def test_actual_shared_drain_mutation_is_detected_at_relocated_base(self):
        shared = lat.SOURCE.parent.parent.parent/'gyro/gyro_drain.S'
        with tempfile.TemporaryDirectory() as directory:
            drain = Path(directory)/'drain.S'
            text = shared.read_text()
            self.assertEqual(text.count('add     r6, r6, #8'), 1)
            drain.write_text(text.replace('add     r6, r6, #8', 'add     r6, r6, #0').replace(
                '"imu_stream.inc.S"', f'"{shared.parent}/imu_stream.inc.S"'))
            source = Path(directory)/'latched.S'
            source.write_text(fixture.mutation_source().replace('"../../gyro/gyro_drain.S"', f'"{drain}"'))
            with patch.object(lat, 'SOURCE', source):
                body, syms = lat.runtime_body()
            result = emulate(body.ljust(lat.CODE_ROOM, b'\0'), syms, self.plans[1],
                             runtime_refs=self.refs(self.plans[1]), advance=0, poison_old=True)
            report = lat.decode(*result[:2], 1200)
            with self.assertRaises(AssertionError):
                self.assertEqual(result[1][:report['appended_records']*8],
                                 b''.join(data for _, data in result[3]))

    def run_host(self, fake):
        with patch.object(lat.gf, 'staging_lock', return_value=nullcontext()), \
             patch.object(lat.gf, 'Backend', side_effect=AssertionError('live forbidden')):
            return lat.capture(fake, runtime=True)

    def test_runtime_host_hash_readback_and_restoration(self):
        fake = Fake(runtime=True)
        report, _, _ = self.run_host(fake)
        self.assertEqual(report['stable_body_sha256'], hashlib.sha256(self.body).hexdigest())
        self.assertEqual(report['placement_mode'], 'runtime_refs')
        self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)
        self.assertEqual([h for c, h, _ in fake.calls if c == 'echo'],
                         [lat.gf.DCACHE, lat.gf.ICACHE, fake.plan.code])
        for mode in ('refs', 'latch', 'output', 'short', 'timeout', 'restore', 'upload'):
            fake = Fake(runtime=True)
            if mode == 'timeout':
                fake.fail_handler = fake.plan.code
            elif mode == 'restore':
                fake.restore_failure = True
            elif mode == 'upload':
                fake.bad_upload = True
            else:
                def mutate(f):
                    if mode == 'short':
                        f.memory[f.plan.state] = f.memory[f.plan.state][:-4]
                    else:
                        at, off = ((f.plan.output, f.plan.output_room-1) if mode == 'output'
                                   else (f.plan.code, self.syms['runtime_refs' if mode == 'refs'
                                                              else 'g_latched_head']))
                        f.memory[at][off] ^= 1
                fake.mutate = mutate
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                self.run_host(fake)
            if mode != 'restore':
                self.assertEqual(fake.handler, lat.gf.ECHO_STOCK)
            if mode == 'upload':
                self.assertEqual(fake.sets, [])


if __name__ == '__main__':
    unittest.main()
