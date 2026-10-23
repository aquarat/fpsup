# fp L owned-RAM execution experiment

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

This is the next experiment after the [stock AutoRun capture](FPL_PORT.md).
It has two distinct questions:

1. Can a small routine allocate USER RAM, publish instructions there, execute
   them, return, and release that allocation?
2. How can we safely enter that routine on a stock camera and restore the
   temporary bootstrap bytes?

`fp_usb_shell/asm/heap_probe.S` implements the first question. It is a finite
diagnostic, not another sup loader: there is no file loader, VBIN parser,
stage2, resident task, callback, settings write or USB code. Future product
loading continues through the shared loader/stage2.

## Body and ownership

The body is position-independent apart from the firmware service addresses
selected through the existing `firmware/loader.h`. `fpl_heap_probe.py` selects
fp L 3.02 explicitly and checks the official MAIN fingerprint before building.

- The caller must provide owned executable storage for the complete initial
  body, including its writable 64-byte result area, and publish D/I first.
- The allocation descriptor is 16 bytes on the saved/aligned stack. The routine
  preserves callee-saved registers and restores the exact incoming SP, including
  callers whose SP is four bytes off eight-byte alignment.
- It requests **4096 bytes of USER memory (class 0)**, never the RAW frame pool.
- A null allocator address returns a failure record. A non-word-aligned address
  is not written/executed and is handed back through the free call.
- It copies a 40-byte leaf into the allocation, calls the selected D-cache
  routine followed by I-cache invalidation, then calls the leaf.
- The leaf records its actual execution address and SP, writes a marker, and
  returns a second marker. It makes no firmware calls and keeps no pointers.
- The caller frees the allocation only after the leaf returns. Results stay
  with the initial body, not in the released heap. The routine returns their
  address in r0; a shell dispatcher is free to ignore that return value.

This body does not restore its own storage while executing from it. A future
bootstrap must collect the result and restore the initial storage and any
borrowed handler, then independently read them back. Allocation failure must
still reach that cleanup. A successful result file alone is not restoration
evidence.

## Build and inspect (offline)

Requires Python, clang with the ARM integrated assembler, and the private
official fp L 3.02 MAIN image. Tests additionally require Unicorn.

```sh
python3 -B fp_usb_shell/fpl_heap_probe.py build \
  --main /path/to/FPL_V302/MAIN.bin --out /path/to/new-local-experiment
python3 -B fp_usb_shell/fpl_heap_probe.py inspect /path/to/RESULT.BIN
(cd fp_usb_shell && python3 -B -m unittest -v test_heap_probe)
```

The output is `heap-probe.bin` plus `manifest.json` with offsets, source and
artifact hashes. **This is not an installable card**: no AutoRun is generated,
no placement address is implied, and the normal fp L card builder remains
disabled. Builds refuse an existing output directory. The manifest's
`camera_tested: false` is intentional until an identified live trial occurs.

## Result ABI, version 1

Exactly sixteen little-endian 32-bit words (64 bytes):

| Offset | Meaning |
|---|---|
| `00` | Magic `58455046` (`FPEX`) |
| `04` | Version, `1` |
| `08` | Status: `1` = null allocation/not yet allocated; `2` = rejected alignment; `3` = leaf returned |
| `0C` | Allocated address, or zero |
| `10` | Requested allocation bytes, `1000` |
| `14` | Copied leaf bytes, `28` |
| `18` | Execution address observed by the leaf |
| `1C` | Expected leaf execution address (allocation base) |
| `20` | SP observed by the leaf |
| `24` | Leaf-written marker, `50454148` |
| `28` | Leaf return value, `21594B4F` |
| `2C` | `1` after H_FREE returns; not an allocator accounting result |
| `30`–`3C` | Reserved, zero |

Values above are hexadecimal except the status/version explanations.
The inspector requires all success fields to agree, an aligned nonzero stack
and allocation, and zero reserved words. Truncated/extended results fail.
It explicitly leaves `restoration_verified` false: restoration needs its own
before/after evidence. A simulator-produced result is not a camera result.

## Promotion to a camera trial

Before constructing an AutoRun for this body, resolve the initial site's
callers and ownership, stock shell serialization, cache-publication entry
ABI, allocator failure behavior and executable mapping. The IMU image's zero
run is not an initial placement. An offline emulator with permissive memory
maps cannot establish executable permissions on the camera.

