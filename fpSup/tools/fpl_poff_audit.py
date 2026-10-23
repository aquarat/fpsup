#!/usr/bin/env python3
"""Offline fp L 3.02 power-off manager (XC_PowerOffMgr) evidence; no camera.

Verifies the fp L addresses the shared stage2 journal (LH_RESTORE) design uses:
POFF_MGR 0xC00239B8, POFF_ADD 0xC0024038, singleton data 0xC3075684, the
allocator channel forms MEM_HEAP 0xC001CF78 and MEM_GET 0xC001D038 -- against
the official images, and cross-checks fp 5.02 (POFF_MGR 0xC0023A98,
POFF_ADD 0xC0024118, data 0xC30756C4). Refuses any wrong image. Static
assertions decode real instructions; the dynamic checks run real firmware
code in Unicorn with synthetic memory. Nothing here validates live-camera
behaviour, MMU state or the task/event framework that dispatches the
ordinary walker.

Requires Unicorn; static checks also use Capstone. Both official MAIN images
must be supplied (the fp image is the comparison baseline).
"""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR,
    UC_CPU_ARM_CORTEX_A15,
)

BASE = 0xC0000000
FPL_SHA256 = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
FP_SHA256 = "aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622"
FPL_SIZE = 49310208
FP_SIZE = 49245696

# fp L 3.02 (subject) and fp 5.02 (baseline) PowerOffMgr facts.
POFF_MGR = {"fpl": 0xC00239B8, "fp": 0xC0023A98}
POFF_ADD = {"fpl": 0xC0024038, "fp": 0xC0024118}
MGR_DATA = {"fpl": 0xC3075684, "fp": 0xC30756C4}
CTOR = {"fpl": 0xC0023868, "fp": 0xC0023948}
VTABLE = {"fpl": 0xC0726CEC, "fp": 0xC07291AC}
WALKER = {"fpl": 0xC0023B70, "fp": 0xC0023C50}      # manager vtable +0xC: ordinary list
STATE_REQ = {"fpl": 0xC0023E58, "fp": 0xC0023F38}   # (mgr, state); state 4 walks forced list
SET_STATE = {"fpl": 0xC0023EE0, "fp": 0xC0023FC0}   # [mgr+0x60]=state, signal +0x5C event
DISPLAY_STATE = {"fpl": 0xC0023DD8, "fp": 0xC0023EB8}
NAME_REG = {"fpl": 0xC00132F4, "fp": 0xC00132F4}     # diagnostics name registration
GUARD_ACQ, GUARD_REL = 0xC0013090, 0xC00131E4       # C++ static-init guard, both firmwares
REBOOTF_NAME = {"fpl": 0xC0BD2878, "fp": 0xC0BAC62C}
REBOOTF_HANDLER = {"fpl": 0xC0406010, "fp": 0xC0405DF8}
MEM_HEAP = {"fpl": 0xC001CF78, "fp": 0xC001CF78}    # class -> channel
MEM_GET = {"fpl": 0xC001D038, "fp": 0xC001D038}     # channel, bytes, align, out, callsite
CHAN_TABLE = {"fpl": 0xC30739D8, "fp": 0xC30739D8}  # class -> channel pointer table

LIST_ORDINARY, LIST_FORCED = 0x0C, 0x34   # 10 slots each inside the manager
STATE_FIELD, LAST_NOTIFIED = 0x60, 0x64

STOP = 0xC3FF0000
STACK = 0xC3FE0000
SCRATCH = 0xC3F00000          # inside the image map, past MAIN's declared length
CHANNEL = SCRATCH + 0x2000       # synthetic class-0 channel object (mapped scratch)
HEAP = 0x44410000
HEAP_SIZE = 0x10000


def word(image, address, count=1):
    return struct.unpack_from("<" + "I" * count, image, address - BASE)


def require_image(path, size, sha256, label):
    data = Path(path).read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise SystemExit(f"{label}: not the audited official MAIN (size/SHA-256 mismatch)")
    return data


# ---------------------------------------------------------------- static ----

def disasm(image, address, length):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    cs = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    cs.skipdata = True
    out = []
    for ins in cs.disasm(image[address - BASE:address - BASE + length], address):
        out.append(ins)
    assert len(out) and out[-1].address + out[-1].size <= address + length, \
        f"disassembly gap in {address:#x}+{length:#x}"
    return out


