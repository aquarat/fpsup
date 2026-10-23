# fp L 3.02: temporary executable bootstrap audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-16. Independent **offline static audit**, not a placement approval or a
runtime implementation. Inputs: `SUP_BUILD_RULES.en.md`, `docs/FPL_PORT.md`, the
private `prerequisites/` inventory, and official fp L 3.02 MAIN. No camera
operations, card writes, commit or push were performed.

## Decision

**`[C03E2B98,C03E2F18)` is a well-supported 896-byte extent of the stock `dir`
handler. It is not established exclusive storage.** The preliminary size happens
to be correct, but the evidence is its complete local control-flow graph,
independently identified neighbouring entry and reference review, not a scan to
the first return.

The critical correction to the proposed borrowing argument is that **the stock
dispatcher has no whole-command mutex**. Normal AutoRun input is processed
synchronously by the shell task, but that is not a global lock over a sequence
of memory writes, cache calls and execution. The apparent guard on the shell
context is a one-time initialization guard; it does not serialize dispatch.

If a bootstrap can fit in **124 bytes**, `version` at
`[C03DF430,C03DF4AC)` is a smaller, statically cleaner candidate: one straight-line
body, no raw external direct-branch hits except wrong-mode short-Thumb patterns,
and exactly one literal pointer in the entire image. This reduces the overwrite
and restoration burden; **it does not resolve exclusivity, interrupted restore,
or executable-heap questions**. No candidate is certified safe by this audit.

The IMU image, including `[C072B8E4,C07304C0)`, remains owned by the IMU path and
is excluded from consideration.

## Reproduction and limits

`fp_usb_shell/audit_fpl_bootstrap.py` requires Python and Capstone 5. It accepts
only the exact MAIN length **49,310,208** and SHA-256:

`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`

```sh
python3 -B fp_usb_shell/audit_fpl_bootstrap.py \
  --main /path/to/firmware/FPL_V302/MAIN.bin \
  --out /path/to/new/private/audit-directory
```

It writes `audit.json` and `disassembly.txt`; output must be a new directory.
The run for this audit is in the session's private temporary directory,
`bootstrap-audit-v2/`. The durable evidence is this report and the reproducer;
the temporary output can be regenerated rather than relying on its retention.

The scanner covers:

- Every 4-byte-aligned ARM immediate B/BL/BLX encoding in the **whole image**.
- Every halfword-aligned Thumb B16, conditional B16, CBZ/CBNZ, B32,
  conditional B32, BL and BLX encoding, including overlapping interpretations.
- Every byte-aligned little-endian 32-bit literal in each candidate range,
  including odd Thumb-tagged values and interior pointers.
- ARM/Thumb MOVW/MOVT same-register pairs separated by at most 64 bytes.
- Entry-rooted ARM control flow for the specified bounded routines, with
  direct calls treated as returning and indirect calls explicitly retained.

**This is not whole-program pointer analysis.** It cannot exclude addresses
formed by arithmetic, widely separated MOV pairs, copied/relocated/generated
code, indirect calls through runtime objects, or accesses from firmware outside
MAIN. Raw branch-pattern hits are deliberately not called genuine xrefs.
MOV pairs are candidates without a proof of register liveness. The script does
not infer a live memory map or perform a hardware cache test.

Checks performed:

- Ten synthetic branch cases spanning the supported branch families and four
  literal alignments passed. Every one of the **498** real-image branch-pattern
  targets independently agreed with Capstone (mode-tag bits normalized).
- The bounded `dir` CFG reached 219 instructions, with no out-of-range local
  edge and no unresolved non-call PC write. The other five words are NOPs.
- A one-instruction mutation of the `dir` entry to branch to `mkdir` was caught
  by the out-of-range-edge oracle. The mutation existed only in host memory.
- No bootstrap execution, Unicorn payload test, MMU test or camera test was run.

## `dir`: extent, entry and callers

Addresses are hexadecimal and ranges are half-open, base `C0000000`.

| Item | Evidence |
|---|---|
| Entry | `C03E2B98`: saves r4–r8, r9, r11, LR; reserves `0x2E0` stack bytes |
| Previous routine | Returns at `C03E2B90`, followed by NOP `C03E2B94`; no fall-through |
| Shared exit | `C03E2F10` restores SP, `C03E2F14` pops the saved registers and PC |
| Next entry | `C03E2F18` is separately named `mkdir` in command-table entry 37 |
| Local control flow | Sixteen actual A32 local B/conditional-B instructions; every local edge stays in the range |
| Unreachable alignment words | `C03E2CDC`, `C03E2D2C`, `C03E2D4C`, `C03E2D94`, `C03E2E94`, all NOP |
| Literal pools / jump tables in body | None identified: no PC-relative loads, no indirect jump, no switch table |
| Exact body SHA-256 | `cad25d06b209e9d29514cfdd4d67e72398cf2efc660450a2678a8c6f86bd80df` |