The live milestone will be considered complete only with identified build
bytes, an actual allocated-RAM result, borrowed-site/handler restoration
readback, and a clean return to normal camera operation. The audits and
validation record below distinguish the work already completed from these
remaining requirements.

## The trial card (built, not yet camera-tested)

The two audits resolved the placement questions: the stock `dir` handler's
verified extent `[C03E2B98,C03E2F18)` is borrowed for the probe's 392 bytes,
and the *existing* `dir` table slot already points at the probe entry, so the
script never writes it. The only firmware word borrowed is the `echo` table
slot (`C0BD2544`), pointed at the stock cache routines during two publication
windows and restored threefold afterwards — the same pattern the fp
four-box bar uses on fp 5.02. The dispatcher's handler ABI matches the
probe's expectations, and its return value is ignored, which the probe
design already assumed.

`fpl_heap_probe.py card` builds the complete AutoRun (offline, into a new
local directory). Phases, in order:

1. `mem save \FPLPROBE\PRE.BIN` — pre-state forensics, including stale-patch
   detection.
2. 98 `mem set` words place the probe body; `WROTE.BIN` captures what was
   actually written, so a silent `mem set` drop is diagnosable post-mortem.
3. Publication: echo slot → stock `C000E91C`, `echo`; echo slot → stock
   `C000EABC`, `echo`.
4. `dir` — dispatches the probe through the untouched slot. Allocation,
   leaf execution, return and free all happen inside this one command.
5. `RESULT.BIN` saves the 64-byte result block before anything overwrites it.
6. 98 `mem set` words restore the stock body from bytes baked into the
   script at build time — restoration never executes the probe, so the
   script is self-healing even over a stale earlier patch.
7. Re-publication (the restored code is executable), then the echo slot is
   restored ×3.
8. `RESTORED.BIN` and `SLOTS.BIN` capture the end state as evidence.

220 commands (~8 s of script time). Build requires the verified official
MAIN (for stock bytes and hashes). The manifest records the AutoRun SHA-256,
every expected result file and its expected hash, the one borrowed word, the
overwritten range and the trial conditions. `verify` checks collected
results against the manifest after the trial.

**Known risks, deliberately accepted or bounded:**

- *No dispatcher mutex.* During a normal boot with USB disconnected and no
  user input, the AutoRun task is the only command source; nested dispatch
  and the exceptional loop are not active in that state. The trial is
  restricted to exactly those conditions (the same conditions under which
  the bring-up capture ran).
- *Silent `mem set` drops.* Not preventable from a script; bounded by the
  `WROTE.BIN`/`RESTORED.BIN` forensics and by the small word count. The
  historical fp cards shipped ~500 `mem set` commands and held in the field.
- *Power cut inside the modification window* leaves patched `dir` bytes in
  RAM. Recovery is a battery-pull cold boot, which reloads the stock image.
  No persistent settings are written, so the settings-area risk does not
  apply. Warm restarts after a *complete* run find stock bytes (the
  double-execution seen in the bring-up is covered: a second run's `PRE`
  shows stock, and the script restores again cleanly).
- *A hang inside the probe* would stop the script mid-way; the native
  allocator tests exercised the exact allocation path to bound this.

## Trial-card validation, 2026-10-16

`test_fpl_heap_card.py` (4 tests) drives the **emitted script itself** — the
actual command lines, not a parallel implementation — against the real image
at the real addresses, with real allocator instructions and the real command
table:

- Clean run: body written, published (D then I) before `dir`, probe's own
  GET→ADDR→D→I→execute→free order intact during the `dir` dispatch, result
  parses, body restored byte-for-byte, echo slot back to stock, dir slot
  never touched, all five evidence files match their expected content, and
  the global cache-call order is exactly publication / probe / republish.
- Second execution over the restored state is equally clean (models the
  observed double-run behaviour).
- Dropping one restore command is caught by the end-state byte comparison
  and the `RESTORED.BIN` evidence.
- Corrupting one emitted probe word (the leaf marker) is caught by both the
  `WROTE.BIN` comparison and the result parser.

Full suite after this change: **51 tests, all passing** — the new fp L files
(16) plus the existing fp profile, boot-chain, loader-hook, splash-era and
probe suites, with both official MAIN images supplied.

