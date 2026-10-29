#!/usr/bin/env python3
"""fp L 3.02 cave-free UI guard: bounded task-context inspection.

--inspect executes the same IRQ-masked admission scan as the installer, with
command zero (no UI writes). Owns worker staging until a confirmed return.
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

SOURCE = Path(__file__).parent/'asm/fpl_ui_guard.S'
CODE_ROOM = 0x800
TASK_ROOM = 0x4000


def layout(caps, publication):
    plan = gf.layout(caps, publication, TASK_ROOM, code_room=CODE_ROOM)
    shift = (-plan.code) % 1024
    if plan.buffer+shift+TASK_ROOM+gf.SLACK > publication[0]+publication[1]:
        raise ValueError('aligned task snapshot exceeds staging')
    return gf.Layout(plan.code+shift, plan.param+shift, plan.fobj+shift,
                     plan.buffer+shift, plan.ask)


def build(plan):
    defines = [f'P={plan.param:#x}', f'B={plan.buffer:#x}']
    code = armasm.assemble(SOURCE, defines)
    if len(code) > CODE_ROOM:
        raise RuntimeError('guard exceeds code reservation')
    return code.ljust(CODE_ROOM, b'\0')


def decode(params, tasks):
    p = struct.unpack_from('<11I', params)
    records = []
    for i in range(500):
        row = struct.unpack_from('<8I', tasks, i*32)
        if row[1]:
            records.append(dict(zip(('id', 'state', 'stack_size', 'stack_top',
                                     'saved_sp', 'cpsr', 'pc', 'skip'), row)))
    return dict(command=p[0], result=p[1], cpsr=p[2], midr=p[3], mpidr=p[4],
                l2ctlr=p[5], scanned=p[6], current=p[7], offender=p[8],
                current_seen=p[9], active_frames=p[10], tasks=records)


def inspect(out, main):
    image = get_camera('fp-l-3.02').verify_main(main)
    out.mkdir(exist_ok=False)
    with gf.staging_lock():
        io = gf.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version:
            raise RuntimeError('fp L 3.02 required')
        publication = io.words(gf.PUBLICATION, 3)
        plan = layout(io.caps(), publication)
        code = build(plan)
        import fpl_ui
        before = {name: io.words(site, 2) for name, site in fpl_ui.STRING_SITES.items()}
        for name, site in fpl_ui.STRING_SITES.items():
            if struct.pack('<2I', *before[name]) != image[site-0xC0000000:site-0xC0000000+8]:
                raise RuntimeError('non-stock string site')
        record = dict(kind='fpl-ui-inspect-v1', publication=publication,
                      layout=vars(plan), sha256=hashlib.sha256(code).hexdigest(),
                      version=version, sites_before=before)
        durable(out/'guard.bin', code)
        durable(out/'manifest.json', json.dumps(record, indent=2).encode())
        pending = gf.LOCK_PATH.with_suffix('.pending')
        durable(pending, json.dumps(dict(record, out=str(out.resolve()))).encode())
        for at, data in ((plan.code, code), (plan.param, bytes(1024)),
                         (plan.buffer, bytes(TASK_ROOM))):
            io.write(at, data)
            if io.read(at, len(data)) != data:
                raise RuntimeError('guard readback mismatch')
        for target in (gf.DCACHE, gf.ICACHE, plan.code, gf.DCACHE):
            execute(io, target)
        params, tasks = io.read(plan.param, 1024), io.read(plan.buffer, TASK_ROOM)
        durable(out/'params.bin', params)
        durable(out/'tasks.bin', tasks)
        report = decode(params, tasks)
        if (io.read(plan.code, len(code)) != code or
                io.words(gf.PUBLICATION, 3) != publication or
                io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK] or
                any(io.words(site, 2) != before[name] for name, site in fpl_ui.STRING_SITES.items())):
            raise RuntimeError('guard identity/restoration mismatch')
        report['final_version'] = io.sh('version', retries=0)
        durable(out/'result.json', json.dumps(report, indent=2).encode())
        pending.unlink()  # no resident pointers: finite diagnostic returned
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inspect', action='store_true', required=True)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.out, args.main)
    print(json.dumps({k: v for k, v in report.items() if k != 'tasks'}, indent=2))