The command table is `[C0BD2398,C0BD2AE8)`: 77 commands and a null terminator,
stride `0x18`, name width `0x14`. `dir` is entry 14; its handler slot is
**`C0BD24FC = C03E2B98`**. The table accessor is `C03DB7B8`.
The lookup at `C03D9DE0` compares names and advances by `0x18` until a null
handler. The dispatcher loads the selected handler at `C03D9F08` and calls it
with `BLX r3` at `C03D9F18`.

There are **no raw direct branches/calls to the exact `dir` entry** and no
MOVW/MOVT pair into its body in the bounded-pair scan. The one exact entry
literal is the table slot above. This supports a shell-private handler;
it is not proof that every runtime reference passes through that slot.

### All non-local long-branch/direct-call candidates into the body

These are the whole-image scan's complete external A32 branch and T32 long-call
hits. They must not be silently omitted from a claim of “zero callers.”

| Source | Raw interpretation / target | Context assessment |
|---|---|---|
| `C0124298` | ARM BLX → Thumb `C03E2E6A` | **Confirmed wrong instruction set/boundary**: actual Thumb `UDIV` starts at `C0124296`; `MUL` follows at `C012429A` |
| `C06D66DE` | Thumb BL → `C03E2D0E` | **Confirmed second-halfword decode**: real Thumb `SMULBB` starts at `C06D66DC`, next at `C06D66E0` |
| `C0B5C164` | ARM BNE → `C03E2CE4` | Monotone 16-bit numeric table (`1ACA,1ACD,…,1ADE,1AE2,…`), not an established code stream |
| `C0FE2208` | ARM BNE → `C03E2E28` | Resource/data-like surrounding bytes; no established executable function |
| `C0FEC1E0` | ARM BNE → `C03E2DD8` | Resource/data-like surrounding bytes; no established executable function |
| `C10373BC` | ARM BHS → `C03E2EB0` | Resource/data-like surrounding bytes; no established executable function |
| `C111A5E4` | ARM BLLO → `C03E2DEC` | Encoded data-like stream with repeating byte records; no established code |
| `C15174D0` | ARM BLLT → `C03E2D28` | Data-like records, no established code |
| `C1204EF8` | Thumb BLX → ARM `C03E2EA4` | Data-like records, no established code |

The latter data assessments are contextual exclusions from the **verified
caller list**, not proofs of the lifetime/type of every resource in MAIN.
In particular they do not license a claim of mathematically exhaustive
call-graph isolation.

Another **171 external short Thumb branch patterns** occur in the surrounding
A32 shell routines (170 unconditional, one conditional). Their source range is
`C03E2446..C03E33E2`. They are alternate decodes of the A32 neighbourhood, not
identified Thumb entry paths. `audit.json` preserves every source/target;
the surrounding A32 listing is emitted for review. Including internal
wrong-mode patterns gives **204 total branch candidates** for `dir`: 20 ARM B,
2 ARM BL, 1 ARM BLX, 177 Thumb B16, 2 Thumb conditional B16, 1 Thumb BL,
1 Thumb BLX. Only the 16 local ARM branches are confirmed `dir` control flow.

### All literal-pointer candidates into the body

Only the first row is a confirmed executable pointer. The others are interior
numeric coincidences in resource/data-like streams; their *consumers* were not
traced. The unaligned scan is intentionally conservative.

| Literal storage | Raw value |
|---|---|
| `C0BD24FC` | `C03E2B98` — `dir` command slot |
| `C1101A84` | `C03E2F03` |
| `C1179D84` | `C03E2C1B` |
| `C186B360` | `C03E2C00` — byte sequence is in a monotone **big-endian** offset-like table (`002C3E28,002C3E90,002C3EC0,002C3EDC,…`) |
| `C1097B45` | `C03E2F08` |
| `C10BDAA1` | `C03E2DA9` |
| `C10F7909` | `C03E2E38` |
| `C1137375` | `C03E2E48` |
| `C113737D` | `C03E2E39` |
| `C115D131` | `C03E2C41` |
| `C11BE2A5` | `C03E2E55` |
| `C2E6AFBD` | `C03E2C3E` — byte sequence is in a repeated 16-bit sequence with marker bytes |
| `C10B017E` | `C03E2D84` |
| `C11B2372` | `C03E2D04` |
| `C1100037` | `C03E2D45` |
| `C115B2BB` | `C03E2C61` |
| `C116890B` | `C03E2E6A` |
| `C11BC76B` | `C03E2D45` |

### Outgoing calls and return obligations

