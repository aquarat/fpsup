# fp L native completion and task-state audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. Offline evidence for fp L 3.02 only. Owned deliverables are this
document and `tools/fpl_thread_completion_audit.py`. The stable task prototype
and production sources are not changed by this audit.

## Conclusion

**Direct `tk_ref_tsk` and `tk_ref_flg` provide object-nonblocking observations
without calling infinite `XT_JOIN`.** Preserve their signed return codes and
interpret output only on success. They can distinguish an existing dormant
task from a started task and observe native completion after callback return.
They do not establish a wall-time deadline, an atomic combined snapshot, or
permission to reclaim anything.

Retaining the worker, native flag/object, body/vtable, executable reservation,
state, output and all referenced storage is the supported first-trial direction.
Completion can precede the worker's next sleep. No destructor, terminate/delete,
free, reuse or unmap follows from this audit, even after a successful observation.
No live implementation or camera trial was performed.

## Firmware and reproducibility

Official decompressed MAIN is 49,310,208 bytes, mapped at `C0000000`, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
The tool rejects other bytes before execution, needs Capstone and Unicorn, and
imports no camera/transport code:

```sh
python3 -B tools/fpl_thread_completion_audit.py \
  --main /path/to/official/FPL_V302/MAIN.bin --self-test
```

Verified result: **25 fingerprinted instruction ranges, 44 execution scenarios,
13 negative cases**. JSON includes each range's address, size and SHA-256,
scenario results, mocked boundaries and `release_authorized: false`. Ranges
include static-only evidence; listing a range does not claim every instruction
or branch in it was executed. No firmware bytes are emitted.

## Binding through the actual dispatcher

ARM stubs call `C00011D0`, with a service word in r12. The dispatcher extracts
the signed high half as an index; `[C0001568] = C0021040` is its table base.
The signed indexing, rather than an assumed SDK syscall list, resolves:

| Interface | Stub | Service | Table slot | Kernel |
|---|---|---|---|---|
| `tk_ref_tsk(id,out32)` | `C01F54CC` | `800F0200` | `C000107C` | `C000B328` |
| `tk_ref_flg(id,out12)` | `C01F5460` | `80250200` | `C00010D4` | `C00040A0` |
| `tk_wai_flg(id,wanted,mode,out4,timeout)` | `C0016C08` | `80240500` | `C00010D0` | `C0003E78` |
| `tk_set_flg(id,bits)` | `C0016B9C` | `80220200` | `C00010C8` | `C0003C58` |

Arguments use r0 onward; flag wait's fifth argument is at caller SP. The stub
retains that SP in r4 and the dispatcher forwards the fifth argument. Signed
status is returned in r0. Use writable, aligned, correctly sized output storage;
these routines do not supply pointer validation or protect a bad caller buffer.

### Task reference: exact 32-byte output

For positive IDs, TCB address is `C3000838 + id*132`. Accepted IDs are 1..500.
ID zero selects current task only when context counter `C3033268 <= 0` and
current TCB `[C3000098]` is nonzero; otherwise zero fails as invalid ID.
Use the retained native object's positive task ID for external observation.

| Offset | Successful output / source |
|---|---|
| +00 | exinf, TCB+0C |
| +04 | current-priority representation: unsigned byte TCB+22, plus one |
| +08 | base-priority representation: unsigned byte TCB+21, plus one |
| +0C | exported state, conversion below |
| +10 | first word of descriptor pointed to by TCB+28, if internal state has bit 2; otherwise zero |
| +14 | waited object ID, TCB+2C, if internal state has bit 2; otherwise zero |
| +18 | pending wake count, TCB+30 |
| +1C | raw counter, TCB+34; no stronger semantic name established here |

State conversion from byte TCB+23:

| Internal | Exported | Evidence / interpretation |
|---|---|---|
| 1, current TCB | 1 | currently running |
| 1, another TCB | 2 | ready |
| 2 | 4 | waiting |
| 4 | 8 | raw state mapping; stronger naming not required here |
| 6 | 12 | waiting bit combined with internal 4 |
| 8 | 16 | dormant |

