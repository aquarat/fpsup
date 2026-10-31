#!/usr/bin/env python3
"""USB-controlled fp L 3.02 slit-scan capture, UHD/8-bit/nominal 24 only.

photo saves one CinemaDNG-derived slit-scan image; video saves a DNG sequence.
The physical selector stays in CINE for both. A finite Vd override and the
existing per-frame GTAG observer share one staging reservation/marker. Camera
files include preroll/postroll; exports select the steady middle of the take.
No boot/card deployment. Commands and --help are offline until an action runs.
"""
import argparse
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import signal
import struct
import time

import armasm
import fpl_getfile as gf
import fpl_getrange as gr
import fpl_gtagpf as tag
import fpl_vd_probe as vd

SCHEMA = 'fpl-slit-scan-v1'
T04, T20 = 0x020B047B, 0x165B0000
CODE_ROOM = 0xC00
MODE = {'SetRecMode': '1', 'SetMovRecSize': '3', 'SetMovFramerate': '12',
        'SetMovCinemaDNGQuality': '4', 'SetMovRecFormat': '0'}
EXPOSURE = ('SetExpMode', 'SetShutterSpeed', 'SetIso')


@dataclass(frozen=True)
class Capture:
    fps: int = 4
    frames: int = 1
    shutter: int = 1000
    iso: int = 100

    def __post_init__(self):
        if self.fps not in (4, 6, 8, 12) or not 1 <= self.frames <= 480:
            raise ValueError('fps must be 4, 6, 8 or 12; frames 1..480')
        if self.shutter not in (250, 500, 1000) or self.iso not in (100, 200, 400, 800, 1600, 3200):
            raise ValueError('unsupported exposure choice')

    @property
    def scale(self):
        return 24 // self.fps

    @property
    def trial(self):
        return ((524*self.scale-1) << 16) | (1148*self.scale-1)

    @property
    def end(self):
        return 8 + self.frames + 24

    @property
    def count(self):
        return self.end + 32

    @property
    def stock_shutter(self):
        # Shorten stock exposure to compensate for the longer row interval.
        # Quantization and effective exposure are reported, not silently hidden.
        choices = (500, 640, 800, 1000, 1250, 1600, 2000, 2500, 3200, 4000, 5000, 6400, 8000)
        wanted = self.shutter*self.scale
        return min(choices, key=lambda n: abs(math.log(n/wanted)))


def menu(io, name):
    return io.sh('menu '+name, retries=0).strip()


def set_menu(io, name, value):
    answer = io.sh(f'menu {name} {value.replace("/", " ")}', retries=0).strip()
    if answer != 'OK' or menu(io, name) != value:
        raise RuntimeError(f'{name} did not verify as {value!r}')


def restore_exposure(io, saved, log):
    errors = []
    for name in ('SetShutterSpeed', 'SetIso', 'SetExpMode'):
        try:
            set_menu(io, name, saved[name])
        except Exception as error:
            errors.append(f'{name}: {error}')
    # The native settings are coupled: e.g. mode can change shutter after the
    # shutter setter already verified. Only the final tuple proves restoration.
    actual = {}
    if not errors:
        for name in EXPOSURE:
            try:
                actual[name] = menu(io, name)
                if actual[name] != saved[name]:
                    errors.append(f'{name}: final value {actual[name]!r} != {saved[name]!r}')
            except Exception as error:
                errors.append(f'{name}: final readback: {error}')
    log('exposure_restore', dict(saved=saved, actual=actual, errors=errors))
    if errors:
        raise RuntimeError('; '.join(errors))


def preflight(io, log):
    publication, _ = tag.preflight(io, log)
    actual = {k: menu(io, k) for k in MODE}
    if actual != MODE:
        raise RuntimeError(f'select CINE, UHD, CinemaDNG 8-bit, 24 fps first: {actual}')
    if vd.words(io, vd.SLOT-4, 5) != [0xC0325758, 0, 1, 0, 0]:
        raise RuntimeError('Vd table is not stock')
    if vd.words(io, 0xC30337EC) != [0x2D810000] or vd.words(io, 0xC2F09408) != [12000000]:
        raise RuntimeError('unexpected timer configuration')
    return publication


