#!/usr/bin/env python3
"""Additive fp L Slit scan row, built from the same-page Audio donor.

Left decrements, Right/OK increments Off/4/6/8/12. Native code owns the private
RAM variables and posts the summary text. No CSV hook or stock setting setter.
Build is offline; a page candidate alone is not a deployable camera feature.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
FPSUP = HERE.parent
sys.path[:0] = [str(FPSUP/'fp_usb_shell'), str(FPSUP/'lossless/menu'), str(FPSUP/'uishare')]
from firmware import get_camera
import build_menu_candidate as donor
from ui import fpui, rows

VARIABLES = ('MV_fpSlitScan', 'MV_fpSlitKey', 'MV_fpSlitText',
             'EXCL_fpSlitScan', 'SUB_MV_fpSlitScan')
LABELS = ('Off', '4 fps', '6 fps', '8 fps', '12 fps')
SYN_LEFT, SYN_ACTION, SYN_SUMMARY = 0x3000000, 0x3000100, 0x3000200
SYN_REQUEST = 0x3000300


def word(data, at, value):
    struct.pack_into('>I', data, at, value)


def build(fp_main, fpl_main):
    source = Path(fp_main).read_bytes()
    target = get_camera('fp-l-3.02').verify_main(fpl_main)
    audit = donor.load_audit(donor.DEFAULT_AUDIT)
    evidence = audit.audit_bytes(source)
    stock_page = source[audit.PAGE_START:audit.PAGE_END]
    pool_stock = source[audit.POOL:audit.POOL_END]
    target_start = 0x18D01A0+0x76FF04
    if (target[target_start:target_start+len(stock_page)] != stock_page or
            target[0x18D01B4:0x18D01B4+len(pool_stock)] != pool_stock):
        raise ValueError('fp L page/pool must match the reviewed same-page donor')
    stock = audit.records(source, audit.PAGE_START, audit.PAGE_END)
    original = {r.offset: r for r in stock}
    profile = deepcopy(donor.PROFILES['audio-toggle'])
    rename = {'MV_fpLossless': VARIABLES[0], 'SUB_MV_fpLossless': VARIABLES[4],
              'EXCL_fpLossless': VARIABLES[3], 'Lossless RAW': 'Slit scan'}
    profile['private_fields'] = {at: (off, old, rename.get(new, new))
                                 for at, (off, old, new) in profile['private_fields'].items()}
    profile['text_animation_values'][0x2054099] = {'0326_C': 'Slit scan', '0326_CI': 'Slit scan'}
    profile['private_fields'][0x20541D1] = (32, '0080', LABELS[0])
    profile['literal_records'].append(0x20541D1)
    profile['text_animation_values'][0x20542C2] = {'0080': LABELS[0], '0081': LABELS[0]}

    def copied(at, identity, owner, local, action=False):
        data = bytearray(original[at].data)
        word(data, donor.OWNER_OFFSETS[original[at].tag], owner)
        word(data, 28 if original[at].tag == 0x10006 else 24, local)
        if action:
            word(data, 28, 1)
        return audit.Record(identity, bytes(data))

    # controlAppVariable's value is a literal, NOT a formula. Each key resets
    # the private request to zero, then writes +/-1. Both actions run in the
    # native event; unchanged-value suppression cannot swallow repeated keys.
    replacements = {}
    requests = {}
    for at, event in ((0x204DE59, 6), (0x204DF49, 7)):
        replacements[at] = copied(0x204ED97, at, 28971, event, action=True)
        data = bytearray(replacements[at].data)
        word(data, 41, pool_stock.index(b'0\0'))
        replacements[at] = audit.Record(at, bytes(data))
        profile['private_fields'][at] = (36, 'SUB_MV_AudioRecord', VARIABLES[1])
        req = copied(0x204ED97, SYN_REQUEST+event, 28971, event, action=True)
        data = bytearray(req.data)
        word(data, 28, 2)
        requests[at] = audit.Record(req.offset, bytes(data))
        profile['private_fields'][req.offset] = (36, 'SUB_MV_AudioRecord', VARIABLES[1])
    removed = {0x204DE8B, 0x204DEC2, 0x204DEF9, 0x204DF7B, 0x204DFB2, 0x204DFE9}
    # Stop the binary AudioRecordFix animation from overwriting the summary.
    replacements[0x204E1B4] = copied(0x204E649, 0x204E1B4, 28971, 15, action=True)
    profile['private_fields'].pop(0x204E1B4)
    left = copied(0x204F2A8, SYN_LEFT, 28971, 21)
    data = bytearray(left.data)
    word(data, 16, 2)
    left = audit.Record(SYN_LEFT, bytes(data))
    action = copied(0x204ED97, SYN_ACTION, 28971, 21, action=True)
    profile['private_fields'][SYN_ACTION] = (36, 'SUB_MV_AudioRecord', VARIABLES[1])
    data = bytearray(action.data)
    word(data, 41, pool_stock.index(b'0\0'))
    action = audit.Record(SYN_ACTION, bytes(data))
    data = bytearray(action.data)
    word(data, 28, 2)
    word(data, 41, pool_stock.index(b'-1\0'))
    left_request = audit.Record(SYN_REQUEST+21, bytes(data))
    profile['private_fields'][left_request.offset] = (36, 'SUB_MV_AudioRecord', VARIABLES[1])
    summary = copied(0x204E14D, SYN_SUMMARY, 28987, 5)
    data = bytearray(summary.data)
    word(data, 45, 1)                 # drawText component, not controlValue
    word(data, 49, pool_stock.index(b'text\0'))
    summary = audit.Record(SYN_SUMMARY, bytes(data))
    profile['private_fields'][SYN_SUMMARY] = (40, 'MV_AudioRecord', VARIABLES[2])
    profile['word_writes'][0x204E125] = [(32, 0x41300000, 0x40800000, 'private_index_max_four')]
    prepared = []
    for rec in stock:
        if not audit.DONOR_START <= rec.offset < audit.DONOR_END or rec.offset in removed:
            continue
        rec = replacements.get(rec.offset, rec)
        if rec.tag == 0x10006 and rec.word(24) == 28971 and rec.word(28) in (6, 7):
            data = bytearray(rec.data)
            word(data, 16, 2)       # reset + request, not donor's four actions
            rec = audit.Record(rec.offset, bytes(data))
        if rec.offset in (0x204DB82, 0x205417D):
            data = bytearray(rec.data)
            word(data, 8, rec.word(8)+1)  # one extra event component each
            rec = audit.Record(rec.offset, bytes(data))
        prepared.append(rec)
        if rec.offset in requests:
            prepared.append(requests[rec.offset])
        if rec.offset == 0x204E35F:
            prepared.extend((left, action, left_request))
        if rec.offset == 0x20542C2:
            prepared.append(summary)
    pool = donor.PrivatePool(pool_stock)
    objects = audit.parse_objects(stock, pool.resolve)
    donor_objects = audit.parse_objects(prepared, pool.resolve)
    mapping = donor.allocate_ids(list(objects), list(donor_objects))
    remap = donor.Remapper(pool, mapping, objects, donor.load_property_schemas(source), profile)
    clone = [(r, remap.transform(r)) for r in prepared]
    if remap.unresolved:
        raise ValueError(f'unclassified donor fields: {remap.unresolved}')
    groups = [r for r in stock if r.tag == 0x1000B]
    group_indexes = [i for i, r in enumerate(groups) if audit.DONOR_START <= r.offset < audit.DONOR_END]
    clips = [audit.parse_clip(r, pool.resolve) for r in prepared if r.tag == 0x1000A]
    header = audit.parse_header(stock[0], pool.resolve)
    delta = dict(objects=len(donor_objects), component_counts=audit.component_counts(prepared, pool.resolve),
                 group_budgets=[header['groups'][i] for i in group_indexes],
                 clip_property_counts=[len(c['properties']) for c in clips],
                 property_key_counts=[len(p['keys']) for c in clips for p in c['properties']])
    parts, locs, cursor = [], [], 0
    def append(rec, data, provenance):
        nonlocal cursor
        locs.append(dict(source_record=audit.address(rec.offset), candidate_offset=cursor,
                         length=len(data), provenance=provenance))
        parts.append(data)
        cursor += len(data)
    for rec in stock:
        if rec.offset == audit.DONOR_END:
            for r, data in clone:
                append(r, data, 'cloned_slit_scan_row')
        data = rec.data
        if rec.offset == audit.PAGE_START:
            data = donor.extend_header(rec, evidence['allocation_header'], delta)
        elif rec.offset == audit.B2_OBJECT:
            data = bytearray(data)
            word(data, 16, rec.word(16)+1)
            data = bytes(data)
        elif rec.offset == audit.MODE_CHANGE:
            data = donor.extend_mode_change(rec, mapping[122])
        append(rec, data, 'stock')
    page = b''.join(parts)
    manifest = dict(record_locations=locs, typed_object_fields=remap.object_fields,
                    typed_string_fields=remap.string_fields, typed_changes=remap.changes,
                    new_row=dict(object_id_map=mapping, root_id=mapping[122]))
    def hint(text):
        at = pool_stock.find(text.encode()+b'\0')
        return at if at >= 0 else fpui.NOT_STOCK
    block, info = rows.row_block('MainB2', 0x76FF04, stock_page, page, manifest, pool_stock, hint,
                                 insert_at=audit.DONOR_END-audit.PAGE_START,
                                 parent_at=audit.B2_OBJECT-audit.PAGE_START,
                                 mode_change_at=audit.MODE_CHANGE-audit.PAGE_START)
    # Object names need not be unique, but name this newly-added root honestly.
    block.strings = [('fpSlitScan_Row' if s == 'fpLossless_Row_GATED' else s, at)
                     for s, at in block.strings]
    for f in manifest['typed_string_fields']:
        if f['text'] == 'fpLossless_Row_GATED':
            f['text'] = 'fpSlitScan_Row'
    # prove_same uses semantic names; the reference page's private offset is
    # relocated using these same typed fields, never by scanning numeric words.
    info['strings'] = [s for s, _ in block.strings]
    blob = block.encode()
    composed, strings = rows.prove_same(blob, 'MainB2', stock_page, page, manifest, pool_stock, hint)
    validate_page(bytes(composed.data), strings.text, audit)
    info.update(kind='fpl-slit-scan-row-v1', labels=LABELS, variables=VARIABLES,
                selection_keys=dict(left=-1, right=1, ok=1),
                stock_page_sha256=hashlib.sha256(stock_page).hexdigest(),
                fpl_main_sha256=CAMERA_SHA, page_bytes=len(page),
                no_stock_setting_setters=True, live_rendering_verified=False)
    return blob, info, dict(stock_page=stock_page, page=bytes(composed.data),
                           strings=strings, manifest=manifest)


def validate_page(page, resolve, audit=None):
    """Check the emitted native graph, independently of the clone manifest.

    Native headers include spare budgets; require capacity, not equality.
    Actions share their event ID, while components/clips have distinct IDs.
    """
    audit = audit or donor.load_audit(donor.DEFAULT_AUDIT)
    records = audit.records(page, 0, len(page))
    objects = audit.parse_objects(records, resolve)
    children = Counter(o['parent_id'] for o in objects.values())
    if any(children[o['id']] != o['child_count'] for o in objects.values()):
        raise ValueError('row graph child counts differ')
    header = audit.parse_header(records[0], resolve)
    counts = audit.component_counts(records, resolve)
    if header['objects'] < len(objects) or any(
            header['component_counts'].get(k, 0) < n for k, n in counts.items()):
        raise ValueError('page allocation budget exceeded')
    components, events, actions, clips = {}, set(), [], set()
    per_object = Counter()
    for rec in records:
        if rec.tag not in donor.OWNER_OFFSETS:
            continue
        owner = rec.word(donor.OWNER_OFFSETS[rec.tag])
        local = rec.word(28 if rec.tag == 0x10006 else 24)
        if owner not in objects:
            raise ValueError('component owner missing')
        key = owner, local
        if rec.tag == 0x10009:
            actions.append(key)
            continue
        if key in components:
            raise ValueError('duplicate component/event/clip ID')
        components[key] = rec
        per_object[owner] += 1
        if rec.tag == 0x10006:
            events.add(key)
        if rec.tag == 0x1000A:
            clips.add(key)
    if any(key not in events for key in actions):
        raise ValueError('action has no event')
    action_counts = Counter(actions)
    if any(components[key].word(16) != action_counts[key] for key in events):
        raise ValueError('event action count differs')
    for rec in records:
        if rec.tag == 0x10003 and per_object[rec.word(20)] > rec.word(8):
            raise ValueError('object component budget exceeded')
        if rec.tag == 0x1000A:
            clip = audit.parse_clip(rec, resolve)
            if any((clip['owner_id'], p['component_ref']) not in components
                   for p in clip['properties']):
                raise ValueError('animation targets absent component')
        # The cloned donor and ModeChange use the no-transition group layout.
        # Other stock groups are preserved by prove_same, not decoded here.
        if rec.tag == 0x1000B and not rec.word(12):
            at = 28 + rec.word(8)*21
            if any((rec.word(at+8*i), rec.word(at+8*i+4)) not in clips
                   for i in range(rec.word(16))):
                raise ValueError('animation group targets absent clip')
    return records


CAMERA_SHA = get_camera('fp-l-3.02').main_sha256

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fp-main', type=Path, required=True)
    ap.add_argument('--fpl-main', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    blob, info, _ = build(args.fp_main, args.fpl_main)
    args.out.mkdir(exist_ok=False)
    (args.out/'slit-scan.fpui').write_bytes(blob)
    (args.out/'manifest.json').write_text(json.dumps(info, indent=2)+'\n')
    print(json.dumps(info, indent=2))