`C000A4C8` initializes dormant state 8; start kernel `C000ACE8` requires it,
then calls ready-enqueue code `C000A548`, which writes internal state 1.
These are static instruction traces, not a full emulation of task creation,
context switching or the start scheduler.

Success returns 0. Invalid ID returns **-18**, leaving output untouched. A valid
ID with state zero (no task) returns **-42**, with **all 32 bytes zeroed**.
The native zero helper `C0015808` takes a word count: argument 8 means 32 bytes.
Never interpret the zeroed missing-task record as a successful task state.

The constructor at `C036E0D0` supplies `thread_object+4` as T_CTSK.exinf.
Thus a successful external reference can correlate ID and identity through
output+00. The constructor calls `sta_tsk` at `C036E22C` and ignores its status.
A non-null holder therefore proves neither successful start nor execution.
An identity-matched dormant snapshot detects the dormant outcome; a ready,
running or waiting snapshot is evidence of a started task under this lifecycle.
It does not recover the ignored status or prove capture ran. Missing/error/
identity mismatch is inconclusive for ownership and must retain storage.

### Flag reference: exact 12-byte output

Accepted IDs are 1..300; flag control block is `C3011428 + id*32`.

| Offset | Successful output |
|---|---|
| +00 | exinf, flag control block+0C |
| +04 | first waiting task's ID, or 0 for an empty queue |
| +08 | current flag pattern, control block+14 |

Returns 0 on success, **-18** on invalid ID, **-42** on missing flag. Both errors
leave output untouched. Reference neither waits for nor clears completion bits.
The native wrapper `C036E3F0(&holder)` calls `C036F1B0(object)`, which references
object+0C's flag and returns `pattern & 1` on success, **0 on any error**.
Prefer the direct reference to preserve missing/error versus incomplete.

### Zero-time flag wait: available, but less suitable

`tk_wai_flg(id,wanted,mode,&observed,0)` returns immediately from the object-wait
logic: 0 on match, **-50** on miss, without enqueuing a wait or installing a timer.
Positive timeouts and -1 enter blocking logic on a miss; -1 is what `XT_JOIN`
uses. Those paths are intentionally stopped before blocking in this emulator.

Mode 0 means AND; bit `0x01` means OR. Bit `0x20` clears requested bits on
success; bit `0x10` clears all bits. Only mask `0x31` is accepted. Successful
output is the **pre-clear pattern**. Both clear bits may be combined.

Errors, in checked order: invalid ID **-18**; zero wanted mask, unsupported mode
bits or timeout below -1 **-17**; disabled dispatch, positive context counter,
absent current task or IRQ/FIQ-masked context **-25**; missing flag **-42**;
another waiter without flag attribute bit 8 **-41**. All failure/miss paths leave
the caller's observed-pattern word untouched. Individual parameter/context
branches are inspected; execution scenarios cover representative errors rather
than every combination or precedence permutation.

A miss still writes the current TCB's wait descriptor and scratch fields.
`C000E058` stores -50 through the temporary result pointer and returns at
`C000E07C` for zero timeout. This is non-enqueueing, not mutation-free. Direct
flag reference avoids those scratch writes and accidental clear-mode behavior.

## Completion ordering and the initial-flag trap

The constructor descriptor at `C0BBEA7C` starts `{exinf=0, attr=0x49, pattern=1}`.
**Before attachment, flag bit 1 is already set.** An initial successful query
cannot mean a submitted callback completed. Attachment `C036F0B0` clears that
bit with AND mask `FFFFFFFE`, stores body in object+8 and object+4, then wakes
the worker. Attach is not a reliable boolean-success API.

Actual pool-worker ordering:

1. Sleep call at `C036F21C`; after waking, invoke body vtable+0C at `C036F23C`.
2. Callback returns to native code. Self-reference task at `C036F284` reads
   output+18, the pending wake count.
