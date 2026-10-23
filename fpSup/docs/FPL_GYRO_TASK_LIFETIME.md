# fp L finite gyro task: offline lifetime prototype

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. **Disposable offline prototype, not a card, live runner or production
worker.** Only `asm/fpl_gyro_task_prototype.S`, `test_fpl_gyro_task.py` and this
document belong to this slice. The complete `SUP_BUILD_RULES.en.md` was read.
Existing capture, shared drain, loader, worker, builders and transport sources
are unchanged by this slice. The historical test record reports a successful live
runtime-reference capture (20 observations, 1114 records, guards/PONG good);
that is evidence for the finite capture, not this new task lifecycle.

## Result and scope

An emulated launcher copies an owned resident body, publishes D/I, creates a
native parked pool worker, and returns. A separate explicit external call attaches
the actual relocatable capture. The task invokes the unchanged capture body,
returns into the native pool, and parks again. An external caller joins, reads
and validates results, then destroys the native thread holder. Only after that
caller has returned to independent code/stack does the test unmap the reservation.

**The capture is finite; the complete native lifecycle is not proved bounded.**
`XT_JOIN` passes an infinite timeout. Several native failure paths assert rather
than return a status. `sta_tsk` failure is ignored by the native constructor.
There is no release on an uncertain join or incomplete destruction, and no
automatic retry of partially completed destruction. These are explicit blockers
to treating this as a safe autonomous/live logger, not issues an emulator pass
resolves. No new live allocator, polling manager or generic lifecycle framework
was added.

The emulator checks real stock ARM instructions against official fp L 3.02 MAIN:
49,310,208 bytes, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
The test fails if this image is missing or differs. Discovery used addressed
Capstone disassembly of the official image. Unlike the earlier bounded recording
audit, the execution test includes the complete join routine and follows the
constructor/destructor and worker dispatch paths below.

## Native ABI, verified instructions and limitations

| Entry | Actual behavior exercised |
|---|---|
| `C036E320` `XT_CREATE(&holder,pri,stack,name8)` | Requests a 0x14-byte native object, constructs it, writes its pointer to `holder`, returns **address of holder**. Test checks holder contents, not return r0. |
| `C036E5A8` allocation adapter | Calls allocator singleton `C2F2F298` virtual slot +C. Null result reaches assertion `C0011130`; the outer create's null branch is not proof of graceful allocation refusal. |
| `C036E6A0` construction adapter | Dereferences saved priority/stack/name arguments, calls `C036E0D0`, installs the derived vtable at object+10. |
| `C036E0D0` constructor | Clears task/body/flag fields, creates completion flag initially set, constructs T_CTSK, creates and starts worker `C036F200`. Nonpositive flag/task ids assert. `C036E22C` calls `C0016BC0` (`sta_tsk`); its return is **not tested**. |
| `C036E3D0` `XT_ATTACH(&holder,body)` | Loads holder and calls `C036F0B0`. Pass the address of the body object, not the vtable address stored in it. There is no reliable boolean return contract. |
| `C036F0B0` attachment | Clears completion bit with AND mask FFFFFFFE, validates task/body, writes body to native object+8 and +4, wakes task. Wake result 0 or -41 is accepted; other results assert. |
| `C036F200` pool worker | Sleeps, then calls `body->vtable[+C](body)`. After body return it checks wake state, clears object+8 and sets completion flag before looping back to sleep. |
| `C036E410..C036E448` `XT_JOIN(&holder)` | Calls `C0016C08(flag,1,0,&observed,-1)`, fifth argument on stack. Returns that wait's status, with no timeout wrapper. The prior audit's 0x20-byte prefix did not cover the entire wait call. |
| `C036E380` `XT_DESTROY(&holder,2)` | Dispatches native object+10 vtable slot +8 with flags 3; flag 2 keeps caller-owned holder storage. Does **not** clear holder. |
| `C036E620` derived destructor | Calls `C036E240`, then frees native object through allocator virtual slot +10 when required. |
| `C036E240` base destructor | May join if body+8 remains; clears it, wakes/terminates/deletes task, deletes flag. Delete-task/flag errors assert; wake and terminate statuses are not independently checked here. |

