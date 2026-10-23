#!/usr/bin/env python3
"""Offline fp L 3.02 bootstrap isolation audit. Requires Capstone 5.

Reads only the supplied MAIN; emits analysis, never firmware or a payload.
Whole-image instruction-pattern hits are candidates, NOT established code xrefs.
Computed addresses, runtime copies and arbitrary indirect calls remain unproved.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs
from capstone.arm import ARM_CC_AL, ARM_OP_IMM, ARM_OP_REG, ARM_REG_PC

BASE = 0xC0000000
SIZE = 49310208
SHA256 = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
TABLE = 0xC0BD2398
# Half-open, manually selected boundaries; cfg() checks reachable edges.
RANGES = {
    "dir": (0xC03E2B98, 0xC03E2F18),
    "mkdir": (0xC03E2F18, 0xC03E2F7C),
    "echo": (0xC03D9BB8, 0xC03D9C04),
    "comment": (0xC03D9C08, 0xC03D9C24),
    "version": (0xC03DF430, 0xC03DF4B0),
    "help": (0xC03E97B0, 0xC03E9840),
    "lookup": (0xC03D9DE0, 0xC03D9E34),
    "dispatcher": (0xC03D9E38, 0xC03D9F2C),
    "shell_iteration": (0xC03D9F30, 0xC03D9FCC),
    "shell_task": (0xC03DA330, 0xC03DA344),
    "dcache": (0xC000E91C, 0xC000E9B8),
    "icache": (0xC000EABC, 0xC000EAD0),
}
BUCKETS = {}
for _name, (_start, _end) in RANGES.items():
    for _bucket in range(_start >> 16, ((_end - 1) >> 16) + 1):
        BUCKETS.setdefault(_bucket, []).append((_name, _start, _end))


def hx(value):
    return f"0x{value:08X}"


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def owner(address):
    address &= ~1
    return [name for name, start, end in BUCKETS.get(address >> 16, ()) if start <= address < end]


def decode(md, data, address):
    offset = address - BASE
    return next(md.disasm(data[offset:offset + 4], address, count=1), None)


def text(insn):
    return f"{insn.address:08X}: {insn.mnemonic} {insn.op_str}"


def cfg(md, data, start, end):
    """Follow A32 local branches, treating calls as returning external callees.

    Not interprocedural: an indirect callee that never returns is not inferred.
    Unknown writes to PC are reported rather than silently followed as code.
    """
    todo, seen, calls, exits, unknown = [start], {}, [], [], []
    while todo:
        address = todo.pop()
        if address in seen:
            continue
        if not start <= address < end or address % 4:
            exits.append(hx(address))
            continue
        insn = decode(md, data, address)
        if insn is None:
            unknown.append({"site": hx(address), "reason": "decode failed"})
            continue
        seen[address] = insn
        name = insn.mnemonic
        operands = insn.operands
        direct = bool(operands and operands[0].type == ARM_OP_IMM)
        conditional = insn.cc != ARM_CC_AL
        # Capstone's id distinguishes bl from conditional b (e.g. blt).
        from capstone.arm import ARM_INS_B, ARM_INS_BL, ARM_INS_BLX, ARM_INS_BX
        if insn.id in (ARM_INS_BL, ARM_INS_BLX):
            calls.append({"site": hx(address), "instruction": text(insn),
                          "target": hx(operands[0].imm & 0xFFFFFFFF) if direct else None})
            todo.append(address + 4)
        elif insn.id == ARM_INS_B:
            todo.append(operands[0].imm & 0xFFFFFFFF)
            if conditional:
                todo.append(address + 4)
        elif insn.id == ARM_INS_BX:
            if insn.op_str != "lr":
                unknown.append({"site": hx(address), "reason": text(insn)})
            if conditional:
                todo.append(address + 4)
        elif name.startswith("pop") and any(op.type == ARM_OP_REG and op.reg == ARM_REG_PC for op in operands):
            if conditional:
                todo.append(address + 4)
        elif ARM_REG_PC in insn.regs_access()[1]:
            unknown.append({"site": hx(address), "reason": text(insn)})
        else:
            todo.append(address + 4)
    return {"start": hx(start), "end_exclusive": hx(end), "bytes": end - start,
            "sha256": hashlib.sha256(data[start - BASE:end - BASE]).hexdigest(),
            "reachable_instructions": len(seen), "calls": sorted(calls, key=lambda x: x["site"]),
            "out_of_range_edges": sorted(set(exits)), "unknown_pc_writes": unknown,
            "unreached_words": [hx(a) for a in range(start, end, 4) if a not in seen],
            "listing": [text(seen[a]) for a in sorted(seen)]}


def scan(data, arm, thumb):
    branches, pointers, materialized = [], [], []

    def record(site, target, mode, kind):
        names = owner(target)
        if not names:
            return
        insn = decode(arm if mode == "ARM" else thumb, data, site)
        # An independent decoder checks the scanner's branch-immediate maths.
        immediates = [op.imm & 0xFFFFFFFF for op in insn.operands if op.type == ARM_OP_IMM] if insn else []
        if not immediates or (immediates[-1] & ~1) != (target & ~1):
            raise ValueError(f"Branch decoder disagreement at {hx(site)} ({kind})")
        branches.append({"site": hx(site), "target": hx(target), "mode": mode,
                         "kind": kind, "target_ranges": names,
                         "source_ranges": owner(site),
                         "decode": text(insn) if insn else None})

    for offset, (word,) in enumerate(struct.iter_unpack("<I", data)):
        site = BASE + 4 * offset
        if word & 0x0E000000 == 0x0A000000:
            target = (site + 8 + signed(word & 0xFFFFFF, 24) * 4) & 0xFFFFFFFF
            if word >> 28 == 15:
                target = (target + ((word >> 23) & 2)) | 1
                kind = "BLX"
            else:
                kind = "BL" if word & 0x01000000 else "B"
            record(site, target, "ARM", kind)
        # MOVW/MOVT pairs within 64 bytes, same register. Candidates only:
        # do not infer liveness through intervening writes or control flow.
        if word & 0x0FF00000 == 0x03400000:
            high = ((word >> 4) & 0xF000) | (word & 0xFFF)
            if high not in {a >> 16 for a, _ in RANGES.values()}:
                continue
            reg = (word >> 12) & 15
            for back in range(4, min(64, site - BASE) + 1, 4):
                lowword = struct.unpack_from("<I", data, site - BASE - back)[0]
                if lowword & 0x0FF0F000 == 0x03000000 | (reg << 12):
                    low = ((lowword >> 4) & 0xF000) | (lowword & 0xFFF)
                    value = high << 16 | low
                    if owner(value):
                        materialized.append({"low_site": hx(site - back), "high_site": hx(site),
                                             "value": hx(value), "mode": "ARM", "target_ranges": owner(value)})

    # Every halfword, including overlapping/misaligned interpretations of ARM/data.
    halves = memoryview(data).cast("H")  # Input and supported host are little-endian.
    for offset, first in enumerate(halves):
        site = BASE + offset * 2
        if first & 0xF800 == 0xE000:
            record(site, (site + 4 + signed(first & 0x7FF, 11) * 2) & 0xFFFFFFFF, "Thumb", "B16")
        elif first & 0xF000 == 0xD000 and (first >> 8) & 15 < 14:
            record(site, (site + 4 + signed(first & 255, 8) * 2) & 0xFFFFFFFF, "Thumb", "Bcond16")
        elif first & 0xF500 == 0xB100:
            target = site + 4 + ((first >> 9) & 1) * 64 + ((first >> 3) & 31) * 2
            record(site, target, "Thumb", "CBZ/CBNZ")
        if offset + 1 == len(halves):
            continue
        second = halves[offset + 1]
        if first & 0xF800 == 0xF000:
            s, j1, j2 = (first >> 10) & 1, (second >> 13) & 1, (second >> 11) & 1
            category = second & 0xD000
            if category in (0xD000, 0xC000, 0x9000):
                # BLX requires bit 0 clear; immediate bit 1 is zero too.
                if category == 0xC000 and second & 1:
                    continue
                imm = s << 24 | (1 ^ j1 ^ s) << 23 | (1 ^ j2 ^ s) << 22 | (first & 0x3FF) << 12 | (second & 0x7FF) << 1
                pc = (site + 4) & ~3 if category == 0xC000 else site + 4
                target = (pc + signed(imm, 25)) & 0xFFFFFFFF
                record(site, target, "Thumb", {0xD000: "BL32", 0xC000: "BLX32", 0x9000: "B32"}[category])
            elif category == 0x8000 and (first >> 6) & 15 < 14:
                imm = s << 20 | j2 << 19 | j1 << 18 | (first & 63) << 12 | (second & 0x7FF) << 1
                record(site, (site + 4 + signed(imm, 21)) & 0xFFFFFFFF, "Thumb", "Bcond32")
        if first & 0xFBF0 == 0xF2C0 and second & 0x8000 == 0:
            high = (first & 15) << 12 | ((first >> 10) & 1) << 11 | ((second >> 12) & 7) << 8 | (second & 255)
            if high not in {a >> 16 for a, _ in RANGES.values()}:
                continue
            reg = (second >> 8) & 15
            for back in range(4, min(64, site - BASE) + 1, 2):
                h1, h2 = struct.unpack_from("<HH", data, site - BASE - back)
                if h1 & 0xFBF0 == 0xF240 and h2 & 0x8F00 == reg << 8:
                    low = (h1 & 15) << 12 | ((h1 >> 10) & 1) << 11 | ((h2 >> 12) & 7) << 8 | (h2 & 255)
                    value = high << 16 | low
                    if owner(value):
                        materialized.append({"low_site": hx(site - back), "high_site": hx(site),
                                             "value": hx(value), "mode": "Thumb", "target_ranges": owner(value)})

    # Include unaligned literal words, with and without Thumb tag.
    for alignment in range(4):
        end = alignment + ((len(data) - alignment) // 4) * 4
        for index, (value,) in enumerate(struct.iter_unpack("<I", memoryview(data)[alignment:end])):
            names = owner(value)
            if names:
                pointers.append({"site": hx(BASE + alignment + index * 4), "value": hx(value),
                                 "alignment": alignment, "target_ranges": names})
    return {"branch_pattern_candidates": branches, "literal_pointer_candidates": pointers,
            "movw_movt_candidates": materialized}


def self_check(arm, thumb):
    """Synthetic xrefs exercise all branch families without touching MAIN."""
    fixture = bytearray(0xEB00)
    expected = []
    target = RANGES["dir"][0]
    for offset, opcode, kind in [(0x100, 0xEA000000, "B"),
                                  (0x104, 0xEB000000, "BL"),
                                  (0x108, 0xFA000000, "BLX")]:
        struct.pack_into("<I", fixture, offset, opcode | (((target - BASE - offset - 8) >> 2) & 0xFFFFFF))
        expected.append((hx(BASE + offset), "ARM", kind))
    for offset, category, kind in [(0x200, 0xD000, "BL32"), (0x206, 0xC000, "BLX32"),
                                   (0x20C, 0x9000, "B32")]:
        pc = ((BASE + offset + 4) & ~3) if kind == "BLX32" else BASE + offset + 4
        imm = (target - pc) & 0x1FFFFFF
        s = imm >> 24
        first = 0xF000 | s << 10 | (imm >> 12) & 0x3FF
        second = category | (1 ^ ((imm >> 23) & 1) ^ s) << 13 | (1 ^ ((imm >> 22) & 1) ^ s) << 11 | (imm >> 1) & 0x7FF
        struct.pack_into("<HH", fixture, offset, first, second)
        expected.append((hx(BASE + offset), "Thumb", kind))
    # Wide conditional, short branches and CBZ all target the cache entry.
    cache = RANGES["icache"][0]
    offset = 0x300
    imm = (cache - BASE - offset - 4) & 0x1FFFFF
    struct.pack_into("<HH", fixture, offset,
                     0xF000 | ((imm >> 20) & 1) << 10 | (imm >> 12) & 63,
                     0x8000 | ((imm >> 18) & 1) << 13 | ((imm >> 19) & 1) << 11 | (imm >> 1) & 0x7FF)
    expected.append((hx(BASE + offset), "Thumb", "Bcond32"))
    for offset, opcode, kind in [(0xEA00, 0xE000, "B16"), (0xEA04, 0xD000, "Bcond16")]:
        struct.pack_into("<H", fixture, offset, opcode | ((cache - BASE - offset - 4) // 2))
        expected.append((hx(BASE + offset), "Thumb", kind))
    offset = 0xEA80
    imm = cache - BASE - offset - 4
    struct.pack_into("<H", fixture, offset, 0xB100 | ((imm >> 6) & 1) << 9 | ((imm >> 1) & 31) << 3)
    expected.append((hx(BASE + offset), "Thumb", "CBZ/CBNZ"))
    for alignment in range(4):
        struct.pack_into("<I", fixture, 0x400 + 8 * alignment + alignment, target | (alignment & 1))
    result = scan(bytes(fixture), arm, thumb)
    found = {(r["site"], r["mode"], r["kind"]) for r in result["branch_pattern_candidates"]}
    if not set(expected) <= found:
        raise AssertionError(f"Missing synthetic branch hits: {set(expected) - found}")
    if {r["alignment"] for r in result["literal_pointer_candidates"]} != {0, 1, 2, 3}:
        raise AssertionError("Unaligned literal scan failed")
    return {"branch_families": len(expected), "literal_alignments": 4,
            "every_reported_branch_target_crosschecked_with_capstone": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory for JSON and disassembly")
    args = parser.parse_args()
    data = args.main.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != SIZE or digest != SHA256:
        parser.error("Not the audited official fp L 3.02 MAIN")
    if args.out.exists():
        parser.error("Output must be a new directory")
    import sys
    if sys.byteorder != "little":
        parser.error("Halfword scanner requires a little-endian host")
    arm, thumb = Cs(CS_ARCH_ARM, CS_MODE_ARM), Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    arm.detail = thumb.detail = True
    report = {"input": {"path": str(args.main.resolve()), "sha256": digest, "bytes": len(data)},
              "scanner_self_check": self_check(arm, thumb),
              "warning": "Pattern scans are not proof that bytes are code, nor proof of absence of computed references.",
              "functions": {name: cfg(arm, data, a, b) for name, (a, b) in RANGES.items()},
              "commands": []}
    for index in range(78):
        offset = TABLE - BASE + index * 24
        name = data[offset:offset + 20].split(b"\0")[0].decode("ascii")
        pointer = struct.unpack_from("<I", data, offset + 20)[0]
        report["commands"].append({"index": index, "name": name, "slot": hx(BASE + offset + 20), "handler": hx(pointer)})
    report.update(scan(data, arm, thumb))
    args.out.mkdir(parents=True)
    (args.out / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    regions = [("shell and AutoRun", 0xC03D9BB8, 0xC03DAAD0),
               ("input registration", 0xC0420E58, 0xC04219C0),
               ("dir surroundings", 0xC03E2700, 0xC03E3500),
               ("recursive dispatcher caller", 0xC03E6808, 0xC03E68F8),
               ("play dispatcher wrapper", 0xC0405A68, 0xC0405AA8),
               ("initialization guard", 0xC0013090, 0xC0013280),
               ("C library lock hooks", 0xC001532C, 0xC0015370),
               ("tokenizer wrapper", 0xC067751C, 0xC067754C),
               ("memory set", 0xC03FA228, 0xC03FA2F4)]
    lines = []
    for name, start, end in regions:
        lines.append(f"\n{name} [{hx(start)}, {hx(end)})")
        # Decode independently, so an inline datum cannot truncate the listing.
        for address in range(start, end, 4):
            insn = decode(arm, data, address)
            lines.append(text(insn) if insn else f"{address:08X}: <undecodable>")
    for name, function in report["functions"].items():
        lines.extend([f"\nCFG {name}", *function["listing"]])
    (args.out / "disassembly.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"output": str(args.out), "branch_candidates": len(report["branch_pattern_candidates"]),
                      "pointer_candidates": len(report["literal_pointer_candidates"]),
                      "mov_pairs": len(report["movw_movt_candidates"])}, indent=2))


if __name__ == "__main__":
    main()