3. On successful self-reference with zero wakes, **or on self-reference error**,
   clear object+8 at `C036F2AC`, then call set-flag(bit 1) at `C036F2B8`.
4. Restore the native guard and loop toward the next sleep. Publication therefore
   occurs **before** the next sleep is entered, let alone completed as a park.

With a successful query and nonzero pending wakes, object+8 remains attached and
completion stays unset. A later iteration may invoke the body again. A self-query
error instead takes the completion-publication branch; it does not certify zero
wakes. The worker also does not check the set-flag return before continuing.
Object+4 retains the historical body pointer after object+8 is cleared.

The execution oracle covers zero wakes, one queued wake, and real self-query
failure (-18 caused by unsuitable context for id zero). It executes real native
post-return instructions and real reference/set kernels, stopping at the next
sleep **entry**. It explicitly reports `parked_proven: false`.

Consequently distinguish:

- Private DONE: may be written before the callback's final return; insufficient.
- Native completion after a known attachment: evidence of callback return and
  body-slot clearing on this path, not evidence of sleep or safe reclamation.
- Waiting task snapshot: evidence of waiting at that sample, not necessarily
  this particular sleep and not a promise it will remain parked.

The sleep kernel `C000BD90` stores descriptor pointer `C2F06B48` in TCB+28 and
zero in TCB+2C before its wait transition. The numeric descriptor word itself is
beyond file-backed MAIN. **Its runtime wait-reason value is not established.**
The query exports the dereferenced word, not the descriptor pointer. Do not
invent a numeric sleep reason or equate any state-4 snapshot with pool sleep.

## Retained-only observation contract

For a separately authorized future implementation, retain all ownership and
record direct query statuses and raw successful records. Correlate task exinf
with the retained native object. Associate completion with a known single
attachment, not merely initial flag=1; prohibit concurrent attach/reuse during
the observation. Preserve evidence of callback return, native body+8 detachment
and flag bit 1 separately from task state. Native object/body reads and the two
queries are **not one atomic snapshot**. A missed transient flag-clear sample
cannot by itself prove attachment failed or completion succeeded.

This supplies a non-waiting alternative to infinite join for diagnostics. It
does not implement a live caller, choose a retry deadline, or prove the worker
has no current PC in owned code from an arbitrary flag sample. The documented
native ordering supports return-to-pool only with the lifecycle/identity
conditions above. Keep executable and data ownership even when those conditions
hold. A finite observation budget may stop observing; it must not trigger cleanup.

## Execution boundary and remaining limits

Real instructions execute query stubs, query kernels, zero-word helper,
queue-first-ID helper and IRQ save/restore helpers. Completion traces additionally
execute native worker instructions and flag-set kernel with an empty waiter
queue. Synthetic memory supplies TCBs, flag objects and BSS. Wait-reason data in
the fixture is deliberately synthetic, not a recovered firmware constant.

The exception dispatcher is statically traced and bridged at `C00011D0`; full
exception-mode entry/return is not executed. Scheduler `C0000CFC` effects are
mocked and counted. Completion traces mock body return, sleep entry and native
IRQ-wrapper boundaries. They do not execute the capture body or prove scheduling
interleavings, cache visibility, cancellation or real task quiescence.

Even reference calls may reach the scheduler on exit. **Nonblocking here means
no object wait, not bounded wall time or transport latency.** The emulator's
instruction cap is a test guard, not a firmware deadline. There are no timestamp,
sample-rate or freshness claims.

Negative cases reject four whole-image/size mutations, four semantic/binding
mutations with the fingerprint bypassed, and five execution mutations with all
static guards bypassed: wrong task output offset, wrong flag output offset,
wrong poll-miss status, wrong clear-mode bit and wrong callback-clear offset.
The last is caught by independent ordering/body-slot assertions. No destructor
or release path is exercised or proposed. No camera, card, commit or push actions
were taken.
