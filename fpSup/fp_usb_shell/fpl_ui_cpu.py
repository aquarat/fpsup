#!/usr/bin/env python3
"""Finite fp L CPU register diagnostic, without installing any UI hooks.

Uses interlocked worker staging and retains an uncertainty marker on failure.
Import/build are offline. --out NEW_DIR performs one live diagnostic.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import armasm
import fpl_getfile as gf
from fpl_gyro_task import durable
from fpl_vd_probe import execute
from firmware import get_camera

SOURCE = Path(__file__).parent/'asm/fpl_ui_cpu.S'


def decode(raw):
    state, cpsr, midr, mpidr, l2ctlr = struct.unpack_from('<5I', raw)
    if state not in (2, 3) or any(raw[20:]):
        raise ValueError('incomplete or corrupted CPU diagnostic')
    a7 = midr & 0xFF0FFFF0 == 0x410FC070
    if (state == 2) != a7:
        raise ValueError('MIDR disagrees with L2CTLR validity')
    return dict(state=state, cpsr=hex(cpsr), midr=hex(midr), mpidr=hex(mpidr),
                l2ctlr=hex(l2ctlr) if a7 else None,
                cluster_cpus=((l2ctlr >> 24) & 3)+1 if a7 else None,
                # One cluster's count alone does not describe a multi-cluster SoC.
                hardware_exclusion_proven=False)


def run(out, main):
    get_camera('fp-l-3.02').verify_main(main)
    out.mkdir(exist_ok=False)
    with gf.staging_lock():
        io = gf.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version:
            raise RuntimeError('fp L 3.02 required')
        publication = io.words(gf.PUBLICATION, 3)
        plan = gf.layout(io.caps(), publication, 1024)
        if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
            raise RuntimeError('echo not stock')
        code = armasm.assemble(SOURCE, [f'P={plan.param:#x}'])
        if len(code) > gf.CODE_ROOM:
            raise RuntimeError('diagnostic exceeds reservation')
        code = code.ljust(gf.CODE_ROOM, b'\0')
        manifest = dict(kind='fpl-ui-cpu-v1', publication=publication,
                        code=plan.code, param=plan.param, version=version,
                        sha256=hashlib.sha256(code).hexdigest())
        durable(out/'probe.bin', code)
        durable(out/'manifest.json', json.dumps(manifest, indent=2).encode())
        pending = gf.LOCK_PATH.with_suffix('.pending')
        durable(pending, json.dumps(dict(manifest, out=str(out.resolve()))).encode())
        for address, data in ((plan.code, code), (plan.param, bytes(gf.PARAM_ROOM))):
            io.write(address, data)
            if io.read(address, len(data)) != data:
                raise RuntimeError('diagnostic readback mismatch')
        for address in (gf.DCACHE, gf.ICACHE, plan.code, gf.DCACHE):
            execute(io, address)
        raw = io.read(plan.param, gf.PARAM_ROOM)
        durable(out/'result.bin', raw)
        report = decode(raw)
        if (io.read(plan.code, len(code)) != code or
                io.words(gf.PUBLICATION, 3) != publication or
                io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]):
            raise RuntimeError('diagnostic identity/restoration mismatch')
        report['final_version'] = io.sh('version', retries=0)
        durable(out/'result.json', json.dumps(report, indent=2).encode())
        pending.unlink()  # finite entry returned; no pointer/callback escaped
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.out, args.main), indent=2))
