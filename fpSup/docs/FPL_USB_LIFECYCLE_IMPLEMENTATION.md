# M1 USB lifecycle implementation — bounded closed admission

2026-10-23. **Partial implementation, offline only. M1 is not complete.**

The new `FPSUP_USB_CLOSED_ADMISSION=1` assembly option refuses **all** fp L
transport admission, including otherwise-ready mode 5. It is a testable
closed boundary, not a working shell, a cancellation fix, or a candidate for
installation. The supported active-lifetime set is currently empty. No tested
lock/reopen protocol justifies opening it. Default/explicit-zero builds retain
the reviewed resident bytes, behavior and the three existing lifecycle xfails.

## Why this bound, rather than a successful-looking mode/status guard

Read the lifecycle, wait-status and generation-boundaries notes together. The
existing official-image generation audit was rerun for **both** images: 22
scenarios and four coverage mutations each passed. In particular:

* fp L controller semaphore `C31E161C` covers run/one stop body, not bulk
  StartTransfer, EndTransfer, reset, init pointer publication or alternate stop.
  Acquiring it in the worker is not exclusion against those writers.
* StartTransfer can enter command polling → retry → global teardown → the
  semaphore-taking stop. Holding the one-count semaphore around submission
  introduces an unsupported nested acquisition, not a proven recursive lock.
* EndTransfer captures the current resource before `C01E368E` stores `0x80`.
  Its endpoint-only ABI cannot identify which submission authorized cleanup.
  The audit's replacement injection between capture and store corrupts the
  replacement's resource. Same-pointer/resource reuse within one global epoch
  defeats an epoch-only cleanup guard as well.
* Init publishes the DMA table at `C01DF97A` before reset. Configuration disables
  DALEPENA at `C01E0BA8` while configured can still be nonzero. Configured/run/
  mode samples are not admission grants or final reopen commits.
* Old StartTransfer's error unwind at `C01E3512` can write status after nested
  global teardown has returned. A new owner cannot be admitted at stop return.
* Stock Wait can return 0 after reset; -1/HWO-clear covers both the compatibility
  fixture and cancellation. Return classification cannot undo Wait's mutations.

These are bounded actual-instruction counterexamples with synthetic hardware
outcomes, not a proof about every firmware caller or a live failure diagnosis.

### Submission-specific rights required before enabling admission

The intended contract is: admission and close serialize through an evidenced
common owner; each admitted submission receives a unique ticket containing its
lifetime, endpoint, pinned CPU/DMA descriptor and buffer, then assigned resource.
Every in-flight mutating call retains its original ticket through nested calls.
An endpoint cancellation invalidates that ticket before resource capture; a
global close invalidates all affected tickets before any destructive operation.
Cleanup atomically compares its original ticket against the current endpoint
owner before resolving tables or calling EndTransfer. A completed transfer must
have completion provenance independent of status/HWO, not just a matching epoch.
Reopen requires configuration completion **and all older mutating frames drained**;
nested teardown must not join/wait on its own outer submission.

No common synchronization, complete writer coverage, completion provenance or
final reopen commit has been established for that contract. Therefore this
patch does not issue tickets, install guessed hooks, allocate a pretend epoch,
hold interrupts across blocking calls, or expose a RAM switch that can reopen
admission. The concrete next blocker is establishing that atomic ownership/
drain boundary across the listed native paths, including old error unwind.

## Implemented behavior

Only `fp_usb_shell/camera/worker.S` changes production source. The option is
boolean and rejected at assembly time for cameras other than fp L 3.02.

* `spawn` returns normally without allocation, publication, task creation or
  start. Thus a closed-profile boot entry cannot create a second server or
  treat a pre-existing pool as permission to reuse it. Return 0 is the existing
  entry ABI, not a readiness indication; stage2 does not interpret it.
* The relocated body's `next_round` closes **before the SWAP check**, so it
  neither consumes a pending request nor jumps to another body.
* Stale command-dispatch, MEMW admission and both MEMW cancellation entries
  branch to the closed path. It clears only the worker's deferred cleanup
  intent (`STATE+08`), records `CLOS` in the previously unused owned word
  `STATE+38`, and yields through the existing 50-ms hold loop. It does not call
  EndTransfer, claim cancellation, clear HWO, free memory or reclaim DMA buffers.
