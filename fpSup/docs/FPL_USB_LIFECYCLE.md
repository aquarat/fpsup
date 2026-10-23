# fp L 3.02 USB lifecycle and OUT ownership

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Offline investigation, 2026-10-20. **No root cause of the failed reboot/reconnect
or disk-mode session is established.** There are concrete cross-lifecycle
hazards in the current worker and one important qualification to the earlier
“stock completion rearms OUT” finding: a matching completion normally sets a
second flag which suppresses that rearm.

This document, `tools/fpl_usb_lifecycle_audit.py` and the follow-up
`fp_usb_shell/test_fpl_worker_lifecycle.py` belong to this work.
No production assembly/profile/packaging changes, camera access, card writes,
commit or publication. Read alongside `FPL_USB_DIAG_2026-10-19.md`, especially
its distinction between observations and inferred causes. The current working
worker's `USB_STATE=2`, `OUT_BUSY=1`, `DALEPENA=A7` are not failure indicators.

## Reproduce

Requires Python, Capstone and Unicorn. Input is official declared-length MAIN,
49,310,208 bytes, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
The script checks both before inspecting or executing anything.

```sh
python3 -B tools/fpl_usb_lifecycle_audit.py \
  --main /path/to/firmware/FPL_V302/MAIN.bin \
  --check
# Disassemble additional bounded code, using a=ARM or t=Thumb:
python3 -B tools/fpl_usb_lifecycle_audit.py --main /path/to/MAIN.bin \
  --range c002f560:c002f690:a --range c01e3078:c01e3264:t \
  --range c01e4000:c01e4298:t
```

**17 evidence checks passed**, including a deliberate in-memory instruction
mutation: changing the completion handler's consumed flag store from 1 to 0
causes the matching completion to rearm the stock buffer. Real firmware runs
with synthetic RAM; type/length lookup, StartTransfer and lower wait/teardown
are explicitly stubbed in completion/wait cases. Reset runs with only memset
stubbed. Mode selection executes the real TBB switch. This is not a DWC3,
IRQ, scheduler, cache or MMU simulation. No candidate worker has been emulated
by this script. The global-teardown loop is also executed with direction,
EndTransfer and controller-stop operations stubbed: mask A7 ends logical
endpoints 1/2/3 before stopping. Disassembly ranges must start at known instruction boundaries;
linear disassembly through inline tables is not evidence of executable code.

## 1. Three different mode/state namespaces

### Active application USB mode: `C3077794`

ARM setter `C002FA30` stores r0; getter `C002FA50` loads this word. This is
**not** the persistent menu preference `SetUsbConnectionMode` (reported as 3
in the live log), and not the driver's transfer-type enum.

| Active value | Exact routing evidence |
|---|---|
| 0 | published by `C002F4A8` at `C002F4DC` / `C002F508` after its detection/error path; not usable shell mode |
| 4 | mass-storage branch: init `C0031EC0`, service `C0031F78`, exit `C0031F68`; backend selector 0 |
| 5 | PTP/Camera Control branch: init `C04D8728`, class callback `C04D7E78`, receiver `C04D79E0`; backend selector 1. **Only this active mode is a shell candidate.** |
| 8 | separate class: init `C003D0F8` then `C003C900`, callback `C003BC78`, exit `C003D1C0`; backend selector 2 |
| 12 | separate class: init `C003A060`, callback `C003A0F0`, service `C003A1D8`; backend selector 3 |
| 13 | explicitly bypasses init/start/stop wrappers `C0031340/1388/13D0`; usbTask startup special-cases it. Lower start switch maps it to selector 2, but the wrapper bypass means that is not evidence it actually starts there |
| 18 | also bypasses those wrappers and usbTask creation |

Do not rename mode 12 as 8: `C0031764` subtracts 4, then 1, then compares
the remainder with 7. The service branch is 12. Names for the remaining enum
values and a complete user-setting-to-active-mode map are not established by
this audit; reject them all for shell ownership rather than guessing names.

