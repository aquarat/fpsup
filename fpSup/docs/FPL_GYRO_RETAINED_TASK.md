# fp L retained finite task: offline prototype variant

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Live follow-up — October 23

The checked `fpl_gyro_task.py` workflow has now completed one live native-task
trial after 25 host tests passed independently. A separate 64-KiB USER block
was allocated, initialized, launched and attached once. Three observations
captured unattached, active, then detached/native-complete states. The actual
finite capture completed 20 observations/997 records, with full code, ownership,
state and output verification; zero observed padding errors/capacity drops.
`proven_valid_records` remains zero. Echo restoration, window revocation and
final structured PONG passed. All task/native objects/storage and the host
pending marker remain retained. No join, destruction, free or reactivation.

The 12,288-byte staged prototype SHA-256 was
`c2c8c9a5a075ba65a63fe4485f111e3559c544f2462782f6dfe891cfe6a52725`.
Private evidence: `fpl-live-2026-10-23/gyro-retained-task-first/`, including
manifest, exact uploaded artifacts and readbacks. This supersedes the offline-
only status below for this one workflow/trial; scheduler generality, repeated
use, recording integration and reclamation remain unproved.

2026-10-23. Owned files:

- `fp_usb_shell/asm/fpl_gyro_task_retained.S`
- `fp_usb_shell/test_fpl_gyro_task_retained.py`
- this document

**This variant retains the worker and every referenced allocation for this boot.**
It has entry, activate and observe operations, with no join, destroy, terminate,
delete, free, release-ready or retry-cleanup operation. It is an offline synthetic
reservation experiment, not a deployable card or a live allocation/host tool.
The stable task prototype remains separate. The complete build rules were read;
the shared loader/AutoRun/pass sequence is not changed.

## Result and evidence boundary

The launcher copies/publishes resident bytes and creates an unattached native
worker, then returns. A later external activation attaches the retained body
once. That body invokes the actual relocatable finite capture at most once,
then returns into the actual native pool trampoline. Observe performs two
sequential query samples, each with surrounding identity reads. There is no
poll-until-done loop or timeout/deadline claim.

The emulator runs official fp L 3.02 native create/attach wrappers, constructor,
pool trampoline, reference-task/reference-flag stubs and kernels, and the
completion set-flag stub/kernel. It embeds the current
`fpl_gyro_latched.code_for(..., runtime=True)` output, which uses the actual
shared drain; no capture/drain algorithm is copied into this variant.

Official MAIN: 49,310,208 bytes, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
Tests require that fingerprint and the completion audit's semantic pins before
using the image. Query ABI evidence is in
[FPL_THREAD_COMPLETION_AUDIT.md](FPL_THREAD_COMPLETION_AUDIT.md).

The historical test record supplied a passive descriptor observation, inspected here as a
local artifact only:
`/path/to/observations/thread-sleep-descriptor.json`.
It records `[C2F06B48] = 1`, version `3.02.0.V90` and
`OK pong seq=92 proof=PONG`, explicitly limited to one descriptor observation.
No camera call was made by this slice. Default `SLEEP_REASON=0` disables the
sleep diagnostic. The optional fixture with `SLEEP_REASON=1` treats that value
as **known once**, not an invariant across boots, versions or task wait types.

## Ownership, entry and one-shot execution

The fixture supplies an initially zeroed, separate, aligned 64-KiB reservation
at synthetic `OWNED=46000000`. This address is not a live allocation grant.
The native thread allocator backend supplies a separate synthetic native object;
the actual constructor still creates its flag/task through mocked RTOS creation
boundaries. All native objects, task stack and retained code/data remain owned.
Retention is not permission to preserve stale pointers across a warm restart.

Entry accepts r0 as its own address, preserves callee-saved registers and keeps
calls eight-byte aligned. It copies the full 8192-byte resident region before
publishing `C000E91C` then `C000EABC`, initializes the body/vtable/capture pointers,
and calls `XT_CREATE` at `C036E320`. It saves the returned holder contents and
task/flag IDs as this reservation's fixed identity. A null holder or native
assertion leaves creation attempted, never resetting the reservation for retry.
The constructor's ignored `sta_tsk` return remains a limitation; an observe
record can expose dormant state 16 despite a non-null holder.

