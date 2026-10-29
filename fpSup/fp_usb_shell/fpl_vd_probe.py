#!/usr/bin/env python3
"""Finite fp L 3.02 frame-sync capture with optional bounded timing override.

--run installs a RAM callback in the empty early-Vd slot, captures a bounded
number of interrupts and removes it. Staging is interlocked throughout. Raw
evidence belongs outside the repository. --teardown recovers this tool's marker
only. --interval-scale changes timing04 temporarily; --record creates a
CinemaDNG take. No boot changes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct
import time

import armasm
import fpl_getfile as gf
from fpl_gtagpf import Log, words

SOURCE = Path(__file__).parent / 'asm/fpl_vd_probe.S'
SLOT = 0xC31D6DD8
MARKER = gf.LOCK_PATH.with_suffix('.pending')
SCHEMA = 'fpl-vd-probe-v1'
CODE_ROOM = 0x400


def record_marker(record):
    import os
    fd = os.open(MARKER, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(dict(record, schema=SCHEMA), f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def execute(io, address):
    if words(io, gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo not stock')
    try:
        gf.set_handler(io, address)
        gf.echo(io)
    finally:
        current = words(io, gf.ECHO_SLOT)[0]
        if current == address:
            gf.set_handler(io, gf.ECHO_STOCK)
        elif current != gf.ECHO_STOCK:
            raise RuntimeError('echo changed owner; retained marker')


def teardown(io, log, record):
    if words(io, gf.PUBLICATION, 3) != record['publication']:
        raise RuntimeError('publication changed; retained marker')
    code, param, callback = (record[k] for k in ('code', 'param', 'callback'))
    body = io.read(code, CODE_ROOM)
    if hashlib.sha256(body).hexdigest() != record['sha256']:
        raise RuntimeError('resident probe bytes changed; retained marker')
    if words(io, SLOT)[0] not in (0, callback):
        raise RuntimeError('foreign callback; retained marker')
    # CPU word store does not round the write into the live parameter block.
    io.set_word(param, 1)
    if words(io, param) != [1]:
        raise RuntimeError('detach command did not verify')
    execute(io, code)
    state = words(io, param, 12)
    log('detached', state)
    if state[1] != 3 or words(io, SLOT) != [0]:
        raise RuntimeError('detach not confirmed; retained marker')
    if state[2] and state[4] != state[5]:
        raise RuntimeError('IRQ and shell ran on different CPUs; staging remains retained')
    MARKER.unlink()
    log('marker_removed', str(MARKER))


def analyse(raw, frequency):
    records = list(struct.iter_unpack('<8I', raw))
    if len(records) < 2 or frequency <= 0:
        raise ValueError('need two records and positive timer frequency')
    ticks = [r[1] for r in records]
    if any(t >= frequency for t in ticks):
        raise ValueError('timer sample exceeds its one-second period')
    intervals = [((b-a) % frequency) / frequency for a, b in zip(ticks, ticks[1:])]
    # This bounded idle diagnostic assumes <1s between callbacks. Epoch values
    # expose gross gaps; sub-second wrap is handled without an IRQ epoch race.
    if any(((b[0]-a[0]) & 0xFFFFFFFF) > 1 for a, b in zip(records, records[1:])):
        raise ValueError('multi-second gap; modulo-timer cadence is ambiguous')
    if not all(intervals):
        raise ValueError('zero interval or whole-second alias')
    groups = {}
    for a, b, dt in zip(records, records[1:], intervals):
        if a[3:5] == b[3:5]:
            groups.setdefault(a[3:5], []).append(dt)
    phases = []
    for (t04, t20), values in groups.items():
        a, b, c = (t04 >> 16)+1, (t04 & 0xFFFF)+1, (t20 >> 16)+1
        phases.append(dict(timing04=f'{t04:08x}', timing20=f'{t20:08x}',
                           intervals=len(values), measured_hz=1/statistics.mean(values),
                           median_interval_ms=statistics.median(values)*1000,
                           predicted_72MHz_interval_ms=(a*(c-1)+b)/72000))
    return dict(records=len(records), timer_hz=frequency,
                median_interval_ms=statistics.median(intervals)*1000,
                min_interval_ms=min(intervals)*1000, max_interval_ms=max(intervals)*1000,
                measured_hz=1/statistics.mean(intervals),
                timing04=sorted({f'{r[3]:08x}' for r in records}),
                timing20=sorted({f'{r[4]:08x}' for r in records}),
                irq_modes=sorted({r[6] & 31 for r in records}),
                cpus=sorted({r[7] for r in records}),
                epoch_crossings=sum(r[0] != r[2] for r in records),
                phases=phases,
                intervals_ms=[v*1000 for v in intervals])


def run(io, log, out, count, scale=1.0, recording=False):
    version = io.sh('version', retries=0)
    if not (re.search(r'\bmodel\s*=\s*w91c1\b', version) and
            re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise RuntimeError('expected fp L 3.02')
    log('version', version)
    publication = words(io, gf.PUBLICATION, 3)
    plan = gf.layout(io.caps(), publication, count*32, prefix=True)
    table = words(io, SLOT-4, 5)
    owner = words(io, 0xC358E9D8, 6)
    log('callback_table', table)
    log('owner', owner)
    if table != [0xC0325758, 0, 1, 0, 0] or bool(any(owner[:3])) != recording:
        raise RuntimeError('unexpected recorder state or callback table')
    if words(io, gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo not stock')
    if words(io, 0xC30337EC) != [0x2D810000]:
        raise RuntimeError('unexpected timer base')
    frequency = words(io, 0xC2F09408)[0]
    if frequency != 12000000:
        raise RuntimeError('unexpected timer frequency')
    timing04, timing20 = words(io, 0x30100004)[0], words(io, 0x30100020)[0]
    defines = [f'PARAM={plan.param:#x}', f'BUFFER={plan.buffer:#x}']
    trial04 = timing04
    if scale != 1:
        a, b = (timing04 >> 16)+1, (timing04 & 0xFFFF)+1
        aa, bb = round(a*scale), round(b*scale)
        if not (a <= aa <= 65536 and b <= bb <= 65536):
            raise ValueError('scaled intervals outside 16-bit bounds')
        trial04 = ((aa-1) << 16) | (bb-1)
        defines.append('TIMING_TEST=1')
        log('timing_trial', dict(scale=scale, before=hex(timing04), trial=hex(trial04)))
    code = armasm.assemble(SOURCE, defines)
    sym = armasm.symbols(SOURCE, defines)
    if len(code) > CODE_ROOM:
        raise RuntimeError('code exceeds staging reservation')
    code = code.ljust(CODE_ROOM, b'\0')
    param = bytearray(gf.PARAM_ROOM)
    struct.pack_into('<8I', param, 0, 0, 0, 0, count, 0, 0, timing04, timing20)
    struct.pack_into('<I', param, 36, trial04)
    record = dict(publication=publication, code=plan.code, param=plan.param,
                  callback=plan.code+sym['callback'], buffer=plan.buffer,
                  count=count, sha256=hashlib.sha256(code).hexdigest(),
                  timing04=timing04, timing20=timing20, trial04=trial04, scale=scale)
    (out/'probe.bin').write_bytes(code)
    (out/'manifest.json').write_text(json.dumps(record, indent=2))
    record_marker(record)
    log('marker', record)
    # On any uncertain upload/entry outcome keep staging reserved. --teardown
    # checks the exact body before executing it; it never uploads over a hook.
    for address, data in [(plan.code, code), (plan.param, bytes(param)),
                          (plan.buffer, bytes(count*32 + 1024))]:
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('upload readback differs')
    for handler in (gf.DCACHE, gf.ICACHE):
        execute(io, handler)
    if words(io, gf.PUBLICATION, 3) != publication:
        raise RuntimeError('publication changed')
    try:
        execute(io, plan.code)
        deadline = time.monotonic() + max(15, scale*4)
        while True:
            state = words(io, plan.param, 9)
            if state[1] != 1 or time.monotonic() >= deadline:
                break
            time.sleep(.2)
        log('capture_state', state)
        if state[1] != 2 or state[2] != count or words(io, SLOT) != [0]:
            raise RuntimeError('finite capture did not complete')
    finally:
        teardown(io, log, record)
    execute(io, gf.DCACHE)
    raw = io.read(plan.buffer, count*32)
    (out/'records.bin').write_bytes(raw)
    report = analyse(raw, frequency)
    (out/'analysis.json').write_text(json.dumps(report, indent=2))
    log('analysis', {k: v for k, v in report.items() if k != 'intervals_ms'})
    log('final_callback_table', words(io, SLOT-4, 5))
    log('final_timing', [words(io, 0x30100004)[0], words(io, 0x30100020)[0]])
    log('final_version', io.sh('version', retries=0))


def press_record(io, log, label):
    for key in ('MOVON', 'MOVOFF'):
        try:
            log(label+'_'+key, io.sh('key '+key, retries=0, timeout_ms=3000))
        except Exception as error:
            log(label+'_'+key, repr(error))
        time.sleep(.12)


def recording_run(io, log, out, count, scale):
    owner = words(io, 0xC358E9D8, 6)
    if any(owner[:3]) or io.sh('menu SetRecMode', retries=0).strip() != '1':
        raise RuntimeError('must start idle in CINE')
    if io.sh('menu SetMovRecFormat', retries=0).strip() != '0':
        raise RuntimeError('CinemaDNG required')
    log('cinema_before', io.sh('dir \\CINEMA', retries=0))
    try:
        press_record(io, log, 'start')
        for _ in range(20):
            time.sleep(.2)
            if any(words(io, 0xC358E9D8, 3)):
                break
        else:
            raise RuntimeError('record start not observed; no toggle retry')
        time.sleep(.5)
        log('imager_recording', io.sh('imager mode_now', retries=0))
        run(io, log, out, count, scale, recording=True)
    finally:
        if any(words(io, 0xC358E9D8, 3)):
            press_record(io, log, 'stop')
            for _ in range(30):
                time.sleep(.5)
                if not any(words(io, 0xC358E9D8, 3)):
                    break
            else:
                raise RuntimeError('recorder still active after one stop press')
        log('cinema_after', io.sh('dir \\CINEMA', retries=0))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument('--run', action='store_true')
    action.add_argument('--teardown', action='store_true')
    p.add_argument('--count', type=int, default=120)
    p.add_argument('--interval-scale', type=float, default=1.0,
                   help='experimental interval multiplier for 80 callbacks, then automatic restore')
    p.add_argument('--record', action='store_true', help='make one CinemaDNG take around the capture')
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if not 2 <= args.count <= 600:
        p.error('count must be 2..600')
    if not 1 <= args.interval_scale <= 6:
        p.error('bounded experiment range is 1..6 (not a supported product range)')
    if args.interval_scale != 1 and args.count < 100:
        p.error('timing trial needs at least 100 observations')
    args.out.mkdir(parents=True, exist_ok=False)
    log = Log(args.out)
    with gf.staging_lock(permit_pending=args.teardown):
        io = gf.Backend()
        if args.teardown:
            record = json.loads(MARKER.read_text())
            if record.get('schema') != SCHEMA:
                raise RuntimeError('marker belongs to another tool')
            teardown(io, log, record)
        else:
            if args.record:
                recording_run(io, log, args.out, args.count, args.interval_scale)
            else:
                run(io, log, args.out, args.count, args.interval_scale)


if __name__ == '__main__':
    main()
