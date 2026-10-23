# fp L retained task: next shared implementation slice

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Implementation follow-up — October 23

The proposed slice below is implemented offline. `gyro/latched_capture.inc.S`
now owns the finite body; the fp L assembly is an explicit firmware adapter.
Opt-in cancellation checks batch boundaries, preserves existing error priority,
and supports zero-row cancelled output without clearing the request. Default
builds retain the original bytes and complete symbol maps. No live cancellation
command, reactivation or ownership-release path was added.

Independent reproduction passed all **138 fp L tests**, including cancellation,
relocation, native-task and 25 host-workflow tests. The implementation agent
also reported unchanged Base/GCSV builds. Main independently verified all 24
archived hashes, exact rebuilt prototype and decoded capture. Shared regressions were
independently rerun: **108 passed, three failed, one skipped**. Failures concern
existing arena-address references and a nested `getfile.S` guard rejected by
the safety test's regex. A separate agent reproduced the identical 108/3/1
result from a fresh archive of committed `the pre-integration development baseline`, establishing these failures
predate this extraction.
The skip requires the absent `../out/MAIN_c0000000.bin`. No new camera trial
or change to the retained task/pending marker accompanied this extraction.

Assessment, 2026-10-23. **Next patch: extract the existing finite latched capture
body into `gyro/latched_capture.inc.S`, parameterize its firmware inputs, and add
opt-in cooperative cancellation at batch boundaries.** Make the current fp L
assembly an adapter to that core. Keep the default artifact byte-identical.
This is one implementation slice, not approval to run another camera trial.

The useful integration unit is the capture body, not Base's complete writer
lifecycle. This puts the already exercised algorithm in the shared gyro tree,
with an explicit bounded-work/retained-ownership contract for a resident caller.
It does not yet make the Base mailbox writer an fp L logger.

## Evidence independently checked

Read-only source: `/path/to/observations/gyro-retained-task-first/`.
All **24** manifest-listed artifacts match their recorded sizes and SHA-256.
Using the existing pure decoders, independently checked:

- `observe-01.bin` through `observe-03.bin` against `observation()`, including
  both raw native samples and identity/status checks in each observation;
- `control.bin` against `identities()`, and `wrapper.bin` against the resident
  portion of `prototype.bin`;
- `capture.bin`, `state.bin`, and the full `output.bin` against `verify_result()`:
  immutable code, six mutable words, ledger and output/sentinel checks agree
  exactly with the archived decoded result.