Activation is external and only accepts phase 2. It first advances to phase 3,
checks the holder and task/flag IDs against saved identity, then calls actual
`XT_ATTACH` at `C036E3D0` with the **address of the owned body object**. Identity
failure or assertion leaves phase 3 permanently blocked. A returned wrapper
advances to phase 4; this records return, not an invented attach-success code.
Sequential duplicate activation does nothing. The owner must call activation
only after entry returns, never from inside the launcher or another host.

Body entry saves the native stack phase and aligns SP for capture. ONCE is set
**before** the capture can initialize its state/output. Only that single native
worker is allowed to invoke this body; ONCE is deliberately not a cross-task
atomic lock. Subsequent callbacks increment REPEATS and return without touching
capture code scratch, state or output. DONE is written after capture returns,
before the body epilogue returns to firmware. DONE alone therefore cannot mean
native completion. If capture does not return, ONCE stays set and nothing retries
or releases the reservation.

Native completion clears object+8 and sets flag bit 1 after callback return;
object+4 retains its historical body pointer. Queued wakes before completion can
make the pool invoke this body again: the one-shot guard prevents capture replay.
A wake **after** object+8 has been cleared takes the native no-body branch at
`C036F248` to `C01F52D4`, not another capture. Tests stop at that self-exit service
boundary rather than invent a returning success or final task state. Thus the
variant guarantees retained ownership, not that the native task stays parked
forever. The native self-query error path can publish completion with wakes
still pending and reach the same boundary. None of these paths authorizes free.

### Owner control block

All offsets below are relative to OWNED; words are little-endian uint32 unless
identified as signed status.

| Offset | Meaning |
|---|---|
| 00 | phase: 0 unattempted, 1 create attempted, 2 created/unattached, 3 attach attempted/blocked, 4 attach wrapper returned |
| 04 | native holder pointer |
| 08 | body object containing vtable pointer |
| 10..1F | owned vtable, callback in slot +0C (at OWNED+1C) |
| 20 | retained capture entry pointer |
| 24 | DONE, initially 0, set to 1 after capture returns |
| 28 | ONCE, initially 0, set to 1 before capture starts |
| 2C | repeat-body counter; diagnostic, wraps as a 32-bit word |
| 30 | saved native object pointer |
| 34 | saved task ID |
| 38 | saved flag ID |

There is no state transition to reclaimed or reusable. Code does not clear
holder/body/vtable references on success, query failure or partial construction.

## Observe ABI and record

Call the retained `observe` symbol from a separate external task/code/stack,
eight-byte aligned. There are no incoming arguments and no status contract in
r0; read the fixed record at OWNED+100. It writes no lifecycle fields. It calls
`tk_ref_tsk` (`C01F54CC`, 32 bytes) and `tk_ref_flg` (`C01F5460`, 12 bytes) directly,
preserving signed statuses. It never calls the boolean completion helper or
`tk_wai_flg`. Task ID zero is skipped, preventing accidental reference of the
observer's own task. Other invalid IDs reach the real invalid-ID paths.

Each sample starts with A5-filled output bytes. Skipped statuses are `80000000`
(INT32_MIN), distinct from a firmware result. Invalid task ID returns -18 with
unchanged output; missing valid task returns -42 with zeroed 32-byte output.
Invalid/missing flag returns -18/-42 with unchanged output. Only rc=0 permits
interpretation of its output. A skipped/failed sample never inherits last
observation's successful values.

The observer reads identity before and after each query pair. It dereferences
the holder only if nonzero and equal to the saved native object. A changed
holder is recorded but not followed. Retained lifetime makes the saved object
readable under the single-owner contract; this is not a general pointer validator.

Record size is exactly **0x100 bytes**. Header/tail offsets are record-relative:

