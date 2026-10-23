# fp L 3.02: USB worker fixed-word (rendezvous) audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-16. Independent **offline static audit** of where the fp L USB-shell
worker's fixed words — the publication triplet, the 16-word STATE block and
the CAP_LEN / SWAP_MAGIC / SWAP_ADDR / CAP_PTR words — may live, given that
fp L has no cave ([FPL_PORT.md](FPL_PORT.md) "no-cave design"). Inputs:
`SUP_BUILD_RULES.en.md`, [FPL_PORT.md](FPL_PORT.md),
[FPL_BOOTSTRAP_AUDIT.md](FPL_BOOTSTRAP_AUDIT.md), `fp_usb_shell/camera/worker.S`,
`fp_usb_shell/firmware/worker_fpl_302.h` (the staged design under audit), the
private fp-vs-fp L research archive, both official MAIN images, and the
2026-10-16 live bring-up captures (pool word zero at boot; class-channel table
populated; shell context live). **No camera operations, card writes, commits
or pushes were performed.** Nothing here approves a live trial.

## Decision, in one paragraph

**The staged design in `worker_fpl_302.h` — publication triplet
{pool, size, code-ptr} at `0xC37588BC+0/+4/+8` and everything else
pool-relative (STATE at `pool+0x1000`, the four trailing words at
`pool+0x1040..+0x1050`) — is the right layout, with one accepted, documented
risk and two design couplings to carry into the worker port.** The word at
`0xC37588BC` is the stock **shell `memmgr bufmem` pool descriptor**: the exact
fp counterpart of `0xC3757A7C`, which fp's whole load chain already shares
with stock the same way. The words *following* it are **not** free: `+0x0C` to
`+0x44` are live stock globals of the shell `log` / LogFile subsystem and a
lazily allocated pathname buffer, so option (a) "spread the fixed words after
the publication word" is dead on evidence. The only stock writer of
`0xC37588BC` is the synchronous `memmgr bufmem` shell-command path — no
interrupt, PTP or background writer exists statically — and host tooling
already has a hard rule never to issue `memmgr` commands live (issuing
`memmgr bufmem get` live wedged the endpoint and froze an fp camera once;
`fp_usb_shell/putfile.py`). The residual risk is a human or foreign script
typing `shl memmgr bufmem …` while the worker is resident, which would
overwrite or *free* the worker's published pool; that is the same class of
exposure fp's card pool at `0xC3757A7C` carries today, except that on fp L it
is the worker's own rendezvous, so it must be written down and watched, not
just inherited.

## Reproduction

`tools/fpl_worker_state_audit.py` (new in this audit) accepts only the exact
official images — fp L 3.02 MAIN (49,310,208 bytes, SHA-256
`fb8c2096…06d4b9`) and fp 5.02 MAIN (49,245,696 bytes, SHA-256
`aaa5208a…0e622`) — and refuses anything else. It scans, in **both** images,
every word of the pool neighbourhood (`+0x00..+0x40`), the shell-context
words and their `+4`, with the same families as
[audit_fpl_bootstrap.py](../fp_usb_shell/audit_fpl_bootstrap.py): aligned ARM
and halfword-aligned Thumb MOVW/MOVT pairs (same register, ≤64 bytes, every
overlapping pairing), MOVTs with a matching high half but no partner
(none found in either image), and 32-bit literals at all four byte
alignments. Each hit is attributed to a hand-established routine range and the
bounded routine listings are emitted; unattributed hits are printed with
context windows, never dropped. A synthetic self-check exercises every scanner
family (and caught a bug in this audit's own first fixture, which is why it
runs before anything else). It emits JSON only; no camera interface.

```sh
python3 -B tools/fpl_worker_state_audit.py \
  --fpl …/FPL_V302/MAIN.bin --fp …/FP__V502/MAIN.bin \
  --out <new private output directory>
```

The run behind this report lives in the session's private temporary directory
(`worker-state-audit/`, regenerable); the durable evidence is this document,
the script and the emitted `disassembly.txt` analysis quoted below.

## 1. What `0xC37588BC` is

**It is word 0 of the shell `memmgr bufmem` descriptor: {+0 address, +4 size,
+8 type}.** The evidence, instruction by instruction (all addresses
hexadecimal, base `C0000000`; listings in the audit output):

