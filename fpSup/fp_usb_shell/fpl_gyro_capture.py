#!/usr/bin/env python3
"""Finite idle fp L 3.02 gyro observer.

Live October 20: shared drain copied 164 records, detected head movement,
stopped with stale status, and restored echo. Full capture remains unverified.

Running --out NEW_DIR operates an authorized idle camera once. Import/help are
offline. No hooks, recording, sensor initialization or card I/O. Observed head
deltas do not establish sample rate, freshness, atomicity or lossless capture.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
import time

import armasm
import fpl_getfile as gf

SOURCE = Path(__file__).resolve().parent / 'asm/fpl_gyro_capture.S'
CODE_ROOM, STATE_ROOM = 4096, 1024
MAGIC, RING = 0x50414347, 0x2E00644C
SENTINEL = b'\xa5'
STATUS = {1: 'finished', 2: 'no_observed_motion', 3: 'unavailable_descriptor',
          4: 'invalid_descriptor', 5: 'invalid_ring', 6: 'invalid_head',
          7: 'stale_during_drain'}
MUTABLE = ('g_ghead', 'g_gcount', 'g_padbad', 'descriptor_ptr', 'descriptor_ring')


def validate_capacity(capacity):
    if type(capacity) is not int or not 1 <= capacity <= 12000:
        raise ValueError('capacity must be an integer in 1..12000')
    return capacity


@dataclass(frozen=True)
class Layout:
    code: int
    state: int
    output: int
    output_room: int


def layout(caps, publication, capacity):
    validate_capacity(capacity)
    # Reuse the publication/MCAPS validation, not its smaller code allocation.
    gf.layout(caps, publication, 0)
    pool, room, _ = publication
    # Owned staging begins at +0x10000. Align upward within that reservation;
    # the published allocation itself need only be word-aligned.
    code = (pool + gf.STAGING_OFFSET + 1023) & ~1023
    state, output = code + CODE_ROOM, code + CODE_ROOM + STATE_ROOM
    output_room = ((capacity * 8 + 1024 + 1023) // 1024) * 1024
    extents = [(code, CODE_ROOM), (state, STATE_ROOM), (output, output_room)]
    if any(a % 1024 or a < pool + gf.STAGING_OFFSET or a+n > pool+room
           for a, n in extents):
        raise ValueError('capture reservations exceed aligned writable staging')
    if any(a < b+m and b < a+n for i, (a, n) in enumerate(extents)
           for b, m in extents[i+1:]):
        raise ValueError('overlapping capture reservations')
    return Layout(code, state, output, output_room)


def code_for(plan, capacity):
    validate_capacity(capacity)
    defines = [f'CODE={plan.code:#x}', f'STATE={plan.state:#x}',
               f'OUTPUT={plan.output:#x}', f'CAPACITY={capacity}']
    code = armasm.assemble(SOURCE, defines)
    symbols = armasm.symbols(SOURCE, defines)
    if not code or len(code) > CODE_ROOM or symbols.get('capture') != 0:
        raise ValueError('invalid capture code extent/entry')
    offsets = [symbols[name] for name in MUTABLE]
    if len(set(offsets)) != len(offsets) or any(o % 4 or not 0 <= o <= len(code)-4 for o in offsets):
        raise ValueError('invalid mutable symbol offsets')
    return code.ljust(CODE_ROOM, b'\0'), symbols


def verify_code(expected, actual, symbols):
    if len(actual) != len(expected):
        raise RuntimeError('short code readback')
    masked = bytearray(actual)
    for name in MUTABLE:
        offset = symbols[name]
        masked[offset:offset+4] = expected[offset:offset+4]
    if masked != expected:
        raise RuntimeError('static code or descriptor guard changed')


def head_valid(head):
    return 8 <= head - RING <= 0x12c0 and (head - RING) % 8 == 0


def decode(state, output, capacity):
    validate_capacity(capacity)
    if len(state) != STATE_ROOM or len(output) < capacity*8 + 1024:
        raise RuntimeError('short capture readback')
    magic, status, iterations, count, observed, padbad, dropped, unchanged = struct.unpack_from('<8I', state)
    if magic != MAGIC or status not in STATUS:
        raise RuntimeError('capture completion marker/status missing')
    if iterations > 20 or count > capacity or padbad > count or unchanged > max(0, iterations-1):
        raise RuntimeError('capture counts out of bounds')
    if observed != count + dropped or (dropped and count != capacity):
        raise RuntimeError('inconsistent capacity accounting')
    if any(state[192:]) or output[count*8:] != SENTINEL * (len(output)-count*8):
        raise RuntimeError('state guard or output tail sentinel changed')
    pre = list(struct.unpack_from('<20I', state, 32))
    post = list(struct.unpack_from('<20I', state, 112))
    if any(not head_valid(pre[i]) or pre[i] != post[i] for i in range(iterations)):
        raise RuntimeError('invalid completed head observations')
    if any(pre[min(iterations+1, 20):]) or any(post[min(iterations+1, 20):]):
        raise RuntimeError('unused head slots changed')
    if status in (1, 2):
        delta = sum(((pre[i]-pre[i-1]) % 0x12c0)//8 for i in range(1, 20))
        if iterations != 20 or observed != delta or (status == 2) != (observed == 0):
            raise RuntimeError('inconsistent finished capture')
        if unchanged != sum(pre[i] == pre[i-1] for i in range(1, 20)):
            raise RuntimeError('inconsistent unchanged-head count')
    elif iterations == 20:
        raise RuntimeError('error after all iterations completed')
    records = [list(struct.unpack_from('<hhHh', output, i*8)) for i in range(count)]
    if any(r[2] != 0 for r in records):
        raise RuntimeError('unexpected gyro record tag')
    return dict(status_code=status, status=STATUS[status], iterations_completed=iterations,
                capacity=capacity, appended_records=count, observed_delta_count=observed,
                copied_nonzero_padding_count=padbad, dropped_for_capacity=dropped,
                unchanged_head_observations=unchanged, heads_before=pre, heads_after=post,
                records_chronological_order=records,
                record_fields=['component_0', 'component_1', 'tag', 'component_2'],
                diagnostic_only=status not in (1, 2), last_batch_invalid=status == 7,
                limitations=['equal heads may hide whole laps; no lossless or rate claim',
                             'no atomicity, freshness, timestamp or physical-axis proof',
                             'on error all output is diagnostic; stale invalidates last batch'])


def capture(io=None, *, capacity=1200):
    validate_capacity(capacity)  # before Backend, lock, or any camera access
    with gf.staging_lock():  # also refuses unresolved worker handoff staging
        return _capture_locked(io if io is not None else gf.Backend(), capacity)


def _capture_locked(io, capacity):
    validate_capacity(capacity)
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
        re.findall(r'^\s*model\s*=\s*(\S+)\s*$', version, re.M) != ['w91c1'] or
        re.findall(r'^\s*rel version\s*=\s*(\S+)\s*$', version, re.M) != ['3.02.0.V90']):
        raise ValueError('expected exact fp L 3.02 version')
    publication = io.words(gf.PUBLICATION, 3)
    plan = layout(io.caps(), publication, capacity)
    if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock')
    code, symbols = code_for(plan, capacity)
    for address, data in ((plan.code, code), (plan.state, bytes(STATE_ROOM)),
                          (plan.output, SENTINEL * plan.output_room)):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('capture upload readback mismatch')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo owner changed during upload')
    try:
        for handler in (gf.DCACHE, gf.ICACHE):
            gf.set_handler(io, handler)
            gf.echo(io)
        gf.set_handler(io, plan.code)
        utc_before, mono_before = time.time_ns(), time.monotonic_ns()
        try:
            gf.echo(io)  # once, no retries even on an uncertain result
        finally:
            mono_after, utc_after = time.monotonic_ns(), time.time_ns()
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    if io.words(gf.PUBLICATION, 3) != publication:
        raise RuntimeError('publication changed during execution')
    verify_code(code, io.read(plan.code, CODE_ROOM), symbols)
    state, output = io.read(plan.state, STATE_ROOM), io.read(plan.output, plan.output_room)
    report = decode(state, output, capacity)
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo changed during readback')
    report.update(firmware_version_reply=version, publication=publication,
                  layout=vars(plan), code_sha256=hashlib.sha256(code).hexdigest(),
                  output_sha256=hashlib.sha256(output).hexdigest(),
                  validation='live partial shared-drain capture verified; full/lossless capture unproven',
                  host_echo_bounds=dict(meaning='host echo call only, not sample timestamps',
                      utc_before_ns=utc_before, utc_after_ns=utc_after,
                      monotonic_before_ns=mono_before, monotonic_after_ns=mono_after))
    return report, state, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='fresh local output directory')
    parser.add_argument('--capacity', type=int, default=1200, help='1..12000 records (default 1200)')
    args = parser.parse_args(argv)
    try:
        validate_capacity(args.capacity)
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(exist_ok=False)
    report, state, output = capture(capacity=args.capacity)
    for name, data in (('state.bin', state), ('output.bin', output)):
        with (args.out / name).open('xb') as handle:
            handle.write(data)
    with (args.out / 'capture.json').open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(f"{args.out}: {report['status']}; {report['appended_records']} records")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