* OUT/IN/raw-IN arming, `out_owned` and `wait_done` refuse with -1 before any
  descriptor/table access or stock transport call. An unowned wait therefore
  cannot mistake a cancellation-cleared or replacement descriptor for success.
* No active transfer is supported. In particular, -1 here means **admission
  refused**, not a new interpretation of native Wait's -1. The candidate is
  not a compatible way to tolerate lost completion flags.

The body-entry tests supply a valid owned pool and state. They are fault-injection
tests of the refusal boundaries, not permission to hot-enter this body from a
live legacy worker with DMA outstanding. The supported normal candidate entry
is `spawn`, which never starts it. Internal legacy bodies remain in the image
for byte-preserving conditional compilation and mutation controls; arbitrary
entry into their middle is outside the contract.

This is deliberately narrower than a universal lifecycle state machine. Global
NOPTP2 suppression remains a separate stock-mode interoperability problem: a
worker refusal cannot restore it. No ordinary card is packaged with this option.

## Executed tests and exact baseline preservation

From `fpSup/fp_usb_shell`, with an ARM-capable `clang` on PATH:

```sh
python3 -B -m unittest -v test_fpl_worker_closed_admission
python3 -B -m unittest -v test_fpl_worker_lifecycle test_fpl_worker_dispatch
python3 -B -m unittest -v test_worker_mem test_worker_upload test_putfile_mem1 \
  test_fpl_swapworker host.tests.test_mem_host host.tests.test_upload_host
```

Results: **11 new refusal tests pass**; existing lifecycle/dispatch tests have
**24 passes and exactly 3 expected failures**; default fp MEM1/upload and host/
reviewed-handoff regressions have **42 passes**. No skips or unexpected failures.
No golden hashes or xfail decorators were changed.

The new suite executes real emitted ARM from the relocated body. It checks
foreign modes and mode5 alike; pending cleanup with a replacement pointer;
all arming/claim/wait entry points; stale dispatch and MEMW cancellation entries;
repeated hold rounds with synthetic same-address reconfiguration between rounds;
untouched SWAP requests; and allocation-free spawn. CPU memory hooks reject
transport reads as well as writes. Stack balance is checked by the shared harness.

Mutations remove individual real ARM refusal branches: admission exposes legacy
driver reads; wait executes the actual cancellation/replacement interleavings
and returns the old false success; stale MEMW abort invokes EndTransfer on the
current endpoint. The exclusion oracle rejects each mutation. These are not
scheduler, DWC3 or cache simulations. In the unmutated closed profile no wait
or transfer is in flight; the original three active-transport defects are
**still unresolved**, not relabelled as passing synchronization tests.

The unchanged reviewed body identities remain:

| Build | Body bytes | SHA-256 |
|---|---:|---|
| fp L legacy `FPSUP_PONG_ACK=0` | 3572 | `48d3b2f4fec039c0c6141c61d4e496ea443e9685468f43366cbfd667271c8668` |
| fp L default PONG | 3572 | `e2b94aeb67938dbb05f581ca6f8ec5aff1e84dfe7dd34de11a1b76e0c7f2b342` |
| fp default | 3476 | `488e016fb270c83f4208144a4ca7aaab6c616c79e14c1fd5bfe64faa45fd4495` |

`fpl_swapworker.reviewed_body(False/True)` still rebuilds both reviewed fp L
images and validates its old symbol offsets. The host allowlist/updater is
unchanged. The new body is **3644 bytes**, hash
`9f1d6760afd6b2942290317e30df6a3768c077d5033c229ca1e917db8bdcdd51`,
and is explicitly tested **not** to be in the live allowlist. Whole standalone
assembly is 4096 bytes, hash
`e90ce02525e54046536ca3f41beab04921a591a8c7eee6a0433fe4c03e6b6df2`.