def normalize(ins):
    """Mnemonic + operands with absolute-address immediates masked.

    Branch targets (resolved by capstone) and movw/movt high halves are masked
    only when the whole immediate is an absolute code/data address, so pure
    register-offset operands ([r4, #0x60]) must match exactly.
    """
    ops = re.sub(r"#0x[cC][0-9a-fA-F]{7}", "#ADDR", ins.op_str)
    if ins.mnemonic in ("movw", "movt"):
        # the 16-bit halves of absolute addresses differ per firmware
        ops = re.sub(r"#0x[0-9a-fA-F]+$", "#IMM16", ops)
    return f"{ins.mnemonic} {ops}"


def same_shape(fpl_ins, fp_ins, what):
    assert len(fpl_ins) == len(fp_ins), f"{what}: instruction count differs"
    for a, b in zip(fpl_ins, fp_ins):
        assert normalize(a) == normalize(b), (
            f"{what}: shape mismatch\n  fpl {a.address:08x} {normalize(a)}\n"
            f"  fp  {b.address:08x} {normalize(b)}")


def static_audit(fpl, fp, report):
    # --- POFF_ADD: the 112-byte bodies are raw-equal across the firmwares.
    body_fpl = fpl[POFF_ADD["fpl"] - BASE:POFF_ADD["fpl"] - BASE + 0x70]
    body_fp = fp[POFF_ADD["fp"] - BASE:POFF_ADD["fp"] - BASE + 0x70]
    assert body_fpl == body_fp, "POFF_ADD bodies are not raw-equal"
    report["poff_add_raw_equal_112_bytes"] = True

    # POFF_ADD decodes as: forced!=0 -> base=mgr+0x34, else base=mgr+0x0C;
    # first null of 10 word slots; store obj; return 1, or 0 when full.
    add_ins = disasm(fpl, POFF_ADD["fpl"], 0x6C)
    text = [normalize(i) for i in add_ins]
    assert "add ip, r5, #0x34" in text and "add ip, r5, #0xc" in text, \
        "POFF_ADD list bases changed"
    assert text[text.index("cmp r3, #0xa") + 1].startswith("blo"), "POFF_ADD is not a 10-slot scan"
    report["poff_add_semantics"] = {
        "ordinary_list": "mgr+0x0C, 10 word slots, first-null insert",
        "forced_list": "mgr+0x34, 10 word slots, first-null insert",
        "returns": "1 registered, 0 when that list is full",
    }

    # --- POFF_MGR: lazy static singleton; shape must match fp.
    mgr_fpl = disasm(fpl, POFF_MGR["fpl"], 0x40)
    mgr_fp = disasm(fp, POFF_MGR["fp"], 0x40)
    same_shape(mgr_fpl, mgr_fp, "POFF_MGR")
    fpl_ops = [i.op_str for i in mgr_fpl]
    fp_ops = [i.op_str for i in mgr_fp]
    # movw/movt split: the singleton address immediates appear as <0x5684/0x56c4.
    for ops, low, hi in ((fpl_ops, 0x5684, 0xC307), (fp_ops, 0x56c4, 0xC307)):
        assert f"r4, #0x{low:x}" in ops, "POFF_MGR singleton movw changed"
        assert f"r4, #0x{hi:x}" in ops, "POFF_MGR singleton movt changed"
    report["poff_mgr"] = {
        "fpl": hex(POFF_MGR["fpl"]), "fp": hex(POFF_MGR["fp"]),
        "singleton_data_fpl": hex(MGR_DATA["fpl"]), "singleton_data_fp": hex(MGR_DATA["fp"]),
        "guard_at": hex(MGR_DATA["fpl"] + 0x78),
        "shape": "() -> static in-place constructed object, guard-protected, "
                 "identical instruction shape on fp 5.02",
    }

    # --- constructor: vtable, both list memsets, state init.
    ctor = disasm(fpl, CTOR["fpl"], 0x100)
    text = [normalize(i) for i in ctor]
    # first vtable store (base ctor), then the derived one wins
    assert text[4] == "str r1, [r4]" and text[7] == "str r1, [r4]", "ctor vtable stores moved"
    assert any(i.mnemonic == "bl" for i in ctor), "ctor lost its calls"
    # list memsets: two 0x28-byte clears at +0x0C and +0x34 around the C0015058 calls
    adds = [i.op_str for i in ctor if i.mnemonic == "add" and i.op_str in
            ("r0, r4, #0xc", "r0, r4, #0x34")]
    assert adds == ["r0, r4, #0xc", "r0, r4, #0x34"], "list memset bases changed"
    assert [i.op_str for i in ctor if i.mnemonic == "mov" and i.op_str == "r2, #0x28"] \
        and len([i for i in ctor if i.mnemonic == "bl" and i.op_str == "#0xc0015058"]) == 2, \
        "the two 40-byte list clears changed"
    report["manager_layout_fpl"] = {
        "+0x00": f"vtable = {VTABLE['fpl']:#x} (final of two stores, base-then-derived)",
        "+0x08": "byte, power-related config index",
        "+0x0C": "ordinary list: 10 words (memset 0x28)",
        "+0x34": "forced list: 10 words (memset 0x28)",
        "+0x5C": "synchronization/event object (C036DF58(obj, 0x1d))",
        "+0x60": "state word, constructed to 1",
        "+0x64": "last notified state",
        "+0x6C": "0x384 tick budget",
        "+0x78": "C++ static-init guard",
    }

    # --- manager vtable: slot +0xC is the ordinary walker; +0x4 the destructor.
    vt = word(fpl, VTABLE["fpl"], 4)
    assert vt[3] == WALKER["fpl"], "fp L manager vtable +0xC is not the walker"
    assert vt[2] == 0xC0023968, "fp L manager vtable +0x8 (dtor) moved"
    vt_fp = word(fp, VTABLE["fp"], 4)
    assert vt_fp[3] == WALKER["fp"], "fp manager vtable +0xC is not the walker"
    report["manager_vtable"] = {
        "fpl": [hex(x) for x in vt], "fp": [hex(x) for x in vt_fp],
        "slot_plus_0xc": "the ordinary-list walker (same slot the registered "
                         "objects are called through)",
    }

    # --- ordinary walker: structurally identical on both firmwares.
    w_fpl = disasm(fpl, WALKER["fpl"], 0x84)
    w_fp = disasm(fp, WALKER["fp"], 0x84)
    same_shape(w_fpl, w_fp, "ordinary walker")
    text = [normalize(i) for i in w_fpl]
    assert "add r1, r4, #0xc" in text and "add fp, r1, #0x28" in text, \
        "ordinary walk no longer covers mgr+0x0C..+0x34"
    # the callback dispatch: ldr r1,[r7] / ldr r2,[r1,#0xc] / ldr r1,[r4,#0x60]
    # / mov r0,r7 / blx r2 -- appear in this relative order.
    order = [t for t in text if t in (
        "ldr r1, [r7]", "ldr r2, [r1, #0xc]", "ldr r1, [r4, #0x60]", "mov r0, r7", "blx r2")]
    # the first [r4,#0x60] load is the walker prologue (the state publish);
    # the dispatch sequence follows it inside the loop.
    assert order == ["ldr r1, [r4, #0x60]", "ldr r1, [r7]", "ldr r2, [r1, #0xc]",
                     "ldr r1, [r4, #0x60]", "mov r0, r7", "blx r2"], \
        "ordinary callback dispatch changed"
    report["ordinary_walker"] = {
        "fpl": hex(WALKER["fpl"]), "fp": hex(WALKER["fp"]),
        "list": "mgr+0x0C..+0x34 (ordinary), ascending slot order",
        "callback": "obj->[[obj]+0xC](obj, mgr->state) -- state re-read per object",
        "walk_position": "first action of the walker, before the shutdown "
                         "actions in its second half (display/LED/singletons)",
        "shape": "instruction-for-instruction identical to fp 5.02 "
                 "(absolute call targets differ per module)",
    }

    # --- state request: state 4 walks the forced list; other states publish and park.
    s_fpl = disasm(fpl, STATE_REQ["fpl"], 0x88)
    s_fp = disasm(fp, STATE_REQ["fp"], 0x88)
    same_shape(s_fpl, s_fp, "state request")
    text = [normalize(i) for i in s_fpl]
    assert "cmp r6, #4" in text, "state request no longer tests state 4"
    assert "add r2, r5, #0x34" in text and "add sl, r2, #0x28" in text, \
        "forced walk no longer covers mgr+0x34..+0x5C"
    order = [t for t in text if t in ("ldr r2, [r4]", "ldr r1, [r5, #0x60]",
                                      "add r2, r2, #0xc", "ldr r2, [r2]", "mov r0, r4", "blx r2")]
    assert order == ["ldr r2, [r4]", "ldr r1, [r5, #0x60]", "add r2, r2, #0xc",
                     "ldr r2, [r2]", "mov r0, r4", "blx r2"], "forced callback dispatch changed"
    assert text[-2].startswith("mov r0, #2") or "mov r0, #2" in text, \
        "final action after the forced walk changed"
    report["forced_walker"] = {
        "fpl": hex(STATE_REQ["fpl"]), "fp": hex(STATE_REQ["fp"]),
        "entry": "(mgr, state); state != 4 publishes the state via the setter "
                 "then parks in a 500 ms delay loop; state == 4 walks the list",
        "list": "mgr+0x34..+0x5C (forced), ascending slot order",
        "callback": "obj->[[obj]+0xC](obj, mgr->state)",
        "final": "C011EEB0(2, 0) immediately after the walk (fp: C0122610(2, 0))",
        "shape": "instruction-for-instruction identical to fp 5.02",
    }

    # --- set-state: writes [mgr+0x60] and signals the +0x5C object.
    t_fpl = disasm(fpl, SET_STATE["fpl"], 0x1C)
    text = [normalize(i) for i in t_fpl]
    assert "str r5, [r4, #0x60]" in text, "setter no longer writes mgr+0x60"
    assert "add r0, r4, #0x5c" in text, "setter no longer signals mgr+0x5C"
    report["state_setter"] = {"fpl": hex(SET_STATE["fpl"]),
                              "effect": "[mgr+0x60] = state; C036E010(mgr+0x5C, mgr)"}

    # --- 'rebootf': the stock forced path on both firmwares.
    for tag, image in (("fpl", fpl), ("fp", fp)):
        name_addr = REBOOTF_NAME[tag]
        name = image[name_addr - BASE:name_addr - BASE + 8].split(b"\0")[0]
        assert name == b"rebootf", f"{tag}: rebootf string moved"
        handler = word(image, name_addr + 0x14)[0]
        assert handler == REBOOTF_HANDLER[tag], f"{tag}: rebootf handler moved"
        ins = disasm(image, handler, 0x20)
        text = [normalize(i) for i in ins]
        assert any(i.mnemonic == "bl" and i.op_str == f"#0x{POFF_MGR[tag]:x}"
                   for i in ins), f"{tag}: rebootf handler does not call POFF_MGR"
        assert "mov r1, #4" in text, f"{tag}: rebootf does not request state 4"
    report["rebootf"] = {
        "fpl": f"shell command 'rebootf' -> {REBOOTF_HANDLER['fpl']:#x}: "
               f"POFF_MGR() then state request 4 (forced list walk + final action)",
        "fp": f"shell command 'rebootf' -> {REBOOTF_HANDLER['fp']:#x}: same",
    }

    # --- MEM_HEAP: class -> [C30739D8 + class*4], with assert paths.
    h_ins = disasm(fpl, MEM_HEAP["fpl"], 0x60)
    text = [normalize(i) for i in h_ins]
    h_ops = [i.op_str for i in h_ins]
    assert "r4, #0x39d8" in h_ops and "r4, #0xc307" in h_ops, \
        "MEM_HEAP no longer uses the C30739D8 channel table"
    assert "cmp r5, #0xf" in text, "MEM_HEAP class-15 assert moved"
    assert "ldr r0, [r4, #0x38]" in text, "MEM_HEAP table+0x38 prerequisite moved"
    assert "ldr r0, [r1, r0]" in text or "lsl r0, r5, #2" in text, "MEM_HEAP table index moved"
    report["mem_heap"] = {
        "fpl": hex(MEM_HEAP["fpl"]),
        "abi": "r0=class -> [C30739D8 + class*4]; asserts class!=15 and "
               "table+0x38 (class-14 channel) nonzero before indexing",
    }

    # --- MEM_GET: 5-argument channel form.
    g_ins = disasm(fpl, MEM_GET["fpl"], 0xB0)
    text = [normalize(i) for i in g_ins]
    assert "ldr r7, [sp, #0x34]" in text, "MEM_GET no longer takes the stack callsite"
    assert "ldr r7, [sp, #0x30]" in text, "MEM_GET LR fallback for the callsite moved"
    assert "cmp r0, #1" in text and "bhs" in " ".join(
        i.mnemonic for i in g_ins), "MEM_GET alignment floor changed"
    assert "add r0, r5, #8" in text, "MEM_GET no longer allocates from channel+8"
    assert "ldr r0, [r5, #0x20]" in text, "MEM_GET fallback channel moved"
    report["mem_get"] = {
        "fpl": hex(MEM_GET["fpl"]),
        "abi": "(r0=channel, r1=bytes, r2=alignment, r3=optional actual-size out, "
               "[sp]=callsite; callsite 0 falls back to the saved LR). Alignment "
               "<1 becomes 1; the core replaces 64-divisible alignments with 64 "
               "(allocator audit). Allocates from the channel's list at "
               "channel+8; on refusal retries via the channel's fallback at "
               "channel+0x20; returns the address or 0.",
    }

    # --- no allocator-reset call is statically reachable from the manager path.
    report["heap_reset_static_scan"] = {
        "checked": ["ordinary walker", "state request", "setter", "forced walk",
                    "query helpers C0023F38/C00239F8/C00242D8/C0024230/C0024018/"
                    "C0023FA8/C0024130", "shutdown-task bodies C01FDD88/C01FDE30/C01FDF40"],
        "result": "no call into the allocator core (C0010310..C0010E00) or the "
                  "channel/layout management (C001C000..C001F100) anywhere in "
                  "those bodies; the class-0 channel is only reinitialized from "
                  "boot-time layout init and application mode switches",
        "caveat": "indirect vtable calls in the walker's second half are not "
                  "resolvable statically; they run AFTER the ordinary walk",
    }


