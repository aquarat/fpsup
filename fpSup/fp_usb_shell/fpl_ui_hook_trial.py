#!/usr/bin/env python3
"""fp L 3.02 cave-free string-hook roundtrips; no card/boot changes.

One IRQ-masked camera entry scans tasks, installs all three absolute transfers,
calls stock/private string operations, restores all six words, and returns.
--resident requires the shared shutdown journal, enables scheduling while the
hooks are installed, redraws the native menu and then removes the hooks.
The retained USER allocation is not freed.
Shared staging is interlocked; an uncertain outcome retains the pending marker.
"""
import argparse
import json
from pathlib import Path
import secrets
import struct
import time

import armasm
import fpl_getfile as gf
import fpl_ui as ui
import fpl_ui_guard as guard
import fpl_gyro_task as task
import fpl_ui_restore as restore
from fpl_vd_probe import execute
from firmware import get_camera

HERE = Path(__file__).resolve().parent
CAMERA = get_camera('fp-l-3.02')
LAYER = HERE.parent/'uishare/ui_strings.S'
CHECK = HERE/'asm/fpl_ui_string_check.S'
TEXTS = [b'Slit scan\0', b'4 / 6 / 8 / 12 fps\0']
# Actual audited save, restore, IRQ-return, and cache implementation intervals.
NATIVE = [(0xC0000CFC, 0xE8), (0xC0000F88, 0xB0),
          (0xC000E91C, 0x9C), (0xC000EABC, 0x14)]


def build_owned(owner, reader, layers, descriptor, token):
    if layers not in (1, 2) or owner & 0xFFFF:
        raise ValueError('one/two layers and aligned owned allocation required')
    body = bytearray(task.SIZE)
    struct.pack_into('<4I', body, 0, *descriptor)
    body[16:32] = bytes.fromhex(token)
    layer = armasm.assemble(LAYER)
    sym = armasm.symbols(LAYER)
    if len(layer) > 0x800:
        raise ValueError('shared string layer exceeds owned slot')
    for i in range(layers):
        off = 0x1000+i*0x800
        base = owner+off
        table = owner+0x2000+i*0x400
        text = table+0x100
        body[off:off+len(layer)] = layer
        inner = owner+0x1000 if i else 0
        fields = [0x4C505346, i, 5, 0x40000000+i, 1, text, text+len(TEXTS[i]),
                  *[inner+sym[k] if inner else 0 for k in ui.STRING_SITES], table,
                  0, 0, 0, 72, *[sym[k] for k in ui.STRING_SITES]]
        struct.pack_into('<18I', body, off, *fields)
        struct.pack_into('<I', body, table-owner, text)
        body[text-owner:text-owner+len(TEXTS[i])] = TEXTS[i]
    checker = armasm.assemble(CHECK, [f'P={owner+0x4000}'])
    if len(checker) > 1024:
        raise ValueError('finite checker exceeds reservation')
    body[0x3000:0x3000+len(checker)] = checker
    struct.pack_into('<3I', body, 0x4000, 0, reader, layers)
    outer = owner+0x1000+(layers-1)*0x800
    entries = [outer+sym[k] for k in ui.STRING_SITES]
    return bytes(body), entries


def check_results(raw, owner, reader, layers):
    expected = bytearray(1024)
    struct.pack_into('<3I', expected, 0, 2, reader, layers)
    values = []
    for i in range(layers):
        values.extend((owner+0x2100+i*0x400, 1, len(TEXTS[i])))
    values.extend((ui.POOL, 1, ui.POOL_LEN))
    struct.pack_into('<%dI' % len(values), expected, 16, *values)
    if raw != expected:
        raise RuntimeError('installed string resolver/borrow/remaining results differ')
    return values


def audit(image):
    """Conservative direct-entry scan, pinned to the exact official image.

    As with any static mixed-mode scan, indirect computed entries are not
    exhaustively proved absent. These are complete leaf-function entries.
    """
    from v3.fpl_owned_hook import direct_candidates
    sites = list(ui.STRING_SITES.values())
    hits = direct_candidates(image, 0xC0000000, min(sites), max(sites)+8)
    interior = [h for h in hits if any(s < h[2] < s+8 for s in sites)]
    # In the native Thumb function, 4651/2a00 are mov r1,sl / cmp r2,#0.
    excluded = [('ARM', 0xC05D0A60, 0xC05E23AC)]
    if interior != excluded or image[0x5D0A5C:0x5D0A66].hex() != '2a6830465146002a42d1':
        raise RuntimeError(f'unreviewed interior branch candidate: {interior!r}')
    for site in sites:
        for off in range(2, 8):
            if struct.pack('<I', site+off) in image:
                raise RuntimeError('unreviewed interior pointer literal')
    return dict(interior_candidates=interior, mode_exclusions=excluded,
                interior_pointer_literals=0, indirect_entries_proved_absent=False)


