#!/usr/bin/env python3
"""One owner-authorized fp L CinemaDNG take with a 560- or 561-byte test GTAG.

Import/help are offline. `--preflight` only reads. `--run` additionally
uploads asm/fpl_gtag560.S into the worker's staging, borrows echo to publish
caches and attach a one-shot observer, presses record once to start and once
to stop, and verifies the observer fired and detached. Never retries a key.

Not a fail-closed gate: nothing can veto the take. The owner accepted card
and clip loss for this experiment (23 October); firmware is never written.
Evidence goes to a new directory given by --out. Test:
projects/gyro2-sup/test_fpl_gtag560.py.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import time

import armasm
import fpl_getfile as gf

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'asm/fpl_gtag560.S'
N = 560          # --n 561 crosses the header padding: H 0x13800 -> 0x13C00
SUBJECT, SLOTS = 0xC31AB0D0, 9
OWNER, CONTEXT = 0xC358E9D8, 0xC31F6ABC
STATES = {1: 'running', 2: 'attached', 3: 'no empty slot', 4: 'already present',
          5: 'unexpected Subject', 6: 'attach did not verify'}


def payload(n):
    head = b'FPL-GTAG-TEST\0' + struct.pack('<I', n)
    return (head + bytes((i * 7 + 3) & 255 for i in range(n)))[:n]


class Log:
    def __init__(self, out):
        self.out, self.events = out, []

    def __call__(self, key, value):
        self.events.append(dict(t=round(time.time(), 3), k=key, v=value))
        (self.out / 'events.json').write_text(json.dumps(self.events, indent=1))
        print(f'{key}: {value}')


def words(io, address, count=1):
    result = io.words(address, count)
    if type(result) is not list or len(result) != count or any(type(v) is not int for v in result):
        raise RuntimeError(f'incomplete word read at {address:#x}')
    return result


def preflight(io, log):
    version = io.sh('version', retries=0)
    if (not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
            not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise RuntimeError(f'expected fp L 3.02: {version!r}')
    publication = words(io, gf.PUBLICATION, 3)
    plan = gf.layout(io.caps(), publication, N, prefix=True)
    log('publication', publication)
    if words(io, gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock')
    context = words(io, CONTEXT, 8)
    log('context', context)
    if context[:2] != [3840, 2160]:
        raise RuntimeError('not the measured 3840x2160 CinemaDNG mode')
    owner = words(io, OWNER, 6)
    log('owner_idle', owner)
    if owner[0] or owner[1] or owner[2]:
        raise RuntimeError('owner not idle: a take may be active')
    a, b = words(io, SUBJECT, SLOTS), words(io, SUBJECT, SLOTS)
    log('subject', a)
    if a != b or 0 not in a:
        raise RuntimeError('Subject unstable or full')
    obj = plan.param + 0x100
    if obj in a:
        raise RuntimeError('our observer is already attached')
    return publication, plan


def run(io, log, publication, plan):
    defines = [f'PARAM={plan.param:#x}', f'SRC={plan.buffer:#x}', f'N={N}']
    code = gf.assemble(SOURCE, defines)
    sym = armasm.symbols(SOURCE, defines)
    if len(code) > gf.CODE_ROOM:
        raise RuntimeError('code exceeds reservation')
    obj, vt = plan.param + 0x100, plan.param + 0x110
    param = bytearray(gf.PARAM_ROOM)
    struct.pack_into('<I', param, 0x100, vt)
    struct.pack_into('<4I', param, 0x110, *(plan.code + sym['ret0'],) * 3,
                     plan.code + sym['observer'])
    for address, data in ((plan.code, code.ljust(gf.CODE_ROOM, b'\0')),
                          (plan.param, bytes(param)),
                          (plan.buffer, payload(N))):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('staging readback mismatch')
    log('uploaded', dict(code=plan.code, param=plan.param, src=plan.buffer, bytes=len(code)))
    if words(io, gf.PUBLICATION, 3) != publication or words(io, gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo changed during upload')
    try:
        for handler in (gf.DCACHE, gf.ICACHE, plan.code):
            gf.set_handler(io, handler)
            gf.echo(io)
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    state = words(io, plan.param, 4)
    log('install', dict(state=STATES.get(state[0], state[0]), subject=state[1],
                        slot=state[2], empty_before=state[3]))
    if state[0] != 2 or words(io, SUBJECT + 4 * state[2]) != [obj]:
        raise RuntimeError('observer not attached; no take started')
    slot = state[2]

    def press(what):
        # One down/up pair; replies may time out although the key lands.
        for key in ('key MOVON', 'key MOVOFF'):
            try:
                log(what, io.sh(key, retries=0, timeout_ms=3000))
            except Exception as error:   # noqa: BLE001 - logged, never retried
                log(what, f'exception {error!r}')
            time.sleep(0.12)

    press('start')
    time.sleep(1.5)
    log('owner_recording', words(io, OWNER, 6))
    log('vars_recording', words(io, plan.param, 14))
    time.sleep(2.0)
    press('stop')
    for _ in range(20):
        time.sleep(0.5)
        owner = words(io, OWNER, 6)
        if not owner[0]:
            break
    log('owner_after_stop', owner)
    v = words(io, plan.param, 14)
    result = dict(calls=v[4], last_mode=v[5], last_type=v[6], fired=v[8],
                  builder=v[9], size_before=v[10], add_return=v[11],
                  size_after=v[12], n=v[13])
    log('observer', result)
    current = words(io, SUBJECT + 4 * slot)[0]
    if current == obj:
        # Did not fire: clear only our own slot, never a snapshot of the list.
        if owner[0]:
            raise RuntimeError('still recording with observer attached; leave it and recover')
        for _ in range(8):
            io.set_word(SUBJECT + 4 * slot, 0)
            if words(io, SUBJECT + 4 * slot) == [0]:
                break
        log('slot_cleared_by_host', words(io, SUBJECT + 4 * slot)[0])
    else:
        log('slot_after', current)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='new evidence directory')
    parser.add_argument('--n', type=int, choices=(560, 561), default=560)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    global N
    N = args.n
    args.out.mkdir(parents=True, exist_ok=False)
    log = Log(args.out)
    (args.out / 'payload.bin').write_bytes(payload(N))
    with gf.staging_lock():
        io = gf.Backend()
        publication, plan = preflight(io, log)
        if args.run:
            result = run(io, log, publication, plan)
            if result['fired'] != 1:
                return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