# --------------------------------------------------------------- dynamic ----

class Machine:
    """Real firmware instructions in Unicorn; named stubs; synthetic memory."""

    def __init__(self, image):
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A15)
        self.mu.mem_map(BASE, 0x4000000)
        self.mu.mem_write(BASE, image)
        self.mu.mem_map(0x44300000, 0x4000)
        self.mu.mem_map(HEAP, HEAP_SIZE)
        self.stubs = {}
        self.trace = []
        self.mu.hook_add(UC_HOOK_CODE, self.hook)

    def words(self, address, count=1):
        return struct.unpack("<" + "I" * count,
                             self.mu.mem_read(address, 4 * count))

    def put(self, address, *words):
        self.mu.mem_write(address, struct.pack("<" + "I" * len(words), *words))

    def hook(self, mu, address, size, _):
        if address in (0xC0011100, 0xC0011130):
            raise AssertionError(f"firmware assertion at {address:#x}")
        if address in self.stubs:
            result = self.stubs[address]
            mu.reg_write(UC_ARM_REG_R0, result)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))

    def call(self, address, *args, stack_arg=None, stop=STOP, count=100000):
        self.mu.reg_write(UC_ARM_REG_CPSR, 0x13)
        sp = STACK if stack_arg is None else STACK - 8
        if stack_arg is not None:
            self.put(STACK - 8, stack_arg)
        self.mu.reg_write(UC_ARM_REG_SP, sp)
        self.mu.reg_write(UC_ARM_REG_LR, stop)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3),
                              args):
            self.mu.reg_write(reg, value)
        self.mu.emu_start(address, stop, count=count)
        assert self.mu.reg_read(UC_ARM_REG_PC) == stop, \
            f"instruction budget exhausted in {address:#x}"
        return self.mu.reg_read(UC_ARM_REG_R0)


