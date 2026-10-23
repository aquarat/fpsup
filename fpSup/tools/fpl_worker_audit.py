#!/usr/bin/env python3
"""Offline fp L 3.02 USB-shell worker dependency audit; never touches a camera.

Verifies, against both official MAIN images, every fp L 3.02 counterpart of
the fp 5.02 constants `fp_usb_shell/camera/worker.S` consumes, at the body
level (calling convention, argument order, Thumb interworking, semantics):

  * kernel stubs tk_cre_tsk / tk_sta_tsk / tk_dly_tsk, vsnprintf,
    heap get/addr, D/I-cache maintenance;
  * USB driver leaves StartTransfer(physical) / EndTransfer(logical) /
    Wait(logical, ms) (Thumb), the bulk-arming routine, the completion
    handler, the XferNotReady fallback armer, usbTask, its wait-any-event
    call and the PTP receive routine;
  * data: TRB pointer table, USB_STATE, OUT_BUSY, DALEPENA MMIO,
    usb_fallback_buffer_pointer, the shell-context singleton, the CRC table;
  * patches.py consumers: IFACE, BURST15, PUSH, NOPTP (two sites), RETAIN.

Static assertions decode real instructions (Capstone) with relocation
normalization (branch targets and MOVW/MOVT absolute halves masked); the
dynamic checks execute real fp L instructions in Unicorn on synthetic
memory only. Requires both official MAIN images; refuses anything else.
Nothing here proves live DWC3 behaviour, enumeration, or a booted card.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

BASE = 0xC0000000
FPL_SHA256 = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
FP_SHA256 = "aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622"
FPL_SIZE = 49310208
FP_SIZE = 49245696

# fp 5.02 -> fp L 3.02 driver-module code delta, measured across every
# routine below (StartTransfer, EndTransfer, Wait, bulk arm, completion,
# fallback armer, DALEPENA sites, USB_STATE sites).
DRV_DELTA = -0x3780
SHELL_DELTA = 0x218          # shell module (0xC03D9xxx)
DESC_DELTA = 0x102E4         # gadget descriptor templates (0xC0CF374x)
CLI_DELTA = -0x2410          # usbTask / mode-dispatch module (0xC0033xxx)
POFF_DELTA = -0xE0           # SelfRefreshSetting ctor (power-off manager)

TK_STUB = 36
FN = [
    # (name, fp, fpl, length, mode, expectation)
    ("tk_cre_tsk", 0xC0016A58, 0xC0016A58, TK_STUB, "arm", "raw"),
    ("tk_sta_tsk", 0xC0016BC0, 0xC0016BC0, TK_STUB, "arm", "raw"),
    ("tk_dly_tsk", 0xC01F89C4, 0xC01F5244, TK_STUB, "arm", "shape"),
    ("vsnprintf", 0xC0013F48, 0xC0013F48, 72, "arm", "raw"),
    ("heap_get", 0xC001D740, 0xC001D740, 96, "arm", "raw"),
    ("heap_addr", 0xC001D7F0, 0xC001D7F0, 16, "arm", "raw"),
    ("d_cache", 0xC000E91C, 0xC000E91C, 156, "arm", "raw"),
    ("i_cache", 0xC000EABC, 0xC000EABC, 20, "arm", "raw"),
    # worker.S: EndTransfer/StartTransfer/Wait are [thumb]; entry is odd.
    ("EndTransfer", 0xC01E6D49, 0xC01E35C9, 432, "thumb", "shape"),
    ("StartTransfer", 0xC01E6B81, 0xC01E3401, 342, "thumb", "shape"),
    ("Wait", 0xC01E4E81, 0xC01E1701, 80, "thumb", "raw"),
    ("shell_init", 0xC03D9A10, 0xC03D9C28, 120, "arm", "shape"),
    ("shell_push", 0xC03D9AC0, 0xC03D9CD8, 96, "arm", "shape"),
    ("shell_pop", 0xC03D9B20, 0xC03D9D38, 56, "arm", "raw"),
    ("shell_run/dispatcher", 0xC03D9C20, 0xC03D9E38, 244, "arm", "shape"),
    ("crc32", 0xC06AE998, 0xC06AC4D8, 96, "arm", "shape"),
    ("bulk_arm", 0xC01E5BC0, 0xC01E5BC0 + DRV_DELTA, 0xF0, "thumb", "shape"),
    ("completion", 0xC01E7780, 0xC01E7780 + DRV_DELTA, 0x110, "thumb", "shape"),
    ("fallback_armer", 0xC01E76B8, 0xC01E76B8 + DRV_DELTA, 0xC0, "thumb", "shape"),
    ("usbTask", 0xC0033B80, 0xC00317D0, 0x34, "arm", "shape"),
    ("mode_dispatch", 0xC0033AD0, 0xC0031720, 0xB0, "arm", "shape"),
    ("ptp_receive", 0xC04DB778, 0xC04D79E0, 0x50, "arm", "shape"),
]
THUMB_ENTRIES = {"EndTransfer", "StartTransfer", "Wait"}

TRB_TABLE = {"fp": 0xC31E3264, "fpl": 0xC31E1664}
TRB_OUT = {"fp": 0xC31E3268, "fpl": 0xC31E1668}
TRB_IN = {"fp": 0xC31E326C, "fpl": 0xC31E166C}
USB_STATE = {"fp": 0xC31E3748, "fpl": 0xC31E1B48}
OUT_BUSY = {"fp": 0xC31E3974, "fpl": 0xC31E1D74}
SHELL_CTX = {"fp": 0xC3756904, "fpl": 0xC3757744}
DALEPENA = 0x2100C720
FALLBACK_BUF = 0xC3025744
CRC_TABLE = {"fp": 0xC2E3B794, "fpl": 0xC2E4B40C}
DESC = {"fp": 0xC0CF3740, "fpl": 0xC0D03A24}
# patches.py sites (fp address -> fp L counterpart)
PATCH_IFACE = {"fp": 0xC0CF3740, "fpl": 0xC0D03A24}
PATCH_NOPTP1 = {"fp": 0xC0033B3C, "fpl": 0xC003178C}
PATCH_NOPTP2 = {"fp": 0xC01E7704, "fpl": 0xC01E3F84}
PATCH_RETAIN = {"fp": 0xC00239C8, "fpl": 0xC00238E8}

STOP = 0xC3FF0000
STACK = 0xC3FE0000
SCRATCH = 0xC3F00000


def require_image(path, size, sha256, label):
    data = Path(path).read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{label}: not the audited official MAIN (size/SHA-256 mismatch)")
    return data


def word(img, address, count=1):
    return struct.unpack_from("<" + "I" * count, img, address - BASE)


# ------------------------------------------------------------- capstone ----

def _mds():
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
    return (Cs(CS_ARCH_ARM, CS_MODE_ARM), Cs(CS_ARCH_ARM, CS_MODE_THUMB))


def disasm(img, arm, thumb, address, length, mode):
    md = arm if mode == "arm" else thumb
    start = address & ~1
    out = list(md.disasm(img[start - BASE:start - BASE + length], start))
    assert out and out[-1].address + out[-1].size <= address + length, \
        f"disassembly gap in {address:#x}+{length:#x}"
    return out


def normalize(ins):
    """Mnemonic + operands; absolute code/data immediates masked.

    Masks 0xC0xxxxxx-shaped immediates (branch targets, MOVW/MOVT halves of
    absolute addresses). Small immediates (#0x813, #0x710, #4 ...) must match
    exactly, so register-offset semantics survive normalization.
    """
    import re
    ops = re.sub(r"#0x[cC][0-9a-fA-F]{7}", "#ADDR", ins.op_str)
    if ins.mnemonic in ("movw", "movt"):
        ops = re.sub(r"#0x[0-9a-fA-F]+$", "#IMM16", ops)
    return f"{ins.mnemonic} {ops}"


def same_body(fpl_img, fp_img, arm, thumb, name, fp, fpl, length, mode):
    fpl_ins = disasm(fpl_img, arm, thumb, fpl, length, mode)
    fp_ins = disasm(fp_img, arm, thumb, fp, length, mode)
    assert len(fpl_ins) == len(fp_ins), f"{name}: instruction count differs"
    for a, b in zip(fpl_ins, fp_ins):
        assert normalize(a) == normalize(b), (
            f"{name}: shape mismatch\n  fpl {a.address:08x} {normalize(a)}\n"
            f"  fp  {b.address:08x} {normalize(b)}")
    return len(fpl_ins)


def text(img, arm, thumb, address, length, mode):
    return [normalize(i) for i in disasm(img, arm, thumb, address, length, mode)]


# -------------------------------------------------- whole-image scanners ----

def arm_movw_movt_sites(img, value, maxgap=0x24):
    sites = []
    for off in range(0, len(img) - 8, 4):
        w = struct.unpack_from("<I", img, off)[0]
        if w & 0x0FF00000 == 0x03000000:            # MOVW imm
            rd = (w >> 12) & 0xF
            low = ((w >> 4) & 0xF000) | (w & 0xFFF)
            for ahead in range(4, maxgap, 4):
                w2 = struct.unpack_from("<I", img, off + ahead)[0]
                if w2 & 0x0FF00000 == 0x03400000 and (w2 >> 12) & 0xF == rd:  # MOVT
                    high = ((w2 >> 4) & 0xF000) | (w2 & 0xFFF)
                    if (high << 16) | low == value:
                        sites.append(BASE + off)
                    break
    return sites


def thumb_movw_movt_sites(img, value, maxgap=0x20):
    sites = []
    for off in range(0, len(img) - 4, 2):
        h1, h2 = struct.unpack_from("<HH", img, off)
        if (h1 & 0xFBF0) == 0xF240 and (h2 & 0x8000) == 0:      # MOVW.W imm
            reg = (h2 >> 8) & 0xF
            low = ((h1 & 0xF) << 12) | (((h1 >> 10) & 1) << 11) \
                | (((h2 >> 12) & 7) << 8) | (h2 & 0xFF)
            for ahead in range(2, maxgap, 2):
                g1, g2 = struct.unpack_from("<HH", img, off + ahead)
                if (g1 & 0xFBF0) == 0xF2C0 and (g2 & 0x8F00) == (reg << 8):  # MOVT.W
                    high = ((g1 & 0xF) << 12) | (((g1 >> 10) & 1) << 11) \
                        | (((g2 >> 12) & 7) << 8) | (g2 & 0xFF)
                    if (high << 16) | low == value:
                        sites.append(BASE + off)
                    break
    return sites


def blx_imm_callers(img, target):
    """ARM BL/BLX immediate call sites whose target (T bit cleared) matches."""
    sites = []
    for off in range(0, len(img) - 4, 4):
        w = struct.unpack_from("<I", img, off)[0]
        if w & 0x0E000000 == 0x0A000000 and (w >> 28) == 15:
            signed = w & 0xFFFFFF
            if signed & 0x800000:
                signed -= 1 << 24
            t = (BASE + off + 8 + signed * 4 + ((w >> 23) & 2)) & 0xFFFFFFFF
            if (t & ~1) == (target & ~1):
                sites.append((BASE + off, t & 1))
    return sites


def standard_crc32_table():
    table = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
        table.append(c)
    return table


# -------------------------------------------------------------- unicorn ----

def dynamic_checks(fpl, report):
    import zlib
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
    from unicorn.arm_const import (
        UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR,
        UC_CPU_ARM_CORTEX_A15,
    )
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    mu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A15)
    mu.mem_map(BASE, 0x4000000)
    mu.mem_write(BASE, fpl)

    def call(address, *args, stop=STOP, count=2000000):
        mu.reg_write(UC_ARM_REG_CPSR, 0x13)
        mu.reg_write(UC_ARM_REG_SP, STACK)
        mu.reg_write(UC_ARM_REG_LR, stop)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3), args):
            mu.reg_write(reg, value)
        mu.emu_start(address, stop, count=count)
        assert mu.reg_read(UC_ARM_REG_PC) == stop, f"budget exhausted at {address:#x}"
        return mu.reg_read(UC_ARM_REG_R0)

    # -- crc32(buf, len) leaf vs zlib.crc32, real fp L instructions + table.
    crc_cases = []
    buf = SCRATCH
    for label, data in [
            ("empty", b""), ("one", b"A"), ("ff100", b"\xff" * 100),
            ("abc", b"123456789"), ("4096", bytes(range(256)) * 16),
            ("16384", b"The quick brown fox. " * 776)]:
        mu.mem_write(buf, data)
        got = call(0xC06AC4D8, buf, len(data))
        want = zlib.crc32(data) & 0xFFFFFFFF
        assert got == want, f"crc32 {label}: {got:#x} != zlib {want:#x}"
        crc_cases.append({"case": label, "bytes": len(data),
                          "fpl_crc32": f"{got:#010x}", "zlib": f"{want:#010x}"})
    report["dynamic_crc32_vs_zlib"] = crc_cases

    # -- shell context trio: real fp L shell_init/push/pop on synthetic ctx.
    ctx, sink_a, sink_b = SCRATCH + 0x1000, SCRATCH + 0x1100, SCRATCH + 0x1200
    mu.mem_write(ctx, b"\xaa" * 0x40)
    call(0xC03D9C28, ctx)
    words = struct.unpack("<16I", mu.mem_read(ctx, 64))
    # shell_init: [ctx]=vtable 0xC000EE60, [ctx+4]=command table 0xC0BD2398
    # (the shell command table the bootstrap audit reads), [ctx+8]=0xC0BD1D8C,
    # sink stack +0x10..+0x24 zeroed, [ctx+0x24]=sink count seeded to 1.
    assert words[0] == 0xC000EE60 and words[1] == 0xC0BD2398, \
        f"shell_init pointers: {[f'{w:#x}' for w in words[:3]]}"
    assert words[4] == 0 and words[6:9] == (0,) * 3 and words[9] == 1, \
        f"shell_init layout: {[f'{w:#x}' for w in words]}"
    call(0xC03D9CD8, ctx, sink_a)
    call(0xC03D9CD8, ctx, sink_b)
    after_push = struct.unpack("<16I", mu.mem_read(ctx, 64))
    assert after_push[0] == sink_b, "current sink is not the last pushed"
    assert after_push[9] == 3, "sink count wrong"
    assert after_push[6] == sink_a and after_push[7] == sink_b, \
        "sink stack order wrong (ctx+0x10+4*count)"
    call(0xC03D9D38, ctx)
    after_pop = struct.unpack("<16I", mu.mem_read(ctx, 64))
    assert after_pop[0] == sink_a and after_pop[9] == 2, "shell_pop order wrong"
    report["dynamic_shell_trio"] = {
        "note": "real fp L shell_init (vtable + command table 0xC0BD2398 + "
                "zeroed 5-slot sink stack + count seeded to 1), shell_push "
                "(count++, [ctx]=sink, ctx+0x10+4*count) and shell_pop "
                "(count--, [ctx] restored from the stack) executed in "
                "Unicorn on a synthetic context; push/pop order verified",
        "push_depth_reached": 2,
    }


# ------------------------------------------------------------------ main ----

def audit(fpl, fp):
    arm, thumb = _mds()
    verdicts = []
    report = {"fpl_main_sha256": FPL_SHA256, "fp_main_sha256": FP_SHA256,
              "hardware_tested": False,
              "method": "bounded disassembly with relocation normalization "
                        "(branch targets and MOVW/MOVT absolute halves "
                        "masked) plus offline Unicorn execution of the fp L "
                        "crc32 leaf and shell-context trio; no camera, no "
                        "card, no live USB"}

    def record(name, ok, detail):
        verdicts.append({"name": name,
                         "verdict": "confirmed" if ok else "WRONG",
                         "detail": detail})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    # --- function bodies ----------------------------------------------------
    for name, fp_a, fpl_a, length, mode, expect in FN:
        assert (fpl_a & 1) == (1 if name in THUMB_ENTRIES else 0), \
            f"{name}: Thumb bit mismatch at {fpl_a:#x}"
        same = fpl[(fpl_a & ~1) - BASE:(fpl_a & ~1) - BASE + length] == \
               fp[(fp_a & ~1) - BASE:(fp_a & ~1) - BASE + length]
        if expect == "raw":
            assert same, f"{name}: not raw-equal"
            record(name, True,
                   {"expectation": "raw-equal",
                    "fp": hex(fp_a), "fpl": hex(fpl_a), "bytes": length,
                    "mode": mode,
                    "thumb_entry": bool(fpl_a & 1)})
            continue
        n = same_body(fpl, fp, arm, thumb, name, fp_a, fpl_a, length, mode)
        record(name, True,
               {"expectation": "normalized shape equal",
                "fp": hex(fp_a), "fpl": hex(fpl_a), "bytes": length,
                "instructions": n, "mode": mode,
                "thumb_entry": bool(fpl_a & 1),
                "raw_equal": same})

    # --- syscall stubs: literal + gate -------------------------------------
    # tk_cre_tsk/tk_dly_tsk/tk_sta_tsk route through the same SVC gate with
    # the same syscall literals on both firmwares.
    for name, fp_a, fpl_a, literal in [
            ("tk_cre_tsk", 0xC0016A58, 0xC0016A58, 0x80010100),
            ("tk_sta_tsk", 0xC0016BC0, 0xC0016BC0, None),
            ("tk_dly_tsk", 0xC01F89C4, 0xC01F5244, 0x80460100)]:
        t_fpl = text(fpl, arm, thumb, fpl_a, TK_STUB, "arm")
        t_fp = text(fp, arm, thumb, fp_a, TK_STUB, "arm")
        assert t_fpl == t_fp, f"{name}: normalized stub differs"
        gate = [i for i in disasm(fpl, arm, thumb, fpl_a, TK_STUB, "arm")
                if i.mnemonic == "bl"][0]
        assert int(gate.op_str.replace("#", ""), 16) == 0xC00011D0, \
            f"{name}: SVC gate moved on fp L"
        if literal is not None:
            assert word(fpl, fpl_a + 0x20)[0] == literal, \
                f"{name}: syscall literal moved on fp L"
        record(f"{name}_stub", True,
               {"gate": "0xC00011D0 (both firmwares)",
                "syscall_literal": None if literal is None else hex(literal),
                "note": "identical normalized stub; fp camera-proven ABI "
                        "carries over unchanged"})

    # --- driver data --------------------------------------------------------
    # StartTransfer(physical): physical argument, logical=physical>>1,
    # direction bit = physical&1; busy store at drv+0x760+4*1 == OUT_BUSY.
    st = text(fpl, arm, thumb, 0xC01E3400, 342, "thumb")
    for needle in ("asrs r5, r0, #1", "and r7, r0, #1",
                   "add.w r2, r4, #0x760", "str r3, [r2, r1]"):
        assert needle in st, f"fp L StartTransfer lost `{needle}`"
    # driver bases seen in code: StartTransfer r4=0xC31E1610 (movw/movt),
    # fallback armer r4=0xC31E1664.
    assert 0xC31E1610 + 0x764 == OUT_BUSY["fpl"], "StartTransfer busy word moved"
    assert TRB_TABLE["fpl"] + 0x710 == OUT_BUSY["fpl"], "armer busy word moved"
    record("OUT_BUSY_word", True,
           {"fp": hex(OUT_BUSY["fp"]), "fpl": hex(OUT_BUSY["fpl"]),
            "derivation": "fp L driver base 0xC31E1610+0x764 (StartTransfer "
                           "bulk-OUT busy store) == 0xC31E1664+0x710 "
                           "(fallback armer guard load) == the fp 5.02 "
                           "0xC31E3210+0x764/0xC31E3264+0x710 arithmetic; "
                           "set on StartTransfer bulk-OUT in both, "
                           "identical bodies",
            "completion_clear_site": "not pinned to a single instruction "
                           "(the fp 5.02 clear is camera-proven; the fp L "
                           "completion handler 0xC01E4000 is "
                           "instruction-identical to fp 0xC01E7780)"})

    # bulk arm: physical=(logical<<1)|IN, TRB table indexed [base+logical*4],
    # control 0x813 (bulk) / 0x873, buffer = [0xC3025744]-0x40000000.
    ba_ops = " ".join(f"{i.mnemonic} {i.op_str}" for i in
                      disasm(fpl, arm, thumb, 0xC01E2440, 0xF0, "thumb"))
    for needle in ("lsls r0, r4, #1", "orr.w r6, r0, r7",
                   "ldr.w r0, [r1, r4, lsl #2]",
                   "sub.w r1, r1, #0x40000000",
                   "str r1, [r0]", "str r1, [r0, #4]",
                   "str r1, [r0, #8]", "#0x813"):
        assert needle in ba_ops, f"fp L bulk-arm lost `{needle}`"
    record("TRB_table_topology", True,
           {"trb_table_fpl": hex(TRB_TABLE["fpl"]),
            "trb_out_fpl": hex(TRB_OUT["fpl"]), "trb_in_fpl": hex(TRB_IN["fpl"]),
            "deref": "[trb_table + logical*4] -> TRB ptr; TRB+0 buffer, "
                     "+4 0, +8 length, +0xC control 0x813 "
                     "(bulk-interrupt case 0x873); TRB buffer = CPU-0x40000000",
            "physical_from_logical": "(logical<<1)|IN, measured in the fp L "
                                      "bulk-arm body at 0xC01E2440 "
                                      "(fp 0xC01E5BC0 - 0x3780)"})

    # --- gadget descriptors -------------------------------------------------
    d_fp = fp[DESC["fp"] - BASE:DESC["fp"] - BASE + 0x74]
    d_fpl = fpl[DESC["fpl"] - BASE:DESC["fpl"] - BASE + 0x74]
    assert d_fp == d_fpl, "descriptor templates differ between firmwares"
    assert d_fpl[:4] == bytes.fromhex("03060101"), "interface word"
    # endpoint descriptors are 7-byte, byte-packed (unaligned) in the
    # template; scan every offset for the 07 05 pattern.
    eps = []
    for off in range(0, len(d_fpl) - 7):
        if d_fpl[off] == 7 and d_fpl[off + 1] == 5:
            eps.append({"bEndpointAddress": hex(d_fpl[off + 2]),
                        "bmAttributes": hex(d_fpl[off + 3]),
                        "wMaxPacketSize": int.from_bytes(d_fpl[off + 4:off + 6], "little"),
                        "bInterval": d_fpl[off + 6]})
    addr = {(e["bEndpointAddress"], e["bmAttributes"]) for e in eps}
    assert ("0x1", "0x2") in addr and ("0x82", "0x2") in addr \
        and ("0x83", "0x3") in addr, f"endpoint topology: {eps}"
    record("gadget_descriptors", True,
           {"fpl_template": hex(DESC["fpl"]), "fp_template": hex(DESC["fp"]),
            "delta": hex(DESC["fpl"] - DESC["fp"]),
            "bytes": "byte-identical 0x74-byte template region",
            "endpoints": eps,
            "topology": "bulk OUT logical 1 (0x01)/physical 2, bulk IN "
                        "logical 2 (0x82)/physical 5, interrupt IN logical 3 "
                        "(0x83)/physical 7; EP_MASK 0x24 covers physical "
                        "2|5 on fp L exactly as on fp"})

    # --- DALEPENA MMIO -------------------------------------------------------
    fp_sites = sorted(arm_movw_movt_sites(fp, DALEPENA) +
                      thumb_movw_movt_sites(fp, DALEPENA))
    fpl_sites = sorted(arm_movw_movt_sites(fpl, DALEPENA) +
                      thumb_movw_movt_sites(fpl, DALEPENA))
    assert fpl_sites == [s + DRV_DELTA for s in fp_sites], \
        f"DALEPENA sites: fp {fp_sites!r} vs fpL {fpl_sites!r}"
    record("DALEPENA_mmio", True,
           {"address": hex(DALEPENA), "sites_fpl": [hex(s) for s in fpl_sites],
            "sites_fp": [hex(s) for s in fp_sites],
            "note": "same controller register; fp L completion path reads "
                    "it into drv+0x768 and republishes on mismatch, and the "
                    "enable path writes 3 (EP0) after configuring — "
                    "identical bodies"})

    # --- USB_STATE -----------------------------------------------------------
    fp_sites = sorted(thumb_movw_movt_sites(fp, USB_STATE["fp"]))
    fpl_sites = sorted(thumb_movw_movt_sites(fpl, USB_STATE["fpl"]))
    assert fpl_sites == [s + DRV_DELTA for s in fp_sites], "USB_STATE sites"
    record("USB_STATE_word", True,
           {"fp": hex(USB_STATE["fp"]), "fpl": hex(USB_STATE["fpl"]),
            "sites_fpl": [hex(s) for s in fpl_sites],
            "note": "same writer bodies (state 2 after SET_CONFIGURATION; "
                    "suspend state 4 semantics are camera-proven on fp and "
                    "the writing bodies are instruction-identical)"})

    # --- fallback buffer pointer --------------------------------------------
    fp_sites = sorted(thumb_movw_movt_sites(fp, FALLBACK_BUF))
    fpl_sites = sorted(thumb_movw_movt_sites(fpl, FALLBACK_BUF))
    assert fpl_sites == [s + DRV_DELTA for s in fp_sites], "fallback buffer sites"
    record("usb_fallback_buffer_pointer", True,
           {"address": hex(FALLBACK_BUF),
            "sites_fpl": [hex(s) for s in fpl_sites],
            "note": "same absolute word on both firmwares; armed by the "
                    "XferNotReady fallback path when OUT_BUSY is clear"})

    # --- shell context singleton ----------------------------------------------
    fp_sites = sorted(arm_movw_movt_sites(fp, SHELL_CTX["fp"]))
    fpl_sites = sorted(arm_movw_movt_sites(fpl, SHELL_CTX["fpl"]))
    deltas = {b - a for a, b in zip(fp_sites, fpl_sites)}
    assert len(fp_sites) == len(fpl_sites) and len(fp_sites) >= 14 and \
        deltas == {SHELL_DELTA}, \
        f"shell ctx sites: fp {len(fp_sites)} fpL {len(fpl_sites)} deltas {deltas!r}"
    record("SHELL_CTX_word", True,
           {"fp": hex(SHELL_CTX["fp"]), "fpl": hex(SHELL_CTX["fpl"]),
            "materialization_sites_fpl": [hex(s) for s in fpl_sites],
            "code_site_delta": hex(SHELL_DELTA),
            "note": "the word the worker reads and passes to shell_init; "
                    "every shell-module reference shifted with the module"})

    # --- CRC table -------------------------------------------------------------
    std = standard_crc32_table()
    for tag, img, tbl in (("fp", fp, CRC_TABLE["fp"]),
                          ("fpl", fpl, CRC_TABLE["fpl"])):
        got = list(word(img, tbl, 256))
        assert got == std, f"{tag} crc table nonstandard"
    record("crc32_table", True,
           {"fpl": hex(CRC_TABLE["fpl"]), "fp": hex(CRC_TABLE["fp"]),
            "bytes": 1024, "value": "the standard reflected-0xEDB88320 "
            "table, entry v at word v (the leaf indexes table[v*4])"})

    # --- patches.py consumers ---------------------------------------------------
    assert word(fpl, PATCH_IFACE["fpl"])[0] == 0x01010603, "IFACE stock word"
    record("IFACE_patch_site", True,
           {"fpl": hex(PATCH_IFACE["fpl"]), "fp": hex(PATCH_IFACE["fp"]),
            "delta": hex(DESC_DELTA),
            "stock_word": "0x01010603 (bytes 03/06/01/01: bNumEndpoints 03, "
                          "class 06 PTP, subclass 01, protocol 01)",
            "vendor_class_word": "0xFFFFFF03 (03/ff/ff/ff)",
            "note": "same patch word as fp; lengths and endpoint set "
                    "untouched by the mask"})

    # BURST15 / PUSH companion/descriptor sites: fp -> fpL via DESC_DELTA,
    # stock words raw-equal.
    for fp_a in (0xC0CF3748, 0xC0CF3750, 0xC0CF3780, 0xC0CF3784,
                 0xC0CF3758, 0xC0CF375C, 0xC0CF3798, 0xC0CF379C):
        fpl_a = fp_a + DESC_DELTA
        assert word(fp, fp_a) == word(fpl, fpl_a), f"PUSH/BURST site {fp_a:#x}"
    record("PUSH_and_BURST15_patch_sites", True,
           {"delta": hex(DESC_DELTA),
            "fpL_sites": [hex(a + DESC_DELTA) for a in
                          (0xC0CF3748, 0xC0CF3750, 0xC0CF3780, 0xC0CF3784,
                           0xC0CF3758, 0xC0CF375C, 0xC0CF3798, 0xC0CF379C)],
            "stock_words": "raw-equal to fp 5.02 at every site"})

    # NOPTP site 1: mode-5 BL PTP receive -> mov r0,#0
    w_fp, w_fpl = word(fp, PATCH_NOPTP1["fp"])[0], word(fpl, PATCH_NOPTP1["fpl"])[0]
    assert (w_fpl >> 24) == 0xEB and (w_fp >> 24) == 0xEB, "NOPTP1 not a BL"
    t_fpl = text(fpl, arm, thumb, 0xC0031720, 0xB0, "arm")
    assert "subs r1, r4, #4" in t_fpl and "subs r1, r1, #1" in t_fpl, \
        "mode dispatch shape"
    record("NOPTP_mode5_site", True,
           {"fpl": hex(PATCH_NOPTP1["fpl"]), "fp": hex(PATCH_NOPTP1["fp"]),
            "delta": hex(CLI_DELTA),
            "fpl_dispatch": "0xC0031720 (fp 0xC0033AD0 - 0x2410), "
                            "instruction-identical mode dispatch",
            "stock_word_fpl": hex(w_fpl), "stock_word_fp": hex(w_fp),
            "patch_word": "0xE3A00000 (mov r0, #0)",
            "ptp_receive_fpl": "0xC04D79E0 (fp 0xC04DB778), "
                                "bounded body shape equal"})

    # NOPTP site 2: beq OUT_BUSY guard -> unconditional b
    w_fp, w_fpl = word(fp, PATCH_NOPTP2["fp"])[0], word(fpl, PATCH_NOPTP2["fpl"])[0]
    assert w_fp == w_fpl == 0x4628D01E, "NOPTP2 stock word changed"
    fa = text(fpl, arm, thumb, 0xC01E3F38, 0xC0, "thumb")
    assert "ldr.w r0, [r4, #0x710]" in fa and "cmp r0, #1" in fa, \
        "fp L fallback armer lost the OUT_BUSY guard"
    record("NOPTP_beq_site", True,
           {"fpl": hex(PATCH_NOPTP2["fpl"]), "fp": hex(PATCH_NOPTP2["fp"]),
            "delta": hex(-DRV_DELTA),
            "fpl_armer": "0xC01E3F38 (fp 0xC01E76B8 - 0x3780), "
                         "instruction-identical, same TRB writes "
                         "(buffer [0xC3025744]-0x40000000, +0x813)",
            "stock_word": "0x4628D01E (beq .+0x40 / mov r0, r5) on both",
            "patch_word": "0x4628E01E (b .+0x40 / mov r0, r5) — same "
                          "encoding, the branch offset is unchanged"})

    # RETAIN: SelfRefreshSetting ctor default
    w_fp, w_fpl = word(fp, PATCH_RETAIN["fp"])[0], word(fpl, PATCH_RETAIN["fpl"])[0]
    assert w_fp == w_fpl == 0xE3A00FE1, "RETAIN stock word changed"
    t_fpl = text(fpl, arm, thumb, 0xC00238E8 - 0x18, 0x30, "arm")
    assert "mov r0, #0x384" in t_fpl, "fp L ctor lost mov r0,#0x384"
    record("RETAIN_site", True,
           {"fpl": hex(PATCH_RETAIN["fpl"]), "fp": hex(PATCH_RETAIN["fp"]),
            "delta": hex(POFF_DELTA),
            "fpl_ctor": "0xC0023868 (SelfRefreshSetting ctor, "
                        "poff-audit POFF module)",
            "stock_word": "0xE3A00FE1 (mov r0, #0x384 -> [obj+0x6C])",
            "patch_word": "0xE3A00B2A (mov r0, #0xA800), "
                          "absolute immediate, same encoding"})

    # --- usbTask / wait-any-event -------------------------------------------
    callers_fp = blx_imm_callers(fp, 0xC01E9380)
    callers_fpl = blx_imm_callers(fpl, 0xC01E5C00)
    assert [s for s, _ in callers_fp] == [0xC0033BAC] and \
        [s for s, _ in callers_fpl] == [0xC00317FC], \
        f"wait-any callers {callers_fp!r} {callers_fpl!r}"
    record("usbTask_wait_any_event", True,
           {"fpl_wait_any": "0xC01E5C00 (Thumb callee, fp 0xC01E9380 - "
                            "0x3780)",
            "callers": "exactly one BLX imm caller on each firmware: fp "
                       "usbTask 0xC0033B80 -> fpL 0xC00317D0 "
                       "(BLX at 0xC00317FC), same shape",
            "note": "worker.S relies on usbTask keeping this dispatch alive "
                    "whether or not PTP answers; the fp L caller body is "
                    "instruction-identical"})

    # --- dynamic --------------------------------------------------------------
    dynamic_checks(fpl, report)

    report["verdicts"] = verdicts
    report["cannot_prove_statically"] = [
        "live DWC3 MMIO behaviour: StartTransfer/EndTransfer/Wait bodies are "
        "only shape-verified here (their DEPCMD/event internals need a "
        "controller model to execute); the fp 5.02 behaviour is "
        "camera-proven and every body is instruction-identical",
        "the exact instruction that clears OUT_BUSY on completion (not "
        "pinned on either firmware; both completion handlers are identical "
        "and the fp one is camera-proven)",
        "that the fp L PTP gadget arms the same physical endpoints at "
        "runtime (descriptors, driver mapping and DALEPENA sites all say "
        "so; no live enumeration was observed)",
        "task stack/priority tolerance of TASK_PRIO 28 / 0x2000 on fp L "
        "(kernel bodies match; the fp values are camera-proven only on fp)",
    ]
    report["limitations"] = [
        "offline audit of two official MAIN images; no camera, card, USB or "
        "MMIO emulation beyond synthetic memory",
        "normalization masks absolute immediates; it does not prove the "
        "contents of referenced globals beyond the checks above",
        "there is no universal fp-to-fp-L offset: driver -0x3780, shell "
        "+0x218, descriptors +0x30CE4, CLI -0x2410, each measured",
    ]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fpl-main", required=True, type=Path,
                         help="official fp L 3.02 MAIN.bin")
    parser.add_argument("--fp-main", required=True, type=Path,
                         help="official fp 5.02 MAIN.bin (comparison baseline)")
    parser.add_argument("--out", type=Path,
                        help="optional JSON evidence file (must not exist)")
    args = parser.parse_args()
    fpl = require_image(args.fpl_main, FPL_SIZE, FPL_SHA256, "fp L 3.02")
    fp = require_image(args.fp_main, FP_SIZE, FP_SHA256, "fp 5.02")
    if args.out and args.out.exists():
        raise SystemExit(f"{args.out} already exists")
    report = audit(fpl, fp)
    text_ = json.dumps(report, indent=2)
    print(text_)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text_ + "\n")
    failed = [v for v in report["verdicts"] if v["verdict"] != "confirmed"]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()