The CFG has **20 direct ARM calls** and **11 indirect calls**. There are no
direct Thumb callees in this handler. Complete callsite lists are generated.
Distinct direct targets:

`C0013E2C`, `C0408038`, `C0366CB0`, `C0366B30`, `C0366BA8`,
`C0366B58`, `C0015058`, `C03E2978`, `C0013F90`, `C03E2770`,
`C03E29C8`, `C0366C10`.

Ten indirect calls are output through `[shell_context]`; the call at
`C03E2C20` is through the object returned by `C0366CB0`, loading its table at
`object+0x18`, slot `+0x1C`. These are not calls back into `dir` established by
this audit. Do not overwrite shared directory/file functions or the preceding
date/name-formatting helpers merely because the `dir` command is idle.

## Dispatcher, task and “mutex” semantics

1. `C03D9E38..C03D9F2C` tokenizes a supplied command, looks up the global
   command table and calls the selected pointer. It contains **no mutex acquire,
   release, interrupt mask or busy check**. Handler arguments are r0=context,
   r1=argument count excluding command name, r2=pointer to argument pointers.
   At `C03D9F1C` it overwrites the handler's r0 with zero before returning:
   **the dispatcher does not propagate a failure code or stop AutoRun**.
2. `C03D9F30..C03D9FCC` is one input/dispatch iteration. It constructs the
   shared context `C3757744` once, obtains an input line (including AutoRun),
   dispatches synchronously at `C03D9F98` or `C03D9FBC`, then updates input
   registration at `C0420E58`. No lock surrounds those calls.
3. The guard address `C3757778` is passed to `C0013090`; if initialization is
   needed, `C03D9C28` runs and `C00131E4` marks completion. Both calls precede
   the input and dispatch paths. It is an initialization guard, **not ownership
   of the shell while the handler executes**. Additionally the C-library lock
   hooks `C001532C`/`C0015330` are just `BX LR` in this image.
4. Task setup `C03DA390` creates the named `shell` task, entry `C03DA330`,
   priority `0x19`, stack `0x4000`, then starts it. Its entry loops through
   `C03D9F30`. This gives normal command-to-command serialization *within that
   task*. A second exceptional shell loop exists at `C03DA080`, reached by
   diagnostic/fault paths. Normal scheduling exclusivity during a probe was
   not established.
5. There are three other confirmed direct calls to the dispatcher:
   `C03E6898` and `C03E68CC` in the command-sequence routine beginning
   `C03E6808`, and `C0405A98` in the wrapper `C0405A68`. The former reads command
   string pointers from runtime globals near `C2F303DC`; the latter formats a
   string using `%s`. These permit nested dispatch. The known callsites do
   not by themselves prove concurrent invocation, but rule out pretending the
   dispatcher can only ever be reached from the top-level input loop.
6. AutoRun startup `C03DA970` opens/registers a character source via
   `C03DA728`; callback `C03DA9C0` obtains characters via `C03DA818`.
   The registration functions `C0420EE0`, `C0420FA8`, `C0420E58` manipulate the
   global source stack. They are not a transaction lock across AutoRun lines.

Thus “no `dir` command occurs in our script” is useful but insufficient for
exclusive borrowing. A proposed protocol must account for other command sources,
the exceptional loop, nested dispatch, in-flight handler PCs/return addresses,
and power-off while partially patched. A lock used only by the new probe cannot
serialize stock callers that do not acquire it.

## Cache publication through the unmodified `echo` slot

`echo` entry 17 has slot **`C0BD2544`**, stock pointer **`C03D9BB8`**.
The dispatcher reads that slot as data and calls it with BLX; its return value
is ignored. Both cache routines are ARM, parameter-independent and return with
`BX LR`, so their calling shape is compatible with dispatch:

| Routine | Exact examined extent | Semantics visible in instructions |
|---|---|---|
| D-cache | `[C000E91C,C000E9B8)` | Saves/restores r4–r7, preserves LR; saves IRQ/FIQ mask, masks both, walks cache set/way operations (`c7,c14,2`) for selectors 0 and 2, restores selector 0, DSB/ISB, restores prior interrupt mask |
| I-cache | `[C000EABC,C000EAD0)` | r0=0; `MCR p15,0,r0,c7,c5,0`; DSB; ISB; return |

For an already written and verified bootstrap, the required logical ordering is
**slot → D routine, dispatch echo, slot → I routine, dispatch echo, slot →
bootstrap, dispatch echo**. The slot stores themselves change data, not executable
instructions. There is no need to execute an unflushed bootstrap to publish it.
The same D-then-I order is required after restoring original executable bytes.
This is a static calling-convention argument, **not evidence that any such
sequence has run on fp L**. Multicore/alias behavior has not been proven here.

