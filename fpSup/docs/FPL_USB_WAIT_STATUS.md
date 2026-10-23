# Stock USB Wait status: compatibility and lifecycle blocker

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Offline audit, 2026-10-20. Scope: this note and
`tools/fpl_usb_wait_status_audit.py` only. No production worker, host,
allowlist, card, camera, commit or release operation.

## Decision

**There is no justified status-only policy that preserves `-1/HWO-clear`
transport completion while rejecting cancellation/reset. Even return 0 is
not evidence that the submission's lifetime survived.** Do not promote the
strict-nonzero guard prototype into a larger candidate trial on the strength
of its positive mocks being changed to 0.

The original worker's event-loss tolerance is important, but its comment that
the TRB cannot be consumed by anybody is too strong across lifecycle changes.
`wait_done` reloads the table pointer and discards every stock Wait result.
The scratch prototype fixes particular exclusions, but rejects the existing
`-1/HWO-clear` positive fixture. Neither behavior establishes ownership.

Three decisive results, reproduced with **both official fp L 3.02 and fp 5.02**:

* A missing completion event with a negative event-wait syscall return gives
  **-5**, not inherently -1. With the firmware's reset marker set it gives
  **-1**, even with a configured endpoint and HWO clear. The old mock's -1 is
  a compatibility requirement, not a unique decoded meaning of “event eaten.”
* Real EndTransfer sets endpoint status 2 and can publish the **same flag bit
  used for completion**. The next Wait returns -1 before waiting. A synthetic
  controller outcome with HWO clear is indistinguishable by `(return,HWO)`
  from the previous -1 case.
* A single successful flag wait returning both device-reset and endpoint
  completion bits executes real reset, clears configured, then returns **0**.
  Completion's result tag 0x12 bypasses the lower helper's reset-marker check.
  This is a synthetic concurrent-flag counterexample, not a claim that it
  occurred during the failed live session.

## Reproduction and provenance

```sh
python3 -B tools/fpl_usb_wait_status_audit.py
# Optional bounded disassembly; fp addresses must be supplied as fp addresses:
python3 -B tools/fpl_usb_wait_status_audit.py --profile fpl \
  --range c01e13b0:c01e1470:t --range c01e1700:c01e1750:t \
  --range c0016c08:c0016c28:a
```

Requires Python, Capstone and Unicorn. The default research root is
`/path/to/firmware`;
`--root` overrides it. Whole-image length and SHA-256 are checked before use.

| Image | Bytes | SHA-256 |
|---|---:|---|
| `FPL_V302/MAIN.bin` | 49310208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |
| `FP__V502/MAIN.bin` | 49245696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |

**24 cases and 4 mutation checks per image pass** (48 cases, 8 mutation
checks total). Output includes statuses, HWO, configured/endpoint state,
event-wait arguments and destructive-path call traces. No worker is assembled
or changed by this script. It extends the evidence, not the implementation,
of `FPL_USB_LIFECYCLE.md` and `FPL_USB_GUARD_PROTOTYPE.md`.

## Instruction-level status chain

Addresses below are fp L. The audited USB bodies in fp are at **+0x3780**;
the driver base is `C31E3210` there instead of `C31E1610`. This offset is a
property of these bounded bodies, not a general firmware translation rule.
Reset marker is `C3032A8F` on fp L and `C3032A93` on fp. Common ARM syscall
veneers used here have the same addresses in both images.

### Public Wait `C01E1700` (Thumb callable address `C01E1701`)

Arguments: r0 logical endpoint, r1 timeout; result r0 signed 32-bit.
It initializes a timestamp and invokes `C01E13B0(logical, 0, timeout)`.

* Lower result -4: calls real global teardown `C01E3778`, then returns -4.
* Lower result -5: calls retry helper `C01E1538`. Retry 0 loops back to the
  lower helper; any other retry value terminates this Wait.
* Every other lower result passes through.

Thus -5 is an internal “no terminal result yet” sentinel **and** a public
deadline result. It is not a raw syscall status. The retry helper checks
elapsed time only when `C01E28A8` observes more than 100 clock units since
its previous check. A requested 20-unit slice is not a hard 20-unit bound.
The harness advances its synthetic clock by 101 per read to bound the runs;
this is not a latency measurement.

