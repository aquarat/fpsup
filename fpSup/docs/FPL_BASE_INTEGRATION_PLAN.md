# fp L Base integration: smallest shared implementation

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. Offline source review and implementation plan only. Read the complete
`SUP_BUILD_RULES.en.md` and the current Base sources, not just their introductory
comments. No implementation, camera operation, card build, commit or deployment
is part of this document. The historical test record reports a healthy reconnected PONG
worker; no recording has been tested in this resumed work.

## Decision and next code change

**Next change: make the existing finite raw diagnostic relocatable, keeping the
actual `gyro/gyro_drain.S` and its existing strict/latched semantics.** Give it
caller-owned runtime code/state/output addresses, bounded capacity and a small
firmware-profile seam. Exercise that change under Unicorn at multiple allocation
addresses before introducing a resident task or firmware hook. The useful first
logger deliverable is a host-saved raw capture plus its provenance ledger, manually
invoked while idle. It need not write a camera file or impersonate a video take.

This extends an already executed shared producer rather than attempting to turn
all of Base on by replacing address constants. The existing finite latched probe
already provides a baseline: twenty observations, 1142 copied records in its
recorded live trial, conditional prefix only, `proven_valid_records = 0`. Repeating
that trial is not this task. Relocatability/owned lifetime is the next integration
property; a longer loop alone would not establish it.

Keep three milestones distinct:

1. **Finite manually controlled raw diagnostic:** explicit invocation, finite
   observation/output budget, no REC association, no producer hooks, no background
   task, no Gyroflow calibration claims. Existing borrowed-echo execution is a
   diagnostic call, not a loader entry permitted to loop.
2. **Resident bounded idle worker:** optional subsequent milestone. A shared-loader
   entry allocates/initializes, starts or attaches an owned worker and returns.
   Capture runs later in that worker; stop/completion and retention of its output
   must be defined before it is enabled. This adds genuine task-lifetime work.
3. **Recording-aware Base product:** shared producer, stream buffers, mailbox
   writer and take lifecycle, with proven recording-state coverage, no-cave
   installation, filename association and shutdown. The other agent's recording
   state/coverage audit owns that analysis; this plan does not duplicate its CFG
   or prescribe a new all-mode hook.

## Source seams and exact scope

| Current file/symbol | Smallest change or disposition |
|---|---|
| `fp_usb_shell/firmware.py:get_camera`, `Camera.loader_defines` | Reuse `FPSUP_CAMERA` selection and existing identities. Keep `card_supported=False` for fp L generic products until product acceptance exists. |
| `fp_usb_shell/firmware/loader.h`, `fp_502.h`, `fpl_302.h` | Existing selector and allocator/cache/media ABI source. Consume these definitions where applicable rather than copy their addresses. |
| Proposed `gyro/firmware.h` | Thin gyro-specific selector using the same `FPSUP_CAMERA`; only audited constants consumed by the current slice. No runtime device-discovery/configuration framework. Unknown targets fail assembly. |
| `gyro/imu_stream.inc.S:GYRO_DESC_PTR`, `gyro/gyro_drain.S:gyro_drain` | Keep shared producer and diagnostic descriptor override. Default fp output must remain unchanged. A real descriptor read and the owned diagnostic descriptor view are different things. |
| `fp_usb_shell/asm/fpl_gyro_capture.S`, `asm/fpl_gyro_latched.S` | Convert owned placement constants to explicitly initialized runtime-local references in these existing probes; preserve their distinct strict and conditional acceptance rules. Do not copy a second drain into them. |
| `fp_usb_shell/fpl_gyro_capture.py`, `fpl_gyro_latched.py` | Supply/check owned extents, retain guards and exact mutable-word ledgers, retrieve before release, and save raw bytes plus diagnostic metadata. No new transport or updater. |
| `gyro/build_base_card.py:launch`, `hook_sites`, `main` | Later accept the same explicit camera profile and pass it through assembly and shared packaging. Current fp-only restoration/park/veneer dependencies must not leak into fp L output. Do not enable fp L Base merely because the assembly succeeds. |
| `gyro/gsup_launch.S:entry`, `gyro/writer_core.inc.S:BLOBBASE`, `blob_at`, `gsup_boot` | Later remove the fp L assumption that any published worker pool is gyro storage. Use a gyro-owned allocation and runtime base references, not a copied fp L writer. |
| `gyro/gcsv_task.S:writer_openfile`, `gyr_header`, `writer_put`, `writer_closefile` | Later add an explicit raw-diagnostic output policy in this shared source. Base's existing raw block writer is reusable; its calibrated header and automatic JSON are not diagnostic defaults. |
| `gyro/ring_task.inc.S`, `rec_trigger.S`, `accel_hook.S` | Parameterize actually used firmware interfaces when their lifecycle slice is implemented; retain common algorithm/hook bodies. Do not port dead constants to satisfy old comments. |