The separate backend selector is written as a byte at `C3032A92` by
`C01E47A8`; it is **1 for active mode 5**, not 5. The lower switch
`C01E4F80` is exercised by the script for 3/4/5/8/12/13. Endpoint transfer
type comes from `C31E1C88 + logical*16`: +0 type (1=bulk), +4 direction
(0=OUT, 1=IN), +8 another endpoint parameter. It is neither active mode nor
backend selector.

### Publication precedes readiness, and teardown need not clear mode first

`C002F560(mode)` stores active mode at `C002F57C`, **before** init through
`C002F690`. If its intermediate detection path clears mode, it republishes
at `C002F5DC` before init. `C002DA70` also publishes the class's mode before
calling the surrounding lifecycle operations.

Init order in `C002F690`:

1. Configure callbacks through `C00314F8(mode, 0, ...)`.
2. `C0031340(active)` -> Thumb `C01E4F38` -> `C01E4748` -> `C01DF718`.
3. Class-specific init through `C002F860`.
4. `C0031388(mode)` -> `C01E4F80` -> `C01E47A8(selector)` -> `C01DFC50`.

`C01DF718` creates driver tasks/events as needed and sets up transfer
addresses, then calls reset `C01E3078` at `C01DF9DE`. Reset clears the
configured byte **`C31E1D6C`** (`drv=C31E1610`, +75C), OUT_BUSY and the
consumed flag described below. It also clears event state and endpoint
resource/status arrays; the configuration is not immutable after boot.
`C01DFC50` sets DWC3 DCTL (`2100C704`) bit 31 (run).

Exit `C002F620(mode)` calls `C00306D0`, then `C00313D0(mode)` ->
`C01E5008` -> `C01E47E8`: stop through `C01DFC98`, driver operation
`C01DFB98(1)`, then `C01E1590` disables IRQ 0x34. It clears `C3077FE0`
after class-specific exit. **This body does not clear `C3077794`.**
Stop clears DCTL run and may wait for controller halt. Thus even a mode-5
value surviving a stop is not permission to touch endpoints.

## 2. Exact stock OUT rearm ownership

| Word | Meaning demonstrated by instructions |
|---|---|
| `C31E1D74` | OUT_BUSY = driver `C31E1610+764` = completion base `C31E1664+710` |
| `C31E1E08` | consumed/claimed OUT flag (descriptive name, not a recovered symbol) = `C31E1664+7A4` |
| `C3025744` | stock fallback CPU receive-buffer pointer |
| `C31E1668` / `C31E166C` | current logical 1 / 2 TRB pointers |

`StartTransfer(physical)` (`C01E3401`) sets OUT_BUSY=1 after successful
bulk-OUT start (`C01E3524..3536`). The current worker's `out_owned` also
sets it to 1 after OUT completion. Neither action is a generation token.

The completion handler `C01E4001(request, physical, result_ptr)` does this
for bulk OUT (`C01E4192..41D2`):

```text
if (request == -1 && OUT_BUSY == 1)
   or ((request & ~0x10000000) == physical):
    *result = 0x12
    consumed = 1
    OUT_BUSY = 0
    if request == -1: return 0
```

Then the bulk branch, **also after bulk IN completion**, reaches:

```text
if OUT_BUSY != 1 && consumed == 0:
    logical = C01E2960()  # first type-1/direction-0 endpoint, scans 1..6
    if logical < 7:
        TRB[logical] = { [C3025744]-0x40000000, 0, packet_length, 0x813 }
        StartTransfer(logical*2)
```

Evidence: gates `C01E41DA/41E2`; selector `C01E2960`; stores and call
`C01E4202..425A`. With request `0x10000002`, physical 2, a normal matching
OUT completion sets consumed=1 and **does not rearm**. The audit executes
that case, the request=-1 case, and unrelated-completion cases with both
guard combinations. `C01E3900` (another stock receive helper) also refuses
work when consumed is nonzero. Reset clears it at `C01E3114`
(`drv+7F8`). This is why “completion handler remains” alone is not evidence
of a steady-state collision.

