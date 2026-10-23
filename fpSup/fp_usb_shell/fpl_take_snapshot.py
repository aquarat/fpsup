#!/usr/bin/env python3
"""Finite passive fp L 3.02 naming/context observation.

Live October 20: expected context/SD identity, uninitialized SSD, matching
observations and restored echo verified. No naming reservation/readiness proof.

Import and --help are offline. --out NEW_DIR operates an authorized camera once:
verified RAM staging/cache publication, borrowed echo, verified restoration.
No recording hooks, constructors, settings writes, media initialization or card I/O.
The ARM routine reads both fixed Cinema managers and accepts ONLY the exact
context object C3074BA8, never arbitrary RAM. Unknown temporary pointers refuse.
Two equal observations do not prove coherence, readiness, reservation or a take's
identity. Host bounds bracket the echo call, not firmware/sample timestamps.
Candidate numbers are explicitly unreserved diagnostics; no filename is emitted.
The advisory staging lock does not exclude camera tasks or unrelated clients.
Build-contract external OG/load-chain evidence is not needed or claimed here;
this is a finite diagnostic, not a sup/card or a replacement loader.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time

import fpl_getfile as gf

HERE = Path(__file__).resolve().parent
MAGIC, ABI = 0x314B4154, 1
RESULT_ROOM, RESULT_BYTES, FRAME_BYTES = 0x400, 0xC0, 0x60
CONTEXT, CONTEXT_END, CONTEXT_PUB = 0xC3074BA8, 0xC307518C, 0xC30751F0
SSD, SD, VTABLE = 0xC34392D0, 0xC3439338, 0xC0B8D874
FIELDS = ('volume', 'vtable', 'letter', 'reel', 'current_take', 'saved_take', 'gate44', 'gate45')


def valid_context(pointer):
    return (pointer % 4 == 0 and CONTEXT <= pointer <= CONTEXT_END-0x5DA
            and pointer == CONTEXT)


def code_for(plan):
    code = gf.assemble(HERE/'asm/fpl_take_snapshot.S',
                       [f'PARAM={plan.param:#x}', f'RESULT={plan.buffer:#x}'])
    if not code or len(code) > gf.CODE_ROOM:
        raise ValueError('take snapshot exceeds code reservation')
    return code.ljust(gf.CODE_ROOM, b'\0')


def decode(param, result):
    if len(param) != gf.PARAM_ROOM or len(result) != RESULT_ROOM:
        raise RuntimeError('short snapshot readback')
    magic, abi, changed, size = struct.unpack_from('<4I', param)
    if (magic, abi, size) != (MAGIC, ABI, RESULT_BYTES) or changed & ~15:
        raise RuntimeError('invalid completion/version/extent')
    if any(param[16:]) or any(result[RESULT_BYTES:]):
        raise RuntimeError('reservation guard changed')
    frames, raw = [], []
    for offset in (0, FRAME_BYTES):
        words = struct.unpack_from('<24I', result, offset)
        raw.append(words)
        before, after, state, reset, letter, reel, z0, z1 = words[:8]
        expected = 0 if before == 0 else 1 if valid_context(before) else 2
        if (state != expected or z0 or z1 or reset > 255 or letter > 255 or reel > 65535
                or (state != 1 and any((reset, letter, reel)))):
            raise RuntimeError('invalid context capture')
        frame = dict(context=dict(publication_before=before, publication_after=after,
                                  status=('unavailable_null', 'exact_object_read', 'unknown_pointer_refused')[state],
                                  reset=reset, letter=letter, reel=reel))
        for name, start, volume in (('ssd', 8, 5), ('sd', 16, 1)):
            values = words[start:start+8]
            manager = dict(zip(FIELDS, values))
            if any(manager[k] > 255 for k in ('letter', 'gate44', 'gate45')):
                raise RuntimeError('manager byte field not zero extended')
            manager['volume_matches'] = manager['volume'] == volume
            manager['vtable_matches'] = manager['vtable'] == VTABLE
            manager['identity_status'] = ('unavailable_uninitialized' if not manager['volume'] or not manager['vtable']
                                          else 'identity_matches_readiness_unproven'
                                          if manager['volume_matches'] and manager['vtable_matches']
                                          else 'identity_mismatch')
            frame[name] = manager
        frames.append(frame)
    a, b = raw
    expected_flags = ((a[8:16] != b[8:16]) | ((a[16:24] != b[16:24]) << 1)
                      | ((a[2:6] != b[2:6]) << 2)
                      | ((len({a[0], a[1], b[0], b[1]}) != 1) << 3))
    if changed != expected_flags:
        raise RuntimeError('changed flags disagree with captured observations')
    candidates = {}
    for name in ('ssd', 'sd'):
        m, c = frames[0][name], frames[0]['context']
        # Conservative diagnostic eligibility; gates are NOT a readiness proof.
        # Refuse an unsynchronized/blocked-looking manager instead of inventing
        # a name. Stock arithmetic is signed; admit only its nonnegative domain.
        eligible = (not changed and c['status'] == 'exact_object_read'
                    and m['volume_matches'] and m['vtable_matches']
                    and m['gate44'] == 0 and m['gate45'] == 1
                    and 65 <= m['letter'] <= 90 and 1 <= m['reel'] <= 999
                    and (m['letter'], m['reel']) == (c['letter'], c['reel'])
                    and 0 <= m['current_take'] <= 999 and 0 <= m['saved_take'] <= 999)
        number = (m['current_take'] if c['reset'] else max(m['current_take'], m['saved_take'])) + 1
        candidates[name] = dict(number=number if eligible and 1 <= number <= 999 else None,
                                meaning='tentative unreserved diagnostic only; not a filename or active take')
    return dict(status='changed' if changed else 'no_change_observed_not_coherent',
                changed_flags=changed, changed=dict(ssd=bool(changed & 1), sd=bool(changed & 2),
                                                  context_fields=bool(changed & 4), publication=bool(changed & 8)),
                observations=frames, candidates=candidates,
                limitations=['sequential loads; intra-tuple races and ABA can escape detection',
                             'no lock on firmware state; not reentrant across staging users',
                             'identity/gates do not establish media readiness or reserve names',
                             'unknown context identities refused, even within mapped RAM',
                             'no active-volume selection or START event observed',
                             'current START hook covers only the audio-file branch',
                             'no clip success, overwrite avoidance, or filename association proof'])


def snapshot(io=None):
    with gf.staging_lock():  # includes pending-handoff refusal before Backend
        return _snapshot_locked(io or gf.Backend())


def _snapshot_locked(io):
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
        re.findall(r'^\s*model\s*=\s*(\S+)\s*$', version, re.M) != ['w91c1'] or
        re.findall(r'^\s*rel version\s*=\s*(\S+)\s*$', version, re.M) != ['3.02.0.V90']):
        raise ValueError('expected exact fp L 3.02 version')
    publication = io.words(gf.PUBLICATION, 3)
    caps = io.caps()
    if not isinstance(caps, dict) or any(type(caps.get(k)) is not int for k in ('pool', 'pool_size', 'xfer')):
        raise ValueError('complete integer MCAPS required')
    plan = gf.layout(caps, publication, RESULT_ROOM)
    if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock')
    code = code_for(plan)
    for address, data in ((plan.code, code), (plan.param, bytes(gf.PARAM_ROOM)),
                          (plan.fobj, bytes(gf.FOBJ_ROOM)), (plan.buffer, bytes(RESULT_ROOM))):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('staging readback mismatch')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo owner changed during staging')
    try:
        for handler in (gf.DCACHE, gf.ICACHE):
            gf.set_handler(io, handler)
            gf.echo(io)
        if io.words(gf.PUBLICATION, 3) != publication:
            raise RuntimeError('publication changed before probe')
        gf.set_handler(io, plan.code)
        utc_before, mono_before = time.time_ns(), time.monotonic_ns()
        try:
            gf.echo(io)  # one attempt only, including an uncertain response
        finally:
            mono_after, utc_after = time.monotonic_ns(), time.time_ns()
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    if io.words(gf.PUBLICATION, 3) != publication:
        raise RuntimeError('publication changed during probe')
    if io.read(plan.code, gf.CODE_ROOM) != code or io.read(plan.fobj, gf.FOBJ_ROOM) != bytes(gf.FOBJ_ROOM):
        raise RuntimeError('code or unused staging guard changed')
    param, result = io.read(plan.param, gf.PARAM_ROOM), io.read(plan.buffer, RESULT_ROOM)
    report = decode(param, result)
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo changed during readback')
    report.update(firmware_version_reply=version, publication=publication,
                  host_probe_echo_bounds=dict(meaning='host call bounds only, not firmware/sample timestamps',
                                              utc_before_ns=utc_before, utc_after_ns=utc_after,
                                              monotonic_before_ns=mono_before, monotonic_after_ns=mono_after,
                                              clock_notes='UTC may adjust; monotonic not comparable across boots/hosts'),
                  code_sha256=hashlib.sha256(code).hexdigest(),
                  result_sha256=hashlib.sha256(result).hexdigest(),
                  layout=dict(code=plan.code, param=plan.param, buffer=plan.buffer),
                   validation='live passive field access verified; naming/readiness/coherence unproven')
    return report, param, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='fresh local output directory')
    args = parser.parse_args(argv)
    args.out.mkdir(exist_ok=False)  # before Backend, lock or camera operations
    report, param, result = snapshot()
    for name, data in (('parameters.bin', param), ('observations.bin', result)):
        with (args.out/name).open('xb') as out:
            out.write(data)
    with (args.out/'snapshot.json').open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(f"{args.out}: {report['status']}; unreserved diagnostic only")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