def resident_roundtrip(io, image, owner, entries, plan, call, upload, report, save):
    """Leave the reviewed layers callable by GUI tasks, then guarded removal.

    Only the shared loader owns shutdown restoration. A failure retains the
    staging marker and all memory; an acknowledged install gets a removal
    attempt even when the checker or GUI command fails. No retry of a key.
    """
    journal = restore.inspect(lambda a, n: ui.words(io, a, n), image)
    if not journal['complete']:
        raise RuntimeError('resident hooks require all six stock journal words')
    report['resident_journal'] = journal
    save()
    def transaction(command):
        params = bytearray(1024)
        struct.pack_into('<I', params, 0, command)
        struct.pack_into('<4I', params, 64, *entries, owner)
        upload(plan.param, bytes(params))
        call(plan.code, 'resident-install' if command == 1 else 'resident-remove')
        call(gf.DCACHE, 'resident-result-d')
        result = guard.decode(io.read(plan.param, 1024), io.read(plan.buffer, guard.TASK_ROOM))
        report.setdefault('resident_transactions', []).append(result)
        save()
        if result['result'] != 2:
            raise RuntimeError('resident transaction refused; inspect retained evidence')
        for entry, site in zip(entries, ui.STRING_SITES.values()):
            expected = ([0xF000F8DF, entry] if command == 1 else
                        list(struct.unpack_from('<2I', image, site-0xC0000000)))
            if io.words(site, 2) != expected:
                raise RuntimeError('resident transaction site readback differs')
        return result
    # Allocation/upload may have taken time: this is the last operation before
    # install, not an assertion inferred from a previous boot's report.
    transaction(1)
    try:
        call(owner+0x3000, 'resident-string-check')
        report['resident_commands'] = []
        # Leave the photographed menu visible. S1 is deliberately separate:
        # its down-event can succeed while the USB reply times out, and an
        # exception must never skip the corresponding release event.
        for command, delay in (('key MENUON', 1), ('key CAPTUREON', 0),
                               ('key CAPTUREOFF', 3)):
            record = dict(command=command, state='intent')
            report['resident_commands'].append(record)
            save()
            answer = io.sh(command, retries=0)
            record.update(state='returned', reply=answer)
            save()
            if answer.lstrip().startswith('ERR'):
                raise RuntimeError('resident GUI command failed; no key retry')
            time.sleep(delay)
    finally:
        transaction(2)