The offline build uses `get_camera('fp-l-3.02').loader_defines()` plus
`FPSUP_USB_CLOSED_ADMISSION=1` with the existing `armasm.assemble/symbols`
helpers. Temporary raw images are in this session's
`m1-closed-admission/{worker,wbody}.bin`; they are **not VBIN/card deliverables**.
Use an ARM-capable `clang` on PATH; `clang -target armv7-none-eabi -c
camera/worker.S -o "$TMPDIR/worker.o" -DFPSUP_CAMERA=10302` checks the basic
assembler invocation used by the existing build helper. A toolchain wrapper
must preserve that target and Cortex-A9 instruction support.
The actual generation-audit output is this session's `m1-generation.json`.
Both are reproducible from source, not permanent dependencies.

No AutoRun change is required by the default byte-preserving patch. Candidate
packaging, hardware acceptance, ordinary-card recovery and synchronized active
transport remain unimplemented/unverified here. No camera, socket, card, reboot,
live marker, commit or push operation was performed.

## Follow-up: native queued owner is not a lifecycle owner

The all-closed profile above is **not progress to usable active M1**. A bounded
follow-up searched the imported `projects/usb-shell-sup` and
`research/interfaces` sources for a reusable native owner. It found two concrete
leads and tested the stronger one against both fingerprinted MAIN images.

### Imported recovery source: not transferable exclusion

`projects/usb-shell-sup/fpshell_tool/camera/predisarm_hook.S` hooks fp's
`C01E62A8(0)` before DALEPENA disabling. It calls EndTransfer(4), EndTransfer(5),
then clears an old cave-based enable flag. It is for obsolete EP05/EP84, not
the current endpoints. It carries no resource/submission identity, prevents no
concurrent admission, and does not drain old calls. Its five-register save also
does not itself establish aligned call frames. Its opening “eliminating” claim
is not evidence for an fp L implementation; no code was reused.

`research/interfaces/notes/USB_COMPLETION_PATHS.md` separates the high-level
USB session queue from the per-endpoint event flag and documents IRQ delivery.
The imported v31–v33 teardown records explicitly leave shutdown failures open.
None supplies a completed ownership protocol missing from the earlier audit.

### Newly executed native message-task edge

fp L `C01E4450` (fp `C01E7BD0`) is a queued transfer task. Its real entry calls
receive at `C01E4470`; the request contains direction, buffer and length. It
obtains current task information, constructs the descriptor, changes priority,
then directly calls StartTransfer. OUT stores are at `4502/450A/4510/451A`;
IN counterparts at `45B6/45BE/45C4/45D0`. Each descriptor field reloads the CPU
pointer table. No controller semaphore acquire or CPU IRQ-mask helper executes
between receive and these writes. A priority change **after the descriptor
stores** is not a lock on those stores or on reset.

`fp_usb_shell/test_fpl_usb_native_owner.py` executes that native task with a
synthetic received OUT request. Results on **both fp L and fp**:

1. Ordinary request reaches real descriptor stores and the StartTransfer entry.
2. Replacing the table slot immediately before `4502` writes the buffer into
   old descriptor A, but size/control into B; B is armed with no buffer. This
   is an explicit synthetic schedule, not a claimed observed firmware schedule.
   It disproves that the task body itself supplies a protected descriptor bundle.
3. Busy StartTransfer → retry → global teardown → old status-zero unwind →
   queued response executes in real native code. Response is -4; the old
   `3512` store precedes response, **after** nested teardown. Returning from
   stop cannot authorize a new queue/worker owner before that outer frame drains.
4. NOP mutations of `4502` and `3512` change their respective observed effects,
   while the latter still returns -4. The tests detect actual stores, not only
   a host-side ownership ledger.

The queue may serialize its own submitted messages, but reset/EndTransfer/
configuration and the worker's direct calls do not acquire that queue. Routing
worker traffic through it would therefore not establish lifetime exclusion.
Syscall receive, task-info, priority, packet-length lookup and hardware command
responses are explicit stubs. The nested path uses the existing audit's native
StartTransfer/command/retry/teardown/stop bodies and documented ancillary stubs.
No scheduler, cache, DMA or semaphore implementation is emulated.

### Context and concrete hook obligations, before any candidate

The actual fp L IRQ entry is `C01DFEE0`, dynamically registered during init.
Its event-ring path acknowledges a consumed entry at `C01DFF76` and publishes
device pending bits at `C01DFF90`. It is not the task dispatcher. Native task
`C01E4298` waits on flags and directly calls `C01E3A60` at `C01E430E`; native
Wait also calls that dispatcher from its caller's context. Thus the dispatcher's
existence is not evidence of execution on one exclusive task.