Each pointer transition must be verified. The slot remains globally callable
while redirected. Pointing `dir`'s own slot at a harmless nonzero routine could
reduce ordinary lookup exposure but adds another restoration obligation and
does not retire pointers already fetched by another caller. Setting its slot
to zero is particularly inappropriate: lookup treats a null handler as the end
of the entire command table, hiding later commands including `mem` and `echo`.

The stock `mem set` body at `C03FA228` performs a store at `C03FA290`, then
readback/printing; it has no instruction-cache publication. Its success text is
not an AutoRun conditional gate. An output file showing wrong bytes after
execution cannot retroactively make executing those bytes safe.

## Restoration requirements

There is no loader/stage2 journal automatically protecting a standalone
stock-command AutoRun experiment. This audit finds no stock mechanism that
restores overwritten command code or the echo pointer on failure or switch-off.
The existing fp warm-restart contract also makes “power off to fix it” an
invalid general recovery assumption for modified image RAM.

A candidate must establish all of the following before any live trial:

- **Ownership interval:** exclusivity before the first overwritten byte, through
  cache publication and execution, until restored bytes are republished. The
  ordinary `dir` table entry remains a route into the body even if `echo` is
  the intended entry. Known absence of commands and a verified single-task
  boot phase may support a deliberately restricted experiment, but neither
  has been demonstrated here.
- **Exact preimage and bounds:** compare the live target and slots with expected
  stock values; retain originals in storage owned by the probe. Never store
  backup bytes in IMU zeros or another assumed-free fixed address. A stale
  patch from a previous run is not a new valid original.
- **Code/data separation:** include literals, parameters, saved originals and
  alignment in the overwritten range, not only executable instruction count.
  Do not cross `C03E2F18` or place a result block in surrounding code/data.
- **Verified publication:** prove all words are present before first execution;
  D clean then I invalidate, before handoff to owned RAM and after restoration.
- **Return topology:** once running in owned RAM, no live PC, return address,
  literal load or continuation may refer to the borrowed bytes being restored.
  Conversely, never free owned code while executing it or leave a return into
  that freed allocation. The original dispatcher continuation is `C03D9F1C`.
- **Early failures:** allocation failure occurs before there is owned executable
  RAM. Restoring the entire borrowed body with a stock copy routine that returns
  into that same body is not a valid general recovery path. Define a valid
  continuation or a proven subsequent stock-command restore; cover file-open,
  short-read, allocation-address and verification failures separately.
- **Interruptions:** ordinary cleanup and a later AutoRun restore do not cover
  reset, lost input, task abort or power-off between commands. Either supply
  an evidenced restoration/recovery mechanism or explicitly restrict the
  experiment and retain this as an unresolved risk. This is not equivalent
  to the shared loader's declared-site power-off journal.
- **Independent completion evidence:** report actual owned-RAM execution,
  restoration of every modified slot/range and allocation cleanup, then save
  independent restored-byte snapshots. A dispatcher return of zero or an
  AutoRun end marker proves none of those individually.

## Alternatives reviewed

| Candidate | Bounded size | Reference/shape observations | Assessment |
|---|---:|---|---|
| `version` `C03DF430` | 124 executable bytes; next entry `C03DF4B0` after one NOP | Slot `C0BD2A84`; single literal, no long direct-branch candidates; 31 straight-line instructions, four service and four output calls | Best smaller static candidate if the complete bootstrap fits. Still needs lifetime/exclusivity proof. Do not claim the padding as additional capacity without explicitly including it. |
| `mkdir` `C03E2F18` | 100 bytes to `C03E2F7C` | Slot `C0BD2724`; only wrong-mode short-Thumb branch hits, plus two data-like interior literals | Smaller than `dir`, but less capacity and no better concurrency guarantee |
| `help` `C03E97B0` | 144 bytes | Slot `C0BD2604`; one literal, two additional long-branch data-pattern hits; walks command names | Plausible small alternative; ordinary diagnostics could call it, so no stronger lifetime claim |
| `echo` `C03D9BB8` | 76 bytes | Slot `C0BD2544`; one extra data-like interior literal | Tiny and the command also used for publication/launch; no clear advantage |
| `#` `C03D9C08` | 28 bytes | Slot `C0BD2ACC`; currently a no-op handler | Too small for an ordinary allocating bootstrap; comments in AutoRun can reach it |

**Confidence:** high in `dir`'s local extent, the table/dispatch ABI, absence of
a dispatcher-wide mutex, and cache routines' parameter-independent calling
shape. Moderate in shell-private entry isolation after excluding wrong-mode
and resource-pattern candidates. **Unproved:** exhaustive computed references,
runtime exclusivity, protection against interrupted restoration, live code
writability, allocator executable mappings and allocation lifetime. Those gaps
prevent an unconditional “safe temporary executable location” conclusion.