def run(out, main, layers, *, resident=False):
    image = CAMERA.verify_main(main)
    evidence = audit(image)
    out.mkdir(exist_ok=False)
    report = dict(kind='fpl-ui-hook-resident-v1' if resident else 'fpl-ui-hook-roundtrip-v1', layers=layers,
                  main_sha256=CAMERA.main_sha256, audit=evidence,
                  token=secrets.token_hex(16), operations=[], retained=True,
                  source_sha256={str(p.relative_to(HERE.parent)): task.sha(p.read_bytes())
                                 for p in (Path(__file__), LAYER, CHECK, guard.SOURCE)})
    def save():
        task.durable(out/'manifest.json', json.dumps(report, indent=2).encode(), replace=True)
    def artifact(name, data):
        task.durable(out/name, data)
        return task.sha(data)
    with gf.staging_lock():
        io = task.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version or task.GIT_HASH not in version:
            raise RuntimeError('exact fp L 3.02 version required')
        publication, caps = io.words(gf.PUBLICATION, 3), io.caps()
        plan = guard.layout(caps, publication)
        if any(a % 1024 for a in (plan.code, plan.param, plan.fobj, plan.buffer)):
            raise RuntimeError('unaligned staging')
        empty = next((i for i, w in enumerate(caps['windows']) if tuple(w) == (0, 0, 0)), None)
        if empty is None or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
            raise RuntimeError('no window or stock echo')
        if any(io.words(0xC358E9D8, 3)):
            raise RuntimeError('recorder must be idle')
        snapshot = ui.snapshot(io, image)
        if resident:
            journal = restore.inspect(lambda a, n: ui.words(io, a, n), image)
            if not journal['complete']:
                raise RuntimeError('resident hooks require all six stock journal words')
            report['journal_preflight'] = journal
        for at, count in NATIVE:
            live = struct.pack('<%dI' % (count//4), *ui.words(io, at, count//4))
            if live != image[at-0xC0000000:at-0xC0000000+count]:
                raise RuntimeError(f'native boundary changed at {at:#x}')
        swap_idle = task.swap_words(io, publication[0])
        report.update(version=version, publication=publication, caps=caps,
                      layout=vars(plan), ui=snapshot, swap_words=swap_idle)
        save()
        pending = gf.LOCK_PATH.with_suffix('.pending')
        task.durable(pending, json.dumps(dict(kind=report['kind'], token=report['token'],
                                             manifest=str((out/'manifest.json').resolve()))).encode())
        def identity():
            if (io.words(gf.PUBLICATION, 3) != publication or io.caps() != caps or
                    io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK] or
                    task.swap_words(io, publication[0]) != swap_idle):
                raise RuntimeError('worker identity/window/echo changed')
        def upload(at, data):
            identity()
            if at % 1024 or len(data) % 1024:
                raise RuntimeError('unowned DMA extent')
            io.write(at, data)
            if io.read(at, len(data)) != data:
                raise RuntimeError('upload differs')
        def call(at, label):
            identity()
            row = dict(address=at, label=label, state='intent')
            report['operations'].append(row)
            save()
            execute(io, at)
            identity()
            row['state'] = 'returned'
            save()
        alloc, sym = task.small_body('fpl_task_allocate.S', CAMERA.loader_defines())
        report['allocator_sha256'] = artifact('allocator.bin', alloc)
        save()
        upload(plan.fobj, alloc)
        for at, label in ((gf.DCACHE, 'alloc-d'), (gf.ICACHE, 'alloc-i'), (plan.fobj, 'allocate')):
            call(at, label)
        actual = io.read(plan.fobj, 1024)
        artifact('allocator-result.bin', actual)
        r = task.words(actual[sym['result']:sym['result']+32])
        zeroed = bytearray(actual)
        zeroed[sym['result']:sym['result']+32] = bytes(32)
        if zeroed != alloc or r[0] != 2 or r[6:] != [0, 0]:
            raise RuntimeError('allocation result/code differs')
        owner, desc = r[1], r[2:6]
        report.update(owner=owner, descriptor=desc)
        save()  # descriptor durable before any new owned write
        if not task.validate_owner(desc, owner, publication):
            raise RuntimeError('allocation failed')
        body, entries = build_owned(owner, snapshot['reader'], layers, desc, report['token'])
        code = guard.build(plan)
        params = bytearray(1024)
        struct.pack_into('<I', params, 0, 3)  # ONLY finite roundtrip exposed live
        struct.pack_into('<4I', params, 64, *entries, owner)
        report.update(owned_sha256=artifact('owned.bin', body),
                      guard_sha256=artifact('guard.bin', code), entries=entries,
                      window_slot=empty, status='grant-intent')
        save()
        original_caps = caps
        io.window(empty, owner, task.SIZE, 3)
        caps = dict(caps, windows=list(caps['windows']))
        caps['windows'][empty] = (owner, task.SIZE, 3)
        identity()
        try:
            for at, data in ((owner, body), (plan.code, code), (plan.param, bytes(params)),
                             (plan.buffer, bytes(guard.TASK_ROOM))):
                upload(at, data)
            for at, label in ((gf.DCACHE, 'publish-d'), (gf.ICACHE, 'publish-i')):
                call(at, label)
            if resident:
                resident_roundtrip(io, image, owner, entries, plan, call, upload, report, save)
            else:
                call(plan.code, 'finite-roundtrip')
            call(gf.DCACHE, 'readback-d')
            gp, rows = io.read(plan.param, 1024), io.read(plan.buffer, guard.TASK_ROOM)
            actual = io.read(owner, task.SIZE)
            artifact('guard-result.bin', gp)
            artifact('task-snapshot.bin', rows)
            artifact('owned-result.bin', actual)
            report['guard_result'] = guard.decode(gp, rows)
            for name, site in ui.STRING_SITES.items():
                if io.words(site, 2) != list(struct.unpack_from('<2I', image, site-0xC0000000)):
                    raise RuntimeError('stock string-site restoration unverified')
            if io.read(plan.code, len(code)) != code:
                raise RuntimeError('guard code changed')
            if report['guard_result']['result'] != 2:
                raise RuntimeError('guard refused; inspect task snapshot')
            report['string_results'] = check_results(actual[0x4000:0x4400], owner, snapshot['reader'], layers)
            if actual[:0x4000] != body[:0x4000] or actual[0x4400:] != body[0x4400:]:
                raise RuntimeError('owned immutable bytes changed')
            report['stock_restored'] = True
            report['status'] = 'resident-roundtrip-verified-retained' if resident else 'roundtrip-verified-retained'
            report['final_version'] = io.sh('version', retries=0)
            save()
        finally:
            # Permission revocation is not memory reclamation. Refuse foreign
            # window state and retain staging marker on any uncertain result.
            identity()
            io.window(empty, 0, 0, 0)
            caps = original_caps
            identity()
        pending.unlink()
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--layers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--resident', action='store_true',
                        help='require shared journal, redraw native menu and screenshot while hooked, then remove')
    args = parser.parse_args()
    result = run(args.out, args.main, args.layers, resident=args.resident)
    print(json.dumps({k: result[k] for k in ('status', 'owner', 'layers', 'stock_restored', 'string_results')}, indent=2))
