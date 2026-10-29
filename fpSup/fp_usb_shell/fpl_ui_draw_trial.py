#!/usr/bin/env python3
"""Temporary fp L draw-handler observation or native-menu integration trial.

Swap one BSS vtable pointer to an owned copy, observe the unchanged native draw
method for three seconds, then restore the pointer. --fp-main adds the tested
controller/page adapter and leaves it active; --detach disables it on the GUI
owner and removes the draw wrapper, followed by a separately requested reboot.
Retain all memory. Imports are offline. No card writes. A failed/uncertain
operation leaves the shared pending marker.
"""
import argparse
import json
from pathlib import Path
import secrets
import struct
import sys
import time

import fpl_getfile as gf
import fpl_gyro_task as task
import fpl_ui as ui
import fpl_ui_restore as restore
from firmware import get_camera

CAMERA = get_camera('fp-l-3.02')
OBJECT, STOCK, NATIVE = 0xC38D37CC, 0xC2E55A70, 0xC06CF498


def run(out, main, *, fp_main=None):
    image = CAMERA.verify_main(main)
    runtime = block = None
    if fp_main is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'slit_scan'))
        import build_adapter
        import menu
        runtime = build_adapter.build(runtime=True)
        block, _, _ = menu.build(fp_main, main)
        if len(runtime.code) > 0x5000 or len(block) > 0x7c00:
            raise RuntimeError('runtime/FPUI exceed owned reservations')
    out.mkdir(exist_ok=False)
    with gf.staging_lock():
        io = task.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version or task.GIT_HASH not in version:
            raise RuntimeError('exact fp L 3.02 version required')
        publication, caps = io.words(gf.PUBLICATION, 3), io.caps()
        if any(io.words(0xC358E9D8, 3)):
            raise RuntimeError('recorder must be idle')
        obj = io.words(OBJECT, 4)
        if obj[0] != STOCK or obj[3] != 1 or not ui.heap_pointer(obj[2]):
            raise RuntimeError('native drawing object identity differs')
        for a, n in ((STOCK, 40), (NATIVE, 0xA8), (0xC000E91C, 0x9C)):
            actual = struct.pack('<%dI' % (n//4), *ui.words(io, a, n//4))
            if actual != image[a-0xC0000000:a-0xC0000000+n]:
                raise RuntimeError(f'native bytes differ at {a:#x}')
        report = dict(kind='fpl-ui-draw-observer-v1', token=secrets.token_hex(16),
                      main_sha256=CAMERA.main_sha256, publication=publication, caps=caps,
                      swap_words=task.swap_words(io, publication[0]), object_before=obj,
                      operations=[], artifacts={}, retained=True)
        if runtime is not None:
            report['kind'] = 'fpl-ui-menu-trial-v1'
            report['ui_before'] = ui.snapshot(io, image)
            report['journal'] = restore.inspect(lambda a, n: ui.words(io, a, n), image)
            if not report['journal']['complete']:
                raise RuntimeError('menu requires all six shared journal words')
            # The separate draw observer proved this slot on the current
            # firmware. Check the live native task descriptor again.
            tcb = 0xC3000838+39*132
            if io.words(tcb+8) != [39] or io.words(tcb+0x18) != [0x4000]:
                raise RuntimeError('observed drawing task identity differs')
            report['expected_tcb'] = tcb
        t = task.Trial(io, out, report)
        t.guard(); t.save()
        pending = gf.LOCK_PATH.with_suffix('.pending')
        task.durable(pending, json.dumps(dict(kind=report['kind'], token=report['token'],
                     manifest=str((out/'manifest.json').resolve()))).encode())
        alloc, labels = task.small_body('fpl_task_allocate.S', CAMERA.loader_defines())
        t.artifact('allocator.bin', alloc); t.upload(t.stage, alloc)
        t.publish('allocation'); t.execute(t.stage, 'allocate')
        raw = t.read(t.stage, 1024); t.artifact('allocator-result.bin', raw)
        r = task.words(raw[labels['result']:labels['result']+32])
        immutable = bytearray(raw); immutable[labels['result']:labels['result']+32] = bytes(32)
        if immutable != alloc or r[0] != 2 or r[6:] != [0, 0]:
            raise RuntimeError('allocation code/result differs')
        owner, desc = r[1], r[2:6]
        report.update(owner=owner, descriptor=desc); t.save()
        try:
            if not task.validate_owner(desc, owner, publication):
                raise ValueError('native allocator returned zero')
        except ValueError as error:
            # The finite allocator returned and its immutable bytes matched.
            # No owner upload/window/hook has happened. Keep the descriptor,
            # but this is a proved refusal rather than an uncertain dispatch.
            report.update(status='allocation-refused-retained', refusal=str(error))
            t.guard(); t.save()
            pending.unlink(); task.sync_dir(pending.parent)
            raise RuntimeError('allocation refused before owned upload; see retained manifest') from error
        defines = [f'OWNED={owner}'] + (['CALLBACK=1'] if runtime is not None else [])
        code, symbols = task.small_body('fpl_ui_draw.S', defines)
        body = bytearray(task.SIZE)
        struct.pack_into('<4I', body, 0, *desc)
        body[16:32] = bytes.fromhex(report['token'])
        struct.pack_into('<3I', body, 0x400, 1, 0, obj[2])
        body[0x1000:0x1400] = code
        body[0x2000:0x2028] = image[STOCK-0xC0000000:STOCK-0xC0000000+40]
        struct.pack_into('<I', body, 0x200c, owner+0x1000+symbols['observe'])
        if runtime is not None:
            s = report['ui_before']; page = s['pages']['MainB2']
            struct.pack_into('<3I', body, 0x40c, owner+0x3000+runtime.functions['slit_tick'],
                             owner+0x8000, tcb)
            body[0x3000:0x3000+len(runtime.code)] = runtime.code
            body[0x8400:0x8400+len(block)] = block
            struct.pack_into('<14I', body, 0x8000, 0x534C4954, 0, 0, 0, 1, s['app'],
                             owner+0x3000+runtime.functions['slit_key'], owner+0x8400, len(block),
                             tcb, page['entry'], page['offset'], 0, 0)
            report['runtime_functions'] = runtime.functions
        t.artifact('owned.bin', bytes(body))
        slot = next(i for i, w in enumerate(caps['windows']) if tuple(w) == (0, 0, 0))
        report.update(window_slot=slot, symbols=symbols); t.save()
        t.window(slot, (owner, task.SIZE, 3), 'grant-owned-window')
        attempted = keep = False
        try:
            t.upload(owner, bytes(body)); t.publish('owned')
            attempted = True
            t.execute(owner+0x1000, 'install-draw-observer')
            if io.words(OBJECT) != [owner+0x2000] or io.words(owner+0x404) != [2]:
                raise RuntimeError('draw observer installation refused')
            time.sleep(3)                 # bounded observation, no scheduling claims
            if runtime is not None:
                t.execute(gf.DCACHE, 'runtime-publication')
                state = io.words(owner+0x8000, 14)
                report['runtime_state'] = state; t.save()
                if state[1] != 2 or state[2] or not state[12]:
                    raise RuntimeError('menu initializer failed; retain evidence and reboot after reconciliation')
                keep = True
        finally:
            if attempted and not keep:
                current = io.words(OBJECT)
                if current == [owner+0x2000]:
                    t.guard()
                    row = t.intent('request-removal')
                    io.set_word(owner+0x400, 2)
                    if io.words(owner+0x400) != [2]:
                        raise RuntimeError('removal request readback differs')
                    t.finish(row)
                    t.execute(owner+0x1000, 'remove-draw-observer')
                    if io.words(OBJECT) != [STOCK] or io.words(owner+0x404) != [2]:
                        raise RuntimeError('draw observer removal unverified')
                elif current != [STOCK]:
                    raise RuntimeError('foreign draw-handler owner; inspect pending evidence')
            t.window(slot, (0, 0, 0), 'revoke-owned-window')
        # A call already in flight may finish in retained code after removal.
        time.sleep(1)
        t.window(slot, (owner, task.SIZE, 1), 'grant-result-window')
        try:
            t.execute(gf.DCACHE, 'readback-publication')
            actual = t.read(owner, task.SIZE)
            t.artifact('owned-result.bin', actual)
        finally:
            t.window(slot, (0, 0, 0), 'revoke-result-window')
        immutable_ranges = ((0, 0x400), (0x500, 0x8000), (0x8400, task.SIZE)) if runtime is not None else ((0, 0x400), (0x500, task.SIZE))
        if any(actual[a:b] != body[a:b] for a, b in immutable_ranges):
            raise RuntimeError('immutable owned bytes changed')
        values = task.words(actual[0x400:0x500])
        report['observation'] = dict(zip(
            ('entered', 'returned', 'active', 'max_depth', 'first_tcb', 'last_tcb',
             'task_changes', 'wrong_self', 'min_sp', 'max_sp', 'native_result',
             'cpsr', 'stack_bottom', 'stack_top', 'task_id'), values[8:23]))
        report['observation']['task_ids'] = [i for i in range(1, 501) if values[32+i//32] & (1 << (i%32))]
        report['object_after'] = io.words(OBJECT, 4)
        if runtime is None:
            report['ui_after'] = ui.snapshot(io, image)
        report['recorder_after'] = io.words(0xC358E9D8, 3)
        if (report['object_after'][0] != (owner+0x2000 if keep else STOCK) or report['object_after'][2:] != obj[2:] or
                any(report['recorder_after']) or (not keep and (values[10] or values[8] != values[9]))):
            t.save()
            raise RuntimeError('final draw identity/in-flight state needs reconciliation')
        report['status'] = 'menu-active-retained' if keep else 'observed-and-restored-retained'
        t.save()
        pending.unlink(); task.sync_dir(pending.parent)
        return report


def detach(manifest):
    """Disable the controller on its GUI owner, then remove the draw wrapper.

    Page/string allocations and private registry variables stay live until a
    subsequent reboot. Shared loader restoration owns the six string sites.
    """
    report = json.loads(manifest.read_text())
    if report['kind'] != 'fpl-ui-menu-trial-v1' or report['status'] != 'menu-active-retained':
        raise ValueError('not an active menu-trial manifest')
    report['caps']['windows'] = [tuple(w) for w in report['caps']['windows']]
    out, owner = manifest.parent, report['owner']
    body = (out/'owned.bin').read_bytes()
    if task.sha(body) != report['artifacts']['owned.bin']['sha256']:
        raise RuntimeError('owned evidence differs')
    with gf.staging_lock():
        io = task.Backend(); t = task.Trial(io, out, report); t.guard()
        current_object = io.words(OBJECT, 4)
        if current_object[0] != owner+0x2000 or current_object[3] != 1:
            raise RuntimeError('draw object ownership changed')
        listener = ui.heap_pointer(current_object[2])
        slot = report['window_slot']
        pending = gf.LOCK_PATH.with_suffix('.pending')
        task.durable(pending, json.dumps(dict(kind=report['kind'], token=report['token'],
                     manifest=str(manifest.resolve()))).encode())
        t.window(slot, (owner, task.SIZE, 1), 'grant-detach-readback')
        try:
            actual = t.read(owner, task.SIZE)
            if any(actual[a:b] != body[a:b] for a, b in ((0, 0x400), (0x500, 0x8000), (0x8400, task.SIZE))):
                raise RuntimeError('owned code/data changed')
            row = t.intent('disable-controller')
            io.set_word(owner+0x8010, 2)
            if io.words(owner+0x8010) != [2]:
                raise RuntimeError('disable command readback differs')
            t.finish(row)
            time.sleep(1)
            t.execute(gf.DCACHE, 'disabled-publication')
            state = io.words(owner+0x8000, 14)
            report['disabled_runtime_state'] = state; t.save()
            if state[1] != 3 or state[3]:
                raise RuntimeError('GUI disable not acknowledged')
            row = t.intent('request-detach')
            # The native listener changes with live-view/menu state. Preserve
            # it; refresh only our compare operand before the atomic detach.
            row['current_native_listener'] = listener; t.save()
            io.set_word(owner+0x408, listener)
            if io.words(owner+0x408) != [listener]:
                raise RuntimeError('listener compare readback differs')
            io.set_word(owner+0x400, 2)
            if io.words(owner+0x400) != [2]:
                raise RuntimeError('detach command readback differs')
            t.finish(row)
            t.execute(owner+0x1000, 'detach-menu-wrapper')
            if io.words(OBJECT) != [STOCK] or io.words(owner+0x404) != [2]:
                raise RuntimeError('draw wrapper detach unverified')
            report['status'] = 'menu-disabled-awaiting-reboot'; t.save()
        finally:
            t.window(slot, (0, 0, 0), 'revoke-detach-readback')
        pending.unlink(); task.sync_dir(pending.parent)
        return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path)
    p.add_argument('--out', type=Path)
    p.add_argument('--fp-main', type=Path, help='install experimental native menu and leave it active')
    p.add_argument('--detach', type=Path, help='active menu manifest; disable/detach, then reboot separately')
    a = p.parse_args()
    if a.detach:
        if a.main or a.out or a.fp_main: p.error('--detach is a separate operation')
        r = detach(a.detach)
    else:
        if not a.main or not a.out: p.error('--main and --out are required')
        r = run(a.out, a.main, fp_main=a.fp_main)
    print(json.dumps({k: r[k] for k in ('status', 'owner', 'observation')}, indent=2))
