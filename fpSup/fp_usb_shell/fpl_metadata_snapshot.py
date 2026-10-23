#!/usr/bin/env python3
"""Finite passive fp L 3.02 raw settings/lens diagnostic.

Live October 20: guarded cache reads and echo restoration verified. Cache
freshness, coherence, field units and calibration remain unverified.

Import/help are offline. --out NEW_DIR runs once on an authorized camera using
verified RAM staging, cache publication, borrowed echo and checked restoration.
No constructors, stock getters, firmware writes, card I/O or calibrated values.
Construction guards do not lock cache updates: consistency/freshness unverified.
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
MAGIC, ABI = 0x3154454D, 1
RESULT_ROOM, RESULT_BYTES = 0x400, 0x60
SETTINGS_GUARD, LENS_GUARD = 0xC31F70B0, 0xC3477208
WIDTH, HEIGHT, FORMAT = 0xC31F6ABC, 0xC31F6AC0, 0xC31F6AC8
NAME, FOCAL = 0xC34657B8, 0xC34657FC


def code_for(plan):
    code = gf.assemble(HERE/'asm/fpl_metadata_snapshot.S',
                       [f'PARAM={plan.param:#x}', f'RESULT={plan.buffer:#x}'])
    if not code or len(code) > gf.CODE_ROOM:
        raise ValueError('metadata snapshot exceeds code reservation')
    return code.ljust(gf.CODE_ROOM, b'\0')


def decode(param, result):
    if len(param) != gf.PARAM_ROOM or len(result) != RESULT_ROOM:
        raise RuntimeError('short snapshot readback')
    magic, abi, mask, size = struct.unpack_from('<4I', param)
    if (magic, abi, size) != (MAGIC, ABI, RESULT_BYTES) or mask & ~3:
        raise RuntimeError('invalid completion/version/extent')
    if any(param[16:]) or any(result[RESULT_BYTES:]):
        raise RuntimeError('reservation guard changed')
    groups = []
    expected_mask = 0
    for offset, guard, length, bit in ((0, SETTINGS_GUARD, 12, 1), (0x20, LENS_GUARD, 36, 2)):
        before, after, copied, reserved = struct.unpack_from('<4I', result, offset)
        payload = result[offset+16:offset+16+length]
        if reserved or any(result[offset+16+length:offset+(0x20 if bit == 1 else 0x40)]):
            raise RuntimeError('group reserved bytes changed')
        expected_copy = length if before == 1 else 0
        if copied != expected_copy or (before != 1 and (after or any(payload))):
            raise RuntimeError('masked or skipped payload inconsistent with exact guard')
        if before == 1:
            expected_mask |= bit
        status = ('not_ready' if before == 0 else 'initializing_or_unknown' if before != 1
                  else 'guard_changed' if after != 1 else 'constructed_cache_observed')
        group = dict(status=status, guard_address=guard, guard_before=before,
                     consistency='unverified', units='unknown', calibrated=False)
        if before == 1:
            group['guard_after'] = after
        # Changed copies remain only in raw_result_hex / observations.bin.
        if status == 'constructed_cache_observed':
            if bit == 1:
                group['payload'] = {key: dict(raw_u32=value, address=address)
                                    for key, value, address in zip(('width', 'height', 'format'),
                                        struct.unpack('<3I', payload), (WIDTH, HEIGHT, FORMAT))}
            else:
                name = payload[:32]
                nul = name.find(b'\0')
                group['payload'] = dict(
                    name=dict(address=NAME, raw_hex=name.hex(), captured_bytes=32,
                              byte_length=nul if nul >= 0 else 32, nul_seen=nul >= 0,
                              limit_reached=nul < 0, encoding='unknown'),
                    focal=dict(address=FOCAL, raw_u32=struct.unpack_from('<I', payload, 32)[0]))
        groups.append(group)
    if mask != expected_mask:
        raise RuntimeError('copied mask disagrees with guards')
    return dict(status='passive_cache_observation', settings_snapshot=groups[0], lens_snapshot=groups[1],
                consistency='unverified', units='unknown', calibrated=False,
                raw_result_hex=result[:RESULT_BYTES].hex(),
                limitations=['construction guards do not protect subsequent updates; torn loads and ABA possible',
                             'groups are sequential, not atomic; no freshness or active recording raster proof',
                             'empty name/focal does not prove no lens; no scale, enum or optical calibration',
                             'advisory host lock does not exclude camera tasks or unrelated clients'])


def snapshot(io=None):
    with gf.staging_lock():
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
            gf.echo(io)  # one attempt, even for an uncertain response
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
    report.update(firmware_identity=dict(model='w91c1', release='3.02.0.V90', version_reply=version),
                  publication=publication,
                  host_probe_echo_bounds=dict(meaning='host call bounds only, not firmware/sample timestamps',
                                              utc_before_ns=utc_before, utc_after_ns=utc_after,
                                              monotonic_before_ns=mono_before, monotonic_after_ns=mono_after,
                                              clock_notes='UTC may adjust; monotonic not comparable across boots/hosts'),
                  code_sha256=hashlib.sha256(code).hexdigest(), result_sha256=hashlib.sha256(result).hexdigest(),
                  layout=dict(code=plan.code, param=plan.param, buffer=plan.buffer),
                   validation='live passive cache access verified; coherence and calibration unproven')
    return report, param, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='fresh local output directory')
    args = parser.parse_args(argv)
    args.out.mkdir(exist_ok=False)
    report, param, result = snapshot()
    for name, data in (('parameters.bin', param), ('observations.bin', result)):
        with (args.out/name).open('xb') as out:
            out.write(data)
    with (args.out/'snapshot.json').open('x') as out:
        json.dump(report, out, indent=2)
        out.write('\n')
    print(f"{args.out}: {report['status']}; raw, uncalibrated cache only")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
