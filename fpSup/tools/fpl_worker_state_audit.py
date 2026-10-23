#!/usr/bin/env python3
"""Offline audit of the fp L 3.02 USB-shell worker's fixed-word candidates.

Reads only the two supplied official MAIN images; emits JSON and bounded
disassembly into a NEW output directory. No camera interface, no firmware or
payload is written anywhere.

What it scans (the same families as fp_usb_shell/audit_fpl_bootstrap.py):

  - the pool publication word and every word +0..+0x40 after it
    (fp L: 0xC37588BC, fp 5.02: 0xC3757A7C) and the shell-context singleton
    words (fp L: 0xC3757744, fp: 0xC3756904) in BOTH images:
      * aligned ARM MOVW/MOVT pairs, same register, at most 64 bytes apart
        (every overlapping pairing is reported; MOVTs with a matching high
        half but no partner are reported separately as `unpaired_movt`);
      * halfword-aligned Thumb MOVW/MOVT pairs, same rules;
      * 32-bit little-endian literals at ALL four byte alignments.
  - Every hit is attributed to a containing routine from a documented range
    table (the ranges below were established by hand for this audit); hits
    outside every range are reported as unattributed, never dropped.

What it deliberately is NOT: whole-program pointer analysis. It cannot see
addresses formed by arithmetic, copied or relocated at runtime, MOV pairs
farther than 64 bytes apart or in different registers, or writes through
registers loaded from elsewhere. Pattern hits are candidates; the
attributions marked `AUDIT_NOTE` below are analyst conclusions from reading
the emitted disassembly, and the script only reproduces their evidence.
See docs/FPL_WORKER_STATE_AUDIT.md for the interpretation.

Usage:

  python3 -B tools/fpl_worker_state_audit.py \
      --fpl /path/to/firmware/FPL_V302/MAIN.bin \
      --fp  /path/to/firmware/FP__V502/MAIN.bin \
      --out /path/to/new/private/output-directory
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

BASE = 0xC0000000

# Exact official images only; anything else is refused.
IMAGES = {
    "fpl": {
        "bytes": 49310208,
        "sha256": "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9",
        "name": "SIGMA fp L 3.02 MAIN",
    },
    "fp": {
        "bytes": 49245696,
        "sha256": "aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622",
        "name": "SIGMA fp 5.02 MAIN",
    },
}

POOL = {"fpl": 0xC37588BC, "fp": 0xC3757A7C}   # shell bufmem pool publication
CTX = {"fpl": 0xC3757744, "fp": 0xC3756904}    # shell context singleton pointer
POOL_SPAN = 0x44                                # words +0 .. +0x40 inclusive

# Ranges established by hand for this audit (see the doc). A hit inside one of
# these is attributed; anything else is reported unattributed. The notes are
# analyst conclusions, each supported by instructions in the emitted listing.
ROUTINES = {
    "fpl": [
        ("memmgr_bufmem_body", 0xC03FA600, 0xC03FA868,
         "AUDIT_NOTE: the `memmgr bufmem` shell-command body. Owns the word "
         "pairing {+0 address, +4 size, +8 type}: `get` writes all three via "
         "C001CFD8 (call at C03FA7B8, r1=0xC37588BC), prints them with "
         "`ldm r5,{r2,r3,r8}` (C03FA7C0), `rel` frees through C001D3D0 and "
         "then zeroes word +0 (C03FA7F8..C03FA804). The ONLY static writer "
         "of 0xC37588BC in the image."),
        ("path_builder_C04071A8", 0xC04071A8, 0xC0407240,
         "AUDIT_NOTE: builds a pathname of up to 0x100 bytes in the lazily "
         "allocated buffer whose address/length pair is at +0xC/+0x10 "
         "(0xC37588C8/CC; lazy allocator C0406EC8, class 0; the length word "
         "+0x10 is written base-relative at C0407228, so it is owned even "
         "though no MOV pair names it)."),
        ("lazy_path_buffer_alloc_C0406EC8", 0xC0406EC8, 0xC0406F78,
         "AUDIT_NOTE: lazily allocates the 0x100-byte path buffer through "
         "FW_MEM_HEAP/FW_MEM_GET and stores the pair at +0xC/+0x10."),
        ("log_subcommand_writers_C04075E0", 0xC04075E0, 0xC04076BC,
         "AUDIT_NOTE: handlers of the shell `log` subcommands log-on / "
         "log-uart / log-sim / log-off / log-out / log-file (subcommand "
         "table at 0xC0BE7A88, stride 0xC). They mutate the output-log "
         "state struct based at +0x14 (0xC37588D0): strb [ip] (C04075FC), "
         "[r4+4]/[r4+8]/[r4+0xC] (C0407630..C04076AC, base-relative, so "
         "+0x18/+0x1C/+0x20 are owned too), each followed by C06AE118 "
         "which copies five words of the struct to the fixed global "
         "0xC38D007C."),
        ("log_file_config_C0407788", 0xC0407788, 0xC0407908,
         "AUDIT_NOTE: the `log` LogFile family: opens a settings file, "
         "parses a number (`addtimeset`, prints 'total:%d sec'), adds a "
         "delta and writes it back. Struct base +0x24 (0xC37588E0); the "
         "counter field is +0x38 (0xC37588F4), written base-relative at "
         "C0407824/C040784C/C0407860."),
        ("log_addtimeset_cmd_C0407908", 0xC0407908, 0xC040795C,
         "AUDIT_NOTE: the `addtimeset` subcommand: clears the counter word "
         "+0x38 (C0407928) then updates the persisted counter via "
         "log_file_config_C0407788."),
        ("log_setfilename_cmd_C0407960", 0xC0407960, 0xC04079B8,
         "AUDIT_NOTE: the `setfilename` subcommand ('LogFile Set Name'): "
         "strncpy (<=0x13) of the log file name into the struct at +0x24 "
         "(C0407980..C0407988)."),
        ("log_default_ptr_C0407A40", 0xC0407A40, 0xC0407A80,
         "AUDIT_NOTE: init-guard at 0xC3758900 (=+0x44) via C0013090; on "
         "first use copies the pointer pair {0xC0BE7DF0, 0} into +0x3C / "
         "+0x40 (0xC37588F8/FC, C0407A64)."),
    ],
    "fp": [
        ("memmgr_bufmem_body", 0xC03FA3E8, 0xC03FA650,
         "AUDIT_NOTE: the fp counterpart of the fp L body, instruction-for-"
         "instruction the same shape (relocation delta +0x218): `get` writes "
         "the triplet at C03FA5A0 (r1=0xC3757A7C) and prints it (C03FA5A8); "
         "`rel` frees via C001D3D0 and zeroes word +0 (C03FA5E0..C03FA5EC). "
         "The ONLY static writer of 0xC3757A7C in the image."),
        ("guard_accessor_C0404F88", 0xC0404F88, 0xC0404FC4,
         "AUDIT_NOTE: one-time-init accessor; the guard is +0xC "
         "(0xC3757A88, C0013090/C00131E4) and the returned object is based "
         "at +0x14 (0xC3757A90), initialised by C06ADE18 (a 0x470-byte "
         "memset plus two calls, C06ADE1C..C06ADE44)."),
        ("media_object_user_C068F8E0", 0xC068F8E0, 0xC068F990,
         "AUDIT_NOTE: second user of the same +0xC guard / +0x14 object "
         "(guard at C068F928..C068F950, use at C068F984 via C06ADEE0)."),
    ],
}


def hx(value):
    return f"0x{value:08X}"


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def routine_for(table, address):
    for name, start, end, note in table:
        if start <= address < end:
            return name
    return None


def load_image(path, spec, parser):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != spec["bytes"] or digest != spec["sha256"]:
        parser.error(
            f"{path} is not the audited official {spec['name']}: "
            f"{len(data)} bytes, sha256 {digest}")
    return data, digest


def scan_image(data, targets):
    tset = set(targets)
    highs = {t >> 16 for t in targets}
    mov, unpaired, literals = [], [], []
    n = len(data)
    words = struct.unpack_from(f"<{n // 4}I", data, 0)
    # ARM MOVT (aligned); every MOVW with the same register within 64 bytes.
    for i, word in enumerate(words):
        if word & 0x0FF00000 != 0x03400000:
            continue
        high = ((word >> 4) & 0xF000) | (word & 0xFFF)
        if high not in highs:
            continue
        reg = (word >> 12) & 15
        if reg == 15:
            continue
        site = BASE + 4 * i
        found = False
        for back in range(4, min(64, site - BASE) + 1, 4):
            lowword = words[i - back // 4]
            if lowword & 0x0FF0F000 == 0x03000000 | (reg << 12):
                low = ((lowword >> 4) & 0xF000) | (lowword & 0xFFF)
                value = high << 16 | low
                if value in tset:
                    mov.append({"low_site": hx(site - back), "high_site": hx(site),
                                "value": hx(value), "mode": "ARM"})
                found = True
        if not found:
            unpaired.append({"site": hx(site), "mode": "ARM", "high_half": hx(high << 16)})
    # Thumb MOVT.W first halfword (any halfword alignment), same rules.
    halves = struct.unpack_from(f"<{n // 2}H", data, 0)
    for off in range(len(halves) - 1):
        first = halves[off]
        if first & 0xFBF0 != 0xF2C0:
            continue
        second = halves[off + 1]
        if second & 0x8000:
            continue
        high = ((first & 15) << 12 | ((first >> 10) & 1) << 11
                | ((second >> 12) & 7) << 8 | (second & 255))
        if high not in highs:
            continue
        reg = (second >> 8) & 15
        if reg in (13, 15):
            continue
        site = BASE + off * 2
        found = False
        for back in range(2, min(64, site - BASE) + 1, 2):
            h1, h2 = halves[off - back // 2], halves[off - back // 2 + 1]
            if h1 & 0xFBF0 == 0xF240 and (h2 & 0x8F00) == (reg << 8):
                low = ((h1 & 15) << 12 | ((h1 >> 10) & 1) << 11
                       | ((h2 >> 12) & 7) << 8 | (h2 & 255))
                value = high << 16 | low
                if value in tset:
                    mov.append({"low_site": hx(site - back), "high_site": hx(site),
                                "value": hx(value), "mode": "Thumb"})
                found = True
        if not found:
            unpaired.append({"site": hx(site), "mode": "Thumb", "high_half": hx(high << 16)})
    # Literals at every byte alignment, exactly as the bootstrap audit does.
    for alignment in range(4):
        end = alignment + ((n - alignment) // 4) * 4
        for index, (value,) in enumerate(
                struct.iter_unpack("<I", memoryview(data)[alignment:end])):
            if value in tset:
                literals.append({"site": hx(BASE + alignment + index * 4),
                                 "value": hx(value), "alignment": alignment})
    return mov, unpaired, literals


def self_check():
    """Synthetic fixtures exercise every scanner family without any MAIN."""
    fixture = bytearray(0x1000)
    target = 0xC37588BC
    # ARM MOVW/MOVT pair (rd = r14), encoded exactly as the A1 encodings the
    # scanner reverses: imm16 = imm4(<<12) | imm12, imm4 at bits 19-16.
    low16, high16 = target & 0xFFFF, target >> 16
    struct.pack_into("<II", fixture, 0x100,
                     0x03000000 | (14 << 12) | ((low16 >> 12) << 16) | (low16 & 0xFFF),
                     0x03400000 | (14 << 12) | ((high16 >> 12) << 16) | (high16 & 0xFFF))
    # Thumb MOVW/MOVT pair, 4 bytes apart (MOVW first).
    low, high = target & 0xFFFF, target >> 16
    w1 = 0xF240 | ((low >> 12) & 15) | (((low >> 11) & 1) << 10)
    w2 = (((low >> 8) & 7) << 12) | (2 << 8) | (low & 0xFF)
    t1 = 0xF2C0 | ((high >> 12) & 15) | (((high >> 11) & 1) << 10)
    t2 = (((high >> 8) & 7) << 12) | (2 << 8) | (high & 0xFF)
    struct.pack_into("<HHHH", fixture, 0x200, w1, w2, t1, t2)
    # A literal at each alignment.
    for alignment in range(4):
        struct.pack_into("<I", fixture, 0x400 + 8 * alignment + alignment, target)
    # An unpaired ARM MOVT (rd = r5) with the right high half, no MOVW near it.
    struct.pack_into("<I", fixture, 0x800,
                     0x03400000 | (5 << 12) | ((high16 >> 12) << 16) | (high16 & 0xFFF))
    mov, unpaired, literals = scan_image(bytes(fixture), [target])
    values = {m["value"] for m in mov}
    if values != {hx(target)} or len(mov) != 2:
        raise AssertionError(f"MOV pair scan self-check failed: {mov}")
    if len(literals) != 4 or {l["alignment"] for l in literals} != {0, 1, 2, 3}:
        raise AssertionError(f"literal scan self-check failed: {literals}")
    if len(unpaired) != 1 or unpaired[0]["mode"] != "ARM":
        raise AssertionError(f"unpaired-MOVT self-check failed: {unpaired}")
    return {"mov_pairs": len(mov), "literal_alignments": len(literals),
            "unpaired_movt": len(unpaired)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fpl", type=Path, required=True,
                        help="official fp L 3.02 MAIN.bin")
    parser.add_argument("--fp", type=Path, required=True,
                        help="official fp 5.02 MAIN.bin")
    parser.add_argument("--out", type=Path, required=True,
                        help="NEW directory for the JSON and disassembly")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output must be a new directory")
    if sys.byteorder != "little":
        parser.error("halfword scanner requires a little-endian host")

    arm, thumb = Cs(CS_ARCH_ARM, CS_MODE_ARM), Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    arm.detail = thumb.detail = True

    report = {"scanner_self_check": self_check(), "images": {}, "warning":
              "Pattern scans are not proof that bytes are code, nor proof of "
              "absence of computed references. Attributions marked AUDIT_NOTE "
              "are analyst conclusions; the routine listings they rest on are "
              "emitted verbatim in disassembly.txt."}

    for key in ("fpl", "fp"):
        data, digest = load_image({"fpl": args.fpl, "fp": args.fp}[key], IMAGES[key], parser)
        pool, ctx = POOL[key], CTX[key]
        targets = [pool + n for n in range(0, POOL_SPAN, 4)] + [ctx, ctx + 4]
        mov, unpaired, literals = scan_image(data, targets)
        table = ROUTINES[key]
        hits = []
        for m in mov:
            hits.append({**m, "kind": "mov_pair",
                         "low_routine": routine_for(table, int(m["low_site"], 16)),
                         "high_routine": routine_for(table, int(m["high_site"], 16))})
        for l in literals:
            hits.append({**l, "kind": "literal",
                         "routine": routine_for(table, int(l["site"], 16))})
        # Word-by-word summary: which routines reference each scanned word.
        # Unattributed hits (outside every routine range) are reported with
        # their sites, never silently dropped.
        words = {}
        for n in range(0, POOL_SPAN, 4):
            addr = pool + n
            refs, stray = [], []
            for h in hits:
                if int(h["value"], 16) != addr:
                    continue
                site = int(h.get("low_site") or h.get("site"), 16)
                r = h.get("low_routine") or h.get("high_routine") or h.get("routine")
                if r:
                    if r not in refs:
                        refs.append(r)
                elif site not in stray:
                    stray.append(site)
            words[f"+0x{n:02X} ({hx(addr)})"] = {
                "referenced_by": refs,
                "unattributed_hit_sites": [hx(s) for s in sorted(stray)],
                "is_shell_context": False,
            }
        for n in (0, 4):
            addr = ctx + n
            refs, stray = [], []
            for h in hits:
                if int(h["value"], 16) != addr:
                    continue
                site = int(h.get("low_site") or h.get("site"), 16)
                r = h.get("low_routine") or h.get("high_routine") or h.get("routine")
                if r:
                    if r not in refs:
                        refs.append(r)
                elif site not in stray:
                    stray.append(site)
            words[f"ctx+0x{n:02X} ({hx(addr)})"] = {
                "referenced_by": refs,
                "unattributed_hit_sites": [hx(s) for s in sorted(stray)],
                "is_shell_context": True,
            }
        report["images"][key] = {
            "input": {"path": str({"fpl": args.fpl, "fp": args.fp}[key].resolve()),
                      "sha256": digest, "bytes": len(data)},
            "pool_word": hx(pool), "shell_context_word": hx(ctx),
            "scanned_words": words,
            "hits": hits,
            "unpaired_movt_with_matching_high_half": unpaired,
            "routines": [{"name": n, "start": hx(s), "end_exclusive": hx(e), "note": note}
                         for n, s, e, note in table],
        }

    args.out.mkdir(parents=True)
    (args.out / "worker_state_audit.json").write_text(json.dumps(report, indent=2) + "\n")

    # Bounded disassembly of every routine that produced a hit, plus a
    # context window around any hit outside every routine range.
    lines = []
    for key in ("fpl", "fp"):
        data = {"fpl": args.fpl, "fp": args.fp}[key].read_bytes()
        lines.append(f"\n================ {IMAGES[key]['name']} "
                     f"(pool word {hx(POOL[key])}) ================")
        md = arm
        hit_sites = [int(h.get("low_site") or h.get("site"), 16)
                     for h in report["images"][key]["hits"]]
        attributed = set()
        for name, start, end, note in ROUTINES[key]:
            if not any(start <= site < end for site in hit_sites):
                continue
            attributed.update(range(start, end))
            lines.append(f"\n--- {name} [{hx(start)}, {hx(end)})\n--- {note}")
            for insn in md.disasm(data[start - BASE:end - BASE], start):
                lines.append(f"{insn.address:08X}: {insn.mnemonic:<8} {insn.op_str}")
        for site in sorted(s for s in hit_sites if s not in attributed):
            lo, hi = max(BASE, site - 0x20), site + 0x24
            lines.append(f"\n--- UNATTRIBUTED hit near {hx(site)} "
                         f"[{hx(lo)}, {hx(hi)})")
            for insn in md.disasm(data[lo - BASE:hi - BASE], lo):
                lines.append(f"{insn.address:08X}: {insn.mnemonic:<8} {insn.op_str}")
    (args.out / "disassembly.txt").write_text("\n".join(lines) + "\n")

    summary = {key: {w: {"referenced_by": v["referenced_by"],
                         "unattributed_hit_sites": v["unattributed_hit_sites"]}
                     for w, v in report["images"][key]["scanned_words"].items()}
               for key in ("fpl", "fp")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