The traced bulk paths produce 0, -1, -2, -4 and -5. No positive success code
or -3 return is established here. The earlier lower-helper-stub test showing
arbitrary values passing through the wrapper does not establish that the real
lower helper produces those values.

### Lower helper `C01E13B0`

* `13CE..13DA`: nonzero logical endpoint and configured byte `drv+75C == 0`
  -> -1 immediately.
* `13DC..13FE`: endpoint status 2 (`drv+700+logical*4` for bulk; special
  layout for endpoint zero) -> -1 immediately. EndTransfer writes this value.
* `1430..1444`: link helper, then dispatcher
  `C01E3A60(0x10000000 | logical<<1, timeout, &result_tag)`.
* `1446..144E`: dispatcher -1 -> **EndTransfer(logical)** before returning.
* `1452..1464`: if result tag remains 0x10 and reset marker is nonzero,
  overwrite the dispatcher result with -1. This occurs **after** the
  EndTransfer test, so marker-induced -1 does not itself take that call.

These are distinct paths with the same -1 return. The marker path can also
overwrite a dispatcher -4: the wrapper then sees -1, not -4. Consequently
“reject -4” alone is not even complete detection of the device-bit-1 path.

### Dispatcher `C01E3A60`

Default result is -5. Platform query `C01DFB98(2)` returning nonzero exits
with that default. For logical 1 it waits for mask **0x90040040**; logical 2
uses **0x90080080**. These include common device/platform wake bits,
completion `1<<(logical+17)` and not-ready `1<<(logical+5)`.

`3B52..3B7A` adds/removes this mask in `drv+674`, the set of currently
requested flags. `3B80..3B82` branches past event processing for **any nonzero
syscall result**, leaving -5. Raw -1, -50 and +7 all collapse identically in
the tests. The kernel's error class is lost here.

With syscall result 0:

* Bit 0x10000000 invokes device-event processing first.
* If its status remains -5 and tag remains 0x10, endpoint processing follows.
* `3C26..3C3A`: nonzero `drv+6EC` plus bulk type -> -2. This is the driver's
  bulk-suppression condition (suspend-related state), not an OS error code.
* Completion bit invokes `C01E4000`, whose bulk branch returns 0. Its HWO/bit-2
  test at `4044` changes length accounting, **not** the successful return:
  the tests get 0 even when synthetic HWO remains 1.
* If device processing terminates first, other flags can be re-posted through
  `C0016B9C`; a flag being delivered is not exclusive transfer ownership.

### Device-event handler `C01E3D18`

Reads pending device bits from `drv+6F0`:

| Pending bit | Demonstrated behavior |
|---|---|
| 1 | `3D3E..3D46`: consume bit, return -4; public wrapper normally tears down |
| 2 | `3D50..3DF0`: set state 2; when DCFG mask 0x3F8 is nonzero, end enabled endpoints, reset, set reset marker 1; handler keeps -5/tag 0x10 |
| 0x200 or 0x800 | `3EDA..3EF4`: consume bit, return -1; lower helper calls EndTransfer |

These bit numbers are evidenced driver branches; assigning undocumented
hardware event names to 0x200/0x800 is unnecessary and not done here.
Reset + completion in one flag result is the reproduced **0 after reset**
counterexample. Reset alone yields -1 through the marker override.

### Retry and EndTransfer

`C01E1538`: after the clock gate, `C01DFDD8 == -1` calls global teardown and
returns -4; otherwise platform query -1 returns -1; otherwise elapsed >=
deadline returns -5, else 0. The harness executes the real platform query
and disconnect detector against synthetic MMIO, including DSTS bit 0x100000.

`C01E35C8` reads **current** mapping/resource index, invalidates the resource,
issues command 8, sets bulk endpoint status 2 and clears its busy state.
`3738..3766` sets the endpoint's completion flag if a waiter registered that
bit in `drv+674`, or clears the bit otherwise. The flag is therefore also a
cancellation wakeup. This code does not establish DMA completion ownership.
Bulk HWO clearing during command 8 is explicitly synthetic in this audit;
the emulator is not a DWC3 model. With no synthetic clear, the tested reset
path leaves that bulk HWO set while clearing configured.

