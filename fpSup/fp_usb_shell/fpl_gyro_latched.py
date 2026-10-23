#!/usr/bin/env python3
"""Opt-in finite fp L conditional gyro diagnostic.

Live October 20: twenty observations/1142 records, guards and echo restored.
That verifies finite execution, not the coherence assumptions below.

--out performs one capture only when separately authorized. There is no resume.
Conditional prefixes assume no hidden laps, ordered visible publications and a
continuous producer epoch. proven_valid_records is ALWAYS zero.

Opt-in invocation (runtime-reference mode live-verified October 23):
  python3 -B fpl_gyro_latched.py --runtime-refs --capacity 1200 --out NEW_DIRECTORY
Without --runtime-refs the established fixed probe is unchanged. Runtime mode
copies a position-independent body, initializes its five PC-relative reference
words, verifies the whole upload, publishes D/I, then calls it as echo. Echo r0
is ignored. References remain immutable during the call and checked on readback;
only the six symbol-derived producer state words may change. Reservations stay
owned/serialized through readback, using the existing verified worker pool; no
allocation/free, task or hook lifecycle is added. Invalid runtime references
return 15 without a result marker; the host rejects that incomplete capture.

Canonical runtime body (reverified with the explicit shared local-slot seams;
identical bytes to the earlier adapter build): 1332 bytes, SHA-256
5a6d1c23b32785b6076efb97762b1997c3cd1cc0da7c81641406168cb0f8512e
(zero reference table, initial mutable state, no 4096-byte reservation padding).
capture.json records this stable-body hash and the separately hashed initialized
upload. It is provenance, not a runtime version/hash pairing requirement.
Runtime live trial: twenty observations/1114 records; code/reference/output
guards and echo restoration passed. Coherence assumptions remain unproven.
The shared drain accepts GYRO_DESC_LOCAL and GYRO_LATCH_LOCAL as local slot
labels; each is exclusive with its corresponding absolute option. The wrapper
undefines its local options after inclusion and never redefines ARM mnemonics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import time

import fpl_gyro_capture as strict

gf, armasm = strict.gf, strict.armasm
SOURCE = Path(__file__).resolve().parent/'asm/fpl_gyro_latched.S'
CODE_ROOM, STATE_ROOM, ROW_BYTES, ROWS = 4096, 2048, 80, 20
MAGIC, UNARMED, P, R = 0x54414C47, 0xFFFFFFFF, 0x2E006004, 0x2E00644C
MUTABLE = strict.MUTABLE + ('g_latched_head',)
STATUS = {1: 'armed_no_copy', 2: 'no_observed_delta', 3: 'conditional_window_pass',
          4: 'possible_overwrite', 5: 'capacity_loss', 10: 'unavailable_descriptor',
          11: 'invalid_descriptor', 12: 'invalid_ring', 13: 'invalid_head',
          14: 'invalid_cursor_provenance', 100: 'finite_observations_completed'}
ASSUMPTIONS = ['no hidden full laps before or during each batch (not established)',
               'ordered and coherent data/head visibility (not established)',
               'single sequential producer with at most one unpublished record',
               'continuous producer epoch; endpoint checks cannot exclude pointer ABA',
               '20 ms delay is not a maximum scheduling gap or a sample-rate measurement']


def layout(caps, publication, capacity):
    plan = strict.layout(caps, publication, strict.validate_capacity(capacity))
    # Same staging/code reservation and guard policy, one extra KiB of metadata.
    plan = strict.Layout(plan.code, plan.state, plan.output+STATE_ROOM-strict.STATE_ROOM,
                         plan.output_room)
    pool, room, _ = publication
    if plan.output+plan.output_room > pool+room:
        raise ValueError('latched metadata/output exceed owned staging')
    validate_plan(plan, capacity)
    return plan


def validate_plan(plan, capacity):
    strict.validate_capacity(capacity)
    extents = [(plan.code, CODE_ROOM), (plan.state, STATE_ROOM), (plan.output, plan.output_room)]
    if (plan.output_room < capacity*8+1024 or plan.output_room % 1024 or
            any(type(a) is not int or a % 1024 or a < 0x40000000 or a+n > 2**32
                for a, n in extents) or
            any(a < b+m and b < a+n for i, (a, n) in enumerate(extents)
                for b, m in extents[i+1:])):
        raise ValueError('invalid/overlapping owned diagnostic extents')


def runtime_body(*, cancel=False):
    """Stable, placement-independent template; its five reference words are zero.

    Invoke capture directly as an echo handler after initializing those words
    with code_for(..., runtime=True) and publishing D/I. Incoming r0 is ignored.
    Invalid references return 15 without writing a completion header. Neither
    this mode nor the fixed mode allocates/frees or installs a resident worker.
    """
    defs = ['RUNTIME_REFS=1', f'LAT_CANCEL={int(cancel)}']
    return armasm.assemble(SOURCE, defs), armasm.symbols(SOURCE, defs)


def code_for(plan, capacity, *, runtime=False, cancel=False):
    """Offline build; cancellation is opt-in and adds no live command surface.

    The opted-in image owns g_cancel_request inside CODE_ROOM. A single owner
    may publish a nonzero request; capture never clears it. The caller retains
    all storage and enforces one-shot invocation. No wall-time bound is implied.
    """
    if type(cancel) is not bool:
        raise ValueError('cancel must be boolean')
    validate_plan(plan, capacity)
    defs = [f'CODE={plan.code}', f'STATE={plan.state}', f'OUTPUT={plan.output}',
            f'CAPACITY={capacity}', f'LAT_CANCEL={int(cancel)}']
    if runtime:
        code, syms = runtime_body(cancel=cancel)
        if (syms['runtime_refs_end']-syms['runtime_refs'] != 20 or
                any(a+n > 0x80000000 for a, n in
                    ((plan.code, CODE_ROOM), (plan.state, STATE_ROOM),
                     (plan.output, plan.output_room)))):
            raise ValueError('invalid runtime reference extent')
        code = bytearray(code)
        struct.pack_into('<5I', code, syms['runtime_refs'], plan.state, STATE_ROOM,
                         plan.output, plan.output_room, capacity)
        code = bytes(code)
    else:
        code = armasm.assemble(SOURCE, defs)
        syms = armasm.symbols(SOURCE, defs)
    offsets = [syms[name] for name in MUTABLE + (('g_cancel_request',) if cancel else ())]
    if (not code or len(code) > CODE_ROOM or syms.get('capture') != 0 or
            len(set(offsets)) != len(offsets) or
            any(o % 4 or not 0 <= o <= len(code)-4 for o in offsets)):
        raise ValueError('invalid code/mutable symbol bounds')
    return code.ljust(CODE_ROOM, b'\0'), syms


def verify_code(expected, actual, syms, *, cancel=False):
    """Exact default six-word mask; only explicit opt-in adds the request word."""
    if len(actual) != len(expected):
        raise RuntimeError('short code readback')
    masked = bytearray(actual)
    if cancel:
        offset = syms['g_cancel_request']
        if offset % 4 or not 0 <= offset <= len(expected)-4:
            raise RuntimeError('invalid cancellation word extent')
        masked[offset:offset+4] = expected[offset:offset+4]
    offset = syms['g_latched_head']
    masked[offset:offset+4] = expected[offset:offset+4]
    strict.verify_code(expected, masked, syms)  # exact guard, same five other words


def _snapshot_status(p, r, h):
    if p != P:
        if r or h:
            raise RuntimeError('unread pointer snapshot fields changed')
        return 10 if p == 0 else 11
    if r != R:
        if h:
            raise RuntimeError('unread head snapshot changed')
        return 12
    return 0 if strict.head_valid(h) else 13


def decode(state, output, capacity, *, cancel=False):
    """Decode the ledger; status 101 is valid only for a cancellation build."""
    strict.validate_capacity(capacity)
    if len(state) != STATE_ROOM or len(output) < capacity*8+1024:
        raise RuntimeError('short diagnostic readback')
    header = struct.unpack_from('<16I', state)
    magic, final, nrows, total, observed, padbad, dropped, prefix, delays, proven, schema, cap = header[:12]
    cancelled = cancel and final == 101
    if (magic != MAGIC or (final not in STATUS and not cancelled) or
            not (0 if cancelled else 1) <= nrows <= ROWS or
            schema != 1 or cap != capacity or proven or any(header[12:])):
        raise RuntimeError('invalid completion header')
    if any(state[64+nrows*ROW_BYTES:]):
        raise RuntimeError('unused rows/state guard changed')
    cursor, count, obs, drops, pads, accepted = UNARMED, 0, 0, 0, 0, 0
    rows = []
    for i in range(nrows):
        w = struct.unpack_from('<20I', state, 64+i*ROW_BYTES)
        status, prior, latch, post, consumed = w[:5]
        pre_p, pre_r, pre_h, post_p, post_r, post_h = w[5:11]
        start, appended, delta, lost, badpad, advance, slack, after, reserved = w[11:]
        if prior != cursor or start != count or reserved or post != post_h:
            raise RuntimeError('cursor/output provenance mismatch')
        before_error = _snapshot_status(pre_p, pre_r, pre_h)
        expected_delta, expected_appended, expected_lost, expected_a, expected_slack = 0, 0, 0, 0, 0
        if before_error:
            expected_status = before_error
            if latch or consumed != prior or any((post_p, post_r, post_h)):
                raise RuntimeError('drained despite invalid initial snapshot')
        else:
            if latch != pre_h or consumed != latch:
                raise RuntimeError('drain consumed an unlatched cursor')
            expected_delta = 0 if prior == UNARMED else ((latch-prior) % 4800)//8
            expected_appended = min(expected_delta, capacity-count)
            expected_lost = expected_delta-expected_appended
            after_error = _snapshot_status(post_p, post_r, post_h)
            if after_error:
                expected_status = after_error
            else:
                expected_a = ((post_h-latch) % 4800)//8
                expected_slack = 600-expected_delta
                if prior == UNARMED:
                    expected_status = 1
                elif expected_delta == 0:
                    expected_status = 2
                elif expected_a >= expected_slack:
                    expected_status = 4
                else:
                    expected_status = 5 if expected_lost else 3
                    accepted += expected_appended
        if (status != expected_status or (delta, appended, lost, advance, slack) !=
                (expected_delta, expected_appended, expected_lost, expected_a, expected_slack)
                or badpad > appended or after != accepted):
            raise RuntimeError('inconsistent batch accounting/window disposition')
        if i < nrows-1 and status not in (1, 2, 3):
            raise RuntimeError('continued after rejected/lost batch')
        count += appended
        obs += delta
        drops += lost
        pads += badpad
        rows.append(dict(index=i, disposition=STATUS[status], prior_cursor=prior,
                         latched_head=latch, post_head=post, consumed_cursor=consumed,
                         pre_snapshot=dict(descriptor=pre_p, ring=pre_r, head=pre_h),
                         post_snapshot=dict(descriptor=post_p, ring=post_r, head=post_h),
                         output_start=start, output_end=count, appended_records=appended,
                         observed_delta=delta, dropped_records=lost, copied_bad_padding=badpad,
                         observed_advance=advance, unread_slack=slack,
                         conditional_prefix_after=accepted,
                         tentative_batch=status not in (1, 2, 3, 5)))
        cursor = consumed
    finished = bool(rows) and rows[-1]['disposition'] in (STATUS[1], STATUS[2], STATUS[3])
    valid_end = ((not rows or finished) and delays in (
        {0} if not rows else {nrows-1} if nrows == ROWS else {nrows-1, nrows})) if cancelled else (
        final == (100 if finished else status) and (not finished or nrows == ROWS)
        and delays == nrows-(not finished))
    if (not valid_end
            or (total, observed, dropped, padbad, prefix) != (count, obs, drops, pads, accepted)):
        raise RuntimeError('inconsistent final totals/status')
    if output[count*8:] != strict.SENTINEL*(len(output)-count*8):
        raise RuntimeError('output sentinel guard changed')
    records = [list(struct.unpack_from('<hhHh', output, i*8)) for i in range(count)]
    if any(r[2] != 0 for r in records):
        raise RuntimeError('unexpected record tag')
    return dict(schema=schema, status_code=final, status='cancelled' if cancelled else STATUS[final], capacity=capacity,
                batches=rows, appended_records=count, observed_delta_count=obs,
                dropped_for_capacity=drops, copied_nonzero_padding_count=pads,
                conditional_prefix_records=accepted, proven_valid_records=0,
                hidden_laps_excluded=False, diagnostic_only=True, delay_calls=delays,
                calibrated=False, sample_period_seconds=None, video_fps=None,
                records_copy_order=records, record_fields=['component_0', 'component_1', 'tag', 'component_2'],
                assumptions=ASSUMPTIONS,
                limitations=['all prefixes are conditional, not atomic or lossless',
                             'rejected batch bytes retained as tentative; no resume',
                             'padding counts cover copied records only'])


def capture(io=None, *, capacity=1200, runtime=False):
    strict.validate_capacity(capacity)
    with gf.staging_lock():
        return _capture_locked(io if io is not None else gf.Backend(), capacity, runtime=runtime)


def _capture_locked(io, capacity, *, runtime=False):
    strict.validate_capacity(capacity)
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
            re.findall(r'^\s*model\s*=\s*(\S+)\s*$', version, re.M) != ['w91c1'] or
            re.findall(r'^\s*rel version\s*=\s*(\S+)\s*$', version, re.M) != ['3.02.0.V90']):
        raise ValueError('expected exact fp L 3.02 version')
    publication = io.words(gf.PUBLICATION, 3)
    plan = layout(io.caps(), publication, capacity)
    if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock')
    code, syms = code_for(plan, capacity, runtime=runtime)
    for address, data in ((plan.code, code), (plan.state, bytes(STATE_ROOM)),
                          (plan.output, strict.SENTINEL*plan.output_room)):
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
            gf.echo(io)
        finally:
            mono_after, utc_after = time.monotonic_ns(), time.time_ns()
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    if io.words(gf.PUBLICATION, 3) != publication:
        raise RuntimeError('publication changed during execution')
    actual_code = io.read(plan.code, CODE_ROOM)
    verify_code(code, actual_code, syms)
    state, output = io.read(plan.state, STATE_ROOM), io.read(plan.output, plan.output_room)
    report = decode(state, output, capacity)
    # Mutable words are masked only for static comparison, then checked against
    # the independently decoded ledger. Descriptor padding stays immutable.
    expected_words = dict(g_ghead=report['batches'][-1]['consumed_cursor'],
                          g_gcount=report['observed_delta_count'],
                          g_padbad=report['copied_nonzero_padding_count'],
                          descriptor_ptr=plan.code+syms['descriptor'], descriptor_ring=R,
                          g_latched_head=next((b['latched_head'] for b in reversed(report['batches'])
                                               if b['latched_head']), 0))
    if any(struct.unpack_from('<I', actual_code, syms[k])[0] != v for k, v in expected_words.items()):
        raise RuntimeError('mutable code state inconsistent with batch ledger')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('publication or echo changed during readback')
    report.update(firmware_version_reply=version, publication=publication, layout=vars(plan),
                   placement_mode='runtime_refs' if runtime else 'fixed',
                  code_sha256=hashlib.sha256(code).hexdigest(),
                  state_sha256=hashlib.sha256(state).hexdigest(),
                  output_sha256=hashlib.sha256(output).hexdigest(),
                   validation='live finite execution verified; conditional coherence assumptions unproven',
                  host_echo_bounds=dict(meaning='host call bounds, not sample timestamps',
                      utc_before_ns=utc_before, utc_after_ns=utc_after,
                      monotonic_before_ns=mono_before, monotonic_after_ns=mono_after))
    if runtime:
        # Canonical body hash includes zero reference slots, excludes reservation
        # padding. The uploaded-code hash above additionally binds actual refs.
        body = bytearray(code[:syms['body_end']])
        body[syms['runtime_refs']:syms['runtime_refs_end']] = bytes(20)
        report['stable_body_sha256'] = hashlib.sha256(body).hexdigest()
        report['runtime_references'] = dict(state=plan.state, state_bytes=STATE_ROOM,
                                          output=plan.output, output_bytes=plan.output_room,
                                          capacity=capacity)
    return report, state, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='fresh local output directory')
    parser.add_argument('--capacity', type=int, default=1200)
    parser.add_argument('--runtime-refs', action='store_true',
                        help='opt-in relocatable body; initialize local refs, never echo argv')
    args = parser.parse_args(argv)
    try:
        strict.validate_capacity(args.capacity)
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(exist_ok=False)
    report, state, output = capture(capacity=args.capacity, runtime=args.runtime_refs)
    for name, data in (('state.bin', state), ('output.bin', output)):
        with (args.out/name).open('xb') as handle:
            handle.write(data)
    with (args.out/'capture.json').open('x') as handle:
        json.dump(report, handle, indent=2)
        handle.write('\n')
    print(f"{args.out}: {report['status']}; conditional prefix {report['conditional_prefix_records']}; proven valid 0")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
