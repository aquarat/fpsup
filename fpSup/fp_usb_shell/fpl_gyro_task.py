#!/usr/bin/env python3
"""Checked, one-attempt retained-task trial for fp L 3.02.

One live trial October 23 completed 20 observations/997 conditional records,
with native completion, full readback and PONG; all ownership stayed retained.

Import/help/build helpers are offline. --out NEW_DIR executes a camera trial;
it requires a separately authorized operator. No resume, free, join or destroy.
The shared staging .pending marker is deliberately NEVER cleared, including on
success/refusal. It blocks another invocation on this host until separate review.
It is not a worker-handoff record: swapworker reconcile must not clear it.
No boot identity is available; publication equality is not proof of same boot.
The staging flock is advisory/local, not multi-host or camera-input exclusion.

Ownership: fixed 64-KiB USER allocation, explicit 64-KiB alignment, class 0.
Native descriptor is copied into +0x400 and manifest before launch. All storage
is retained even before launch on failure: no descriptor remains needed in
reusable staging. If allocation outcome itself is unknown, the pending manifest
records that gap rather than guessing an address. No arbitrary inspect/resume.
Admission requires exact git identity, the reviewed PONG resident bytes and a
structured transport PONG. Window restoration fails closed on any foreign caps
change: it may leave our grant present for review, never adopts foreign changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import tempfile

import fpl_gyro_latched as lat
import fpl_swapworker as swap
from firmware import get_camera

gf, armasm = lat.gf, lat.armasm
HERE = Path(__file__).resolve().parent
SIZE, CAPACITY, OUTPUT_ROOM = 0x10000, 1200, 11264
OWNER_INFO, OBS = 0x400, 0x100
WORKER_GUARD = 0x10000  # conservatively exclude 64 KiB at published worker
CAMERA = get_camera('fp-l-3.02')
GIT_HASH = '13aa621060efff11aaba9b21ad925005302605cf'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def words(data):
    if len(data) % 4:
        raise ValueError('partial word readback')
    return list(struct.unpack('<'+'I'*(len(data)//4), data))


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable(path, data, *, replace=False):
    """Same-directory atomic replace + file and directory fsync; private files."""
    target = path.with_suffix(path.suffix+'.new') if replace else path
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if replace:
        os.replace(target, path)
    sync_dir(path.parent)


def validate_owner(descriptor, address, publication):
    if descriptor != [address, 0, address, SIZE]:
        raise ValueError('native descriptor mismatch (address/class/duplicate/size)')
    if address == 0:
        return False
    pool, room, worker = publication
    if (address % SIZE or not 0x44400000 <= address or address+SIZE > 0x46400100 or
            any(address < b+n and b < address+SIZE
                for b, n in ((pool, room), (worker, WORKER_GUARD)))):
        raise ValueError('allocation outside USER, unaligned, or overlaps pool/worker')
    return True


def staging(caps, publication):
    # gf.layout admits word-aligned pools and 1-KiB-multiple pool sizes; it
    # does not promise a 1-KiB-aligned pool base. Reuse its MCAPS/publication
    # checks without requesting an unrelated file buffer plus download slack.
    gf.layout(caps, publication, 0)
    pool, room, worker = publication
    start = (pool+gf.STAGING_OFFSET+1023) & ~1023
    end = start+0x4000
    if (end > pool+room or worker+WORKER_GUARD > 0x80000000 or
            start < worker+WORKER_GUARD and worker < end):
        raise ValueError('aligned staging exceeds pool or overlaps worker')
    return start


def build_owned(owner, *, sleep_reason=0):
    """Same retained prototype and actual shared capture; no test-module import."""
    if owner % SIZE or not 0x44400000 <= owner <= 0x46400100-SIZE:
        raise ValueError('invalid owned build extent')
    if sleep_reason not in (0, 1):
        raise ValueError('sleep diagnostic must be disabled or known-once value 1')
    plan = lat.strict.Layout(owner+0x2000, owner+0x4000, owner+0x5000, OUTPUT_ROOM)
    capture, cs = lat.code_for(plan, CAPACITY, runtime=True)
    source = HERE/'asm/fpl_gyro_task_retained.S'
    with tempfile.TemporaryDirectory() as directory:
        binary = Path(directory)/'capture.bin'
        binary.write_bytes(capture)
        defines = [f'OWNED={owner}', f'SLEEP_REASON={sleep_reason}', f'CAPTURE_FILE="{binary}"']
        body = armasm.assemble(source, defines)
        syms = armasm.symbols(source, defines)
    if (len(body) != 0x3000 or body[0x2000:] != capture or
            syms['entry'] != 0 or syms['resident_image'] != 0x1000 or
            syms['capture_image'] != 0x2000 or syms['image_end'] != 0x3000 or
            any(not 0x1000 <= syms[n] < 0x2000 for n in ('activate', 'observe', 'body_entry')) or
            plan.output+plan.output_room > owner+SIZE):
        raise ValueError('retained artifact extent mismatch')
    return body, syms, plan, cs


def small_body(name, defines=()):
    source = HERE/'asm'/name
    body, syms = armasm.assemble(source, defines), armasm.symbols(source, defines)
    if syms['entry'] != 0 or syms['image_end'] != len(body) or len(body) > 1024:
        raise ValueError('finite bootstrap exceeds reservation')
    return body.ljust(1024, b'\0'), syms


class Backend(gf.Backend):
    window = staticmethod(gf.transport.mem_window)

    def ping(self):
        return gf.transport.mem_line('PING', timeout=10)


def swap_words(io, pool):
    values = [io.words(pool+offset) for offset in (0x1080, 0x10C0)]
    if any(len(v) != 1 or type(v[0]) is not int or not 0 <= v[0] <= 0xFFFFFFFF for v in values):
        raise RuntimeError('incomplete swap words')
    if values[0] != [0]:
        raise RuntimeError('swap is not idle')
    # The worker clears magic, not address, after handoff. A stale address with
    # zero magic is idle; record both words and require them to stay unchanged.
    return [v[0] for v in values]


class Trial:
    def __init__(self, io, out, report):
        self.io, self.out, self.report = io, out, report
        self.publication = report['publication']
        self.caps = report['caps']
        self.stage = staging(self.caps, self.publication)
        self.counter = 0
        self.candidate = None
        self.installed = False

    def save(self):
        durable(self.out/'manifest.json', (json.dumps(self.report, indent=2)+'\n').encode(), replace=True)

    def intent(self, operation, **fields):
        self.counter += 1
        row = dict(number=self.counter, operation=operation, state='intent', **fields)
        self.report['operations'].append(row)
        self.save()                  # must succeed BEFORE any executing command
        return row

    def finish(self, row):
        row['state'] = 'returned-and-checked'
        self.save()

    def artifact(self, name, data):
        durable(self.out/name, data)
        self.report['artifacts'][name] = dict(bytes=len(data), sha256=sha(data))
        self.save()

    def guard(self):
        if self.io.words(gf.PUBLICATION, 3) != self.publication:
            raise RuntimeError('publication changed; no boot identity available')
        if self.io.caps() != self.caps:
            raise RuntimeError('MCAPS/windows changed')
        if self.io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
            raise RuntimeError('echo is not stock')
        if swap_words(self.io, self.publication[0]) != self.report['swap_words']:
            raise RuntimeError('swap words changed')

    def pong(self, label):
        self.guard()
        row = self.intent(label)
        reply = self.io.ping()
        row['reply'] = reply
        self.save()                 # preserve legacy/malformed replies too
        match = re.fullmatch(r'OK pong seq=([0-9]+) proof=PONG', reply.strip())
        if not match or not 0 <= int(match[1]) <= 0xFFFFFFFF:
            raise RuntimeError('structured proof=PONG required')
        row.update(sequence=int(match[1]), proof='PONG')
        self.guard()
        self.finish(row)
        return dict(reply=reply, sequence=int(match[1]), proof='PONG')

    def read(self, address, count):
        data = self.io.read(address, count)
        if len(data) != count:
            raise RuntimeError('short memory readback')
        return data

    def upload(self, address, data):
        self.guard()
        # Every write owns its rounded 1-KiB DMA extent; never short writes into
        # adjacent live metadata. Neither silent loss nor uncertainty is retried.
        if address % 1024 or len(data) % 1024:
            raise ValueError('upload must own complete 1-KiB DMA extents')
        self.io.write(address, data)
        if self.read(address, len(data)) != data:
            raise RuntimeError('upload readback mismatch')
        self.guard()

    def execute(self, handler, label):
        self.guard()
        row = self.intent(label, handler=handler, cleanup='restore own echo slot to stock')
        try:
            self.io.set_word(gf.ECHO_SLOT, handler)
            if self.io.words(gf.ECHO_SLOT) != [handler]:
                raise RuntimeError('echo arm readback uncertain')
            gf.echo(self.io)        # retries=0, exactly one dispatch
        finally:
            # Restore only our own slot (or already-stock), never a third owner.
            # Restoration intent is in the durable execute row already. A disk
            # failure after dispatch must not prevent the slot restoration.
            current = self.io.words(gf.ECHO_SLOT)
            if current not in ([handler], [gf.ECHO_STOCK]):
                raise RuntimeError('echo owner changed; refusing overwrite')
            if current != [gf.ECHO_STOCK]:
                self.io.set_word(gf.ECHO_SLOT, gf.ECHO_STOCK)
            if self.io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
                raise RuntimeError('echo restoration unverified')
            row['echo_restored'] = True
        self.guard()
        self.finish(row)

    def publish(self, label):
        self.execute(gf.DCACHE, label+'-dcache')
        self.execute(gf.ICACHE, label+'-icache')

    def command(self, target, label):
        body, syms = small_body('fpl_task_entry.S', [f'TARGET={target}'])
        self.artifact(label+'-trampoline.bin', body)
        self.upload(self.stage+0x400, body)
        self.publish(label)
        owner, candidate, labels, owner_info, cs = self.candidate
        if self.read(owner+OWNER_INFO, 1024) != owner_info:
            raise RuntimeError('ownership record changed before execution')
        if self.installed:
            if target not in (owner+labels['observe'], owner+labels['activate']):
                raise ValueError('unexpected retained entry target')
            if self.read(owner+0x1000, 4096) != candidate[0x1000:0x2000]:
                raise RuntimeError('immutable wrapper changed before execution')
            lat.verify_code(candidate[0x2000:], self.read(owner+0x2000, 4096), cs)
        elif target != self.stage+0x1000 or self.read(target, len(candidate)) != candidate:
            raise RuntimeError('staged launcher changed before execution')
        self.execute(self.stage+0x400, label)
        actual = self.read(self.stage+0x400, 1024)
        expected = bytearray(body)
        struct.pack_into('<4I', expected, syms['result'], 2, target, 0, 0)
        if actual != expected:
            raise RuntimeError('entry trampoline did not return or changed bytes')
        self.artifact(label+'-trampoline-readback.bin', actual)

    def window(self, slot, window, label):
        if self.io.words(gf.PUBLICATION, 3) != self.publication or self.io.caps() != self.caps:
            raise RuntimeError('publication/windows changed before permission update')
        row = self.intent(label, slot=slot, window=window)
        self.io.window(slot, *window)
        expected = dict(self.caps, windows=list(self.caps['windows']))
        expected['windows'][slot] = tuple(window)
        actual = self.io.caps()
        if actual != expected:
            raise RuntimeError('window change unverified')
        self.caps = expected
        self.finish(row)


def identities(control, owner, syms):
    c = words(control)
    if (len(control) != 0x400 or c[2] != owner+0x10 or
            c[7] != owner+syms['body_entry'] or c[8] != owner+0x2000 or
            c[1] != c[12] or not 0x40000000 <= c[1] <= 0xFFFFFFE8 or c[1] % 4 or
            not 1 <= c[13] <= 500 or not 1 <= c[14] <= 300):
        raise RuntimeError('retained control identity mismatch')
    return [c[1], c[13], c[14]]


def observation(data, owner, identity, sequence, *, admission=False, sleep_reason=0):
    """Validate raw snapshots independently; do not trust the ARM evidence bits."""
    if len(data) != 256:
        raise RuntimeError('observation size')
    w = words(data)
    obj, tid, fid = identity
    if w[0:2] != [sequence, 1] or w[0xE4//4] != sleep_reason:
        raise RuntimeError('observation sequence/commit marker')
    samples = []
    for at in (0x20, 0x80):
        s = words(data[at:at+0x60])
        before, after, task, flag = s[:5], s[18:23], s[7:15], s[15:18]
        signed = [v if v < 2**31 else v-2**32 for v in s[5:7]]
        if signed != [0, 0]:
            raise RuntimeError(f'query error task_rc={signed[0]} flag_rc={signed[1]}')
        if (before != after or
                [before[0], before[1], before[4]] != identity or task[0] != obj+4):
            raise RuntimeError('query error, exinf or native identity mismatch')
        if task[3] not in (1, 2, 4):
            raise RuntimeError('dormant/unknown task state; refusing admission/continuation')
        samples.append(dict(identity=before, task=task, flag=flag, task_rc=0, flag_rc=0))
    if samples[0]['identity'] != samples[1]['identity']:
        raise RuntimeError('identity changed between samples')
    if admission:
        if (w[2:5] != [2, 0, 0] or w[58:61] != [2, 0, 0] or
                samples[0]['identity'][2:4] != [0, 0] or
                any(s['flag'][2] != 1 for s in samples)):
            raise RuntimeError('not a fresh unattached worker')
    elif w[2] != 4 or w[58] != 4:
        raise RuntimeError('attachment return not established')
    elif (samples[0]['identity'][2] != owner+8 or samples[0]['identity'][3] not in (0, owner+8) or
          any(v not in (0, 1) for v in (w[3], w[4], w[59], w[60]))):
        raise RuntimeError('attached body/control identity unknown')
    completed = (not admission and w[3:5] == [1, 1] and w[59:61] == [1, 1] and
                 samples[0]['identity'][2:4] == [owner+8, 0] and
                 all(s['flag'][2] & 1 for s in samples))
    if bool(w[56] & 8) != completed or w[56] & 7 != 7:
        raise RuntimeError('observation evidence bits disagree with raw fields')
    sleep_sample = bool(sleep_reason and all(s['task'][3:7] == [4, sleep_reason, 0, 0]
                                             for s in samples))
    if bool(w[56] & 16) != sleep_sample or w[56] & ~31:
        raise RuntimeError('sleep diagnostic evidence disagrees with raw fields')
    return dict(samples=samples, native_completion=completed, evidence=w[56],
                sampled_sleep_diagnostic=bool(w[56] & 16), release_authorized=False)


def verify_result(body, cs, plan, actual, state, output):
    lat.verify_code(body[0x2000:], actual, cs)
    result = lat.decode(state, output, CAPACITY)
    expected = dict(g_ghead=result['batches'][-1]['consumed_cursor'],
                    g_gcount=result['observed_delta_count'],
                    g_padbad=result['copied_nonzero_padding_count'],
                    descriptor_ptr=plan.code+cs['descriptor'], descriptor_ring=lat.R,
                    g_latched_head=next((b['latched_head'] for b in reversed(result['batches'])
                                         if b['latched_head']), 0))
    if any(struct.unpack_from('<I', actual, cs[n])[0] != v for n, v in expected.items()):
        raise RuntimeError('mutable code state disagrees with capture ledger')
    return result


def _run(t, budget, sleep_reason):
    alloc, als = small_body('fpl_task_allocate.S', CAMERA.loader_defines())
    t.artifact('allocator.bin', alloc)
    t.upload(t.stage, alloc)
    t.publish('allocate')
    t.execute(t.stage, 'allocate')
    raw = t.read(t.stage, 1024)
    t.artifact('allocator-readback.bin', raw)
    r = words(raw[als['result']:als['result']+32])
    expected = bytearray(raw)
    expected[als['result']:als['result']+32] = bytes(32)
    if expected != alloc or r[0] != 2 or r[6:] != [0, 0]:
        raise RuntimeError('allocation helper result/code mismatch')
    owner, desc = r[1], r[2:6]
    t.report.update(allocation_address=owner, descriptor=desc)
    t.save()                         # retain raw ownership even if bounds fail
    if not validate_owner(desc, owner, t.publication):
        t.report['status'] = 'allocation-refused-no-create'
        return
    body, syms, plan, cs = build_owned(owner, sleep_reason=sleep_reason)
    owner_info = (struct.pack('<4I', *desc)+bytes.fromhex(t.report['token'])+
                  struct.pack('<4I', *t.publication, SIZE)).ljust(1024, b'\0')
    t.report.update(symbols={k: syms[k] for k in ('entry', 'activate', 'observe', 'body_entry')},
                    capture_symbols=cs, layout=vars(plan), owner_info_sha256=sha(owner_info),
                    prototype_sha256=sha(body), retain_for_boot=True)
    t.artifact('prototype.bin', body)
    t.artifact('ownership.bin', owner_info)
    t.candidate = (owner, body, syms, owner_info, cs)
    t.save()                         # ownership durable BEFORE launch can escape
    slot = next(i for i, w in enumerate(t.caps['windows']) if tuple(w) == (0, 0, 0))
    try:
        t.window(slot, (owner, SIZE, 3), 'grant-owned-window')
        initial = bytearray(SIZE)
        initial[OWNER_INFO:OWNER_INFO+1024] = owner_info
        initial[0x5000:0x5000+OUTPUT_ROOM] = lat.strict.SENTINEL*OUTPUT_ROOM
        t.upload(owner, bytes(initial))
        t.upload(t.stage+0x1000, body)
        t.command(t.stage+0x1000, 'launch')
        control = t.read(owner, 0x400)
        t.artifact('launch-control.bin', control)
        identity = identities(control, owner, syms)
        if words(control)[0] != 2 or words(control)[9:12] != [0, 0, 0]:
            raise RuntimeError('launcher not fresh/unattached')
        native = t.io.words(identity[0], 5)
        if len(native) != 5 or native[:4] != [identity[1], 0, 0, identity[2]]:
            raise RuntimeError('native object does not match retained holder')
        t.report['native_identity'] = identity
        t.save()
        if (t.read(owner+0x1000, 8192) != body[0x1000:] or
                t.read(owner+OWNER_INFO, 1024) != owner_info):
            raise RuntimeError('installed owned image/ownership mismatch')
        t.installed = True

        def observe(sequence, admission=False):
            label = f'observe-{sequence:02d}'
            t.command(owner+syms['observe'], label)
            data = t.read(owner+OBS, 256)
            t.artifact(label+'.bin', data)  # archive before parsing errors
            result = observation(data, owner, identity, sequence, admission=admission,
                                 sleep_reason=sleep_reason)
            t.report['observations'].append(result)
            t.save()
            return result

        observe(1, admission=True)
        t.command(owner+syms['activate'], 'activate')
        completed = False
        for sequence in range(2, budget+2):
            result = observe(sequence)
            if result['native_completion']:
                completed = True
                break
        # Full actual extents, including all padding/sentinels; no prefix read.
        control = t.read(owner, 0x400)
        wrapper = t.read(owner+0x1000, 4096)
        actual = t.read(plan.code, 4096)
        state = t.read(plan.state, lat.STATE_ROOM)
        output = t.read(plan.output, OUTPUT_ROOM)
        for name, data in (('control.bin', control), ('wrapper.bin', wrapper),
                           ('capture.bin', actual), ('state.bin', state), ('output.bin', output)):
            t.artifact(name, data)
        if (identities(control, owner, syms) != identity or wrapper != body[0x1000:0x2000] or
                t.read(owner+OWNER_INFO, 1024) != owner_info):
            raise RuntimeError('retained identity/code/ownership readback mismatch')
        lat.verify_code(body[0x2000:], actual, cs)
        if completed:
            t.report['capture'] = verify_result(body, cs, plan, actual, state, output)
        t.report['status'] = 'completed-retained' if completed else 'budget-exhausted-retained'
        t.guard()
    finally:
        # Window permission is not memory ownership. Revocation never frees.
        current = t.io.caps()
        owned_caps = dict(t.caps, windows=list(t.caps['windows']))
        owned_caps['windows'][slot] = (owner, SIZE, 3)
        revoked_caps = dict(t.caps, windows=list(t.caps['windows']))
        revoked_caps['windows'][slot] = (0, 0, 0)
        if current not in (owned_caps, revoked_caps):
            raise RuntimeError('foreign MCAPS/window change; refusing revoke; pending retained')
        if tuple(current['windows'][slot]) == (owner, SIZE, 3):
            # Only our precisely predicted grant may differ after a lost WIN
            # reply. Never normalize/adopt any other slot or capability field.
            t.caps = owned_caps
            t.window(slot, (0, 0, 0), 'revoke-owned-window')
        elif tuple(current['windows'][slot]) != (0, 0, 0):
            raise RuntimeError('window owner changed; pending retained')


def run(out, main, *, io=None, budget=4, sleep_reason=0):
    if type(budget) is not int or not 1 <= budget <= 20 or sleep_reason not in (0, 1):
        raise ValueError('budget must be 1..20; sleep reason 0 or 1')
    CAMERA.verify_main(main)          # offline identity check before Backend
    out = Path(out).resolve()
    with gf.staging_lock():           # existing pending refuses before Backend
        out.mkdir(exist_ok=False)
        sync_dir(out.parent)          # make the fresh manifest directory durable too
        io = io if io is not None else Backend()
        version = io.sh('version', retries=0)
        if (version.lstrip().startswith('ERR') or
                re.findall(r'^\s*model\s*=\s*(\S+)\s*$', version, re.M) != ['w91c1'] or
                re.findall(r'^\s*rel version\s*=\s*(\S+)\s*$', version, re.M) != ['3.02.0.V90'] or
                re.findall(r'^\s*git hash\s*=\s*(\S+)\s*$', version, re.M) != [GIT_HASH]):
            raise ValueError('expected exact fp L 3.02 version')
        publication, caps = io.words(gf.PUBLICATION, 3), io.caps()
        stage = staging(caps, publication)
        swap.reconcile_caps(caps, publication)
        worker_plan = swap.plan(publication, caps, 1)  # bounds only; never arms a swap
        idle = swap_words(io, worker_plan['POOL'])
        if (len(caps.get('windows', [])) != 8 or
                not any(tuple(w) == (0, 0, 0) for w in caps['windows']) or
                io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]):
            raise ValueError('staging/window/echo admission refused')
        report = dict(kind='fpl-retained-task-v1', token=secrets.token_hex(16),
                      main_sha256=CAMERA.main_sha256, version=version, publication=publication,
                      firmware_git_hash=GIT_HASH, swap_words=idle,
                      staging_address=stage, staging_bytes=0x4000,
                      caps=caps, boot_identity_available=False, hardware_validated=False,
                      release_authorized=False, status='pre-allocation', operations=[], observations=[],
                      artifacts={}, source_sha256={str(p.relative_to(HERE)): sha(p.read_bytes())
                          for p in (Path(__file__).resolve(), HERE/'asm/fpl_task_allocate.S',
                                    HERE/'asm/fpl_task_entry.S', HERE/'asm/fpl_gyro_task_retained.S')})
        t = Trial(io, out, report)
        t.save()
        marker = dict(kind=report['kind'], token=report['token'], manifest=str(out/'manifest.json'),
                      policy='retained; no automatic clear/resume/retry; boot identity unavailable')
        durable(gf.LOCK_PATH.with_suffix('.pending'), (json.dumps(marker)+'\n').encode())
        try:
            t.guard()
            try:
                resident = swap.resident(io, worker_plan['DEST'])
            finally:
                t.guard()           # whole MCAPS must equal the pre-grant snapshot
            resident_sha = sha(resident)
            report['resident'] = dict(address=worker_plan['DEST'], bytes=len(resident),
                                      sha256=resident_sha, required_sha256=swap.PONG_SHA)
            t.save()
            if len(resident) != swap.SIZE or resident_sha != swap.PONG_SHA:
                raise RuntimeError('unknown/non-PONG resident body')
            t.artifact('resident-pong.bin', resident)
            report['admission_pong'] = t.pong('admission-pong')
            t.save()
            _run(t, budget, sleep_reason)
            outcome = report['status']
            report['status'] = 'final-pong-pending-retained'
            t.save()
            report['final_pong'] = t.pong('final-pong')  # after all readback and revocation
            report['status'] = outcome
        except BaseException as error:
            status = ('final-pong-uncertain-retained' if report['status'] == 'final-pong-pending-retained'
                      else 'failed-retained-or-allocation-uncertain')
            report.update(status=status, error=str(error))
            t.save()
            raise
        t.save()
        return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True, help='fresh directory; executes ONE camera trial')
    ap.add_argument('--main', type=Path, required=True, help='official fp L 3.02 MAIN')
    ap.add_argument('--budget', type=int, default=4, help='1..20 finite observations after activation')
    ap.add_argument('--sleep-reason', type=int, choices=(0, 1), default=0)
    args = ap.parse_args(argv)
    result = run(args.out, args.main, budget=args.budget, sleep_reason=args.sleep_reason)
    print(f'{args.out}: {result["status"]}; ownership and pending interlock retained')


if __name__ == '__main__':
    main()