def build(plan, capture):
    """Both callbacks in one allocation; all live references supplied by caller."""
    param = bytearray(gf.PARAM_ROOM)
    obj, vt = plan.param+0x100, plan.param+0x110
    defs = [f'PARAM={plan.param}', f'SRC={plan.buffer}', f'N={tag.N}']
    code = armasm.assemble(tag.SOURCE, defs)
    sym = armasm.symbols(tag.SOURCE, defs)
    if len(code) > 0x800:
        raise RuntimeError('frame observer exceeds its reservation')
    struct.pack_into('<I', param, 0x100, vt)
    struct.pack_into('<4I', param, 0x110, *(plan.code+sym['ret0'],)*3, plan.code+sym['observer'])
    vp, vb = plan.param+0x200, plan.buffer+0x400
    defs = [f'PARAM={vp}', f'BUFFER={vb}', 'TIMING_TEST=1', 'WATCH_MODE=1',
            f'END_COUNT={capture.end}', f'FRAME_INDEX={plan.param+0xF0}']
    vcode = armasm.assemble(vd.SOURCE, defs)
    vsym = armasm.symbols(vd.SOURCE, defs)
    if len(vcode) > 0x400:
        raise RuntimeError('Vd observer exceeds its reservation')
    struct.pack_into('<10I', param, 0x200, 0, 0, 0, capture.count, 0, 0, T04, T20, 0, capture.trial)
    return (code.ljust(0x800, b'\0') + vcode.ljust(0x400, b'\0'), bytes(param),
            dict(obj=obj, code=plan.code, param=plan.param, vcode=plan.code+0x800,
                 vparam=vp, buffer=vb, callback=plan.code+0x800+vsym['callback']))


