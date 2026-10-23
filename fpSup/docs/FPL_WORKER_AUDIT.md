# fp L 3.02 USB-shell worker dependency audit (offline)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

**2026-10-19 follow-up:** the constants audited here did not cover the shared
worker's CPU-frame alias assumption. Independent MMU/stock-USB checks found
that `pool+40000000` is not the fallback alias of the allocated fp L buffer;
the corrected profile uses the pointer directly. See
[live investigation and conditional reproduction](FPL_PORT.md).
Also, the mode-dispatch third branch is **mode 12**, not mode 8: the code
compares 7 after subtracting 5. NOPTP's fallback-armer patch does not remove
the separate completion-handler OUT rearm at `C01E41E8..C01E425A`.

Date: 2026-10-16. Method: bounded disassembly of both official MAIN images
with relocation normalization (branch targets and MOVW/MOVT absolute halves
masked; small immediates like `#0x813`, `#0x710`, `#4` must match exactly),
plus offline Unicorn execution of the real fp L `crc32` leaf and the real fp L
shell-context trio on synthetic memory. Evidence script:
[`tools/fpl_worker_audit.py`](../tools/fpl_worker_audit.py) — it verifies
both image fingerprints, refuses anything else, prints JSON and exits
non-zero on any failed verdict. **No camera, card, USB or MMIO emulation was
involved; nothing here is hardware verification.**

Inputs (never modified):

| Image | SHA-256 | Role |
|---|---|---|
| fp L 3.02 `MAIN.bin` | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` | subject |
| fp 5.02 `MAIN.bin` | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` | comparison baseline (camera-proven on fp) |

Run:

```sh
python3 -B tools/fpl_worker_audit.py \
  --fpl-main .../FPL_V302/MAIN.bin --fp-main .../FP__V502/MAIN.bin \
  --out <new-file>/worker-audit.json     # 39/39 verdicts confirmed, exit 0
```

## Result

**Every fp L 3.02 counterpart of `fp_usb_shell/camera/worker.S`'s firmware
dependencies is confirmed.** There is no universal fp→fp L offset — the
driver module shifts −0x3780, the shell module +0x218, the descriptor
templates +0x102E4, the CLI/usbTask module −0x2410, the power-off manager
module −0xE0 — but every constant the worker consumes was found, and every
checked body is either raw-equal to fp 5.02 or instruction-identical after
normalization. **The worker.S fp L port can proceed on these constants.**

### Function verdicts

`worker.S` value → fp L value; mode is the interworking level the worker's
`blx r12` relies on.

| worker.S name | fp 5.02 | fp L 3.02 | Mode/Thumb bit | Body | Verdict |
|---|---|---|---|---|---|
| `FN_CRETSK` | `0xC0016A58` | `0xC0016A58` | ARM | 36 B raw-equal; SVC gate `0xC00011D0`, syscall literal `0x80010100` identical | confirmed |
| `FN_STATSK` | `0xC0016BC0` | `0xC0016BC0` | ARM | 36 B raw-equal | confirmed |
| `FN_DELAY` | `0xC01F89C4` | `0xC01F5244` | ARM | 36 B shape-equal; same gate, same literal `0x80460100` (`tk_dly_tsk`) | confirmed |
| `FN_VSNPRINT` | `0xC0013F48` | `0xC0013F48` | ARM | 72 B raw-equal | confirmed |
| `FN_ENDX` | `0xC01E6D49` | `0xC01E35C9` | **Thumb** (odd entry) | 432 B shape-equal; `EndTransfer(logical)` | confirmed |
| `FN_STARTX` | `0xC01E6B81` | `0xC01E3401` | **Thumb** (odd entry) | 342 B shape-equal; `StartTransfer(physical)` | confirmed |
| `FN_WAIT` | `0xC01E4E81` | `0xC01E1701` | **Thumb** (odd entry) | 80 B **raw-equal** (`Wait(logical, ms)`) | confirmed |
| `FN_SHINIT` | `0xC03D9A10` | `0xC03D9C28` | ARM | 120 B shape-equal | confirmed |
| `FN_SHPUSH` | `0xC03D9AC0` | `0xC03D9CD8` | ARM | 96 B shape-equal (assert-string constant differs) | confirmed |
| `FN_SHPOP` | `0xC03D9B20` | `0xC03D9D38` | ARM | 56 B raw-equal | confirmed |
| `FN_SHRUN` | `0xC03D9C20` | `0xC03D9E38` | ARM | 244 B shape-equal (dispatcher) | confirmed |
| `FW_CRC32` | `0xC06AE998` | `0xC06AC4D8` | ARM | 96 B shape-equal, only the table immediate differs | confirmed |
| `H_GET`/`H_ADDR` | `0xC001D740`/`0xC001D7F0` | same | ARM | 96/16 B raw-equal | confirmed |
| `F_DCACHE`/`F_ICACHE` | `0xC000E91C`/`0xC000EABC` | same | ARM | 156/20 B raw-equal | confirmed |