The proposed profile is data, not another implementation. For the finite slice
it needs the real gyro publication `C31E23CC`, optional accel cache `C37772F4`,
and delay binding `C01F5244`; shared allocator/cache calls already have headers.
Runtime P/R must still be read and validated. The existing diagnostic's expected
P=`2E006004`, R=`2E00644C` are validation bounds for this inspected firmware,
not a license to follow arbitrary pointers or use those locations for storage.
The owned view freezes the validated ring; the optional owned latch freezes H.

Recording-product bindings already audited include accel `C0509730`, START
`C03792D0`, STOP `C038C69C`, media write/seek/stamp `C0366300/C03663F8/C0369528`,
thread create/attach/join/destroy `C036E320/C036E3D0/C036E410/C036E380`, and
mailbox create/send/receive/delete `C01F5124/C01F55C8/C01F53F4/C0680C54`.
These are candidates for the later profile, not proof that the callbacks can
safely run the current synchronous open/close path. Thumb raw accessor, if used,
is callable at `C01E9141`; a direct snapshot needs no accessor call.

## Memory ownership and dynamic publications

There is **no fp L cave**. Embedded IMU firmware occupies the apparent candidate
space (`C072A4C0`, length `6200`); zero regions belong to that image too. Do not
carry `CAVE_BUMP`, `CAVE_ARENA_END`, `ENTRY_AT`, `PARK_AT`, or an inferred fp
relocation into this port. USER RAM is outside ARM BL reach from these firmware
sites. Current `s_hook` cannot become fp L-safe through a profile-only edit.

Current `gsup_launch` tests fp `POOL_PTR`, reuses any nonzero value, copies at
`+44000`, then calls routine-table offset `O_GSUP_BOOT=18`. `BLOBBASE`, `blob_at`
and `gsup_boot` independently recompute that base from `FRAMEBUF`; changing just
the launcher's destination leaves the consumers wrong. `JPOOLAT` also assumes
the relative job-pool position (`43000`, versus code `44000`), and file storage
uses `42000`. Carry initial values with relocated state, including
`g_ghead=HEAD_UNARMED`, empty buffers/jobs and a closed producer gate.

For the next finite call, caller-owned execution and result memory may remain
in the diagnostic runner's verified reservation for the entire call/readback.
For a standalone allocation use `H_GET(desc,0,size,0)`, then test `H_ADDR(desc)`:
`H_GET` returns the descriptor even on refusal. Initialize requested bytes;
allocator rounding slack is not owned. Retain the 16-byte descriptor outside
the allocation until a caller outside that block calls `H_FREE(desc,2)`.
Free does not clear it: clear the owner's bookkeeping after return, and never
execute, read results, return through or keep a stack in the released block.

A resident logger needs a durable descriptor/owner and its own code/state/output
allocation. Use patched local pointer literals or PC-relative owned state to
resolve that allocation; keep the default fp `BLOBBASE` path intact initially.
An internal worker receives a body object/context; that private ABI is not the
loader's entry ABI. Do not publish gyro storage over `FW_FRAMEBUF` merely to
make existing macros work.