The native worker's body return is not a task exit. Our body never calls
`tk_ext_tsk`. The native pool itself has a no-body branch at `C036F248` calling
`C01F52D4` (stub materializes service 80040000); the successful capture path does
not take it. This prototype neither certifies that service nor depends on it
for cleanup. Destruction runs externally and its scheduling boundaries are
modeled, as explained below.

Prototype-to-firmware and body-to-capture calls are eight-byte stack aligned.
Native internal prologues do not uniformly preserve that alignment, so
`body_entry` saves original SP and aligns a temporary call stack before invoking
capture, then restores the original SP before returning to the pool. Tests use
both possible four-byte stack phases at worker entry. They do not rewrite stock
instructions to impose a different ABI.

## Ownership and invocation sequence

The fixture supplies a separate, initially zeroed **64-KiB owned reservation**.
This is a synthetic successful allocation, not a grant to use that address live.
No prototype code allocates or frees it. Compile-time `OWNED` has size/domain/
alignment checks; the fixture validates complete artifact and embedded capture
sizes. The fixture's reservation and staging are separate allocations:

| Relative to OWNED | Use |
|---|---|
| +0000..0037 | Owner control, holder, body object, vtable and result-lifetime words |
| +1000..1FFF | Retained activate/body/join/retire code and name |
| +2000..2FFF | Actual current relocatable capture, padded to its 4096-byte reservation |
| +4000..47FF | Capture state/ledger |
| +5000, 11264 bytes | Output plus sentinel guard, capacity 1200 records |

`build()` calls current `fpl_gyro_latched.code_for(..., runtime=True)` and embeds
those exact bytes with `.incbin`. It does not copy the capture or drain algorithm.
Its runtime table already points to the retained state/output. `entry` copies
the complete 8192-byte resident image, initializes owned body/vtable/capture
pointers, then calls `C000E91C` followed by `C000EABC` before creating the task.
The native holder is retained at OWNED+4, body at +8, vtable at +10 with callback
at +1C. The task name also lives in the retained image.

The launcher's r0 is its **own entry address**, as in the shared loader ABI; it
does not reinterpret r0 as an owner/configuration object. Status is retained in
owned words rather than used by a loader entry chain. This prototype does not
implement allocation discovery, standalone product packaging or pass-2 sections;
its compiled synthetic reservation means it is not a deployable loader product.
It adds neither a loader nor a third pass nor a shared pool publication.

Sequence exercised:

1. Owner supplies reservation/capture references and zero control words. Staging
   contains launcher plus initial resident image.
2. `entry` installs/creates, then returns **without attaching the capture**.
   Native constructor clears its body pointer before starting the worker.
   Scheduling that worker while unattached only parks it.
3. Owner invalidates/poisons staging and calls retained `activate` externally.
   Only now may capture work run. This separation avoids assuming task priority
   or scheduling can ensure entry returns before an attached body starts.
4. Worker calls owned vtable slot +C, capture completes, and body returns. A
   private DONE word alone is not a join: native pool must clear its callback
   and signal completion after that return.
5. External `join` requires wait status 0, DONE=1 and native object+8=0 before
   setting phase joined. Failed or unreturned waits retain every allocation.
6. Owner reads and validates capture code/state/output. `retire(r0=1)` is an
   explicit **trusted external readback acknowledgement**, not a claim that
   camera assembly can prove host readback. Without it, retirement is refused.
7. External retirement attempts native destruction once. Only a returned
   destructor clears retained holder/body/vtable/capture pointers and marks
   release-ready. The test releases memory after returning to independent code
   and stack, never from the worker or while retirement code is executing.

