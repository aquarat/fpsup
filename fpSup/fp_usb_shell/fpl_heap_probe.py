#!/usr/bin/env python3
"""Build/inspect the finite fp L owned-RAM execution experiment, offline only.

Build emits a relocatable test body and its manifest, NOT an installable card.
Placement, initial cache publication and restoring borrowed firmware bytes
belong to the bootstrap audit. This tool never accesses USB or block devices.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from armasm import assemble, symbols
from firmware import get_camera

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'asm/heap_probe.S'
CAMERA = get_camera('fp-l-3.02')
BASE = 0xC0000000
# Trial placement, from docs/FPL_BOOTSTRAP_AUDIT.md: the stock `dir` handler's
# verified extent. The probe occupies only its first PROBE_LEN bytes; the dir
# table slot keeps pointing at DIR_ENTRY, so no slot write is needed to run it.
DIR_ENTRY = 0xC03E2B98
DIR_SLOT = 0xC0BD24FC          # entry 14 handler slot; never written by the script
PROBE_LEN = 0x188              # 392: heap_probe body incl. its result block
RESULT_OFFSET = 0x148
RESULT_ADDR = DIR_ENTRY + RESULT_OFFSET
# The only firmware word the script borrows: the `echo` table slot (entry 17),
# pointed at the stock cache routines during publication windows.
ECHO_SLOT = 0xC0BD2544
ECHO_STOCK = 0xC03D9BB8
DCACHE = 0xC000E91C
ICACHE = 0xC000EABC
TABLE = 0xC0BD2398             # 77 entries + terminator, for final slot evidence
TABLE_LEN = 77 * 24 + 24
PROBE_DIR = 'FPLPROBE'         # exists on the card from the 2026-10-16 bring-up
FIELDS = (
    'magic', 'version', 'status', 'allocation', 'allocation_bytes', 'leaf_bytes',
    'observed_pc', 'expected_pc', 'leaf_sp', 'leaf_marker', 'leaf_return',
    'free_returned', 'reserved_0', 'reserved_1', 'reserved_2', 'reserved_3',
)


def artifact():
    defines = CAMERA.loader_defines()
    body = assemble(SOURCE, defines)
    offsets = symbols(SOURCE, defines)
    selected = {name: offsets[name] for name in
                ('heap_probe', 'heap_leaf', 'heap_leaf_end', 'heap_result', 'heap_probe_end')}
    if (selected['heap_probe'] != 0 or selected['heap_probe_end'] != len(body) or
            selected['heap_result'] + 64 != len(body) or
            not 0 < selected['heap_leaf_end'] - selected['heap_leaf'] <= 4096 or
            any(offset % 4 for offset in selected.values())):
        raise ValueError('unexpected probe layout')
    if len(body) != PROBE_LEN or selected['heap_result'] != RESULT_OFFSET:
        raise ValueError(f'probe body does not match the trial placement '
                         f'(len {len(body):#x}, result {selected["heap_result"]:#x})')
    return body, selected


def card_script(image):
    """The finite owned-RAM execution trial, as AutoRun command lines.

    Phases: capture pre-state, write the probe into the borrowed `dir` body,
    capture what was actually written, publish via the stock cache routines,
    dispatch `dir` (the untouched slot already points at the probe), save the
    result, restore the stock body, republish, restore the echo slot, and
    capture restoration evidence. Restoration uses stock bytes baked in here,
    so the script is self-healing even over a stale earlier patch.
    """
    body, _ = artifact()
    stock = image[DIR_ENTRY - BASE:DIR_ENTRY - BASE + PROBE_LEN]
    lines = ['# --- fp L owned-RAM execution trial: stock bytes captured first']
    lines.append(f'mem save \\{PROBE_DIR}\\PRE.BIN 0x{DIR_ENTRY:08X},,0x{PROBE_LEN:X}')
    lines.append('# --- place the probe body (borrowed dir handler region)')
    lines += [f'mem set 0x{DIR_ENTRY + off:08X} 0x{word:08X}'
              for off, word in zip(range(0, PROBE_LEN, 4),
                                   struct.unpack(f'<{PROBE_LEN // 4}I', body))]
    lines.append(f'mem save \\{PROBE_DIR}\\WROTE.BIN 0x{DIR_ENTRY:08X},,0x{PROBE_LEN:X}')
    lines.append('# --- publish: echo slot -> stock D-cache, then I-cache, dispatched')
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{DCACHE:08X}', 'echo',
              f'mem set 0x{ECHO_SLOT:08X} 0x{ICACHE:08X}', 'echo']
    lines.append('# --- run: the dir slot already points at the probe entry')
    lines.append('dir')
    lines.append(f'mem save \\{PROBE_DIR}\\RESULT.BIN 0x{RESULT_ADDR:08X},,0x40')
    lines.append('# --- restore the stock dir body from baked-in image bytes')
    lines += [f'mem set 0x{DIR_ENTRY + off:08X} 0x{word:08X}'
              for off, word in zip(range(0, PROBE_LEN, 4),
                                   struct.unpack(f'<{PROBE_LEN // 4}I', stock))]
    lines.append('# --- republish the restored code before the slot goes back')
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{DCACHE:08X}', 'echo',
              f'mem set 0x{ECHO_SLOT:08X} 0x{ICACHE:08X}', 'echo']
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_STOCK:08X}'] * 3
    lines.append('# --- restoration evidence')
    lines.append(f'mem save \\{PROBE_DIR}\\RESTORED.BIN 0x{DIR_ENTRY:08X},,0x{PROBE_LEN:X}')
    lines.append(f'mem save \\{PROBE_DIR}\\SLOTS.BIN 0x{TABLE:08X},,0x{TABLE_LEN:X}')
    return lines, body, stock


def build_card(main, out):
    image = CAMERA.verify_main(main)
    lines, body, stock = card_script(image)
    script = (''.join(line + '\n' for line in lines)).encode('ascii')
    expected = {
        'PRE.BIN': ('stock dir body', hashlib.sha256(stock).hexdigest()),
        'WROTE.BIN': ('probe body as written', hashlib.sha256(body).hexdigest()),
        'RESTORED.BIN': ('stock dir body', hashlib.sha256(stock).hexdigest()),
        'SLOTS.BIN': ('stock command table',
                      hashlib.sha256(image[TABLE - BASE:TABLE - BASE + TABLE_LEN]).hexdigest()),
        'RESULT.BIN': ('must pass inspect_result', None),
    }
    report = dict(
        camera=CAMERA.name, kind='owned-ram-execution-trial-autorun',
        installable_card=True, camera_tested=False,
        main_sha256=CAMERA.main_sha256,
        autorun_sha256=hashlib.sha256(script).hexdigest(),
        commands=len(lines), mem_set_words=PROBE_LEN // 4 * 2 + 6,
        borrowed_words=[{'address': f'0x{ECHO_SLOT:08x}', 'stock': f'0x{ECHO_STOCK:08x}',
                         'purpose': 'echo slot, temporarily pointed at stock cache routines'}],
        overwritten_range=f'0x{DIR_ENTRY:08X}..0x{DIR_ENTRY + PROBE_LEN:08X}',
        execution_entry=f'0x{DIR_ENTRY:08X} via the untouched dir slot 0x{DIR_SLOT:08X}',
        expected_files=expected,
        conditions=['boot with USB disconnected and no user input or recording',
                    'card carries \\FPLPROBE (present from the 2026-10-16 bring-up)',
                    'remove this AutoRun after collecting results'],
        recovery='A power cut inside the modification window leaves patched dir bytes; '
                 'a battery-pull cold boot reloads the stock image. No persistent '
                 'settings are written by this script.',
    )
    out.mkdir(parents=True, exist_ok=False)
    (out / 'AutoRun.txt').write_bytes(script)
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def verify_card(manifest_path, results):
    report = json.loads(Path(manifest_path).read_text())
    expected = report['expected_files']
    records, complete = [], True
    for name, (purpose, digest) in expected.items():
        row = dict(file=name, purpose=purpose)
        path = Path(results) / name
        if not path.is_file():
            row.update(ok=False, error='missing')
        else:
            data = path.read_bytes()
            if digest is None:
                row.update(ok=inspect_result(data)['execution_evidence_passed'],
                           sha256=hashlib.sha256(data).hexdigest(),
                           note='see fpl_heap_probe.py inspect for the decoded words')
            else:
                actual = hashlib.sha256(data).hexdigest()
                row.update(ok=actual == digest, sha256=actual)
        complete &= row['ok']
        records.append(row)
    return dict(complete=complete, files=records,
                scope='File-level trial verification. Restoration is evidenced by '
                      'RESTORED.BIN/SLOTS.BIN hashes; RESULT.BIN shows allocated-RAM '
                      'execution only under the documented assumptions.')



def build(main, out):
    CAMERA.verify_main(main)
    body, offsets = artifact()
    inputs = ('asm/heap_probe.S', 'firmware/loader.h', 'firmware/fpl_302.h', 'armasm.py')
    report = dict(
        camera=CAMERA.name, kind='offline-owned-ram-execution-body',
        installable_card=False, camera_tested=False,
        main_sha256=CAMERA.main_sha256,
        body_bytes=len(body), body_sha256=hashlib.sha256(body).hexdigest(),
        offsets=offsets, allocation_class=0, allocation_bytes=4096,
        result_words=list(FIELDS),
        source_sha256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                       for name in inputs},
        requirements=['owned initial placement', 'D-cache then I-cache publication before entry',
                      'verified allocator and executable mapping',
                      'copy result before restoring initial placement',
                      'independent restoration readback'],
    )
    out.mkdir(parents=True, exist_ok=False)
    (out / 'heap-probe.bin').write_bytes(body)
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def inspect_result(data):
    if len(data) != 64:
        raise ValueError(f'expected 64 result bytes, got {len(data)}')
    words = dict(zip(FIELDS, struct.unpack('<16I', data)))
    checks = {
        'magic': words['magic'] == 0x58455046,
        'version': words['version'] == 1,
        'returned_from_leaf': words['status'] == 3,
        'allocation_nonzero_aligned': words['allocation'] != 0 and words['allocation'] % 4 == 0,
        'allocation_size': words['allocation_bytes'] == 4096,
        'leaf_size': words['leaf_bytes'] == 40,
        'executed_at_allocation': words['observed_pc'] == words['expected_pc'] == words['allocation'],
        'stack_nonzero_aligned': words['leaf_sp'] != 0 and words['leaf_sp'] % 8 == 0,
        'leaf_marker': words['leaf_marker'] == 0x50454148,
        'leaf_return': words['leaf_return'] == 0x21594B4F,
        'free_call_returned': words['free_returned'] == 1,
        'reserved_zero': all(words[f'reserved_{i}'] == 0 for i in range(4)),
    }
    return dict(execution_evidence_passed=all(checks.values()), checks=checks,
                words={name: f'0x{value:08x}' for name, value in words.items()},
                restoration_verified=False,
                scope='Execution marker only. Requires separate borrowed-site and handler '
                      'restoration readback; free_returned does not measure heap accounting.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='new local directory; no AutoRun or card output')
    b.add_argument('--main', type=Path, required=True)
    b.add_argument('--out', type=Path, required=True)
    i = sub.add_parser('inspect', help='decode a local 64-byte result snapshot')
    i.add_argument('result', type=Path)
    c = sub.add_parser('card', help='build the live-trial AutoRun into a new local directory')
    c.add_argument('--main', type=Path, required=True)
    c.add_argument('--out', type=Path, required=True)
    v = sub.add_parser('verify', help='check collected trial files against a card manifest')
    v.add_argument('--manifest', type=Path, required=True)
    v.add_argument('--results', type=Path, required=True)
    args = ap.parse_args()
    try:
        if args.command == 'build':
            report = build(args.main, args.out)
        elif args.command == 'inspect':
            report = inspect_result(args.result.read_bytes())
        elif args.command == 'card':
            report = build_card(args.main, args.out)
        else:
            report = verify_card(args.manifest, args.results)
    except (OSError, ValueError) as exc:
        ap.exit(1, f'{exc}\n')
    print(json.dumps(report, indent=2))
    if args.command == 'inspect' and not report['execution_evidence_passed']:
        ap.exit(1)
    if args.command == 'verify' and not report['complete']:
        ap.exit(1)


if __name__ == '__main__':
    main()