The actual fp L worker publication is `C37588BC + {0,4,8}` = pool, size, code.
State is pool-relative, never adjacent free BSS. **Current source wins over the
older worker-state audit:** `firmware/worker_fpl_302.h` now places state at
`+1000`, capture length `+1040`, swap magic `+1080`, swap address `+10C0`, capture
pointer `+1100`. Do not use that audit's historical `1044/1048/104C` swap layout.
The worker's capture, transfer windows, staging and replacement storage are not
an implicit gyro arena. Any intentionally shared reservation must be checked
against the actual worker map, capacity, identity and in-flight transport use;
a nonzero pointer is insufficient. Avoid such a reservation for resident gyro
by owning a separate allocation, and do not make a standalone product depend
on a USB worker.

Dynamic pointers into resident allocations belong in owned state. If a future
host-discovery pointer is needed, use an explicitly allocated/owned descriptor
reachable through an existing, versioned product interface; do not invent a
fixed firmware scratch word. Any actual firmware publication word changed by
a card needs a corresponding original-word journal section. A pointer published
in a prior boot must never be reused after heap reset. Repeated entry in the
same boot must refuse/reuse a proven live instance without reinitializing memory
under a running worker; duplicate invocation and allocation failure need tests.

## Shared load-chain and hook contract

Keep `build_autorun.py --loader`, `entries.S`, the existing two stage2 passes,
and nonzero entries. Destination-zero boot blobs run in staging; entry r0 is
that entry's own resolved address, not settings or a pool. Save used callee
registers/LR and keep SP eight-byte aligned. Entry installs and returns; staging
is freed afterward. Copy every surviving body, vtable, string, descriptor view,
callback target and state word before returning. D-cache `C000E91C` followed
by I-cache `C000EABC` precedes first execution of copied code.

Use no pass-2 gyro sections for the separate-allocation design: the boot entry
copies its own body. Stage2's pass 2 still exists and still resolves against
the worker publication when a package legitimately uses it. Do not repoint it
to a private gyro pool or add a third pass. Current restricted fp L headless
shell packaging is offline-tested; generic Base composition remains unsupported.

For a later runtime hook, `build_base_card.hook_sites()` is the reference:
declare every overwritten firmware word as a section containing its stock word
so stage2 journals it before the entry. fp L's `FW_CAVE_LO==FW_CAVE_HI` excludes
nothing. The audited one-word originals are accel `E3A02000`, START `E5DB25CE`,
STOP `E3500000`. An eventual multi-instruction far-transfer patch must journal
its **whole extent**, replay every displaced instruction and preserve flags/
LR/continuation correctly; these three single-word audits do not establish that.
No unreviewed multiword patch is recommended as the next change.

Prepare all target code, resources and pointers, publish D/I, then arm the
site last and publish that instruction change. Current `s_hook` writes a near
veneer and immediately arms its site, with cache work after the installation
sequence; that is not an independently established concurrent fp L install
protocol. The loader restores firmware, not a new sup power-off callback.
Restoration alone does not prove no hook or worker is already executing.
Do not free resident storage on stop/power-off until references are quiescent;
keeping it through the boot avoids self-free but does not certify shutdown.

## Disable versus parameterize

For the finite milestone, **do not call `gsup_boot` or `take_open`**. They are
not passive producer setup. `DRY_RUN` is also insufficient: it suppresses file
operations while allocation/task/lifecycle effects remain.

* Disable REC START/STOP and accel hook installation, `s_hook`, mailbox/thread
  construction, camera-side file output, `take_path`, stamp and fallback ladder.
  Manual bounded observation drives `gyro_drain` with owned bounded adapters.
  An accel-cache read is a separate observation; repeated identical cache values
  are not new samples and must not fabricate the hook's interleaving.
* Omit `gcsv_json_write`, `gcsv_json.S`/`gcsv_dist.S` execution, geometry query/
  free, focus virtual calls, correction interpolation and optical fit. Current
  Base calls JSON unconditionally after `gyr_header` and includes these sources;
  `FPGYRO_EDITION_BASE` alone does not remove them.