Control phases: 0 unattempted (or a returned null holder), 1 creation attempted,
2 created/unattached, 3 attachment attempted, 4 joined, 5 retired, 6 destruction
attempted. DONE +24, last join status +28, readback acknowledgement +2C,
release-ready +30 and null-holder error +34 are separate words. Sequential
duplicate entry/activation is refused without resetting live state. This is not
an atomic multi-caller launch protocol. Phase 1/3/6 can remain indefinitely on
native assertion or nonreturn; the owner must retain memory rather than infer
that no references escaped.

## Emulator boundary and promotion blockers

Real instructions execute the four public wrappers, allocator adapter,
constructor, attachment body, pool trampoline and both destructor layers. Full
firmware fingerprint and explicit executable ranges prevent silently following
unknown callees. Firmware data/vtables are read from that image. The allocator
singleton itself is synthetic because it lies beyond the file-backed image.

Mocks are explicit: allocator virtual allocate/free; RTOS flag create/clear/
set/wait/delete, task create/start/wake/sleep/reference/terminate/delete; native
assertions; memset, bounded name copy and special-name comparison; IRQ guard
boundaries; D/I cache calls; and capture's delay. The delay advances a synthetic
raw-ring producer by 50 records. No capture function or public thread wrapper
is mocked. Native assertions raise a test exception instead of inventing a
successful return. Infinite waits without a signaled flag stop as `WaitBlocked`.

The scheduler is deliberately narrow: create records a native task; tests run
its real trampoline with a separate stack, wake once for capture, and stop at
the next sleep. Destruction's wake/terminate/delete execute without interleaved
task scheduling. The mocked delete refuses a task not successfully terminated
and removes its pending wake on success. This proves fixture ownership and
call ordering, **not real RTOS cancellation/quiescence, cross-core cache behavior,
all scheduling interleavings or power-off lifetime**. Those require further
kernel evidence and separately authorized testing before any live adoption.

In particular, the existing pool API cannot honestly supply a bounded safe
join/creation-refusal contract just because its addresses are known. This slice
stops at that exact boundary. Do not add a timeout and free the still-referenced
body, treat a create-holder address as success, assume attach returns a boolean,
or take an ignored task-start status as evidence that a task is runnable.
There are no REC/IMU hooks, calibration claims or recording/file operations.

## Acceptance and reproduction

From `fp_usb_shell/`, with the ARM assembler and Unicorn available:

```sh
FPL_MAIN=/path/to/official/FPL_V302/MAIN.bin \
  python3 -B -m unittest test_fpl_gyro_task
```

Eight tests pass: normal lifecycle with both worker stack phases; sequential
duplicate launch/attach; native allocation/flag/task-create assertion failures;
attach refusal and ignored start failure; blocked/error/false-success join;
partially failed destruction without retry; failed readback retaining storage;
and three intentionally broken temporary source variants. The variants pass a
vtable instead of a body-object address, publish a callback into poisoned staging,
or remove call-stack alignment; independent execution/ABI oracles reject each.
Real capture emits 950 expected raw records in these fixtures, twenty delay
calls, and proven-valid count zero. The difference from live record counts is
the explicit synthetic producer, not a timing/calibration measurement.

The combined existing finite/strict/coherence/relocation suites plus this task
suite also pass: **87 tests**. Their default fp Base, fixed-latched and strict
byte-regression checks remain intact.

Artifacts are built only in temporary directories and identified for this
fixture (`OWNED=46000000`), not handed over as a runnable card:

| Bytes | SHA-256 |
|---:|---|
| 12288, whole prototype | `61a6455a9ac45263209c9bf2f8c5a43990de5b5658cb9b42fdb50131a4dcd1fe` |
| 8192, retained image | `a798f5852b7622afc20b2f67bc5a0f09946e1c91b7f7cab3c8f5353380dc89ad` |

No AutoRun change, card build, live operation, commit or push was made. Tests do
not instantiate a transport backend. The prototype remains separate from the
validated finite probe and can be removed without changing a product interface.