## Syscall and stub ABI: what is proven

The **real ARM veneer** at `C0016C08` executes. Its r0..r3 are flag ID,
wait pattern, mode, output-pattern pointer. The fifth argument is the timeout
value on the caller's stack. The veneer saves r4, makes r4 point to that
original stack argument, saves LR, loads r12=`0x80240500`, then calls
`C00011D0`. It restores r4/LR and returns the gateway's r0 unchanged.

The harness intercepts **that gateway**, checks ID, exact mask, mode 0x21,
and the fifth argument through r4, writes flags through r3, and injects r0.
It does not return a flag pattern in r0 or mistake the timeout for a pointer.
`C0016B9C` and `C00169C8` set/clear calls are traced separately. This is
consistent with the repo's `twai_flg`/OR-clear usage; the kernel scheduler and
the exact clearing semantics of mode 0x21 are **not executed here**.

In particular -50 is the repo's `E_TMOUT` convention and is a **synthetic
kernel outcome in this test**, not a newly verified execution of kernel
timeout code. The evidence needed for worker policy is stronger and simpler:
the dispatcher deliberately collapses *every* nonzero gateway result to -5.
There is no way for its caller to distinguish timeout, deleted flag object,
forced release, invalid call or other raw kernel error from that result alone.
Do not label public Wait -1 as `E_TMOUT`, or public -4 as a raw OS status.

## Coverage and limitations

Per image: normal/stale-HWO completion; logical-2 completion and missing
events; bulk suppression; no event; three nonzero syscall classes;
unconfigured/status-2 early rejection; reset-marker missing event; device
bits 1/0x200/0x800 and marker-overwritten -4; reset with both HWO outcomes; reset plus completion;
retry disconnect; platform off; explicit EndTransfer with both HWO outcomes.

Four in-memory instruction mutations are detected independently: omit wrapper
teardown; replace unconfigured -1; replace reset-marker -1; erase dispatcher's
default -5. These assert behavioral changes, not merely changed bytes.

Real bodies execute through Wait, lower helper, dispatcher, completion,
device events, reset, EndTransfer, global-teardown loop, clock arithmetic,
platform query and retry. Controller command submission, controller stop,
IRQ helper, reset ancillary helpers, endpoint post-EndTransfer command helper,
memset, semaphore/delay calls and clock source are explicit stubs. The clock
and HWO sequence are synthetic. No IRQ/task interleaving, cache coherency,
kernel scheduling, physical disconnect, protocol dispatch or camera recovery
is claimed. Whole-image fingerprints prevent a wrong firmware silently passing.

## Smallest defensible policy and missing evidence

1. Treat -4 as a definite rejection when observed, and -2 as a bulk-suppression
   rejection; do not turn either into success because HWO cleared. Retire old
   cleanup ownership rather than EndTransfer against possibly new tables.
2. **Do not whitelist -1 or -5 as benign timeouts.** They include destructive
   or unknown paths. Nor is 0 sufficient. Rejecting every nonzero is a bounded
   conservative experiment, not a compatible replacement for the current
   transport; accepting every HWO-clear is not a lifecycle solution.
3. To preserve physically completed `-1/HWO-clear` transfers, require evidence
   independent of these values: a generation-bound submission and cancellation
   identity, closed before reset/init pointer publication/stop/per-endpoint
   cancellation; synchronized admission/quiescence; a proven reopen boundary;
   and completion provenance for that submission, with correct DMA visibility.
   If cancellation has already ended a transfer, unchanged mode or configured
   values cannot retroactively classify its HWO clear as successful transport.
4. Preserve raw syscall result, device-event outcome/tag and endpoint-cancel
   provenance if using stock Wait diagnostically. Stock Wait can perform its
   destructive actions before returning; post-return classification cannot undo
   them. A bounded non-mutating poll still requires generation/admission evidence.

The concrete frontier and synchronization gaps remain those in lifecycle
section 7. Pointer pin equality does **not** solve ABA, same-address descriptor
reuse, same-mode reinitialization or the check-to-submit race. No guessed
status whitelist or new production policy is supplied by this audit.