* Base already leaves `WANT_MODE_HOOK` undefined. Keep orientation/level-gate
  mutation disabled. `EXPOSURE_FN` is defined but not called by current Base;
  no frame-exposure hook is installed. Do not invent either dependency.
* Later parameterize file, mailbox, thread, allocator and audited take-manager
  fields in the same shared bodies. Preserve `F_WRITE`'s boolean return semantics,
  not a byte-count comparison. Test open/write failures and destructor ownership.
* Disable fp-only `phase_fwrite_restore.S` at `F_WRITE_AT=C03660E8` and park
  section `C072EFB4` in any future fp L build. The former address is fp L's
  **file destructor**, not its write entry; blind reuse would patch live code.
  `check()`'s fp cave bounds cannot validate the new allocation layout.

For recording output, audited managers are SSD `C34392D0`, SD `C3439338`,
settings pointer `C30751F0`; the raw fields and arithmetic are described in
`FPL_GYRO_PATH_BINDINGS.md`. Base's root `A001_037` is not a filename reservation
or collision check. Do not call manager advance/sync just to create a sidecar
identity, or assume an idle candidate names a later recording. The coverage
audit and subsequent product work must establish actual take/volume association.

## Diagnostic output: raw means raw

Retain eight-byte records with signed components at +0/+2/+6 and tag at +4,
plus firmware identity, schema, invocation and observation indices, source
pointer snapshots, pre/post/consumed heads, output extents, drops, padding errors,
termination reason and conditional-prefix ledger. Unknown acquisition time is
not zero time. Host request times are observation bounds, not exposure timestamps.
Use the existing diagnostic schema/decoder where possible, not shipping `.GYR`
magic with silently bogus calibration fields.

Do not inherit `GYR_PERIOD_PS=400085400`, `GYR_GSCALE=0.000137923`, accel scale
`2^-10`, orientation `xyz`, or fp callback offsets as fp L measurements. Mark
period/scale/body-axis calibration unknown (`calibrated: false`); retain sample
indices rather than fabricate seconds. No fps or first-exposure offset follows
from nominal 20-ms delays, settings dimensions or record counts. Disable the
JSON's 72-MHz/6000-column/35.9-mm calculations and unconditional 16/10 padding.

Optional metadata reuses the passive snapshot semantics: settings guard
`C31F70B0` must equal 1 before/after raw width/height/format at
`C31F6ABC/C31F6AC0/C31F6AC8`; lens guard `C3477208` similarly protects a bounded
observation of 32 name bytes at `C34657B8` and focal word `C34657FC`.
No constructing accessor is needed. Label units unknown, consistency unverified;
retain raw bytes/length/NUL-limit status and escape display strings. Settings
dimensions are not proved encoded raster, and a construction guard is not a
snapshot lock. Sensor mode, if added later, is a raw id, not a calibrated fps.

Conditional drain acceptance keeps the existing strict inequality, next cursor
H rather than post-head Q, and sentinel -1 on each invocation. Hidden laps,
descriptor ABA, visibility and scheduling gaps remain unproved even when the
window passes. Keep tentative failed-batch bytes separate from the conditional
prefix and keep `proven_valid_records=0`. Capacity loss stops this diagnostic;
it is not permission to concatenate another call as a continuous stream.

## Offline implementation order and acceptance

1. **Profile/relocation patch:** touch only the existing finite wrappers/runners,
   shared include seam and a thin gyro profile. Test real ARM code at at least
   two unrelated allocation bases and with deliberately poisoned former bases.
   Reject invalid/overlapping/extreme extents; verify exact initialized state,
   bounded writes, ABI, finite return, cache-before-execute and results-before-free.
   Freeze default fp Base assembled bytes before the patch and compare afterward.