**Existing NOPTP scope is wider than PTP.** `C003178C` suppresses only the
mode-5 receiver. But `C01E3F84` is changed from conditional to unconditional
skip in the generic XferNotReady fallback, which has no active-mode test.
It suppresses the type-1 OUT fallback for other classes too. A worker-only
mode gate does not restore that stock fallback in disk mode. This is a
specific interoperability concern, not proof it caused the recorded failure.

## 3. Wait and cancellation are not passive observation

Current `wait_done` retains the **table-slot address**, not the submitted
TRB pointer. Each iteration reloads the current pointer and reads its HWO.
It can therefore accept a replacement descriptor with HWO clear as completion
of the old transaction. Pointer equality alone would still miss reuse of the
same memory across reconfiguration (ABA).

`Wait=C01E1701(logical, ms)` calls `C01E13B0(logical,0,ms)`:

* -5: retry/deadline path via `C01E1538`.
* **-4: call global teardown `C01E3778`, then return -4.** The retry helper
  can itself call teardown and return -4 at `C01E1554..155C`.
* Other returns pass through. The lower helper can call EndTransfer on -1
  (`C01E1446..144E`). A 20 ms Wait slice is not guaranteed side-effect-free.

`C01E3778` loops logical endpoints 1..6, consulting current direction and
enabled mask (`C31E1D8C`), calls EndTransfer on enabled endpoints, then stops
the controller through `C01DFC98` and `C01DFB98(1)`. `wait_done` discards
the return entirely and checks HWO again. It may interpret cancellation as
success or continue following new TRBs. The script proves -4 invokes the
teardown call; it does not model the actual MMIO teardown.

EndTransfer `C01E35C9` itself uses **current** logical-to-physical mapping and
current resource index (`C31E1610+820+physical*4`). Therefore the worker's
deferred `STATE+08` fault cleanup, and MEMW cleanup, cannot safely call it
after losing lifecycle ownership. “Clean up the old transfer” can instead
end a new class's transfer. All arm paths and `out_owned`, not just the
top-of-loop gate, need the same ownership checks.

## 4. Smallest defensible candidate, and its limits

### Worker-only mitigation suitable for a first separately reviewed RAM trial

Keep this fp L-only initially. Preserve fp behavior and the existing entry,
pool-publication, swap and cache ABI; size growth needs explicit handoff
capacity review, not merely another allowlisted hash.

1. Before every driver/TRB/OUT_BUSY write, require active mode **5**, configured
   byte `C31E1D6C != 0`, backend selector **1**, DCTL run set, existing
   `DALEPENA & 0x24 == 0x24` and non-suspended state. Prefer a positive
   `USB_STATE == 2` trial gate (the working state), explicitly treating any
   other otherwise-valid firmware state as a hold until characterized.
2. Snapshot both nonzero, aligned TRB pointers at acquisition, plus expected
   endpoint type/direction (logical 1 bulk OUT, logical 2 bulk IN). Associate
   cleanup with that acquisition, not with the next successful gate check.
   After every yield and before accepting HWO-clear, recheck identity/readiness
   **before dereferencing the snapshot**; reject changed pointers or changed
   submitted buffer/control identity. HWO-clear alone is not completion proof.
3. Preserve and inspect the actual Wait result. On -4, stop the transaction
   immediately: no reply, no out_owned, no deferred EndTransfer against current
   tables. Retire its cleanup token. On other cancellation/error paths, do not
   convert cleared HWO to success. Distinguish timeout from lifecycle loss.
4. Gate every command phase: frame OUT, MEMW OUT, READY/status IN, MEMR/raw IN,
   multi-frame reply, explicit MEMW cancellation and fault recovery. If loss
   occurs, abandon protocol state; the host must start a fresh transaction.