def marker_write(record):
    import os
    with vd.MARKER.open('x') as f:
        os.chmod(vd.MARKER, 0o600)
        json.dump(record, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(vd.MARKER.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def stop_recording(io, log):
    if any(vd.words(io, tag.OWNER, 3)):
        vd.press_record(io, log, 'stop')
        deadline = time.monotonic()+20
        while any(vd.words(io, tag.OWNER, 3)):
            if time.monotonic() > deadline:
                raise RuntimeError('recording still active after one stop press')
            time.sleep(.25)


def cleanup(io, log, record):
    """No upload during recovery. Keep ownership marker until both hooks are gone."""
    if record.get('schema') != SCHEMA:
        raise RuntimeError('pending marker belongs to another tool')
    if vd.words(io, gf.PUBLICATION, 3) != record['publication']:
        raise RuntimeError('worker publication changed; retained marker')
    slot = vd.words(io, vd.SLOT)[0]
    if slot not in (0, record['callback']):
        raise RuntimeError('foreign Vd callback; retained marker')
    if slot == record['callback']:
        if hashlib.sha256(io.read(record['code'], CODE_ROOM)).hexdigest() != record['sha256']:
            raise RuntimeError('resident code differs; retained marker')
        io.set_word(record['vparam'], 1)
        if vd.words(io, record['vparam']) != [1]:
            raise RuntimeError('detach command did not verify')
        vd.execute(io, record['vcode'])
        if vd.words(io, vd.SLOT) != [0]:
            raise RuntimeError('Vd detach failed')
    # Recording stop moves the sensor back to ordinary live-view timing, also
    # covering an uncertain upload before install. Never retry its toggle.
    stop_recording(io, log)
    if not tag.detach(io, log, record['obj']):
        raise RuntimeError('frame observer still attached; retained marker')
    restore_exposure(io, record['exposure'], log)
    vd.MARKER.unlink()
    log('cleanup_complete', True)


def folders(io):
    text = io.sh('dir \\CINEMA', retries=0)
    return {m[3]: ''.join(m[:3]) for m in re.findall(
        r'(\d{4})/(\d{2})/(\d{2})[^\n]*<DIR>\s+(A\d{3}_\d{3})', text)}


def select_frames(raw, capture):
    records = list(struct.iter_unpack('<8I', raw))
    if len(records) != capture.count:
        raise RuntimeError('incomplete Vd capture')
    # Native mode-3 counter is the recorded file index, proven by GTAG in each
    # downloaded DNG. Keep twelve Vd events away from each timing transition.
    first = records[8+12][5]+1
    last = first+capture.frames-1
    if first < 1 or last > records[capture.end-12][5]:
        raise RuntimeError('not enough identified steady-state DNG frames')
    steady = records[10:capture.end-2]
    if any(r[3:5] != (capture.trial, T20) for r in steady):
        raise RuntimeError('timing changed during steady capture')
    return list(range(first, last+1))


def capture_take(io, log, out, capture):
    publication = preflight(io, log)
    saved = {k: menu(io, k) for k in EXPOSURE}
    (out/'exposure-original.json').write_text(json.dumps(saved, indent=2))
    before = folders(io)
    plan = gf.layout(io.caps(), publication, 0x400+capture.count*32, prefix=True, code_room=CODE_ROOM)
    code, param, addresses = build(plan, capture)
    record = dict(addresses, schema=SCHEMA, publication=publication, exposure=saved,
                  sha256=hashlib.sha256(code).hexdigest(), capture=capture.__dict__)
    (out/'payload.bin').write_bytes(code)
    (out/'manifest.json').write_text(json.dumps(record, indent=2))
    marker_write(record)
    try:
        for address, data in ((plan.code, code), (plan.param, param),
                              (plan.buffer, tag.payload(0).ljust(0x400+capture.count*32+1024, b'\0'))):
            io.write(address, data)
            if io.read(address, len(data)) != data:
                raise RuntimeError('staging readback differs')
        if vd.words(io, gf.PUBLICATION, 3) != publication:
            raise RuntimeError('publication changed during upload')
        for fn in (gf.DCACHE, gf.ICACHE, plan.code):
            vd.execute(io, fn)
        if vd.words(io, plan.param)[0] != 2:
            raise RuntimeError('frame observer did not attach')
        set_menu(io, 'SetExpMode', '1')
        set_menu(io, 'SetShutterSpeed', f'1/{capture.stock_shutter}')
        set_menu(io, 'SetIso', str(capture.iso))
        time.sleep(.5)
        vd.press_record(io, log, 'start')
        deadline = time.monotonic()+5
        while not any(vd.words(io, tag.OWNER, 3)):
            if time.monotonic() > deadline:
                raise RuntimeError('record start not observed; no retry')
            time.sleep(.2)
        time.sleep(.5)
        mode = io.sh('imager mode_now', retries=0)
        log('imager_recording', mode)
        exposure_match = re.search(r'shutter:(\d+),gain:(\d+)', mode)
        if not exposure_match or int(exposure_match[2]) != capture.iso:
            raise RuntimeError('recording exposure readback is missing or differs')
        stock_exposure_us = int(exposure_match[1])
        if not 0 < stock_exposure_us <= 1000000/capture.stock_shutter*1.2:
            raise RuntimeError('recording shutter differs from requested short exposure')
        if vd.words(io, 0x30100004) != [T04] or vd.words(io, 0x30100020) != [T20]:
            raise RuntimeError('recording timing is not the verified UHD/24 mode')
        vd.execute(io, record['vcode'])
        deadline = time.monotonic() + (capture.frames+24)/capture.fps+15
        while True:
            state = vd.words(io, record['vparam'], 12)
            if state[1] != 1 or time.monotonic() > deadline:
                break
            time.sleep(.2)
        log('vd_result', state)
        if state[1:4] != [2, capture.count, capture.count] or state[10:] != [0, 1]:
            raise RuntimeError('timing run incomplete or restoration unconfirmed')
        if state[4] != state[5] or vd.words(io, vd.SLOT) != [0]:
            raise RuntimeError('CPU/detachment verification failed')
        if vd.words(io, 0x30100004) != [T04] or vd.words(io, 0x30100020) != [T20]:
            raise RuntimeError('stock recording timing not restored')
        stop_recording(io, log)
        vd.execute(io, gf.DCACHE)
        raw = io.read(record['buffer'], capture.count*32)
        (out/'records.bin').write_bytes(raw)
        frames = select_frames(raw, capture)
        analysis = vd.analyse(raw, 12000000)
        (out/'timing.json').write_text(json.dumps(analysis, indent=2))
        observed = next(p['measured_hz'] for p in analysis['phases'] if p['timing04'] == f'{capture.trial:08x}')
        if abs(observed/capture.fps-1) > .01:
            raise RuntimeError('measured cadence differs from request')
        after = folders(io)
        new = set(after)-set(before)
        if len(new) != 1:
            raise RuntimeError('cannot uniquely identify the new take')
        folder = new.pop()
        result = dict(folder=folder, pattern=folder+'_'+after[folder], frames=frames,
                      measured_fps=observed, requested=capture.__dict__,
                      stock_shutter=f'1/{capture.stock_shutter}',
                      stock_exposure_us=stock_exposure_us,
                      estimated_exposure_seconds=capture.scale*stock_exposure_us/1000000,
                      exposure_status='row-interval estimate; brightness compensation checked at 4/6/12 fps, not precision exposure calibration',
                      nominal_camera_fps=24, camera_frame_count=vd.words(io, plan.param+0xF0)[0])
        (out/'capture.json').write_text(json.dumps(result, indent=2))
        log('capture', result)
    finally:
        cleanup(io, log, record)
    return result


def patch_frame_rate(data, fps, frame_index=None):
    """Edit existing FrameRate and optional zero-based TimeCodes; pixels unchanged."""
    if data[:4] != b'II*\0':
        raise ValueError('expected little-endian TIFF')
    offset = struct.unpack_from('<I', data, 4)[0]
    count = struct.unpack_from('<H', data, offset)[0]
    if offset+2+12*count+4 > len(data):
        raise ValueError('truncated IFD')
    result, found_rate, found_time = bytearray(data), False, False
    for i in range(count):
        code, kind, n, ptr = struct.unpack_from('<HHII', data, offset+2+12*i)
        if code == 51044:
            if kind != 10 or n != 1 or ptr+8 > len(data):
                raise ValueError('unexpected FrameRate representation')
            rate = Fraction(fps).limit_denominator(100000)
            struct.pack_into('<ii', result, ptr, rate.numerator, rate.denominator)
            found_rate = True
        elif code == 51043 and frame_index is not None:
            if kind != 1 or n != 8 or ptr+8 > len(data):
                raise ValueError('unexpected TimeCodes representation')
            seconds, frame = divmod(frame_index, round(fps))
            minutes, second = divmod(seconds, 60)
            hour, minute = divmod(minutes, 60)
            values = (frame, second, minute, hour % 24)
            result[ptr:ptr+8] = bytes((v//10*16+v%10 for v in values))+bytes(4)
            found_time = True
    if not found_rate or (frame_index is not None and not found_time):
        raise ValueError('FrameRate or TimeCodes tag missing')
    return bytes(result)


def export(out, result):
    dest = out/'images'
    dest.mkdir(exist_ok=True)
    manifest = dest/'manifest.json'
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if previous and (previous.get('capture') != result or previous.get('export_format') != 2):
        raise RuntimeError('existing export has different capture/metadata format; preserve it in another directory')
    existing = {row['file']: row for row in previous.get('files', [])}
    hashes = []
    for index, frame in enumerate(result['frames'], 1):
        name = 'photo.DNG' if len(result['frames']) == 1 else f'{index:06d}.DNG'
        path = dest/name
        remote = f'\\CINEMA\\{result["folder"]}\\{result["pattern"]}_{frame:06d}.DNG'
        known = existing.get(name)
        if path.exists() and known:
            if (known['source'] != remote or known['frame'] != frame or
                    hashlib.sha256(path.read_bytes()).hexdigest() != known['sha256']):
                raise RuntimeError(f'existing export changed: {path}')
            hashes.append(known)
            continue
        data = gr.download(remote, 16 << 20)
        counter, valid = tag.parse_gtag(data)
        if not valid or counter != frame:
            raise RuntimeError(f'frame identity failed: requested {frame}, GTAG {counter}')
        fixed = patch_frame_rate(data, result['measured_fps'], index-1)
        if path.exists():
            if path.read_bytes() != fixed:
                raise RuntimeError(f'untracked export differs: {path}')
        else:
            # If interrupted, no half-DNG is mistaken for a complete export.
            partial = path.with_suffix('.DNG.partial')
            with partial.open('wb') as f:
                f.write(fixed)
            partial.rename(path)
        hashes.append(dict(file=name, source=remote, frame=frame,
                           source_sha256=hashlib.sha256(data).hexdigest(),
                           sha256=hashlib.sha256(fixed).hexdigest()))
        pending = dest/'manifest.json.partial'
        pending.write_text(json.dumps(dict(export_format=2, capture=result, files=hashes), indent=2))
        pending.replace(manifest)
    return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('check', 'photo', 'video', 'recover', 'export'))
    p.add_argument('--fps', type=int, choices=(4, 6, 8, 12), default=4)
    p.add_argument('--frames', type=int, default=24, help='video frames, 1..480')
    p.add_argument('--shutter', type=int, choices=(250, 500, 1000), default=1000,
                   help='desired effective exposure denominator (estimated compensation)')
    p.add_argument('--iso', type=int, choices=(100, 200, 400, 800, 1600, 3200), default=100)
    p.add_argument('--out', type=Path, required=True, help='new capture directory; existing for export')
    p.add_argument('--card-only', action='store_true', help='retain capture on camera without downloading')
    args = p.parse_args()
    try:
        capture = Capture(args.fps, 1 if args.action == 'photo' else args.frames, args.shutter, args.iso)
    except ValueError as error:
        p.error(str(error))
    if args.action == 'export':
        print(export(args.out, json.loads((args.out/'capture.json').read_text())))
        return
    args.out.mkdir(parents=True, exist_ok=False)
    log = tag.Log(args.out)
    # SIGINT and SIGTERM unwind into cleanup; SIGKILL leaves the durable marker
    # for `recover`. The Vd timing override independently ends after its bound.
    def interrupted(signum, frame):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt(f'signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with gf.staging_lock(permit_pending=args.action == 'recover'):
        io = gf.Backend()
        if args.action == 'check':
            preflight(io, log)
        elif args.action == 'recover':
            cleanup(io, log, json.loads(vd.MARKER.read_text()))
        else:
            result = capture_take(io, log, args.out, capture)
    if args.action in ('photo', 'video') and not args.card_only:
        print(export(args.out, result))


if __name__ == '__main__':
    main()