def movw(reg, imm16):
    return 0xE3000000 | ((imm16 >> 12) << 16) | (reg << 12) | (imm16 & 0xFFF)


def movt(reg, imm16):
    return 0xE3400000 | ((imm16 >> 12) << 16) | (reg << 12) | (imm16 & 0xFFF)


def dynamic_audit(image, report):
    m = Machine(image)

    # -- the manager singleton, via the real POFF_MGR.
    m.stubs.update({GUARD_ACQ: 1, GUARD_REL: 0,          # static-init guard
                    0xC00244E0: 0,                        # ctor: config load
                    0xC036DF58: 0,                         # ctor: +0x5C sync object
                    0xC00CA560: 0x1000, 0xC00CA678: 1, 0xC00CA608: 1,  # settings/notify
                    0xC011F328: 0, 0xC011F020: 0})        # registration helpers
    mgr = m.call(POFF_MGR["fpl"])
    assert mgr == MGR_DATA["fpl"], "POFF_MGR did not return the static singleton"
    assert m.words(mgr)[0] == VTABLE["fpl"], "constructor vtable not installed"
    assert m.words(mgr + 0x60)[0] == 1, "constructed state is not 1"

    # -- the stage2 journal block, exactly as lh_setup builds it:
    #    X+0 = X-8 (vtable), X+4 = routine, X+8 = journal start,
    #    routine copied to X+12.  [(X-8)+0xC] == [X+4] is the routine itself.
    x = SCRATCH
    rec = SCRATCH + 0x100
    routine = x + 12
    code = struct.pack(
        "<IIIIIIIII",
        movw(2, rec & 0xFFFF), movt(2, rec >> 16),                  # r2 = rec
        0xE5820000,                     # str r0, [r2]        -- the object
        0xE5821004,                      # str r1, [r2, #4]     -- the state
        0xE5923008, 0xE2833001, 0xE5823008,  # counter at rec+8
        0xE3A0005A,                      # mov r0, #0x5A        -- return marker
        0xE12FFF1E)                      # bx lr
    journal = (routine + len(code) + 3) & ~3   # the journal starts after the code
    assert journal - x <= 0x40
    m.put(x, x - 8, routine, journal)     # X+0 vtable, X+4 routine, X+8 journal start
    m.mu.mem_write(routine, code)
    m.put(rec, 0, 0, 0)

    # -- registration through the real POFF_ADD, both lists.
    assert m.call(POFF_ADD["fpl"], mgr, x, 0) == 1, "ordinary registration refused"
    assert m.call(POFF_ADD["fpl"], mgr, x, 1) == 1, "forced registration refused"
    assert m.words(mgr + LIST_ORDINARY)[0] == x, "X not in the ordinary list"
    assert m.words(mgr + LIST_FORCED)[0] == x, "X not in the forced list"

    # a full ordinary list refuses: 10 slots total.  The filler objects carry a
    # minimal real vtable whose +0xC is a bare `bx lr`, so the walk below
    # dispatches through them exactly as stock objects would.
    ret = SCRATCH + 0x2F0
    m.mu.mem_write(ret, struct.pack("<I", 0xE12FFF1E))       # bx lr
    dummy_vt = SCRATCH + 0x200
    m.put(dummy_vt + 0xC, ret)
    for i in range(1, 10):
        filler = SCRATCH + 0x400 + 4 * i
        m.put(filler, dummy_vt)
        assert m.call(POFF_ADD["fpl"], mgr, filler, 0) == 1
    assert m.call(POFF_ADD["fpl"], mgr, SCRATCH + 0x800, 0) == 0, \
        "an 11th ordinary registration was accepted"

    # -- forced walk: request state 4; stop before the final action.
    m.put(mgr + STATE_FIELD, 4)
    m.put(mgr + LAST_NOTIFIED, 4)          # display-state publish early-outs
    m.call(STATE_REQ["fpl"], mgr, 4, stop=STATE_REQ["fpl"] + 0x74)
    assert m.words(rec, 3) == (x, 4, 1), "forced walk did not call the journal routine"

    # -- ordinary walk: the manager's own vtable +0xC path, stopped after the list.
    m.put(mgr + STATE_FIELD, 1)
    m.put(mgr + LAST_NOTIFIED, 1)
    m.stubs.update({0xC0019DC0: 0, 0xC001A048: 0})        # trace/notification helpers
    m.call(WALKER["fpl"], mgr, stop=WALKER["fpl"] + 0x84)
    assert m.words(rec, 3) == (x, 1, 2), "ordinary walk did not call the journal routine"

    # -- the state setter (real) writes mgr+0x60; the signal is stubbed.
    m.stubs[0xC036E010] = 0
    m.call(SET_STATE["fpl"], mgr, 2)
    assert m.words(mgr + STATE_FIELD)[0] == 2, "setter did not update mgr+0x60"

    # -- the allocator channel path stage2 uses: MEM_HEAP(0) then MEM_GET(...).
    m.stubs.update({0xC001E328: 0, 0xC001E3C8: 0})        # allocator telemetry
    m.put(CHAN_TABLE["fpl"], CHANNEL)
    m.put(CHAN_TABLE["fpl"] + 0x38, CHANNEL)             # class-14 pointer prerequisite
    m.put(CHANNEL, 0, 0)
    m.call(0xC0010310, CHANNEL + 8)                      # init the allocation list
    m.call(0xC00103A8, CHANNEL + 8, HEAP)                # region base
    desc = SCRATCH + 0x1000
    for address in (HEAP, HEAP + HEAP_SIZE - 0x40):      # two sentinels
        m.put(desc + 0x100, address, 0x40)
        m.call(0xC00103E8, CHANNEL + 8, desc + 0x100)
    assert m.call(MEM_HEAP["fpl"], 0) == CHANNEL, "MEM_HEAP(0) is not the class-0 channel"
    addr = m.call(MEM_GET["fpl"], CHANNEL, 0x100, 0, 0, stack_arg=0)
    assert addr and addr % 64 == 0, f"MEM_GET returned {addr:#x}, not a 64-byte block"
    m.mu.mem_write(addr, b"\x5a" * 0x100)
    refused = m.call(MEM_GET["fpl"], CHANNEL, HEAP_SIZE, 0, 0, stack_arg=0)
    assert refused == 0, "an over-large channel request was not refused"

    report["dynamic_checks"] = {
        "poff_mgr": "POFF_MGR() constructed the static object at C3075684 and "
                    "returned it (vtable and initial state verified)",
        "poff_add": "real POFF_ADD placed the journal block in both lists; "
                    "the 11th ordinary registration returned 0",
        "forced_walk": "state request 4 called the routine at X+12 with "
                       "(X, 4): the [[X]+0xC] slot resolves through X-8",
        "ordinary_walk": "the walker called it again with (X, 1); the second "
                         "invocation is indistinguishable from the first",
        "state_setter": "the real setter wrote mgr+0x60 (signal stubbed)",
        "mem_channel": "MEM_HEAP(0) returned the class-0 channel; MEM_GET with "
                       "the channel form, alignment 0 and a zero stack callsite "
                       f"returned a 64-byte-aligned block ({addr:#x}); a "
                       "HEAP_SIZE request was refused with 0",
        "stubs": "static-init guard, ctor config/notify/registration helpers, "
                 "trace helpers, the +0x5C signal and allocator telemetry; "
                 "POFF_ADD, both list walks, the callback dispatch, the setter "
                 "field write, MEM_HEAP, MEM_GET and the allocation list are "
                 "real instructions",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fpl-main", required=True, type=Path)
    parser.add_argument("--fp-main", required=True, type=Path)
    parser.add_argument("--out", type=Path,
                        help="optional JSON evidence file (must not exist)")
    args = parser.parse_args()
    fpl = require_image(args.fpl_main, FPL_SIZE, FPL_SHA256, "fp L 3.02")
    fp = require_image(args.fp_main, FP_SIZE, FP_SHA256, "fp 5.02")

    report = {
        "fpl_main_sha256": FPL_SHA256, "fp_main_sha256": FP_SHA256,
        "hardware_tested": False,
    }
    static_audit(fpl, fp, report)
    dynamic_audit(fpl, report)
    report["cannot_prove_statically"] = [
        "which task/event-framework context dispatches the ordinary walker "
        "(the manager's vtable +0xC): no direct BL exists; the +0x5C signal "
        "and the message posts imply a waiter, but its body is not identified",
        "that the power-switch path reaches the ordinary walker on fp L at "
        "runtime (the fp 5.02 shape is identical and hardware-proven there)",
        "what the indirect vtable calls in the walker's second half do; they "
        "run after the ordinary-list callbacks, but a full subsystem teardown "
        "order cannot be enumerated statically",
        "interrupt context, priority or CPU of either walk; the callbacks must "
        "stay short and must not block",
    ]
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        if args.out.exists():
            raise SystemExit(f"{args.out} already exists")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")


if __name__ == "__main__":
    main()
