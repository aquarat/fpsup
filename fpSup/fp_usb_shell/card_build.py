#!/usr/bin/env python3
"""Shared VBIN packaging and fp L ordinary/trial bootstrap (offline only).

The complete load chain on one card, using the pattern the live heap-probe
trial proved (docs/FPL_HEAP_PROBE.md): the loader is spelled into the stock
`dir` handler's verified extent, published through the stock cache routines
via the borrowed echo slot, and dispatched through the UNTOUCHED dir slot.
The loader reads \\fpSup.BIN (stage2 + worker), stage2 registers the
power-off journal and calls the worker's `spawn`, which allocates its pool
and code, copies itself out of staging, creates the serve task and RETURNS.
The script then restores the dir body and the echo slot; the worker stays,
resident entirely in memory it allocated.

Not carried over from fp: the EP-shaping patches (hook-push only), the abort,
the store/Fast Start or the banner. The interface-class patch is placed by
the script as on fp. Diagnostic and ordinary shell cards also apply the two
audited fp L NOPTP words; the original non-diag trial does not. These script
patches are not journaled and retain the trial's lifetime (battery-pull reset).

Build and verify are offline. This tool never opens USB or a block device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from armasm import assemble, symbols
from firmware import get_camera

HERE = Path(__file__).resolve().parent
CAMERA = get_camera('fp-l-3.02')
BASE = 0xC0000000
DIR_ENTRY = 0xC03E2B98            # LOADER_BASE: the verified dir extent
DIR_SLOT = 0xC0BD24FC             # entry 14's handler slot: never written
POOL_DESC = DIR_ENTRY + 0x200     # the loader's descriptor (above the 316
                                  # byte loader, inside the 896 byte extent)
RESTORE_LEN = 0x210               # loader bytes + the 16 byte descriptor
ECHO_SLOT = 0xC0BD2544
ECHO_STOCK = 0xC03D9BB8
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
TABLE, TABLE_LEN = 0xC0BD2398, 77 * 24 + 24
IFACE = 0xC0D03A24                # fp L counterpart of fp's 0xC0CF3740
IFACE_STOCK = 0x01010603          # verified against the image at build
IFACE_PATCH = 0xFFFFFF03          # 03/06/01/01 -> 03/ff/ff/ff
PUBLICATION = 0xC37588BC          # the fp L pool publication triplet
PROBE_DIR = 'FPLPROBE'            # present on the card from the bring-up
BIN_NAME = 'fpSup.BIN'
READ_CAP = 0xF000


def build_vbin(sections, entries):
    """Lay out a complete VBIN and its ordered entry chain.

    Entries are (section index, byte offset) for staging entries, or existing
    header-ABI values (absolute addresses / staging offsets). Thumb bit is
    retained. Return bytes, header entry, and the final section list. Neither
    callers nor diagnostic wrappers calculate file offsets independently.
    """
    sections = list(sections)
    for addr, blob in sections:
        if len(blob) % 4:
            raise ValueError(f'section for 0x{addr:08X} is {len(blob)} bytes; '
                             'every section must be a multiple of four')
    for item in entries:
        if isinstance(item, tuple):
            index, offset = item
            if (not 0 <= index < len(sections) or sections[index][0] != 0
                    or offset < 0 or offset % 4 == 2
                    or (offset & ~1) >= len(sections[index][1])):
                raise ValueError(f'invalid staging entry {item}')
        elif not 0 < item <= 0xFFFFFFFF:
            raise ValueError(f'invalid header entry {item:#x}')
    tramp_sec = None
    if len(entries) > 1:
        tramp = assemble(HERE / 'asm/entries.S', [])
        tramp_tbl = symbols(HERE / 'asm/entries.S', [])['table']
        tramp_sec = len(sections)
        sections.append((0, tramp + bytes(4 * (len(entries) + 1))))
    table = b''.join(struct.pack('<II', addr, len(blob))
                     for addr, blob in sections)
    body = bytearray()
    offsets = []
    for _, blob in sections:
        offsets.append(16 + len(table) + len(body))
        body.extend(blob)
    resolved = [offsets[item[0]] + item[1] if isinstance(item, tuple) else item
                for item in entries]
    entry = resolved[0] if resolved else 0
    if tramp_sec is not None:
        entry = offsets[tramp_sec]
        words = struct.pack(f'<{len(resolved) + 2}I',
                            entry + tramp_tbl, *resolved, 0)
        at = entry - 16 - len(table) + tramp_tbl
        body[at:at + len(words)] = words
    return (struct.pack('<4sIII', b'VBIN', len(sections), entry, len(body))
            + table + body, entry, sections)


def artifact(stock_sections=()):
    """Assemble the real chain and build the VBIN the loader reads."""
    defines = list(CAMERA.loader_defines())
    ld = defines + [f'LOADER_BASE={DIR_ENTRY:#010X}',
                    f'POOL_DESC={POOL_DESC:#010X}',
                    f'READ_CAP={READ_CAP:#x}',
                    f'BIN_PATH="\\\\{BIN_NAME}"']
    loader = assemble(HERE / 'asm/loader.S', ld)
    if len(loader) > 0x200:
        raise ValueError(f'loader is {len(loader)} bytes; the descriptor at '
                         f'+0x200 would overlap')
    stage2 = assemble(HERE / 'asm/stage2.S',
                      defines + ['LH_RESTORE=1', f'LOADER_BASE={DIR_ENTRY:#010X}'])
    worker = assemble(HERE / 'camera/worker.S', defines)
    w = symbols(HERE / 'camera/worker.S', defines)
    # The fp-only bootstrap is compiled out: spawn is the first thing in the
    # worker image (assert rather than assume).
    if w['spawn'] != 0:
        raise ValueError(f"spawn sits at +{w['spawn']:#x}, not the image start")
    sections = [(0, stage2), (0, worker), *stock_sections]  # runtime hooks are journaled first
    binfile, entry, _ = build_vbin(sections, [(1, w['spawn'])])
    if len(binfile) > READ_CAP:
        raise ValueError('binary exceeds the ordinary loader read capacity')
    return dict(loader=loader, stage2=stage2, worker=worker,
                binfile=binfile, entry=entry, symbols=w)


FW_PTPBUF = 0xC3025744            # the firmware's PTP receive buffer
FW_USBSTATE = 0xC31E1B48
FW_OUTBUSY = 0xC31E1D74
FW_DALEPENA = 0x2100C720

# NOPTP (from the worker audit, docs/FPL_WORKER_AUDIT.md): the firmware's own
# PTP receiver, off.  usbTask answers every USB event and calls the mode-5 PTP
# receiver, which arms EP 0x01 OUT on the firmware's own buffer (C3025744);
# when it wins the race with the worker, a command lands in PTP's parser and
# the worker waits out its TIMEOUT -- frame0 TIMEOUT, moved=0/64.  Same
# posture as fp's shell-sup card: left patched while powered, re-applied every
# boot, restored by a battery pull.
NOPTP1 = 0xC003178C                 # mode-5 call: BL FUN_c04d79e0 -> mov r0,#0
NOPTP1_STOCK = 0xEB129893
NOPTP1_PATCH = 0xE3A00000
NOPTP2 = 0xC01E3F84                 # armer guard: beq (OUT_BUSY) -> b
NOPTP2_STOCK = 0x4628D01E
NOPTP2_PATCH = 0x4628E01E
# Historical diagnostic addresses, retained only to reproduce trial AutoRun
# bytes. Later boots used other pools: these dumps are NOT reliable current
# state evidence. Discover publication + MCAPS with fpl_status.py instead.
DIAG_POOL = 0x4533AEC0
DIAG_SLEEP_MS = 90000               # the host window while the script waits


def card(image, diag=False, *, trial=True, stock_sections=()):
    """(AutoRun lines, manifest) for the bring-up trial (diag: + NOPTP,
    a USB wait window, and state dumps that localize a silent worker)."""
    seen = set()
    for address, data in stock_sections:
        if (address & 3 or len(data) != 4 or address < BASE or
                address+4 > BASE+len(image) or address in seen or
                data != image[address-BASE:address-BASE+4]):
            raise ValueError('fp L runtime hook declarations must be unique aligned stock firmware words')
        if DIR_ENTRY <= address < DIR_ENTRY+RESTORE_LEN or address in (ECHO_SLOT, IFACE, NOPTP1, NOPTP2):
            raise ValueError('runtime hook declaration overlaps shell bootstrap')
        seen.add(address)
    art = artifact(stock_sections)
    stock = image[DIR_ENTRY - BASE:DIR_ENTRY - BASE + RESTORE_LEN]
    iface_stock = struct.unpack_from('<I', image, IFACE - BASE)[0]
    if iface_stock != IFACE_STOCK:
        raise ValueError(f'IFACE word at {IFACE:#x} is {iface_stock:#x}, not '
                         f'the audited {IFACE_STOCK:#x}')
    for _name, _addr, _want in (('NOPTP1', NOPTP1, NOPTP1_STOCK),
                                 ('NOPTP2', NOPTP2, NOPTP2_STOCK)):
        _got = struct.unpack_from('<I', image, _addr - BASE)[0]
        if _got != _want:
            raise ValueError(f'{_name} word at {_addr:#x} is {_got:#x}, not '
                             f'the audited {_want:#x}')
    lines = ['# --- fp L shell bring-up trial: stock dir body captured first']
    if trial:
        lines.append(f'mem save \\{PROBE_DIR}\\SHELL-PRE.BIN 0x{DIR_ENTRY:08X},,0x{RESTORE_LEN:X}')
    lines.append('# --- interface class patch: stop the host PTP stack claiming interface 0')
    lines.append(f'mem set 0x{IFACE:08X} 0x{IFACE_PATCH:08X}')
    if diag:
        # The firmware's own PTP receiver, off (see NOPTP above): without this
        # the receiver arms EP 0x01 OUT on the firmware buffer and the worker
        # never sees a command.
        lines.append('# --- NOPTP: the firmware PTP receiver off; the worker owns the pipes')
        lines.append(f'mem set 0x{NOPTP1:08X} 0x{NOPTP1_PATCH:08X}')
        lines.append(f'mem set 0x{NOPTP2:08X} 0x{NOPTP2_PATCH:08X}')
    lines.append('# --- place the loader (borrowed dir handler region)')
    lines += [f'mem set 0x{DIR_ENTRY + off:08X} 0x{word:08X}'
              for off, word in zip(range(0, len(art['loader']), 4),
                                   struct.unpack(f"<{len(art['loader']) // 4}I",
                                                 art['loader']))]
    if trial:
        lines.append(f'mem save \\{PROBE_DIR}\\SHELL-WROTE.BIN 0x{DIR_ENTRY:08X},,0x{RESTORE_LEN:X}')
    lines.append('# --- publish: echo slot -> stock D-cache, then I-cache, dispatched')
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{DCACHE:08X}', 'echo',
              f'mem set 0x{ECHO_SLOT:08X} 0x{ICACHE:08X}', 'echo']
    lines.append('# --- run the load: dir dispatches the loader; the worker stays')
    lines.append('dir')
    lines.append('# --- rendezvous evidence: the publication triplet')
    if trial:
        lines.append(f'mem save \\{PROBE_DIR}\\SHELL-POOL.BIN 0x{PUBLICATION:08X},,0x10')
    if diag and trial:
        lines.append('# --- USB window: connected in Camera Control mode at power-on,')
        lines.append('#     the host gets this whole window to reach the worker')
        lines.append(f'ctrl sleep {DIAG_SLEEP_MS}')
        lines.append('# --- diagnostics: what the worker did while USB was up')
        lines += [
            f'mem save \\{PROBE_DIR}\\DIAG-POOL.BIN 0x{PUBLICATION:08X},,0x10',
            f'mem save \\{PROBE_DIR}\\DIAG-STATE.BIN 0x{DIAG_POOL + 0x1000:08X},,0x40',
            f'mem save \\{PROBE_DIR}\\DIAG-FRAME.BIN 0x{DIAG_POOL:08X},,0x40',
            f'mem save \\{PROBE_DIR}\\DIAG-PTP.BIN 0x{FW_PTPBUF:08X},,0x40',
            f'mem save \\{PROBE_DIR}\\DIAG-FAULTS.BIN 0x{DIAG_POOL + 0x6C00:08X},,0x210',
            f'mem save \\{PROBE_DIR}\\DIAG-USBSTATE.BIN 0x{FW_USBSTATE:08X},,0x4',
            f'mem save \\{PROBE_DIR}\\DIAG-OUTBUSY.BIN 0x{FW_OUTBUSY:08X},,0x4',
            f'mem save \\{PROBE_DIR}\\DIAG-DALEPENA.BIN 0x{FW_DALEPENA:08X},,0x8',
        ]
    lines.append('# --- restore the stock dir body (loader bytes + descriptor)')
    lines += [f'mem set 0x{DIR_ENTRY + off:08X} 0x{word:08X}'
              for off, word in zip(range(0, RESTORE_LEN, 4),
                                   struct.unpack(f'<{RESTORE_LEN // 4}I', stock))]
    lines.append('# --- republish the restored code before the slot goes back')
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{DCACHE:08X}', 'echo',
              f'mem set 0x{ECHO_SLOT:08X} 0x{ICACHE:08X}', 'echo']
    lines += [f'mem set 0x{ECHO_SLOT:08X} 0x{ECHO_STOCK:08X}'] * 3
    lines.append('# --- restoration evidence')
    if trial:
        lines.append(f'mem save \\{PROBE_DIR}\\SHELL-RESTORED.BIN 0x{DIR_ENTRY:08X},,0x{RESTORE_LEN:X}')
        lines.append(f'mem save \\{PROBE_DIR}\\SHELL-SLOTS.BIN 0x{TABLE:08X},,0x{TABLE_LEN:X}')
    manifest = dict(
        camera=CAMERA.name, kind='fp-l-shell-bringup-trial',
        installable_card=True, camera_tested=False,
        main_sha256=CAMERA.main_sha256,
        loader_sha256=hashlib.sha256(art['loader']).hexdigest(),
        stage2_sha256=hashlib.sha256(art['stage2']).hexdigest(),
        worker_sha256=hashlib.sha256(art['worker']).hexdigest(),
        bin_sha256=hashlib.sha256(art['binfile']).hexdigest(),
        loader_bytes=len(art['loader']), restore_bytes=RESTORE_LEN,
        worker_spawn_file_offset=art['entry'],
        serve_off=art['symbols']['serve'] - art['symbols']['wbody'],
        wbody_len=art['symbols']['wbody_end'] - art['symbols']['wbody'],
        iface=dict(address=f'0x{IFACE:08x}', stock=f'0x{IFACE_STOCK:08x}',
                   patch=f'0x{IFACE_PATCH:08x}',
                   note='left patched while powered, like fp; every boot re-runs'),
        expected_files={
            'SHELL-PRE.BIN': hashlib.sha256(stock).hexdigest(),
            'SHELL-WROTE.BIN': None,       # loader bytes + stock tail: built below
            'SHELL-RESTORED.BIN': hashlib.sha256(stock).hexdigest(),
            'SHELL-SLOTS.BIN': hashlib.sha256(
                image[TABLE - BASE:TABLE - BASE + TABLE_LEN]).hexdigest(),
            'SHELL-POOL.BIN': None,        # the triplet: checked by value
        },
        conditions=['boot with USB disconnected and no user input or recording',
                    'card carries \\FPLPROBE and \\fpSup.BIN',
                    'after the boot, connecting in Camera Control mode exposes '
                    'the worker on 1003:c442 (fpshd --pid 0xc442)',
                    'remove this AutoRun when the trial is done'],
        recovery='Power cut inside the window leaves a patched dir body; a '
                 'battery-pull cold boot reloads the stock image. The worker '
                 'is task-scheduled and touches no endpoint until USB '
                 'enumerates (DALEPENA gate). No persistent settings written.',
    )
    wrote = bytearray(stock)
    wrote[:len(art['loader'])] = art['loader']
    manifest['expected_files']['SHELL-WROTE.BIN'] = hashlib.sha256(bytes(wrote)).hexdigest()
    manifest['expected_files']['SHELL-POOL.BIN'] = 'zero triplet means the load or spawn refused'
    return lines, manifest, art


def ordinary_card(main, *, stock_sections=()):
    """Offline-tested headless shell: NOPTP on, no evidence files or wait window.

    Optional stock-word sections reserve runtime hook restoration. Not Fast,
    UI installation or arbitrary product packaging. The loader/worker remain
    byte-identical to the diagnostic trial; only the AutoRun presentation and
    evidence commands differ. Firmware patches retain the trial's lifetime.
    """
    image = CAMERA.verify_main(main)
    lines, _, art = card(image, diag=True, trial=False, stock_sections=stock_sections)
    commands = [line for line in lines if not line.startswith('#')]
    return '\n'.join(commands) + '\n', art


def build_card(main, out, diag=False):
    image = CAMERA.verify_main(main)
    lines, manifest, _art = card(image, diag=diag)
    script = ''.join(line + '\n' for line in lines).encode('ascii')
    manifest['autorun_sha256'] = hashlib.sha256(script).hexdigest()
    manifest['commands'] = len(lines)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'card').mkdir()
    (out / 'card' / 'AutoRun.txt').write_bytes(script)
    (out / 'card' / BIN_NAME).write_bytes(_art['binfile'])
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def verify_card(manifest_path, results):
    report = json.loads(Path(manifest_path).read_text())
    records, complete = [], True
    for name, digest in report['expected_files'].items():
        row = dict(file=name)
        path = Path(results) / name
        if not path.is_file():
            row.update(ok=False, error='missing')
        else:
            data = path.read_bytes()
            row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
            if name == 'SHELL-POOL.BIN':
                words = struct.unpack('<4I', data)
                row.update(ok=(words[0] != 0 and words[1] == 0x100000
                               and words[2] != 0),
                           words=[f'0x{w:08x}' for w in words],
                           note='pool, size, code; zeros mean the load or spawn refused')
            elif digest:
                row.update(ok=row['sha256'] == digest)
            else:
                row.update(ok=True, note='described in the manifest only')
        complete &= row['ok']
        records.append(row)
    return dict(complete=complete, files=records,
                scope='Card evidence only. The worker itself is proven by '
                      'its task answering over USB, which this cannot check.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    b = sub.add_parser('card', help='build into a new local directory')
    b.add_argument('--main', type=Path, required=True)
    b.add_argument('--out', type=Path, required=True)
    b.add_argument('--diag', action='store_true',
                   help='add NOPTP, a USB wait window and state dumps')
    v = sub.add_parser('verify', help='check collected trial files')
    v.add_argument('--manifest', type=Path, required=True)
    v.add_argument('--results', type=Path, required=True)
    args = ap.parse_args()
    try:
        report = (build_card(args.main, args.out, diag=args.diag)
                  if args.command == 'card'
                  else verify_card(args.manifest, args.results))
    except (OSError, ValueError) as exc:
        ap.exit(1, f'{exc}\n')
    print(json.dumps(report, indent=2))
    if args.command == 'verify' and not report['complete']:
        ap.exit(1)


if __name__ == '__main__':
    main()
