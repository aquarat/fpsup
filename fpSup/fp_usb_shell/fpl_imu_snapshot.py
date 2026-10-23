#!/usr/bin/env python3
"""Finite passive fp L 3.02 IMU snapshot.

Live October 20: expected pointers, 600 records, accel cache and restoration
verified; moving head correctly reported stale. Atomic sampling is not proven.
--records N selects a bounded recent-record copy for N<600 (offline-tested
only); default 600 retains the original full-ring code and binary artifact.

Import/help are offline. Running --out DIR operates the camera once, using
fpl_getfile's advisory staging lock and checked echo/cache bootstrap. Use only
on an authorized idle camera. No recording, IMU init/stop, hooks or card I/O.
Stable heads/publications do NOT prove atomicity, freshness or zero sample loss;
accel is three successive loads. No rate, scale or physical-axis calibration.
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
MAGIC = 0x31554D49
P_EXPECTED, R_EXPECTED = 0x2E006004, 0x2E00644C
RING_BYTES, RESULT_ROOM = 0x12C4, 0x1400
STATUS = {1: 'valid_observed_stable', 2: 'stale', 3: 'unavailable',
          4: 'invalid_descriptor', 5: 'invalid_ring', 6: 'invalid_head'}


def validate_records(records):
    if type(records) is not int or not 1 <= records <= 600:
        raise ValueError('records must be an integer in 1..600')
    return records


def code_for(plan, records=600):
    validate_records(records)
    code = gf.assemble(HERE / 'asm/fpl_imu_snapshot.S',
                       [f'PARAM={plan.param:#x}', f'RESULT={plan.buffer:#x}',
                        f'RECORD_COUNT={records}'])
    if not code or len(code) > gf.CODE_ROOM:
        raise ValueError('snapshot code exceeds gf code reservation')
    return code.ljust(gf.CODE_ROOM, b'\0')


def head_index(head, ring):
    """Zero-based last completed record; None for uninitialized/invalid head."""
    delta = head - ring
    return delta // 8 - 1 if 8 <= delta <= 0x12C0 and delta % 8 == 0 else None


def decode(param, result, records=600):
    validate_records(records)
    copy_bytes = 4 + records * 8
    if len(param) != gf.PARAM_ROOM or len(result) != RESULT_ROOM:
        raise RuntimeError('short snapshot readback')
    fields = struct.unpack_from('<16I', param)
    magic, status, p, ring, m64, m68, hb, ha, pe, re_, ax, ay, az, copied, z0, z1 = fields
    if magic != MAGIC or status not in STATUS:
        raise RuntimeError('snapshot did not complete with known status')
    if z0 or z1 or any(param[64:]) or any(result[copy_bytes:]):
        raise RuntimeError('snapshot reservation guard changed')
    if copied not in (0, copy_bytes) or (not copied and any(result)):
        raise RuntimeError('invalid snapshot copy extent')
    if copied and (p, ring) != (P_EXPECTED, R_EXPECTED):
        raise RuntimeError('copy from unvalidated pointers')
    hi = head_index(hb, ring) if ring == R_EXPECTED else None
    ai = head_index(ha, ring) if ring == R_EXPECTED else None
    raw_head = struct.unpack_from('<I', result)[0] if copied else None
    if records < 600 and copied and (hi is None or raw_head != hb):
        raise RuntimeError('recent snapshot header differs from latched head')
    if status == 1 and (copied != copy_bytes or p != pe or ring != re_ or
                        hi is None or ai is None or hb != ha or hb != raw_head):
        raise RuntimeError('inconsistent stable snapshot')
    if status == 3 and (p or pe or ring or copied):
        raise RuntimeError('inconsistent unavailable snapshot')
    changed = p != pe or (p == P_EXPECTED and ring != re_)
    if status == 2 and not (changed or (copied and (hb != ha or hb != raw_head))):
        raise RuntimeError('stale status without observed change')
    if status == 4 and (p in (0, P_EXPECTED) or changed or ring or copied):
        raise RuntimeError('inconsistent invalid descriptor')
    if status == 5 and (p != P_EXPECTED or ring == R_EXPECTED or changed or copied):
        raise RuntimeError('inconsistent invalid ring')
    if status == 6 and (p != P_EXPECTED or ring != R_EXPECTED or changed or
                        (hi is not None if not copied else ai is not None)):
        raise RuntimeError('inconsistent invalid head')
    def signed(v):
        return v if v < 0x80000000 else v - 0x100000000
    accel = [signed(v) for v in (ax, ay, az)]
    if any(v < -32768 or v > 32767 for v in accel):
        raise RuntimeError('accelerometer is not sign-extended i16')
    samples = [list(struct.unpack_from('<hhhh', result, 4 + i*8))
               for i in range(records)] if copied else []
    order = 'ring_storage' if records == 600 else 'recent_chronological'
    return dict(status_code=status, status=STATUS[status],
                descriptor_before=p, descriptor_after=pe,
                ring_before=ring, ring_after=re_,
                descriptor_64_uninterpreted=m64, descriptor_68_uninterpreted=m68,
                head_before=hb, head_after=ha, head_in_copy=raw_head,
                last_completed_index_before=hi, last_completed_index_after=ai,
                next_index_before=(hi+1) % 600 if hi is not None else None,
                copied_bytes=copied, accel_raw_i16=accel,
                requested_records=records, record_order=order,
                header_kind='copied_ring_head' if records == 600 else 'latched_head_before',
                first_record_storage_index=(0 if records == 600 else (hi-records+1) % 600)
                if copied else None,
                record_fields=['component_0', 'component_1', 'padding', 'component_2'],
                **{'records_storage_order' if records == 600 else 'records_chronological_order': samples},
                nonzero_padding_records=sum(r[2] != 0 for r in samples),
                limitations=['not an atomic CPU/coprocessor snapshot',
                             'no freshness, lap-count, rate or physical-axis proof',
                             'record order is not a validated time series',
                             'accelerometer components loaded successively'])


def snapshot(io=None, *, records=600):
    validate_records(records)           # before lock, Backend, or camera I/O
    with gf.staging_lock():
        return _snapshot_locked(io or gf.Backend(), records)


def _snapshot_locked(io, records=600):
    validate_records(records)
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
        re.findall(r'^\s*model\s*=\s*(\S+)\s*$', version, re.M) != ['w91c1'] or
        re.findall(r'^\s*rel version\s*=\s*(\S+)\s*$', version, re.M) != ['3.02.0.V90']):
        raise ValueError(f'expected exact fp L 3.02 version, got {version!r}')
    publication = io.words(gf.PUBLICATION, 3)
    plan = gf.layout(io.caps(), publication, RESULT_ROOM)
    if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock; cannot borrow it')
    code = code_for(plan, records)
    for address, data in ((plan.code, code), (plan.param, bytes(gf.PARAM_ROOM)),
                          (plan.fobj, bytes(gf.FOBJ_ROOM)),
                          (plan.buffer, bytes(RESULT_ROOM))):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('snapshot staging readback mismatch')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo owner changed during staging')
    try:
        for handler in (gf.DCACHE, gf.ICACHE):
            gf.set_handler(io, handler)
            gf.echo(io)                 # retries=0: never rerun uncertain code
        gf.set_handler(io, plan.code)
        utc_before = time.time_ns()
        monotonic_before = time.monotonic_ns()
        try:
            gf.echo(io)                 # exactly one probe attempt, retries=0
        finally:
            monotonic_after = time.monotonic_ns()
            utc_after = time.time_ns()
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    if io.words(gf.PUBLICATION, 3) != publication:
        raise RuntimeError('publication changed during execution')
    if io.read(plan.code, gf.CODE_ROOM) != code or io.read(plan.fobj, gf.FOBJ_ROOM) != bytes(gf.FOBJ_ROOM):
        raise RuntimeError('code or unused staging guard changed')
    param = io.read(plan.param, gf.PARAM_ROOM)
    result = io.read(plan.buffer, RESULT_ROOM)
    report = decode(param, result, records)
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo owner changed during readback')
    report.update(firmware_version_reply=version, publication=publication,
                  host_probe_echo_bounds=dict(
                      meaning='host call bounds only, not sample timestamps',
                      utc_clock='Unix epoch nanoseconds (UTC); wall clock may adjust',
                      monotonic_clock='host monotonic nanoseconds; not comparable across hosts or boots',
                      utc_before_ns=utc_before, utc_after_ns=utc_after,
                      monotonic_before_ns=monotonic_before,
                      monotonic_after_ns=monotonic_after),
                  code_sha256=hashlib.sha256(code).hexdigest(),
                  result_sha256=hashlib.sha256(result).hexdigest(),
                  layout=dict(code=plan.code, param=plan.param, buffer=plan.buffer),
                  tool_validation='offline-tested; live full-ring access observed, atomic sampling unproven')
    if records < 600:
        report['recent_mode_validation'] = 'offline-tested only; no live recent-mode trial'
    return report, param, result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True,
                        help='new local directory for snapshot.json, parameters.bin, ring.bin')
    parser.add_argument('--records', type=int, default=600,
                        help='1..599: last N records, chronological; 600 (default): full ring, storage order')
    args = parser.parse_args(argv)
    try:
        validate_records(args.records)
    except ValueError as error:
        parser.error(str(error))
    # Reserve destination before any camera access; preserve empty dir on failure.
    args.out.mkdir(exist_ok=False)
    report, param, result = snapshot(records=args.records)
    with (args.out / 'parameters.bin').open('xb') as f:
        f.write(param)
    if report['copied_bytes']:
        with (args.out / 'ring.bin').open('xb') as f:
            f.write(result[:report['copied_bytes']])
    report['ring_artifact'] = 'ring.bin' if report['copied_bytes'] else None
    with (args.out / 'snapshot.json').open('x') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print(f"{args.out}: {report['status']}; {report['copied_bytes']} ring bytes")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