The `blx r12` interworking holds: worker.S loads the odd entry values for
the three driver leaves, and the fp L entries are odd exactly like fp's —
`blx` from ARM switches to Thumb for them, and the aligned bodies decode as
the same functions (`push.w {r4…lr}` prologues).

### Data verdicts

| worker.S name | fp 5.02 | fp L 3.02 | Evidence | Verdict |
|---|---|---|---|---|
| `TRB_OUT` | `0xC31E3268` | `0xC31E1668` | pointer table at `0xC31E1664 + logical*4`; bulk-arm body writes TRB+0 buffer (`[0xC3025744]-0x40000000`), +4 zero, +8 length, +12 control `0x813` (bulk-interrupt case `0x873` — same values on both firmwares); deref shape instruction-identical to fp | confirmed |
| `TRB_IN` | `0xC31E326C` | `0xC31E166C` | table + logical 2 | confirmed |
| `USB_STATE` | `0xC31E3748` | `0xC31E1B48` | 5 Thumb materialization sites each, all fp sites − 0x3780; writer bodies identical (state 2 after SET_CONFIGURATION; suspend 4 semantics camera-proven on fp) | confirmed |
| `OUT_BUSY` | `0xC31E3974` | `0xC31E1D74` | `0xC31E1610+0x764` (StartTransfer bulk-OUT busy store) == `0xC31E1664+0x710` (fallback-armer guard load) == the word; set-on-StartTransfer semantics identical | confirmed |
| `DALEPENA` | `0x2100C720` | `0x2100C720` (same MMIO) | 4 Thumb materialization sites each, all − 0x3780; enable path writes 3 (EP0), completion path caches it at drv+0x768 and republishes on mismatch | confirmed |
| `SHELL_CTX` | `0xC3756904` | `0xC3757744` | 15 ARM materialization sites each, every site + 0x218 (moves with the shell module) | confirmed |
| `usb_fallback_buffer_pointer` | `0xC3025744` | `0xC3025744` (same word) | armed by the XferNotReady fallback path when `OUT_BUSY` is clear — bodies identical | confirmed |
| CRC table | `0xC2E3B794` | `0xC2E4B40C` | both are the standard reflected-`0xEDB88320` zlib table, entry `v` at word `v` (the leaf indexes `table[v*4]`) | confirmed |

**Endpoint topology (fp L == fp):** the gadget descriptor template region is
**byte-identical** (fp `0xC0CF3740..` → fp L `0xC0D03A24..`, +0x102E4):
interface `{bNumEndpoints 03, class 06 PTP, subclass 01, protocol 01}`, and
endpoint descriptors for bulk OUT **0x01** (logical 1), bulk IN **0x82**
(logical 2), interrupt IN **0x83** (logical 3), each in SuperSpeed
(wMaxPacketSize 1024) and full-speed (64) variants. The driver's own mapping
`physical = (logical << 1) | (direction == IN)`, measured in the fp L
bulk-arm body at `0xC01E2440` (`lsls r0,r4,#1; orr r6,r0,r7` with
`r7 = physical & 1`) and in `StartTransfer` (`asrs r5,r0,#1` — logical =
physical>>1), gives bulk OUT physical **2**, bulk IN physical **5**. So
`EP_MASK 0x24` (physical 2|5) and `TRB_ARMED 0x813` are valid unchanged on
fp L.

### Dynamic execution (offline, real fp L instructions)

- **`crc32(buf, len)` at `0xC06AC4D8`**: executed under Unicorn against
  `zlib.crc32` — identical on all cases including empty, 1 byte, 100×`0xFF`,
  `"123456789"` (`0xcbf43926`), 4096 and ~16 KiB buffers. Init/final `~`,
  reflected `0xEDB88320` — the FPSH frame CRC and the UP01 data CRC will
  compute exactly what the host expects.
- **Shell trio** (`0xC03D9C28` init / `0xC03D9CD8` push / `0xC03D9D38` pop):
  executed on a synthetic context. `shell_init` installs `[ctx]=0xC000EE60`
  (vtable), `[ctx+4]=0xC0BD2398` (the shell command table the bootstrap
  audit reads), zeroes the sink stack at `+0x10`, seeds the count at `+0x24`
  to 1; push stores `[ctx]=sink` and `ctx+0x10+4*count`; pop decrements and
  restores. Exactly the ABI worker.S's `capture` sink relies on.

