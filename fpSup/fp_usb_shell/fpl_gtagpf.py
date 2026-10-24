#!/usr/bin/env python3
"""One owner-authorized fp L CinemaDNG take with a PER-FRAME GTAG rewrite.

Resumes the paused 24-October M3 slice. Import/help are offline. `--preflight`
only reads. `--run` additionally uploads asm/fpl_gtagpf.S into the worker's
staging, borrows echo to publish caches and attach a PERSISTENT observer
(never detaches itself), presses record once to start and once to stop,
reads the observer's counters, and clears the observer's own Subject slot
once the owner is idle. Never retries a key. Afterwards it lists the new
take's folder, requires its frame count to equal the observer's frame index,
downloads whole frames (fpl_getrange) and reports which frame's DNG carries
which frame-notify counter.

While the observer's code sits in staging and may be attached, the shared
~/.cache/fpsup/fpl-staging.pending marker blocks every other staging tool
(which would overwrite the observer's code under a live Subject slot). It is
written before the upload and removed only once no Subject slot holds the
observer. Any failure leaves it; `--teardown` clears the observer's slot
(owner idle only) and then the marker.

The per-frame value written on each mode-3/type-3 notify is
'FPLP', counter, ~counter, N, then (i*7+3)&255 from byte 16, where counter is
the take's frame index (mode-3 notifies since mode 0, skipped ones included);
a frame whose notify never wrote shows counter 0. Not a fail-closed gate: nothing can veto
the take. The owner accepted card and clip loss for this line of experiments
(23 October); firmware is never written. Evidence goes to a new directory
given by --out. Test: projects/gyro2-sup/test_fpl_gtagpf.py.

`--gyro` builds the observer with GYRO=1 and N=1584 (H 0x13C00, the growth
the N=561 take showed decodes correctly): each frame carries the coprocessor
gyro records drained at its notify, with ticks and ring heads (block layout in
the assembly header). Afterwards every frame's header prefix is downloaded
and reported: continuity of the drain cursor, losses, frame intervals and the
gyro rate against the TickTimer. Two whole frames check StripOffsets = H.
Tests: test_fpl_gtagpf_gyro.py (ARM), test_fpl_gtagpf_host.py (report).
"""
import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import re
import struct
import sys
import time

import armasm
import fpl_getfile as gf
import fpl_getrange

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'projects/gyro2-sup'))
SOURCE = HERE / 'asm/fpl_gtagpf.S'
N = 560                      # same no-growth size as the gtag560 take
CODE_ROOM = 0x800            # asm/fpl_gtagpf.S is ~1500 bytes
SUBJECT, SLOTS = 0xC31AB0D0, 9
OWNER, CONTEXT = 0xC358E9D8, 0xC31F6ABC
TPTR, TLEN = 0xC358E9E8, 0xC358E9E4
MAGIC = 0x504C5046
STATES = {1: 'running', 2: 'attached', 3: 'no empty slot', 4: 'already present',
          5: 'unexpected Subject', 6: 'attach did not verify'}
VARS = 0x100                 # install state .. GYRO tick (0xFC)
MARKER = gf.LOCK_PATH.with_suffix('.pending')
SCHEMA = 'fpl-gtagpf-observer-v1'
GMAGIC, HDR, RING_RECORDS = 0x474C5046, 0x40, 600
GYRO_GLOBAL, GYRO_P, GYRO_R = 0xC31E23CC, 0x2E006004, 0x2E00644C
BLOCK = ('magic', 'index', 'tick', 'prev_tick', 'before', 'latched', 'after', 'due',
         'written', 'dropped', 'padbad', 'status', 'tick_after', 'capacity',
         'total_written', 'total_dropped')
STOCK_FRAME = 8447488        # 3840x2160 8-bit CinemaDNG frame at H 0x13800


@dataclass(frozen=True)
class Profile:
    name: str
    n: int
    code_room: int
    defines: tuple
    h: int                   # the header length this N gives in the measured mode

    def source(self):
        return payload(0) if self.name == 'pattern' else bytes(self.n)