`C000EC14` saves CPSR and sets I/F; `C000EC24` restores those mask bits. Those
instructions could protect **short owned bookkeeping on an evidenced single
execution domain**, but cannot drain an old StartTransfer after masks are
restored. No proof here establishes RTOS dispatch/migration semantics or that
every writer participates. In particular these helpers cannot turn an entry
counter into permission for destructive code to proceed while an older frame
remains inside a blocking command. Do not mask across StartTransfer or a join.

Exact fp L instruction bytes checked against official MAIN (little endian):

| Edge | Bytes / displaced instruction | Requirement |
|---|---|---|
| `C01DFEE0` IRQ entry | `2de9f04b`, push.w r4-r8,r9,r11,lr | IRQ-context attribution; not a blocking close/join site |
| `C01E4298` event task entry | `2de9f04d`, push.w r4-r8,r10,r11,lr | Distinguish task from caller-context dispatcher |
| `C01E3A60` dispatcher | `2de9f04f`, push.w r4-r11,lr | Preserve nested/caller context; shared event bits are not ownership |
| `C01E4450` queued task | `2de9f04f`, push.w r4-r11,lr | One task entry is too early to identify each later message |
| `C01E4502` first OUT write | `0160` then `5bf82400` (str; ldr.w) | **Six bytes** of whole instructions for a four-byte branch patch, not four; admission must precede descriptor load/use |
| `C01E3400` StartTransfer | `2de9f04b`, push.w r4-r8,r9,r11,lr | Too late to protect caller TRB construction; retain per-call identity through unwind |
| `C01E35C8` EndTransfer | `2de9f045`, push.w r4-r8,r10,lr | Atomically authorize original submission before current-resource capture |
| `C01E3512` old error unwind | `086012e0`, str r0,[r1]; branch to `C01E353C` | Replay/redirect branch explicitly; old frame still mutates after teardown |
| `C01E0B8E` configuration close | `4cf2c028`, movw r8,#0xc2c0 | Close before DALEPENA disable, plus previously documented init/reset/stop edges |
| `C01E0C54` configured publication | `84f85c07`, strb.w r0,[r4,#0x75c] | **Not** a proven reopen site; callback follows |

These are inspected edges, **not certified installable hooks**. The existing
generation-boundary frontier still applies, including fallback/completion
rearm and direct per-endpoint cancellation. Any eventual patch must journal
every modified firmware word through shared stage2, preserve complete displaced
instructions/flags/state, and reserve near Thumb veneers within B.W reach
(`site+4 ±16 MiB`). Owned USER allocations do not guarantee that reach. No fp L
cave or near-veneer allocation has been established; an IRQ target must already
be fully published before its hook is armed. Nothing here installs such hooks.

### Minimal missing proof and stop decision

The immediate missing fact is **how a close entered by an independent task or
IRQ can delay its first destructive write until old mutating frames drain,
while nested teardown on the submitting task closes without waiting on itself**.
Neither native queue nor controller semaphore supplies this distinction. It
requires proved caller/IRQ contexts and a deferrable continuation or common
owner for all destructive entries, not just an atomic counter update. Then the
last configuration callback and stale queued-message cancellation must define
when reopening is permitted. This follow-up establishes neither fact, so no
active candidate or additional dead-shell feature was implemented.

Reproduce the new four tests (each exercises both firmware images):

```sh
cd fpSup/fp_usb_shell
# FIRMWARE_ROOT: directory holding the two official versioned MAIN inputs
python3 -B -m unittest -v test_fpl_usb_native_owner
cd ../
python3 -B tools/fpl_usb_generation_audit.py --root "$FIRMWARE_ROOT"
```

The test requires exported `FIRMWARE_ROOT`, validates both entire images, and
skips explicitly if it is absent. Actual run: four tests pass with no skips.
The existing generation audit additionally exercises same-epoch ABA, nested
old unwind, and close-before-command interleavings; those are counterexamples,
not active-ticket certification. Production worker/default bytes, allowlist,
host paths and camera remain untouched by this follow-up.
