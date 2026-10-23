#!/usr/bin/env python3
"""Offline MOV epoch diagnostics. No live observer or hardware certification."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def classify(events):
    """Untrusted/imported events: labels and alleged proof fields prove no association.

    There is deliberately no caller-settable 'verified epoch' switch. Only
    replay_audit establishes association, and only within its synthetic model.
    """
    return _classify(events, synthetic_association=False)


def _classify(events, *, synthetic_association):
    raw = deepcopy(events)
    state, identity, previous = 'await_start', None, None
    reasons = []

    def refuse(reason):
        if reason not in reasons:
            reasons.append(reason)

    if not synthetic_association:
        refuse('causal_association_unproven')
    for event in raw:
        if not isinstance(event, dict):
            refuse('malformed_event')
            continue
        seq = event.get('seq')
        if type(seq) is not int or seq < 0:
            refuse('invalid_sequence')
        else:
            if previous is not None and seq != previous + 1:
                refuse('duplicate_out_of_order_or_missing_evidence')
            previous = seq
        kind = event.get('kind')
        if kind in ('gap', 'association_unknown'):
            refuse('evidence_gap_or_unknown_association')
            continue
        if kind == 'start':
            if state != 'await_start':
                refuse('overlapping_or_reused_epoch')
                continue
            # These identifiers constrain consistency, not authenticity. The
            # software epoch field, if supplied, is intentionally never read.
            owner, writer = event.get('owner'), event.get('writer')
            if not isinstance(owner, str) or not owner or not isinstance(writer, str) or not writer:
                refuse('missing_owner_or_writer')
            identity = (owner, writer)
            state = 'await_message2'
            continue
        if (event.get('owner'), event.get('writer')) != identity or identity is None:
            refuse('owner_or_writer_unassociated')
        if state == 'terminal':
            refuse('late_or_duplicate_evidence')
            continue
        if kind == 'event30':
            # Includes result 1: never a substitute for a raw engine callback.
            continue
        if kind == 'message2':
            if state != 'await_message2':
                refuse('duplicate_or_out_of_order_message2')
            else:
                state = 'await_finalizer'
        elif kind == 'finalizer_return':
            if state != 'await_finalizer':
                refuse('finalizer_without_unique_message2')
            r0, flags = event.get('r0'), event.get('flags')
            if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in (r0, flags)):
                refuse('missing_or_invalid_finalizer_registers')
            elif r0 != 0 or flags & 0x1F:
                refuse('finalizer_error')
            state = 'await_raw1'
        elif kind == 'raw_status':
            status = event.get('status')
            if type(status) is not int or status not in (1, 2):
                refuse('unexpected_raw_status')
            elif status == 2:
                refuse('raw2_is_not_clean_completion')
            if state != 'await_raw1':
                refuse('terminal_without_finalizer_evidence')
            state = 'terminal'
        else:
            refuse('unknown_event_kind')
    if state != 'terminal':
        refuse('incomplete_epoch')
    return dict(
        classification='inconclusive' if reasons else 'local_finalization_observed',
        evidence_scope='bounded_synthetic_execution' if synthetic_association else 'unverified_import',
        state=state, reasons=reasons, raw_events=raw,
        hardware_certified=False,
        claims=dict(durability=False, quiescence=False, resource_retirement=False))


def replay_audit(data, **case):
    """Run the existing bounded audit; establish association ONLY in that model.

    Mock finalizer returns are not real observations at C070E47C. No imported
    JSON assertion, epoch tag, or status event can select this evidence scope.
    """
    from fpl_gyro_audit import fingerprint
    from fpl_mov_stop_audit import run, validate
    fingerprint(data, 'fpl')
    allowed = {'started', 'state', 'pools', 'send_error', 'writer_send_errors',
               'remainder_error', 'finalize_error'}
    if case.keys() - allowed:
        raise ValueError('only pipeline fault-injection parameters are supported')
    row = run(data, **case)
    validate(row)
    events = []

    def emit(kind, **fields):
        events.append(dict(seq=len(events), kind=kind, owner='synthetic-owner',
                           writer='synthetic-writer', **fields))

    emit('start', origin='injected single-epoch model, not observed hardware start')
    for index, item in enumerate(row['log']):
        if item[:3] == ['receive', 102, 2]:
            emit('message2', audit_log_index=index)
        elif item[0] == 'finalizer_mock':
            emit('finalizer_return', r0=item[1], flags=8 if item[1] else 0,
                 audit_log_index=index, origin='mock return and flags')
        elif item[0] == 'engine_notification' and item[1] in (1, 2):
            emit('raw_status', status=item[1], audit_log_index=index)
    result = _classify(events, synthetic_association=True)
    result['audit_trace'] = row
    result['firmware_sha256'] = hashlib.sha256(data).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--events', type=Path, help='JSON event array; association remains unproven')
    source.add_argument('--audit-replay', action='store_true', help='execute synthetic normal-stop audit')
    parser.add_argument('--fpl', type=Path, default=Path.home()/
                        '.local/share/fpsup/firmware/FPL_V302/MAIN.bin')
    args = parser.parse_args()
    if args.audit_replay:
        result = replay_audit(args.fpl.read_bytes())
    else:
        events = json.loads(args.events.read_text())
        if not isinstance(events, list):
            parser.error('--events must contain a JSON array')
        result = classify(events)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