**This is a mitigation, not a race-free lifecycle fix.** Checks can race with
teardown between the final check and a store/call; a same-address, same-mode
reinit can escape all value comparisons. Keeping stock Wait also retains its
internal cross-lifecycle mutations before the worker sees -4. Do not label
this candidate “safe mode switching” or infer successful reboot from it.

### What is required for stronger ownership

The narrow complete design needs a lifecycle generation/closed marker in
owned RAM, closed **before** driver stop/reset, and opened only after a new
mode-5 configuration. A transfer holds that generation. Closing must prevent
new worker submissions and coordinate with an in-flight submission before
stock reconfiguration. An epoch checked without synchronization only detects
some races; it does not prevent them. No suitable common stock lock or full
set of reset/disconnect entry points was proven here, so this is a design
requirement, not permission to install guessed hooks or hold an IRQ-disabled
region across blocking driver calls.

An alternative to stock Wait in the worker is a bounded, non-mutating delay
plus pinned-TRB polling, with generation checks. It avoids the worker invoking
the global event dispatcher/teardown, but requires latency and completion
ownership tests; fixed 20 ms sleeps would materially degrade small-transfer
latency. Other stock tasks still handle events. Merely shortening Wait is not
equivalent. Neither polling nor an epoch makes an uncoordinated submit safe.

Stock receive suppression should be **scoped to shell-owned mode-5 lifetime**:
retain NOPTP1's mode-5 restriction, replace NOPTP2's unconditional global skip
with conditional ownership behavior, and suppress completion rearm only when
the shell owns OUT. Do not set the consumed flag globally as a shortcut: it
also blocks the stock receiver, and reset clears it. Such hooks must preserve
stock paths outside shell ownership and be declared/journaled through the
shared loader contract. A worker-only RAM trial cannot claim to fix existing
global NOPTP2 behavior. Do not add an independent power-off restoration list.

## 5. Candidate acceptance before any live lifecycle test

Extend the real worker dispatch emulator with injection points after every
yield and around arm/wait/cleanup:

* Mode 4/8/12 with identical endpoint mask: zero worker TRB writes, driver
  calls or OUT_BUSY stores; mode 5 with each readiness condition absent holds.
* Replace TRB pointer during wait with HWO-clear descriptor: no dispatch/reply,
  no cleanup of replacement. Clear HWO due to -4 cancellation: same result.
* Reuse same pointers across a reset: an epoch-based candidate must reject it.
  A check-only candidate should document this case as an expected limitation.
* MEMW loss after READY: no old-phase writes/cancellation against new endpoints;
  all multi-frame/raw IN paths abandon the transaction on loss.
* Valid mode-5 completion still works if another task consumes the event bit.
* Exercise generic fallback and completion rearm with shell ownership on/off,
  including active mode 4: stock behavior must survive outside ownership.
* Repeated handoffs preserve stack, pending-marker and fault-state contracts;
  mutation checks must break each new guard independently.

Then a separately authorized RAM-only candidate can first prove ordinary
MCAPS, known-byte transfers and card readback without mode switching. Lifecycle
trials need independent observation of the camera and a recovery path; USB
silence alone cannot distinguish shutdown, mode selection and a driver hang.
No such new trial was performed here. Reliable reboot/reconnect and settings
persistence remain unresolved.

## 6. Real-worker regression targets (offline follow-up, October 20)

Added **only** `fp_usb_shell/test_fpl_worker_lifecycle.py` and this section in
the follow-up. It subclasses `Dispatch` from `test_fpl_worker_dispatch.py`
without changing that harness or production sources. The current source is
assembled for fp L, its actual relocated body runs in Unicorn, and firmware
services are mocked. No official MAIN is required for these worker tests.

```sh
cd fp_usb_shell
python3 -B -m unittest -v test_fpl_worker_lifecycle
```

The run used the existing clang wrapper on PATH at
`/path/to/arm-toolchain/bin/clang`.
**9 tests ran: 6 passed, 3 expected failures; no skips or unexpected failures.**
The expected-failure traceback messages were separately inspected to ensure
they were the desired behavior assertions, not fixture or emulator errors.