| Offset | Meaning |
|---|---|
| 00 | observation number, incremented on entry, wraps |
| 04 | 0 in progress, 1 after a DMB at completion |
| 08 / 0C / 10 | phase / DONE / ONCE before the samples |
| 20..7F | sample A, layout below |
| 80..DF | sample B, same layout |
| E0 | evidence bitmask, below |
| E4 | compiled optional sleep reason (0 disables) |
| E8 / EC / F0 | phase / DONE / ONCE after the samples |
| other header/tail words | reserved, initially zero; not a timestamp |

Each 0x60-byte sample contains:

| Offset | Size | Meaning |
|---|---:|---|
| 00 | 20 | before identity: holder, task ID, historical body+4, active body+8, flag ID |
| 14 | 4 | signed task-reference status or skipped sentinel |
| 18 | 4 | signed flag-reference status or skipped sentinel |
| 1C | 32 | raw task-reference output |
| 3C | 12 | raw flag-reference output |
| 48 | 20 | after identity, same five fields |
| 5C | 4 | A5-filled reserved word |

Task words are exinf, current/base priority representations, state, wait reason,
waited object ID, queued wake count, and raw counter. Flag words are exinf,
first waiter ID, and pattern. Their exact source fields are in the audit.

### Evidence bits, not lifecycle permissions

| Bit | Meaning |
|---|---|
| 01 | all four identity tuples agree; holder nonzero and holder/task/flag match saved creation identity |
| 02 | both task statuses are 0 and both exinf fields equal saved native object+4 |
| 04 | both flag statuses are 0 |
| 08 | bits 01/02/04 all hold; phase is 4 and DONE/ONCE are exactly 1 before and after; historical body is this owned body; active body is zero in all tuples; both flag patterns have bit 1 |
| 10 | bits 01/02/04 all hold; optional reason nonzero and matches both task samples; both states are exactly waiting (4), waited object IDs and wake counts zero |

Bit 08 is retained **native-completion evidence** under this single-attachment
contract. The constructor's initial flag=1 cannot satisfy it: no attachment,
DONE, ONCE or historical body has been established. Pausing with DONE=1 before
the native post-return code also cannot satisfy it. Conversely it can become
true before the next native sleep. Bit 10 is only a **sampled sleep diagnostic**,
independent of completion; an unattached worker may already be sleeping.

Two query samples and four identity tuples are not an atomic snapshot. The
worker can change between reads; agreement does not exclude ABA or a transition
immediately afterward. The record's counter/complete marker is not a lock, a
multi-host lease or proof of atomic host readback. Concurrent external commands,
reattachment, native-object destruction, or reuse are outside this prototype's
contract. Uncertain observations retain ownership and may simply end diagnostics.

Reference kernels can call the scheduler on exit. “Nonblocking” here means
no object wait; neither the fixed query count nor the emulator instruction cap
proves wall time. There are no timestamps, fake deadlines or freshness claims.

## Immutable code and readback extent contract

For a future host implementation, resolve symbols from the exact assembled
artifact and bind the entire allocation to this boot. Do not infer an address
from another candidate. This fixture's checked, non-overlapping extents are:

| OWNED-relative extent | Contract |
|---|---|
| 0000..003B | owner control and stable body/vtable/identity words |
| 0100..01FF | observation record |
| 1000..1FFF | retained wrapper/name/literal bytes: **entire extent immutable** |
| 2000..2FFF | capture reservation: immutable except six named scratch words |
| 4000..47FF | capture state/ledger, 2048 bytes |
| 5000..7BFF | output plus sentinel guard, 11264 bytes, capacity 1200 records |

The staging artifact is 12288 bytes: launcher at +0..FFF, resident wrapper at
+1000..1FFF, capture at +2000..2FFF. Entry copies only the latter 8192 bytes into
owned storage, so staging can be poisoned after return. The resident body,
vtable, capture references and task name have no surviving staging references.
The fixture tests that property through executable and data-access guards.

Read back the whole 4096-byte retained wrapper exactly. Read back the entire
4096-byte capture and compare it using `fpl_gyro_latched.verify_code`; its only
permitted differences are four-byte words named `g_ghead`, `g_gcount`, `g_padbad`,
`g_latched_head`, `descriptor_ptr` and `descriptor_ring`. In this exact capture
they are at offsets 4A4, 4A8, 4AC, 4B0, 4B4 and 518, respectively. Obtain those
offsets from symbols when rebuilding. The runtime reference table at 490..4A3
is **immutable**, including state/output extents and capacity. Do not mask the
entire descriptor, table, code page or padding to accommodate a mismatch.
Also validate the retained body/vtable/capture pointers and saved holder/task/
flag identity; those control words are not capture scratch.