2. **Raw output contract:** use current ledger decoding and add explicit unknown
   calibration/recording labels if missing. Test serialization round-trip, guard
   failures, capacity drops, failed retrieval and retention/cleanup ordering.
   Do not import live transport into ARM-only tests. No new audit script is needed
   for recording coverage; consume the other agent's results when available.
3. **Only if resident operation is selected:** add a minimal installation test
   for actual `gsup_launch`/shared body changes, with injected allocation/task
   failures, duplicate entry, worker completion, retained results, poisoned freed
   staging and no firmware stores. Emulator must prove entry returns before
   capture work, and all worker callbacks/vtables remain owned. This is a
   separate code slice from the finite-call improvement.
4. **Only after no-cave hook design and coverage are resolved:** add the real
   installation/journal tests, exact overwritten-word fixtures, branch-reach and
   displaced-instruction/flags checks, callbacks before readiness, STOP without
   START, duplicate/unpaired/error cases, allocation failure and power-off restore.
   Exercise recording lifecycle only in modes the coverage audit supports.

Existing suites to run for the finite slice, from `fp_usb_shell/`:

```sh
python3 -B -m unittest test_fpl_gyro_capture test_fpl_gyro_capture_host \
  test_fpl_gyro_latched test_fpl_gyro_coherence
```

Add relocation/ownership cases to those suites instead of testing a substitute
Python drain. Preserve their source mutation controls, hidden-lap counterexample,
wrap, invalid publication, initial cursor and capacity tests. Demonstrate that a
new emulator test fails under an intentional mutation before restoring it.
Optional metadata changes also require `test_fpl_metadata_snapshot`.

If shared loader/packaging is changed later, additionally run:

```sh
python3 -B -m unittest test_boot_chain test_loader_hook test_splash \
  test_stage2_registration_failure test_firmware_profiles \
  test_fpl_stage2 test_fpl_shell_card
```

Add actual new product-entry coverage; a USB worker or OG test passing is not
gyro installation evidence. For entry-chain/composer changes the contract also
requires the full research tree's `projects/open-gate/build/test_boot_entry_chain.py`;
record it as unavailable if that external tree is missing. Compare AutoRun for
compatible payload-only changes: no hash/version pairing, new pass or new loader.
Build into fresh output directories, never the default frozen release directory.

## Blockers and upstream practicality

The finite slice is implementable offline now. Live calibration, proven lossless
sampling and recording coverage are not prerequisites to an explicitly raw,
conditional finite diagnostic. Its later hardware verification remains a separate
authorized step. A resident or recording product is blocked by no-cave hook
reach/installation, callback and worker quiescence, retained allocation ownership,
mode coverage, actual media/naming/error behavior and reliable shutdown. Current
PONG health proves none of those recording properties.

This is practical to merge upstream because it preserves one loader, one drain,
one writer core and `gcsv_task.S` as the Base/GCSV implementation. The first patch
has narrow profile/owned-state seams, default-fp byte regression and real ARM
tests, without forcing upstream to accept an unfinished fp L product. Later
writer/lifecycle work can reuse those seams with explicit diagnostic feature
gates instead of a parallel fp L logger or generic firmware framework.

Evidence references: `FPL_GYRO_BINDINGS.md`, `FPL_GYRO_DRAIN_COHERENCE.md`,
`FPL_GYRO_RECORDING_BINDINGS.md`, `FPL_GYRO_PATH_BINDINGS.md`,
`FPL_GYRO_METADATA_BINDINGS.md`, `FPL_ALLOCATOR_AUDIT.md`,
`FPL_WORKER_STATE_AUDIT.md`, and the current status in `FPL_PORT.md`.
Older original-audit statements are qualified by their later follow-ups and
current source. No tests were executed for this documentation-only review;
the commands above are required implementation acceptance, not claimed results.
# Historical Base integration slice

This technical slice remains useful for Base compatibility, but the current
[parity roadmap](FPL_PARITY_ROADMAP.md) supersedes its product prioritization.
Gyro2's source is now available; completing the entire Base logger is not a
prerequisite for a Gyro2 port.