| Regression | Actual result and assertion |
|---|---|
| `test_mode4_identical_endpoint_mask_must_not_serve` | Starting at real `next_round`, mode=4 with mask A7 and otherwise control-mode-shaped readiness still arms OUT, dispatches `echo lifecycle`, sends one reply and increments served. Desired exclusion fails with `foreign mode armed OUT` (1 versus 0). |
| `test_minus4_with_hwo_clear_must_not_be_completion` | Starting at real `wait_done(1,40)`, the first mocked `Wait(1,20)` clears original HWO and returns -4. Worker returns 0. Desired rejection fails with `lost transfer reported success`. |
| `test_replacement_clear_trb_must_not_complete_old_submission` | During that first wait, replace the table pointer with a distinct HWO-clear descriptor and return 0. Original descriptor retains HWO=1. Worker nevertheless returns 0; same rejection assertion fails. |

These expected failures assert **desired behavior**, not that the bug must
persist. When a candidate fixes one, unittest will report unexpected success
until its decorator is removed. The tests do not install speculative guards.

Positive/control coverage:

* Mode 5 executes the full gate → OUT arm → wait → SHL/capture → IN reply →
  next-round path, with no faults and aligned firmware calls.
* Normal completion of the original OUT descriptor returns 0.
* The existing suspend gate excludes mode 4 using the same exclusion oracle;
  that oracle independently rejects a known mode-5 serving trace.
* Non-expected-failure tests execute the foreign-mode fixture and both wait
  injections, checking bounded termination/stack balance and descriptor effects.
  This prevents expectedFailure from disguising broken setup or hook assumptions.
* An in-memory instruction mutation changes wait_done's HWO-clear success
  return into unconditional failure. Both rejection oracles then pass, while
  the normal-completion oracle fails. This is a sensitivity control, **not a
  candidate fix**: rejecting all completions would break the transport.

The fixture initializes active mode5/configured1/backend1/DCTL-run, consumed1,
OUT configuration `[1,0,1,0]`, IN `[1,1,2,0]`, state2/maskA7, matching values
reported by the main session's read-only snapshot. This subtask performed no
live read. The mode4 test deliberately changes only active mode to isolate
the missing gate; it does not claim to reproduce complete stock MSC setup.

The cancellation's HWO clear is an explicitly **synthetic outcome**. The
official-firmware audit proves -4 calls teardown, but neither suite proves
that real teardown clears this submitted TRB in the observed failed session.
The replacement test models a pointer change, not same-address reuse. The two
wait tests stop on function return and do not claim subsequent SHL dispatch
or DMA writes. No scheduler/IRQ race, MEMW cancellation phase, same-pointer
generation reuse, stock rearm concurrency or synchronization design is tested
here. These are narrow runnable regression targets, not race-proof acceptance.

## 7. Synchronization follow-up: concrete exclusion gap (October 20)

**No reusable common lifecycle lock or synchronous task-message ownership
boundary is established.** The bounded bodies provide counterexamples to using
the controller semaphore as that lock. This is not proof that the entire
firmware lacks other synchronization; callers outside these paths remain to
be audited. The three worker regressions in section 6 remain unchanged.

### Controller semaphore: real, but narrower than the required ownership

`C31E161C` holds an object created at `C01DF872` through `C01F516C`, with
initial/max count fields both 1 (`C01DF868..86E`). Run `C01DFC50` and stop
`C01DFC98` acquire it via `C01F570C(id,1,-1)` and release it through
`C01F555C(id,1)`. Their syscall veneers use service words `80190300` and
`80180200` respectively, via `C00011D0`. This is semaphore-shaped exclusion,
not demonstrated recursive mutex ownership; kernel scheduling and error
semantics have not been emulated. Neither caller checks the acquire result.