PATTERN = Profile('pattern', N, CODE_ROOM, (), 0x13800)
GYRO = Profile('gyro', 1584, 0xC00, ('GYRO=1',), 0x13C00)


def payload(counter):
    head = struct.pack('<4I', MAGIC, counter, ~counter & 0xFFFFFFFF, N)
    return head + bytes((i * 7 + 3) & 255 for i in range(16, N))


def parse_gtag(data):
    """(counter, ok) for the GTAG value inside a whole DNG; raises if absent."""
    import fsg2
    _, maker = fsg2.maker_note(data)
    ty, count, off = maker[fsg2.GTAG]
    if (ty, count) != (7, N):
        raise RuntimeError(f'unexpected GTAG type/count {(ty, count)}')
    value = data[off:off + N]
    magic, counter, comp, n = struct.unpack_from('<4I', value)
    ok = (magic == MAGIC and comp == (~counter & 0xFFFFFFFF) and n == N and
          value[16:] == bytes((i * 7 + 3) & 255 for i in range(16, N)))
    return counter, ok


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


def write_marker(record):
    fd = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(dict(record, schema=SCHEMA), f)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(MARKER.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def read_marker():
    record = json.loads(MARKER.read_text())
    if type(record) is not dict or record.get('schema') != SCHEMA or type(record.get('obj')) is not int:
        raise RuntimeError(f'{MARKER} is not a GTAG observer marker; leaving it')
    return record


def detach(io, log, obj):
    """Clear every Subject slot holding obj, owner idle only; True once none does.

    The marker is the caller's to remove, and only on True."""
    owner = words(io, OWNER, 6)
    log('teardown_owner', owner)
    if owner[0] or owner[1] or owner[2]:
        log('teardown', 'owner not idle: observer left attached, marker retained')
        return False
    for _ in range(8):
        slots = words(io, SUBJECT, SLOTS)
        held = [i for i, v in enumerate(slots) if v == obj]
        if not held:
            break
        for i in held:
            io.set_word(SUBJECT + 4 * i, 0)
    a, b = words(io, SUBJECT, SLOTS), words(io, SUBJECT, SLOTS)
    log('teardown_subject', a)
    return obj not in a and obj not in b


def preflight(io, log, prof=PATTERN):
    version = io.sh('version', retries=0)
    if (not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
            not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise RuntimeError(f'expected fp L 3.02: {version!r}')
    publication = words(io, gf.PUBLICATION, 3)
    plan = gf.layout(io.caps(), publication, prof.n, prefix=True, code_room=prof.code_room)
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
    if prof is GYRO:
        heads = []
        for _ in range(2):
            p = words(io, GYRO_GLOBAL)[0]
            r = words(io, GYRO_P + 0x60)[0] if p == GYRO_P else None
            heads.append(words(io, GYRO_R)[0] if r == GYRO_R else None)
            log('gyro_ring', dict(p=p, r=r, head=heads[-1]))
            time.sleep(0.05)
        if None in heads or not all(GYRO_R + 8 <= h <= GYRO_R + 0x12C0 and h % 8 == 4 for h in heads):
            raise RuntimeError('gyro ring not published as bound; no take')
        if heads[0] == heads[1]:
            raise RuntimeError('gyro head did not move in 50 ms; no take')
    return publication, plan


def run(io, log, publication, plan, prof=PATTERN, seconds=4.0):
    defines = [f'PARAM={plan.param:#x}', f'SRC={plan.buffer:#x}', f'N={prof.n}', *prof.defines]
    code = gf.assemble(SOURCE, defines)
    sym = armasm.symbols(SOURCE, defines)
    if len(code) > prof.code_room:
        raise RuntimeError('code exceeds reservation')
    obj, vt = plan.param + 0x100, plan.param + 0x110
    param = bytearray(gf.PARAM_ROOM)
    struct.pack_into('<I', param, 0x100, vt)
    struct.pack_into('<4I', param, 0x110, *(plan.code + sym['ret0'],) * 3,
                     plan.code + sym['observer'])
    write_marker(dict(obj=obj, code=plan.code, param=plan.param, publication=publication))
    log('marker', str(MARKER))
    took = False
    try:
        result = attach_and_take(io, log, publication, plan, code, param, obj,
                                 prof, sym, seconds)
        took = True
    finally:
        # Clear our slot on every path; keep the marker unless that is proven.
        if detach(io, log, obj):
            MARKER.unlink()
            log('marker_removed', str(MARKER))
        elif took:
            raise RuntimeError(f'observer may still be attached; {MARKER} retained, run --teardown')
        else:
            log('marker_retained', str(MARKER))
    return result


def attach_and_take(io, log, publication, plan, code, param, obj, prof, sym, seconds):
    for address, data in ((plan.code, code.ljust(prof.code_room, b'\0')),
                          (plan.param, bytes(param)),
                          (plan.buffer, prof.source())):
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
    log('template_recording', words(io, TPTR, 1) + words(io, TLEN, 1))
    time.sleep(max(0.0, seconds - 1.5))
    press('stop')
    for _ in range(20):
        time.sleep(0.5)
        owner = words(io, OWNER, 6)
        if not owner[0]:
            break
    log('owner_after_stop', owner)
    v = words(io, plan.param, VARS // 4)
    ring = [v[0x6C // 4 + 4 * i:0x6C // 4 + 4 * i + 4] for i in range(8)]
    result = dict(calls=v[4], last_mode=v[5], last_type=v[6], mode0=v[7], adds=v[8],
                  builder=v[9], size_before=v[10], add_return=v[11], size_after=v[12],
                  n=v[13], mode2=v[14], located=v[15], tpl_ptr=v[16], tpl_len=v[17],
                  woff=v[18], room=v[19], mode3=v[20], writes=v[21], last_counter=v[22],
                  tpl_ptr_now=v[23], tpl_len_now=v[24], mismatches=v[25], skipped=v[26],
                  ring=ring, ring_index=v[0xEC // 4], frame_index=v[0xF0 // 4])
    if prof is GYRO:
        names = ('tot_written', 'tot_dropped', 'frames_ok', 'last_status', 'arm_status', 'arm_head')
        result['gyro'] = {k: words(io, plan.code + sym[k])[0] for k in names}
        result['gyro'].update(block_offset=v[0xF4 // 4], capacity=v[0xF8 // 4])
    log('observer', result)
    return result


def latest_folder(io, log):
    listing = io.sh('dir \\CINEMA', retries=0)
    log('cinema_dir', listing)
    folders = sorted(int(m) for m in re.findall(r'A001_(\d{3})', listing))
    if not folders:
        raise RuntimeError('no CinemaDNG clip folder found')
    return f'A001_{folders[-1]:03d}'


def take_frames(listing, folder):
    """(pattern, frame count) from a folder listing; frames must run 1..count."""
    found = re.findall(rf'({folder}_\d{{8}})_(\d{{6}})\.DNG', listing)
    patterns = {p for p, _ in found}
    numbers = sorted(int(n) for _, n in found)
    if len(patterns) != 1 or numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f'{folder}: frames not one contiguous 1..N run')
    return patterns.pop(), len(numbers)


def analyse(io, log, out, folder, pattern, frames, notifies):
    wanted = sorted({1, 2, 3, max(1, frames // 2), max(1, frames - 1), frames})
    rows, hashes = [], []
    for number in wanted:
        remote = f'\\CINEMA\\{folder}\\{pattern}_{number:06d}.DNG'
        data = fpl_getrange.download(remote, 16 << 20)
        counter, ok = parse_gtag(data)
        local = out / f'frame{number:02d}.full.DNG'
        local.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        hashes.append(f'{digest}  {local.name}')
        rows.append(dict(frame=number, bytes=len(data), counter=counter,
                         payload_ok=ok, sha256=digest))
        log('frame', rows[-1])
    (out / 'FULL_FRAMES.SHA256').write_text('\n'.join(hashes) + '\n')
    pairs = [(r['frame'], r['counter']) for r in rows]
    verdict = None
    if frames != notifies:
        verdict = f'{frames} frames on the card but {notifies} frame notifies: association unsettled'
    elif not all(r['payload_ok'] for r in rows):
        verdict = 'a sampled payload is damaged'
    elif all(c == f for f, c in pairs):
        verdict = 'each frame f carries counter f: the mode-3 notify precedes its own frame DMA'
    elif all(c == f - 1 for f, c in pairs):
        verdict = 'each frame f carries counter f-1: writes land one frame late'
    analysis = dict(folder=folder, pattern=pattern, card_frames=frames, notifies=notifies,
                    frames=pairs, verdict=verdict)
    (out / 'analysis.json').write_text(json.dumps(analysis, indent=1))
    log('analysis', analysis)
    return analysis


def parse_block(data, n=GYRO.n):
    """(header dict, [(x, y, z)]) for the gyro block in a frame's header bytes."""
    import fsg2
    _, maker = fsg2.maker_note(data)
    ty, count, off = maker[fsg2.GTAG]
    if (ty, count) != (7, n):
        raise RuntimeError(f'unexpected GTAG type/count {(ty, count)}')
    block = (off + 3) & ~3
    head = dict(zip(BLOCK, struct.unpack_from('<16I', data, block)))
    written = head['written'] if head['magic'] == GMAGIC else 0
    if HDR + 8 * written > n - (block - off):
        raise RuntimeError(f'block claims {written} records beyond its tag')
    recs = [struct.unpack_from('<hhhh', data, block + HDR + 8 * k) for k in range(written)]
    return head, [(x, y, z) for x, y, _, z in recs]


def backfill(b):
    """True when a frame's drain reached back one capacity from its latch."""
    span = RING_RECORDS * 8
    return (not b['status'] and b['due'] == b['capacity'] and
            (b['latched'] - b['before']) % span == 8 * b['capacity'] % span)


def gyro_report(blocks, notifies):
    """Continuity, losses and rate from the frames' block headers, frame 1 first."""
    frames = len(blocks)
    bad = [i + 1 for i, b in enumerate(blocks) if b['magic'] != GMAGIC or b['index'] != i + 1]
    status = {}
    for b in blocks:
        status[b['status']] = status.get(b['status'], 0) + 1
    breaks = [i + 1 for i in range(1, frames)
              if not blocks[i]['status'] and not blocks[i - 1]['status'] and
              blocks[i]['before'] != blocks[i - 1]['latched']]
    dts = [(b['tick'] - b['prev_tick']) & 0xFFFFFFFF for b in blocks]
    # Rate from frames whose drain and predecessor both succeeded: due records
    # over the TickTimer interval between the two latches' notifies.
    pairs = [(b['due'], dt) for i, (b, dt) in enumerate(zip(blocks, dts))
             if i and not b['status'] and not blocks[i - 1]['status'] and dt]
    rate = sum(d for d, _ in pairs) * 1e6 / sum(t for _, t in pairs) if pairs else None
    laps = []
    if rate:
        lap_us = RING_RECORDS / rate * 1e6
        # A gap near a whole ring, or a count a ring away from the rate's
        # prediction, may hide a lap the heads cannot show.  Frame 1 counts
        # too unless it is a backfill (its consumed head one capacity before
        # its latch): the observer that drained it from the mode-2 arming lost
        # a lap live (24 October, 331 ms).
        for i, (b, dt) in enumerate(zip(blocks, dts)):
            if i == 0 and backfill(b):
                continue
            if not b['status'] and (dt > 0.9 * lap_us or
                                          abs(b['due'] - rate * dt / 1e6) > RING_RECORDS / 2):
                laps.append(i + 1)
    ordered = sorted(dts[1:])
    return dict(
        card_frames=frames, notifies=notifies, frames_match=frames == notifies,
        bad_blocks=bad, status=status, chain_breaks=breaks,
        due=sum(b['due'] for b in blocks), written=sum(b['written'] for b in blocks),
        dropped=sum(b['dropped'] for b in blocks), padbad=sum(b['padbad'] for b in blocks),
        rate_hz=round(rate, 2) if rate else None,
        frame_dt_us=dict(min=ordered[0], median=ordered[len(ordered) // 2], max=ordered[-1])
        if ordered else None,
        lap_suspects=laps,
        complete=(frames == notifies and not bad and not breaks and set(status) == {0} and
                  not laps and not sum(b['dropped'] for b in blocks) and
                  not sum(b['padbad'] for b in blocks)))


def analyse_gyro(io, log, out, folder, pattern, frames, notifies):
    blocks, csv = [], ['frame,k,x,y,z']
    hashes = []
    for number in range(1, frames + 1):
        remote = f'\\CINEMA\\{folder}\\{pattern}_{number:06d}.DNG'
        data = gf.download(remote, GYRO.h, prefix=True)
        (out / f'frame{number:03d}.prefix').write_bytes(data)
        hashes.append(f'{hashlib.sha256(data).hexdigest()}  frame{number:03d}.prefix')
        head, recs = parse_block(data)
        blocks.append(head)
        csv += [f'{number},{k},{x},{y},{z}' for k, (x, y, z) in enumerate(recs)]
        log('block', dict(frame=number, **{k: head[k] for k in BLOCK[1:12]}))
    (out / 'gyro_records.csv').write_text('\n'.join(csv) + '\n')
    whole = []
    for number in sorted({1, frames}):
        import fsg2
        remote = f'\\CINEMA\\{folder}\\{pattern}_{number:06d}.DNG'
        data = fpl_getrange.download(remote, 16 << 20)
        local = out / f'frame{number:03d}.full.DNG'
        local.write_bytes(data)
        hashes.append(f'{hashlib.sha256(data).hexdigest()}  {local.name}')
        strip = fsg2.ifd_entries(data, 8)[0x111][2]
        whole.append(dict(frame=number, bytes=len(data), strip_offset=strip,
                          ok=strip == GYRO.h and len(data) == STOCK_FRAME + GYRO.h - PATTERN.h))
        log('whole_frame', whole[-1])
    (out / 'SHA256SUMS').write_text('\n'.join(hashes) + '\n')
    report = gyro_report(blocks, notifies)
    report.update(folder=folder, pattern=pattern, whole_frames=whole,
                  complete=report['complete'] and all(w['ok'] for w in whole))
    (out / 'analysis.json').write_text(json.dumps(report, indent=1))
    log('analysis', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='new evidence directory')
    parser.add_argument('--no-frames', action='store_true',
                        help='stop after the take; do not download frames')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--run', action='store_true')
    mode.add_argument('--teardown', action='store_true',
                      help='clear a left-behind observer (owner idle) and its marker')
    parser.add_argument('--gyro', action='store_true',
                        help='GYRO build: per-frame gyro records instead of the pattern')
    parser.add_argument('--seconds', type=float, default=4.0,
                        help='take length between the presses (1.5..30, default 4)')
    args = parser.parse_args(argv)
    if not 1.5 <= args.seconds <= 30:
        parser.error('--seconds must be 1.5..30')
    prof = GYRO if args.gyro else PATTERN
    args.out.mkdir(parents=True, exist_ok=False)
    log = Log(args.out)
    if args.teardown:
        with gf.staging_lock(permit_pending=True):
            record = read_marker()
            log('marker', record)
            if not detach(gf.Backend(), log, record['obj']):
                raise RuntimeError(f'observer not proven detached; {MARKER} retained')
            MARKER.unlink()
            log('marker_removed', str(MARKER))
        return 0
    (args.out / 'payload.bin').write_bytes(prof.source())
    with gf.staging_lock():
        io = gf.Backend()
        publication, plan = preflight(io, log, prof)
        if args.run:
            result = run(io, log, publication, plan, prof, args.seconds)
            if result['writes'] < 1:
                return 1
    if args.run and not args.no_frames:
        io = gf.Backend()
        folder = latest_folder(io, log)
        listing = io.sh(f'dir \\CINEMA\\{folder}', retries=0)
        log('folder_dir', listing)
        pattern, frames = take_frames(listing, folder)
        log('card_frames', dict(pattern=pattern, frames=frames))
        if prof is GYRO:
            report = analyse_gyro(io, log, args.out, folder, pattern, frames, result['frame_index'])
            return 0 if report['complete'] else 1
        analysis = analyse(io, log, args.out, folder, pattern, frames, result['frame_index'])
        if not analysis['verdict'] or 'carries counter f:' not in analysis['verdict']:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