### patches.py consumers on fp L (for a later live shell)

| Patch | fp 5.02 site | fp L site | fp L stock word | Patch word |
|---|---|---|---|---|
| `IFACE` (interface → vendor class) | `0xC0CF3740` | `0xC0D03A24` | `0x01010603` (03/06/01/01) | `0xFFFFFF03` (03/ff/ff/ff) — same as fp |
| `BURST15` ×2 | `0xC0CF3748`, `0xC0CF3750` | `0xC0D03A2C`, `0xC0D03A34` | `0x00033006` each, raw-equal | `0x000F3006` each |
| `PUSH` ×6 | `0xC0CF3758/5C`, `0xC0CF3780/84`, `0xC0CF3798/9C` | `+0x102E4` each | raw-equal at every site | same words as fp |
| `NOPTP` mode-5 BL → `mov r0,#0` | `0xC0033B3C` (in `FUN_c0033ad0`) | `0xC003178C` (in fp L `0xC0031720` = fp − 0x2410) | `0xEB129893` (BL `0xC04D79E0`, the fp L PTP-receive counterpart of fp `0xC04DB778`) | `0xE3A00000` |
| `NOPTP` `beq` guard → `b` | `0xC01E7704` (in `FUN_c01e76b8`) | `0xC01E3F84` (in fp L `0xC01E3F38` = fp − 0x3780) | `0x4628D01E` (beq .+0x40 / mov r0,r5) — raw-equal | `0x4628E01E` (b .+0x40) — same encoding, the branch offset is unchanged |
| `RETAIN` self-refresh default | `0xC00239C8` (SelfRefreshSetting ctor `0xC0023948`) | `0xC00238E8` (ctor `0xC0023868`, − 0xE0) | `0xE3A00FE1` (`mov r0,#0x384` → `[obj+0x6C]`) — raw-equal | `0xE3A00B2A` (`mov r0,#0xA800`), absolute immediate, same encoding |

Both NOPTP sites sit in instruction-identical surroundings: the fp L
mode-dispatch (`0xC0031720`) keeps the same `mode==4 → BL`, `mode==5 → BL`,
`mode==8 → BL`, default `mov r0,#3` shape, and the fp L fallback armer keeps
the same `OUT_BUSY` guard, the same TRB writes and the same
`[0xC3025744]-0x40000000` buffer. `usbTask` is at fp L `0xC00317D0`, and its
single `BLX` wait-any-event call targets fp L `0xC01E5C00` (Thumb callee, fp
`0xC01E9380` − 0x3780) — the dispatch worker.S depends on to keep running
whether or not PTP answers.

### Explicit unknowns (not blockers, recorded honestly)

1. **No live MMIO emulation.** `StartTransfer`/`EndTransfer`/`Wait` are only
   shape-verified here; executing their DEPCMD/event internals would need a
   DWC3 controller model. Their fp 5.02 behaviour is camera-proven and every
   body is instruction-identical, but "shape-equal" is not "executed".
2. **The exact instruction that clears `OUT_BUSY` on completion was not
   pinned** on either firmware (the completion handlers `fp 0xC01E7780` /
   `fp L 0xC01E4000` are identical and the fp behaviour is camera-proven,
   but the clearing site itself was not reduced to one instruction).
3. **No live fp L enumeration was observed.** The descriptor templates,
   driver mapping and DALEPENA sites all say physical 2/5 carry the bulk
   pipes, but nothing here watched a host do it.
4. **`TASK_PRIO 28` / `TASK_STACK 0x2000` tolerance is fp-proven only.** The
   kernel bodies match; the fp L scheduler's tolerance of those values is
   assumed from body equality, not measured.
5. `usbTask`'s own body beyond its wait-loop head, and the fp L PTP-receive
   body beyond its first 0x50 bytes, were not fully audited — only located
   and shape-bounded.

### Conclusion

All 39 verdicts **confirmed**, zero wrong, zero unverifiable within the
stated method. The fp L driver module is a clean −0x3780 shift of fp's with
identical semantics, the shell/kernel stubs are raw-equal where it matters,
and every patches.py site exists with the same stock word and the same patch
word. **A worker.S fp L profile can be written from these constants now**;
what it still cannot claim is anything the camera has not done — the live
DWC3 behaviour and the fp L enumeration stay with the shell bring-up trial,
exactly as [FPL_PORT.md](FPL_PORT.md)'s next-integration plan already
sequences them.