The official MAIN hash is
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`;
firmware identity is `w91c1`, `3.02.0.V90`, git
`13aa621060efff11aaba9b21ad925005302605cf`.
Prototype SHA-256 is
`c2c8c9a5a075ba65a63fe4485f111e3559c544f2462782f6dfe891cfe6a52725`.

| Archived observation | Native state in both samples |
| --- | --- |
| 1: unattached | historical/active body zero; flag 1; wait reason 1 |
| 2: active | historical/active body both owner+8; flag 0; wait reason 2 |
| 3: returned/detached | historical body owner+8, active body zero; flag 1; wait reason 1 |

All query return codes are zero; object identity `3276931260`, task ID `124`,
flag ID `146` remain stable. Evidence bits are respectively 7, 7, 15. The
optional sleep diagnostic was **disabled**: observing raw reason 1 is not the
same as establishing its optional diagnostic bit or a universal sleep invariant.

There are **20 capture batches**, distinct from the three host task observations:
997 appended records, conditional prefix 997, proven-valid 0, no reported
capacity drops or copied bad padding. Admission PONG is 126; final PONG is 568.
The operation log records echo restoration and owned-window revocation before
the final PONG. These are archived observations, not a query of current camera
state. The manifest still says `hardware_validated:false`,
`boot_identity_available:false`, `release_authorized:false`; retain those fields
as written, alongside the successful live-run evidence.

## Why not substitute the task addresses in Base?

| Native interface | fp Base 5.02 | fp L 3.02 |
| --- | --- | --- |
| create holder | `C036E108` | `C036E320` |
| attach body/wake | `C036E1B8` | `C036E3D0` |
| infinite join | `C036E1F8` | `C036E410` |
| destroy | `C036E168` | `C036E380` |

Both use priority 6, stack `0x2000`, holder passed by address, and callback
vtable slot `+0xC`. The retained prototype's `entry`, `activate`, `body_entry`,
`identity`, `sample`, and `observe` additionally enforce one create/attach
attempt, one capture invocation, and retained identities. fp L direct queries
are `tk_ref_tsk=C01F54CC` and `tk_ref_flg=C01F5460`; delay is `C01F5244`.
Query statuses must remain signed. “Nonblocking query” means no object wait,
not a guaranteed wall-clock return time.

Current shared code has more dependencies than this ABI:

- `gyro/ring_task.inc.S`: Base native, mailbox, file and allocator addresses.
- `gyro/writer_core.inc.S:take_open`: initializes `O_W_BODYOBJ`/`O_W_VT`,
  creates `O_W_THREAD`, then attaches the callback.
- `writer_body`: receives mailbox jobs with `TMO_FEVR`, calls `writer_put`,
  releases blocks/jobs and returns on the stop job or receive error.
- `take_close`: posts stop, calls infinite `XT_JOIN`, deletes the mailbox,
  destroys the thread, then closes the file. `JOIN_TMO=8000` does not bound
  that native join.
- `gsup_boot`, `gsup_offsets`, `BLOBBASE`/`SHAREDAT`: pool-derived state and
  initialization, plus `s_hook` allocating cave veneers for producer hooks.
- `gyro/gcsv_task.S`: Base/GCSV share this core via `FPGYRO_EDITION_BASE` and
  the `writer_openfile`, `writer_put`, `writer_closefile` seams.
- `gyro/ring_task_deploy.py:_check`, `patch_offsets`, `CODE_POOL_OFF`, and
  `gyro/build_base_card.py:sections`, `launch`, `hook_sites` still describe this
  Base product layout, not the diagnostic retained owner.

Native callback return precedes active-body clearing and native completion;
completion precedes the next sleep. DONE alone cannot establish detachment.
Queued wakes can rerun a callback before detachment; the prototype's ONCE guard
prevents capture reinitialization. A later wake can reach native no-body/self-exit,
so retaining memory does not promise permanent parking. Constructor assertions
can occur synchronously, and ignored `sta_tsk` status means a populated holder
does not prove a runnable worker. Those limitations survive this proposed patch.

## Exact proposed patch scope

Existing names below are inspection anchors; new names are proposed interfaces.

1. **New `gyro/latched_capture.inc.S`: move, do not copy, the implementation**
   currently in `fp_usb_shell/asm/fpl_gyro_latched.S`: `capture`/`.Lcapture`,
   `loop`, `row_done`, `finish`, `snapshot`, `valid_head`, `stream_claim`,
   `stream_commit`, `validate_refs`, runtime reference table, and local cursor/
   descriptor storage. Continue including the single `gyro/gyro_drain.S` with
   `GYRO_DESC_LOCAL`/`GYRO_LATCH_LOCAL` or the existing absolute-pointer mode.
   Keep the 600-record, eight-byte-record format fixed for this slice.
2. **`fp_usb_shell/asm/fpl_gyro_latched.S`: thin adapter.** Preserve existing
   build guards and exported symbols; supply explicit compile-time inputs
   `LAT_DESC_ROOT=0x2E006004`, `LAT_RING_BASE=0x2E00644C`,
   `LAT_DELAY=0xC01F5244`, then include the shared body. The shared include must
   reject missing inputs instead of silently selecting Base or fp L addresses.
   Descriptor traversal and ring checks move with the body; no algorithm fork.
3. **Add opt-in `LAT_CANCEL=1` to that same core.** It allocates a local aligned
   `g_cancel_request` word inside the caller-owned code extent. Default builds
   emit neither the word nor cancellation instructions. The word is initialized
   in the image before execution, never cleared by `capture`; this avoids
   losing a request to the existing 2048-byte state initialization.
4. **`fp_usb_shell/fpl_gyro_latched.py`: extend `code_for`, `verify_code`, and
   `decode` narrowly.** An explicit offline-build cancellation option selects
   the new assembly flag and reports its symbol. Only that variant permits the
   additional mutable word and final status `101` (`cancelled`). Preserve the
   old decoder schema/behavior for uncancelled artifacts; allow a legitimate
   zero-row cancelled result without inventing a batch. Existing host calls
   retain their default build. No live cancel/resume CLI is added in this slice.
5. **Tests:** extend `test_fpl_gyro_latched.py`,
   `test_fpl_gyro_latched_relocation.py`, and
   `test_fpl_gyro_task_retained.py` to execute the shared core and opt-in variant.
   Use the existing native-worker harness rather than a second worker prototype.

This is deliberately capture-loop parameterization, not an XT profile migration
plus a writer rewrite in one patch. `fp_usb_shell/firmware/fpl_302.h` already
profiles loader/allocation/cache services and declares an empty cave interval;
it does not yet profile the XT lifecycle. Changing that profile and Base's
teardown is a later consumer integration once this body has a tested stop seam.

## Cancellation and ownership contract to implement

- Single owner publishes only `0 -> 1` to `g_cancel_request`; any nonzero value
  is treated as stop. It is a request, not an acknowledgement, task termination,
  rearm capability, or permission to clear capture results.
- Check before each batch starts and after the complete `row_done` ledger
  publication, before the next delay. Do not interrupt `gyro_drain` midway or
  discard its post-snapshot/coherence classification. Existing batch failure
  takes precedence over cancellation; otherwise a noticed request ends with
  status 101 and the existing `finish` publication path.
- Preserve cursor, copied data, tentative batches and conditional-prefix
  accounting. A pre-entry request yields initialized header, zero rows/copies,
  and cancelled status. A request during the final delay may lose to normal
  completion; it must never restart the body.
- Keep the hard 20-batch ceiling, capacity checks and 20-ms delay. Cancellation
  has a bounded **work** boundary: at most the currently admitted batch before
  the next check (plus an already-entered delay). Firmware scheduling, memory
  visibility and delay calls provide no wall-time deadline. Publication barriers
  belong to the request protocol; barriers alone do not prove cross-agent cache
  coherence. Offline injection tests establish control flow, not that live proof.
- Capture result publication is separate from wrapper DONE and native completion.
  Preserve ONCE before capture, signed query errors, stable before/after
  identities and finite observation budget. No join, destroy, free, terminate,
  wake-to-cancel, or polling-until-success path is introduced.
- All native objects and every referenced byte stay owned for the boot on
  completion, cancellation, timeout or uncertainty. Reusable means shared code
  usable by another explicitly owned instance, **not** reuse of this allocation.

## Placement and entry are separate contracts

The successful run requested a separate class-0 USER allocation of 64 KiB with
explicit 64-KiB alignment. The archived owner is `1162870784`; it is evidence,
not a future placement constant. Host staging is
`align_up(pool + STAGING_OFFSET, 1024)`, with the full 0x4000 extent checked.
The observed pool `0x4533aec0` is only 64-byte aligned. No-cave allocation
solves storage ownership; it does not install hooks or prove a boot lifecycle.

The shared loader's stage-entry convention supplies the entry's own address in
r0. `gyro/gsup_launch.S:entry` is an existing allocate/copy/publish/bootstrap
example, using Base publication and blob offset `+0x44000`, then calling the
`gsup_boot` table entry at `+0x18`. Its pool adoption and cave-hook boot path are
not the retained-owner contract. Any eventual card integration must follow the
shared build contract and shared loader/stage2, not create another loader.

`fp_usb_shell/asm/fpl_task_entry.S` is instead a diagnostic echo trampoline:
echo supplies argv in r0, so it sets r0 to the checked target before dispatch.
It is neither the product entry ABI nor a resident dependency. The capture core
uses its validated owned reference table, not echo argv. The tests must keep
proving that no resident reference escapes into recyclable staging.

The checked host workflow and durable `fpl-retained-task-v1` pending marker
continue to block another allocation/attempt. Existing `fpl_swapworker` strict
schema rejection remains mandatory. Cancellation does not bypass that lock or
authorize a command against the current retained camera instance. No marker
deletion, retry, resume or automatic reconciliation is part of this patch.

## Acceptance tests for the next implementation

1. **Extraction equivalence:** default runtime and fixed-reference builds at
   multiple placements have identical bytes/symbol offsets to pre-extraction
   builds, including six mutable offsets. Reproduce the archived prototype with
   its owner/reference inputs and match its hash. Re-decode the archived 24
   artifacts read-only; do not reinterpret their provenance flags.
2. **Real ARM cancellation:** request before entry, at each batch boundary,
   during drain, during delay, and after finish. Verify finite copy count, exact
   ledger/cursor/output, zero-row cancellation, error precedence and no extra
   delay after an observed request. Poison all guards and output tail.
3. **Native wrapper:** cancellation runs through the real retained wrapper;
   queued wakes invoke capture only once, DONE alone is insufficient, native
   completion follows return, and no retained pointer targets poisoned staging.
   Keep dormant/unknown state, query failure, identity-change and constructor
   failure cases. No test interprets sleep or completion as release permission.
4. **Profile and relocation:** missing parameters fail assembly. Synthetic
   alternate descriptor/ring/delay addresses must actually be used; trap the
   old addresses. Preserve descriptor/ring/head rejection and complete runtime
   extent validation. Assert the opted-in core still fits CODE[4096] and does
   not move into state/ownership records.
5. **Meaningful mutations:** removing a stop check, clearing the request during
   initialization, resetting the cursor on stop, broadening the mutable mask,
   moving ONCE after capture, or branching into join/free must fail executable
   tests. A partial batch cannot be relabelled as a proven-valid prefix.
6. **Regressions:** run existing finite capture, coherence, relocation, retained
   and host suites (including the 25 host tests). Run
   `gyro/test_imu_stream.py`, `gyro/test_lifecycle.py`, and `gyro/test_safety.py`
   for shared drain/ABI/layout assumptions; assemble both Base/GCSV editions
   offline and compare with their pre-patch bytes. Broader card changes are not
   needed for this slice.

Acceptance establishes one shared finite, cancellable capture body and preserves
the live-tested default. Calibration, unconditional coherence, recording
association, continuous logging, safe reclamation and production card admission
remain gated. This assessment changed only this new document; no implementation,
camera/card operation, commit or push was performed.