- The **only** materialization of `0xC37588BC` in the whole fp L image is the
  ARM MOVW/MOVT pair at `C03FA610/C03FA618` (`movw r5,#0x88BC` /
  `movt r5,#0xC375`), inside the routine `[C03FA600,C03FA868)` — the
  `memmgr bufmem` shell-command body. No literal at any alignment anywhere in
  the image names it; no Thumb pair, no unpaired MOVT with a `0xC375` high
  half exists.
- That body is the **instruction-for-instruction counterpart** of the fp 5.02
  body `[C03FA3E8,C03FA650)` (relocation `+0x218`, the shell-code delta from
  the portability research), which materializes `0xC3757A7C` at
  `C03FA3F8/C03FA400`. The independent portability scan records exactly this
  correspondence (`shell-relocations.json`: `site_fp C03FA3F8 ↔ site_fpL
  C03FA610`, `fp_value C3757A7C ↔ fpL_value C37588BC`).
- What the body does with r5 (the descriptor):
  - **`get`**: parses class and size, resolves the channel through
    `C001CF78`, then calls `C001CFD8` with **r1 = 0xC37588BC** (fp L
    `C03FA7B8`; fp `C03FA5A0` with r1 = `C3757A7C`), which writes the
    descriptor; it then prints the triplet with `ldm r5,{r2,r3,r8}`
    (`C03FA7C0`), format `"get type::%d , 0x%08x , %dByte"` (`C0BE0744`) —
    hence {+0 address, +4 size, +8 type}.
  - **`rel`**: prints the same triplet, calls `C001D3D0` with the descriptor,
    then **stores 0 to word +0** (`C03FA7F8..C03FA804`; fp `C03FA5E0..C03FA5EC`).