Read the full 2048-byte state and 11264-byte output reservations, not merely the
reported record count. Validate the existing capture ledger and sentinel guard;
`lat.decode` still reports proven-valid records as zero. Preserve the 256-byte
observation, raw signed statuses and native identity records together. A bad or
partial readback is inconclusive and retains everything. None of the readback
checks is a release predicate. No host readback/allocation implementation is
introduced here; the test-only reader exercises this contract against memory.

For this build (`OWNED=46000000`), symbol offsets are entry=0, activate=1000,
body_entry=1070, observe=118C. These are evidence, not a stable host ABI promise.
Hashes identify offline candidate bytes only, with no runtime pairing check:

| Diagnostic | Whole 12288 bytes SHA-256 | Retained 8192 bytes SHA-256 |
|---|---|---|
| default reason 0 | `c9978ffe4a5e2a923cd40e33309c1d09302a4f4656e168420b9fdd65088d4663` | `34ce7d70002ab8fc9005965848a8aee5016c15eade70cb8662bf5dec0d41c2a0` |
| optional reason 1 | `e71811057c7bc6a274b5e6e70a3a0f2293041884266d24229f086755bd4595be` | `14abaaa12549774c9f31cb4e958bb808694d82ac2be8e2129cc3434beac4757e` |

## Tests, mocks and reproduction

From `fp_usb_shell/`, with Clang's ARM target, Capstone and Unicorn available:

```sh
FPL_MAIN=/path/to/official/FPL_V302/MAIN.bin \
  python3 -B -m unittest test_fpl_gyro_task_retained
```

Artifacts are assembled in fresh temporary directories, not installed. The
fixture extends the stable task test harness without modifying it and replaces
its task-reference and flag-set mocks with real firmware execution; flag
reference is also real. The exception dispatcher remains an explicit
stub-to-kernel bridge using the audited service table. IRQ helpers and the
32-byte zero helper execute as instructions. Scheduler effects are counted and
returned without a real context switch. Native allocator backend, creation,
start/wake/sleep scheduling, native IRQ-wrapper boundaries, assertions, libc/
cache calls and capture delay remain explicit mocks. Sleep state/reason are
synthetic scheduling fixtures, not emulated proof of a hardware park.

Verification passed: **13 retained-variant tests; 100 tests combined** with the
existing finite capture/host, latched, coherence, relocation and stable task
suites. The five negative source variants are subcases of the retained suite.

The native no-body self-exit boundary is stopped, not modeled as task deletion.
All task/object/storage ownership remains retained even at that stop. The
single-core scheduler fixture and two stack phases do not certify cross-core
visibility, real-time latency, exception-mode dispatch or all interleavings.

Coverage includes initial flag vs attachment, DONE before native return,
publication before sleep, exact raw output snapshots, both stack phases,
repeated queued wakes, wake after completion, self-reference error, dormant
start failure, allocation/creation/attachment assertions, invalid and missing
IDs with stale-buffer protection, exinf mismatch, changing holder/task-related
identities, duplicate commands, optional sleep-reason mismatch, immutable/code
and reference-table readback rejection, and scheduler entry from observation.
Capture produces the fixture's expected 950 records over 20 finite delays;
duplicates do not reinitialize or append to those results.

Five intentional source mutations independently fail: body-object ABI,
callback into poisoned staging, missing call-stack alignment, removed one-shot
guard, and wrong exinf expectation. Memory hooks restrict query writes to their
32/12-byte output extents and disallow writes to immutable resident code after
installation. Forbidden lifecycle entrypoints fail immediately if reached.

No live/card action, commit or push was made. No AutoRun change is needed for
this offline prototype, and no card packaging is claimed. The main session owns
the shared log; this document records only this variant's contract and evidence.