Observed order: acquire → DCTL run-bit update → (stop only) halt/status polling
and endpoint status clearing → release. Stop's polling calls `C01DFB98(2)`
and `C01DFDD8`; the semaphore is held across those calls. There is no proven
total lock order with other firmware objects.

Counterexamples, at exact mutation boundaries:

| Operation | Why taking this semaphore in the worker is insufficient |
|---|---|
| Bulk StartTransfer `C01E3400` | Sets logical status at `C01E346A`, issues command at `C01E34FE`, sets OUT_BUSY at `C01E3536`; no acquire/release in the body. |
| EndTransfer `C01E35C8` | Loads current resource and changes it to `80` at `C01E368E` **before** command 8; then changes status/OUT_BUSY and event flags. No acquire. |
| Reset `C01E3078` | Clears configured/status/ownership and descriptor contents without acquiring it. |
| Platform operation `C01DFB98(1)` | Clears platform register bits and driver state without acquiring it. |
| Alternate stop `C01DFD68` | Clears DCTL at `C01DFD8C` and polls halt without the semaphore. Its existence alone defeats a hook only at `C01DFC98`; reachability in the observed failure is unproven. |
| Init `C01DF718` | Rewrites TRB pointer tables at `C01DF98E` and `C01DF9D6` **before** calling reset at `C01DF9DE`. A reset-entry epoch alone is too late. |

Wrapping StartTransfer with this semaphore can additionally produce a nested
acquisition: its command helper `C01E32C8` polls CMDACT, calls retry helper
`C01E1538`, which can call global teardown `C01E3778`, which calls the
semaphore-taking stop. With a one-count semaphore, treating this as a recursive
lock is unsupported and risks self-deadlock. This path is not merely the
separate worker Wait routine.

### Interrupt helpers and wait semantics

* `C000EC14` saves CPSR and sets I/F (`C0`); `C000EC24` restores those bits.
  `C01E26F8` uses them only around checking `C31E1E1C` and conditionally
  enabling IRQ `34` via `C000FCA0(34,1)`. CPU masks are restored before return.
* `C01E2750` sets `C31E1E1C=1` and disables IRQ 34;
  `C01E2730` enables it then clears that flag. StartTransfer brackets this
  only for **logical endpoint zero**, not worker bulk endpoints. The flag is
  not a task lock or nesting count.
* Command helpers `C01E2FD8/3030` save/clear and restore bits `140` of
  controller register `2100C200`, using shared `C31E1E28`. They do not acquire
  the semaphore or disable CPU interrupts; shared saved bits are not a
  mutual-exclusion primitive. `C01E3818` performs link-state/DCTL operations,
  not lock acquisition.
* `C01E32C8` writes command registers, polls CMDACT, and uses a `60000`
  deadline argument to `C01E1538`. This is not an atomic bounded store.
  `C01E2888` initializes timestamps via `C0016B30`; it is not a wait lock.
* Worker Wait enters `C01E3A60` through `C01E13B0`. The dispatcher calls
  event wait `C0016C08` with mode `21` and a stack timeout, then processes
  device/endpoint events itself. Driver task `C01E4298` also calls this same
  dispatcher. No exclusive request/acknowledgement protocol covering worker
  submission, reset and stop was found. Do not infer one from the task's existence.

High-level exit `C002F620(5)` synchronously calls `C00306D0` (three state
stores, no task join), `C00313D0` (lower stop), then `C002FD98(0)` and clears
`C3077FE0`. Lower `C01E47E8` orders controller stop → platform operation 1 →
IRQ disable. Thus IRQ disable is **after** destructive operations, not an
exclusion boundary around them. These functions do not establish that the
separately running worker has quiesced. Never hold CPU interrupts disabled
across StartTransfer, EndTransfer, stock Wait, semaphore acquisition or halt polls.

### Smallest evidenced generation-hook frontier, not an installable hook set

The concrete sites below are the minimum *known coverage obligations* for the
paths audited, not a claim of globally minimal/full coverage. Close means
invalidate the epoch and prevent new submissions **before** the mutation.
Repeated/nested closes must be harmless; no nested path may wait for its own
in-flight submission. An epoch alone still does not serialize mutation.