- Live cross-check: the 2026-10-16 bring-up captured the 16 bytes at
  `0xC37588BC` **all zero** at boot + AutoRun time (POOL.BIN) — exactly what
  this analysis predicts when no `memmgr bufmem get` line has run, and
  consistent with `FPL_PORT.md`'s "no allocation requested". The word sits in
  the firmware's BSS (`C3000000..C38D6FB0`), the one range the boot code
  clears (BUILDING.md's memory map) — so every boot starts it at zero, warm
  restart included.

So it is a **publication word stock itself writes and reads**, not a
descriptor of anything else — precisely the role the ported stage2
(`FW_FRAMEBUF`) and the staged worker profile (`FW_WFRAMEBUF`) already give
it. **Does fp stock ever write `0xC3757A7C` at runtime? Yes, identically**:
through the same `memmgr bufmem get/rel` body, and historically through the
AutoRun's own `memmgr bufmem get` line — which the fp loader stopped spelling
when it began asking the allocator itself (`loader.S`: "0xC3757A7C is NOT
written here any more… what it holds now is whatever the payload's entry
published"). fp L inherits the same situation with no AutoRun ever needing to
spell `memmgr`.

## 2. The neighbourhood map (fp ↔ fp L fixed-RAM shell globals)

| fp 5.02 | fp L 3.02 | purpose | who writes it |
|---|---|---|---|
| `C3756904` | `C3757744` | shell context singleton pointer (worker's `SHELL_CTX` / `FW_WSHELL_CTX`) | constructed once by shell one-time init (`C03D9A10` / `C03D9C28`); **15 materialization sites in each image, in the same four 64 KiB pages** (shell iteration/task, AutoRun setup, input registration) — a perfect 1:1 correspondence, and the bring-up captured the fp L word live |
| `C3757A7C` +0/+4/+8 | `C37588BC` +0/+4/+8 | `memmgr bufmem` descriptor {address, size, type} = the pool publication triplet | stock: the `memmgr bufmem` body (§1); ours: stage2's pass-2 pool and (staged) the worker's own pool |
| `C3757A88` | `C37588C8`/`CC` | fp: init guard for the object at `+0x14`; fp L: **address/length pair of a lazily allocated 0x100-byte pathname buffer** (allocator `C0406EC8`, class 0; builder `C04071A8`, length written base-relative at `C0407228`) | stock path subsystem, on first use |
| `C3757A90` (0x470 bytes) | `C37588D0` (+0x14, ≥5 words) | fp: a lazily-initialised 0x470-byte object (init `C06ADE18`, users `C0404F88`, `C068F928`); fp L: **shell `log` output-state struct** — the handlers of `log-on/log-uart/log-sim/log-off/log-out/log-file` (subcommand table at `C0BE7A88`, stride 0xC) mutate `strb [base]`, `[base+4/+8/+0xC]` (`C04075FC..C04076AC`), then `C06AE118` mirrors five words of it to the fixed global `C38D007C` | stock `log` subcommands |
| — | `C37588E0` (+0x24) | fp L only: **`log` LogFile config struct** — `setfilename` strncpy's the log file name (≤0x13) into it (`C0407980..C0407988`); `addtimeset` keeps its seconds counter at +0x38 (`C37588F4`), written base-relative `C0407824/C040784C/C0407860` and cleared by the command at `C0407928` | stock `log` subcommands |
| — | `C37588F8`/`FC` (+0x3C/+0x40), guard at `C3758900` (+0x44) | fp L only: once-initialised pointer pair `{C0BE7DF0, 0}` for the LogFile family (guard `C0013090`, copy at `C0407A64`) | stock, on first use |
| `C072F000..C072F058` (cave) | **no counterpart** (IMU-owned image space) | the fp worker's STATE (16 words), CAP_LEN/SWAP_MAGIC/SWAP_ADDR/CAP_PTR, publication triplet | ours only, by design |

Two structural observations worth keeping: both firmware images keep the
shell-context singleton exactly **`+0x1178` below** the pool word
(`C3757A7C − C3756904 = C37588BC − C3757744 = 0x1178`), and the whole
shell-globals block moved by the same delta `+0xE40` between the firmwares.
The globals are one relocated block — a good sanity check for any future
profile edit.

**The words after the publication triplet are dense, live stock state on both
firmwares.** On fp L, every word from `+0x0C` to `+0x44` is owned: materialized
references where shown above, plus base-relative (`[r,#imm]`) accesses that
own their neighbours without naming them (`+0x10` length, `+0x18/+0x1C/+0x20`
log-state fields, `+0x38` counter). On fp, `+0x0C/+0x14` are owned and the
object at `+0x14` is 0x470 bytes, so the fp window is at least as occupied.

## 3. Are the 16 bytes at `0xC37588BC` safe for the worker triplet?

**Safe from everyone except the stock `memmgr bufmem` command path — and that
path is synchronous shell-command execution, nothing else.**

- **No interrupt, DMA, PTP or background-task writer exists statically.** The
  single materialization is the memmgr body; its descriptor words are
  touched only through r5 there and through the pointers it passes to
  `C001CFD8`/`C001D3D0`. Shell output, the shell capture sink, PTP and the
  allocator itself have no static reference to the word.
- **Who can run `memmgr bufmem` while the worker is resident?** Any shell
  line: the AutoRun file (loader cards spell none), the UART console, a host
  `shl memmgr bufmem …` through our own worker, the nested-dispatch sites
  (`C03E6808`, `C0405A68`) and the exceptional shell loop catalogued in
  FPL_BOOTSTRAP_AUDIT.md. Ordinary lines serialize in the shell task; these
  surfaces are why "nobody else sends memmgr" is a discipline, not a lock.
- **The hazard is two-directional, and the worse direction is ours:**
  1. A `memmgr bufmem get` overwrites the triplet → the worker's next round
     reads a foreign pool as its own (capture writes, TRB buffers, window
     table all rebased onto a wrong allocation).
  2. A `memmgr bufmem rel` calls **stock's free on our published pool**
     (`C001D3D0` with the descriptor = our {address, size, code-ptr} read as
     {address, size, type}) → heap corruption under a running worker.
- **Existing mitigation, inherited from fp:** host tools already refuse to
  issue memmgr commands live, with a recorded reason — `putfile.py`: "`bufmem
  get` … issued live through the shell it wedged the endpoint and froze the
  camera". The daemon's `shl` command surface must keep that rule on fp L,
  and the doc that ships with the fp L shell should say so explicitly.
- **Boot discipline:** the word is BSS and cleared every boot, so a stale
  publication cannot survive a power cycle or warm restart; there is no
  "previous card left a pool here" state to defend against (the fp cave words
  do survive a warm restart and must be treated as possibly stale — the fp L
  design is *cleaner* here).

## 4. Recommended layout

**Adopt the staged `worker_fpl_302.h` layout (option b), with the notes
below. Confidence: high on the placement itself; moderate on the exclusivity
discipline; the couplings are design requirements, not risks.**

| Fixed words | fp 5.02 | fp L 3.02 (recommended) |
|---|---|---|
| Publication triplet {pool, size, code} | cave `C072F050/54/58` | **`0xC37588BC +0/+4/+8`** — the stock bufmem descriptor's own three words, same shape {address, size, third-word} |
| STATE (16 words) | cave `C072F000` | **`pool+0x1000`** (`FW_WSTATE_OFF`), in the worker-owned gap between the frame buffer (`+0x0`, 4 KiB) and the capture buffer (`+0x2000`) |
| CAP_LEN / SWAP_MAGIC / SWAP_ADDR / CAP_PTR | cave `C072F040..4C` | **`pool+0x1040/44/48/4C`** (`FW_WCAP_LEN_OFF`…), the same `+0x40`-within-block shape fp uses |

Why this and not the alternatives:

- **Option (a) — fixed words after `0xC37588BC` — rejected on evidence.**
  Every word `+0x0C..+0x44` is live stock state (§2): the path buffer pair,
  the `log` output struct, the LogFile config (name at `+0x24`, counter at
  `+0x38`), the once-initialised pointer pair at `+0x3C`. Writing there would
  corrupt the `log` subsystem and the path builder; reading "zero at boot"
  (the LogFile fields are zero until a `log` command runs) would have been a
  false "free".
- **Option (c) — a different fixed word somewhere else — none exists on
  evidence.** The audited window is fully accounted for; beyond it we have no
  BSS symbol map, and the build contract's rule stands: "it reads zero" does
  not make an address free. The bufmem triplet is the one place where sharing
  with stock is *precedented on both firmwares* — fp's entire load chain
  already publishes through the fp counterpart.
- **Why pool-relative for the rest is correct:** the words must not live in
  the worker's **code** allocation (a live swap rewrites it — the reason the
  fp words are in the cave, per `worker.S`), but the **pool** allocation is
  never swapped and is allocator-owned, which is a stronger ownership
  guarantee than any cave ever had. `+0x1000..+0x1050` collides with nothing
  in the worker's own map (frames `+0x0`, capture `+0x2000`, faults
  `+0x6800`, upload tuple `+0x6900`, windows `+0x6A00`, fault log
  `+0x6C00`, staging `+0x10000`).

Design notes the port must carry (not new risks; consequences of the
placement):

1. **Double-spawn protection** (the AutoRun provably runs twice per boot on
   this camera, both trials): the check is **`[0xC37588BC] != 0` ⇒ already
   spawned**, as `worker_fpl_302.h` says. Two properties to preserve from the
   fp semantics: publish *after* a successful allocation so a refused pool
   leaves the word zero and the second AutoRun run retries (this is actually
   better than fp, whose STATE magic is set before allocating); and rely on
   the two AutoRun executions being **sequential in one shell task** (they
   were, in both trials) — the check-and-publish is not atomic against a
   concurrent spawner, and the bootstrap audit found no whole-command mutex.
2. **The publication word is shared with stage2's pass 2.** On an fp L worker
   card, pass-2 pool-offset sections are placed relative to the **same word**
   the worker publishes (FPL_PORT.md's stage2 test relies on this). Either
   worker cards carry no pass-2 sections, or the card layout must keep them
   clear of the worker's internal pool offsets (`+0x0..+0x10000` as used).
   State the choice in the port, don't discover it in a collision.
3. **Host discovery and the swap protocol.** The daemon's first contact needs
   no fixed address (the worker answers on the USB bulk pipes, whose TRB
   words are fixed firmware globals); the host then reads the 12 bytes at
   `0xC37588BC` via `shl mem get` and derives every other word pool-relative
   — one extra round compared with fp's fixed cave addresses, and the fpL
   equivalent of `cave.py`'s ABI map should be written that way. For
    **Historical proposal, superseded:** this audit originally proposed
    `SWAP_ADDR/SWAP_MAGIC` at `pool+0x1048/0x1044`. The current reviewed
    `firmware/worker_fpl_302.h` instead uses `SWAP_ADDR=pool+0x10C0` and
    `SWAP_MAGIC=pool+0x1080`, with capture pointer at `pool+0x1100`.
    Use the current header and `fpl_swapworker.py`, not those historical offsets.
    The write-address-then-magic sequence works in principle (the worker clears the magic before
   branching, so a half-written pair cannot fire twice), but note two fp
   differences: the host must read the pool first, and **the fp swap's jump
   target is the resident loader at the fixed cave address `C072DE64` — fp L
   has no resident loader**, so the fp L swap target (new code allocation?
    loader staged by the host inside the pool?) was outside this original
    audit's scope. The later two-body equal-size handoff is live-verified;
    separately allocated forward/reverse prototypes remain offline. See
    `FPL_ALLOCATED_HANDOFF.md` and `FPL_TOOLS.md` for their limits.
4. **A stock `memmgr bufmem get` after our publication makes the report
   path print our {pool, size, code} as `{address, size, type}`** — cosmetic;
   the *rel* path is the destructive one (§3).

## 5. What static analysis cannot prove here

Honest limits, inherited from the bootstrap audit's methodology and specific
to this question:

- **Computed and copied references.** Anything that reaches
  `0xC37588BC` (or any pool word) through register arithmetic, a pointer
  copied from another location, a relocated/generated code block, or a MOV
  pair farther than 64 bytes apart or split across registers, is invisible to
  the scan. The log-state mirror at `C38D007C` (five words copied *out* by
  `C06AE118`) is a worked example of a second fixed address holding a copy
  of neighbourhood data; only the copy-out direction is visible.
- **No interrupt-driven writer can be excluded** — only that none is
  *statically evident*. Same for a writer with a table-driven computed
  address.
- **Runtime behaviour**: whether the path buffer is ever allocated, the
  `log` commands ever run, or the exceptional shell loop can ever dispatch a
  `memmgr` line concurrently with a worker round, is not decidable offline.
- **The two AutoRun executions being sequential** is an observation from two
  live trials, not a proof for all boots.

## 6. What a live trial should verify first

In this order, each before the next, all read-only over `shl mem save/get`:

1. **Publication and state**: boot the worker card; read the 12 bytes at
   `0xC37588BC` = {pool, size, code} with size = the requested 1 MiB and the
   code pointer inside the second allocation; read 16 words at `pool+0x1000`
   (STATE magic/task id/rounds sane).
2. **Double-spawn**: confirm exactly one worker task after the observed
   double AutoRun run (STATE `+0x04` task id; rounds advancing once), i.e.
   the nonzero-pool-word check held across the second execution.
3. **The stock neighbourhood stays intact**: dump `0xC37588C0..0xC3758900`
   before and after worker start and after a few hundred served rounds; the
   words should either stay stock-zero or change only in ways traceable to
   commands actually run. Any change at `+0x0C..+0x44` caused by the worker
   itself is a placement bug — stop.
4. **Long-idle stability of the publication word**: read `0xC37588BC`
   periodically during a long serve; it must never change unless a `memmgr`
   line was deliberately sent. Then send one deliberate `shl memmgr bufmem
   rel` in a throw-down boot *with the understanding that it may corrupt the
   heap*, only if the owner accepts that, to confirm the §3 hazard direction
   — or skip it and keep the discipline.
5. **Swap dry-run**: write `SWAP_ADDR`/`SWAP_MAGIC` pool-relative with the
   target being the *same* worker image, confirm the protocol round-trips
   (magic cleared, worker re-entered cleanly) before any real swap design is
   built on it.

## Conclusion for the port

The staged `worker_fpl_302.h` rendezvous is structurally sound and rests on
the same sharing fp has proven for a year; the audit's contribution is the
evidence that (i) the three words it takes are exactly the stock bufmem
triplet and nothing else in the window is takable, (ii) the only stock
writer is the `memmgr bufmem` shell path, whose live use is already forbidden
practice in host tooling, and (iii) the pool-relative STATE/swap words are
the strongest-ownership home available on a no-cave camera. The residual
exposure — a stray `memmgr bufmem` line while the worker is resident — must
be carried as a documented discipline of the fp L shell, checked in the live
trial (§6.4), and never dismissed as impossible, because nested dispatch and
the exceptional shell loop can spell shell lines from places other than the
AutoRun file.