## Live trial result, 2026-10-16 — **milestone complete**

Installed with the owner's authorization at 09:50:29 UTC (6744-byte AutoRun,
SHA-256 `fcb03ae4261ccc8922760994da0533e364394daee1e8aad1c9140f7889aa5542`;
readback after unmount, cache flush and read-only remount matched every
byte). The owner booted with USB disconnected and no interaction; results
were collected at 09:58:43 UTC after reconnecting in mass-storage mode.

**Both executions passed every check.** The camera again ran the script
twice (numbered `000` files, ~66 s apart, cause still unestablished — the
same behaviour as the bring-up). For each run:

- `PRE` = the stock `dir` body hash — including the second run, which proves
  run 1's restoration was complete before run 2 started.
- `WROTE` = the exact probe body hash — all 98 `mem set` words landed; no
  silent drops.
- `RESULT` passed all twelve field checks (magic, version, returned-from-leaf
  status, aligned nonzero allocation, 4096 requested, 40-byte leaf, executed
  at the allocation, aligned nonzero stack, leaf marker, return marker, free
  returned, reserved zero).
- `RESTORED` = the stock `dir` body hash, byte-for-byte.
- `SLOTS` = the stock command-table hash (also matching the bring-up's
  `SHELL.BIN`), so the `dir` slot was untouched and the `echo` slot restored.

The two allocations were **`0x4532ADC0`** (run 1) and **`0x45309A40`**
(run 2) — different addresses inside the audited USER region
`[0x44400000,0x46400100)`, allocated, executed at, returned from and freed.
Both leaves observed the same stack `0xC3AB2018` (the shell dispatcher
task's stack). This is direct hardware evidence that:

1. the stock fp L allocator hands out USER RAM at AutoRun time,
2. that RAM is executable on the live MMU configuration,
3. custom ARM code there can call stock firmware services, execute, return
   and free cleanly, and
4. a borrowed-handler bootstrap with baked-in stock restoration restores the
   camera to stock bytes, surviving an immediate second execution.

After archive verification the exact trial `AutoRun.txt` was removed; the
card was unmounted and `fsck.exfat -n` reported clean (17 directories, 129
files). `FPLPROBE` retains both the bring-up and trial result sets on the
card. Private evidence:
`/path/to/observations/` —
`trial-install-20261016T095029Z/`, `trial-capture-20261016T095843Z/`
(raw `FPLPROBE/` with both runs, `capture.json`, normalized `first-run/`
and `second-run/`, both `verify` reports passing, `cleanup.json`) and the
built artifacts in `heap-probe-trial-card-v1/`.

**Scope of what this proves:** a finite, one-shot owned-RAM execution
primitive under restricted-boot conditions. It does not port the loader,
stage2, USB worker or host tools, and no recording/power-off coexistence
has been tested. Those are the next steps, now unblocked.



## Offline validation, 2026-10-16

The independent `test_heap_probe.py` suite passed **9 tests**. It runs the
assembled routine in Unicorn at two unrelated initial/heap placements, with
literal firmware-call address oracles and allocator/cache service stubs.
Twelve normal/failure scenarios cover null and misaligned allocations, aligned
and misaligned incoming stacks, callee-saved registers, clobbered caller-saved
registers/flags, permitted write ranges, D-before-I-before-execution ordering,
and freeing only after the leaf returns. Code outside the result block stays
unchanged. Result parsing rejects altered fields, zero PC/stack values and
wrong-sized snapshots.

Two single-instruction mutations are required to fail: removing the D-cache
call and altering the leaf's execution marker. Both were rejected by the
independent emulator oracle. These tests prove the probe's control/data flow
under those stubs, not the camera's memory mappings or allocator internals.

The first assembled body is 392 bytes (leaf offset 288, result offset 328),
SHA-256 `85a462952f942408ca76bd970b22f1ea99e4ee587cc9a3541dfbd92ae0df4028`.
Build toolchain: Fedora clang **22.1.8**, target `armv7-none-eabi`; the compiler
was extracted into session-local storage with matching host LLVM libraries,
without installing/upgrading system packages. Rebuild with the command above
and retain its manifest; do not treat these offsets as a public placement ABI.