| Site | Required role / displaced instruction at entry |
|---|---|
| `C002F620` ARM | Close before high-level mode exit; first instruction `push {r4,r8,lr}`. |
| `C01DF718` Thumb | Close before init can republish TRB pointers; first four bytes `2de9f041`. |
| `C01E3078` Thumb | Close for independently entered reset; first four bytes `2de93041`. |
| `C01E3778` Thumb | Close before the global EndTransfer loop (not merely at its final controller stop). Confirm displaced bytes against the fingerprint before any trampoline design. |
| `C01DFC98`, `C01DFD68` Thumb | Cover both demonstrated stop bodies; first four bytes `2de97041`, `2de93041`. |
| `C01DFB98` Thumb | Argument-sensitive close for destructive platform operations 1/3, and init via 0; do not invalidate on health query 2. First four bytes `2de9f04c`. |
| `C01E3D50` Thumb | Device-event mask-`0x2` reset branch: close before its state write and endpoint teardown, rather than waiting until `C01E3DD2` calls reset. Four-byte `bic sl,sl,#2`; preserve its effect. |

EndTransfer `C01E35C8` additionally needs **per-submission cancellation identity**
before resource invalidation, including direct calls not preceded by one of
these lifetime closes. It must not blindly close a newly acquired unrelated
generation. Submission/rearm paths (`C01E3400`, fallback, completion) need the
same admission protocol. There is **no verified reopen hook** yet: DCTL run or
active-mode publication is too early, and this audit has not established the
last configuration publication/callback boundary. Keep closed until that is
proved; do not guess a configured-byte store as a commit point.

For four-byte Thumb `B.W` entry hooks, the same-state trampoline must be
halfword-aligned and displacement from `site+4` must be in
`[-0x1000000, 0xFFFFFE]`. ARM `B` uses `site+8`, word alignment and
`[-0x2000000, 0x1FFFFFC]`. Ordinary distant payload allocation is not proof of
reachability; no near cave or reserved allocation is certified here. Reserve
and fingerprint a near veneer through the shared loader before choosing it.
Replay whole displaced instructions exactly once, preserve flags/registers
and ARM/Thumb state, and verify return branches too. No branch patch or
trampoline was produced by this audit.

### Executable evidence and remaining observation

The same `--check` command now passes **31 checks** (the original 17 plus 14).
New checks execute real run/stop bodies against synthetic MMIO with semaphore
calls stubbed, verify bulk start/end/reset/platform mutations with no observed
semaphore calls, and execute the real command polling + retry bodies on both
completion and injected-disconnect paths. The latter returns -4 and calls
teardown, while normal completion does neither. CPU IRQ save/restore runs real
instructions, explicitly starting unmasked; only the IRQ-controller API is
stubbed. The device-event mask-`0x2` body is executed with enabled endpoints 1/2:
both EndTransfer calls precede reset. These are bounded control-flow checks,
not hardware timing, scheduler exclusion or syscall implementation proofs.

The next decisive evidence is a call-site/context audit (including indirect
callers) and, only if separately authorized, independent tracing of **task ID,
IRQ context, entry/exit nesting, generation, TRB pointer, endpoint/resource and
configuration publication** at these boundaries. In particular establish
whether reset/stop can preempt a worker command, whether stop is reentered by
that command, where configuration becomes stable, and whether alternate stop
is used on mode change or power transition. USB silence cannot supply these
facts; use a preserved trace plus independent camera-state observation.

Actionable conclusion: fix the three narrow worker regressions only as a
mitigation in a separately reviewed candidate. A race-free candidate requires
a new admission/quiescence protocol covering the frontier above, including
nested teardown and stock rearm, or a newly proven common owner. Simply taking
`C31E161C`, adding an epoch at reset, or polling with interrupts masked does not
meet that requirement. No production change, live operation or commit occurred.
