# USB submission invalidation boundaries — observer-only audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-20, offline. **Closing a generation is necessary evidence, not exclusion.**
The smallest *demonstrated coverage obligations* include direct per-endpoint
EndTransfer, init before pointer publication, both stop bodies, reset, destructive
platform operations, device-event branches, and the configuration-request branch.
A reset-only counter or a global-teardown-only counter misses real paths.

Only this note and `tools/fpl_usb_generation_audit.py` were added in this
follow-up. No firmware hook is installed or assembled. No production, kernel,
host, card, camera, allowlist, commit or release changes. See
`FPL_USB_LIFECYCLE.md` section 7 and `FPL_USB_WAIT_STATUS.md` for prior evidence.

## Reproduce

```sh
python3 -B tools/fpl_usb_generation_audit.py
```

Python, Unicorn and Capstone are required. The script imports the unchanged
wait-status harness for its fingerprint constants and four wait counterexamples
plus a missing-history control. Defaults use the durable official MAINs under
`/path/to/firmware`.
`--root` and `--profile fpl|fp|both` are supported. Both whole-image lengths and
SHA-256 values are checked (the exact values are in the wait-status note and
printed in the result).

**22 scenarios and 4 observer-coverage mutation checks pass per image**:
44 scenarios and 8 mutation checks across fp L 3.02 and fp 5.02. JSON contains
executed-PC events, CPU stores, stub calls, ticket state and labelled synthetic
injections. Full logs are reproducible; no generated firmware artifact exists.

All addresses below are **fp L**; tested USB bodies in fp are at +0x3780.
Driver base `D=C31E1610` on fp L, `C31E3210` on fp. This bounded translation
does not apply to arbitrary firmware addresses or all data globals.

## 1. Earliest relevant changes, and where a close must precede them

“Before” means admission must already be closed and existing submissions
accounted for, not merely schedule a callback after the store. Function entry
sites are conservative observer boundaries, not certified patch points.

| Path | Earliest relevant action / later consequences | Close obligation |
|---|---|---|
| Bulk EndTransfer `C01E35C8(ep)` | Direction resolved at `3666`; current resource first read at `3674`, captured again at `3680/3684`; **resource=0x80 at `368E`**; command8 at `3696`; status2 `36A4`; busy0 `36B4`; wake/clear `3752/3766` | Per-endpoint close at entry, **before mapping/resource capture**, associated with the affected active ticket. Waiting for status2 or wake is too late. |
| EP0 EndTransfer | Current resource loop; resource=0x80 at `360E`, command8 `3616`, status2 `3624`, flag operation `3644/3658` | Endpoint-zero scope includes both directions. The observer currently records ep0 as one logical endpoint; worker bulk scenarios exercise ep1/2 only. |
| Reset `C01E3078` | First pointed store `3094`; bookkeeping `30A2..30AA`; configured=0 **`30B0`**; enabled-mask=0 `3110`; consumed=0 `3114`; current waiter mask=0 `3140`; memsets below | Close at entry, not configured-byte store. A configured-only observer starts after earlier mutations. |
| Init `C01DF718` | May create/start tasks and enable IRQ before descriptor publication; warm-path buffer pointer `DF8C2`, event pointer `DF92C`, driver buffer `DF94C`; **DMA pointer table `DF97A`**, CPU table `DF98E`; auxiliary tables `DF9C2/DF9D6`; reset call only at `DF9DE` | Close at init entry before task/IRQ setup and pointer publication. A reset-entry close is demonstrably late. CPU-pointer-only tracking misses the DMA pointer StartTransfer actually loads. |
| Stop `C01DFC98` | Acquires controller semaphore, clears DCTL run at **`DFCC8`**; later clears endpoint-config flag bit0 at `DFD22` and driver state `DFD2C` | Close before blocking acquire/stop, not merely after DCTL clear. Semaphore does not serialize bulk submission. |
| Alternate stop `C01DFD68` | No semaphore; clears DCTL run **`DFD8C`** before halt loop | Independently covered entry; hooking only the other stop is incomplete. |
| Platform `C01DFB98(1 or 3)` | First hardware write **`DFBD2`** clears platform bit4; clears further platform bits; can wake common bit31; clears driver state | Argument-sensitive entry close. Argument0 invokes init; argument2 is a query and must not be treated as a destructive close. |
| Global teardown `C01E3778` | Calls EndTransfer per enabled logical endpoint, then stop and platform1 | Close the whole lifetime before the first EndTransfer, not only at the final stop. Nested closes are expected. |
| Device pending bit2 branch `C01E3D50` | Driver state2 at **`3D56`**, endpoint teardown, DCFG rewrite `3DCE`, reset `3DD2`, reset marker1 `3DEC` | Close at branch entry before the state write. Reset or EndTransfer entry alone is later. |
| Device pending bit1 branch `C01E3D3E` | Produces -4, normally leading to global teardown, but the lower helper's reset marker can overwrite it to -1 | Record this terminal device event before returning. No mutation need occur in the masked-return case, so waiting to observe global teardown misses this event. |
| Configuration request zero | Branch `C01E0B56`: global marker0 at `0B60`, configured0 **`0B64`**, state flag1 `0B6A`; no EndTransfer required | Close at this branch, not only in reset or EndTransfer. |
| Configuration request nonzero | Branch **`C01E0B8E`** after validation: snapshot DALEPENA to `D+77C` at `0B9A`; **DALEPENA=3 at `0BA8`**, then EndTransfer loop; controller commands/config helpers; configured publication only `0C54` | Close before snapshot/disable, while configured can still be 1. EndTransfer entry is too late to cover the first hardware mutation. |

This is a **lower bound on necessary coverage**, not a proof of all callers,
all aliases, direct MMIO writers or indirect configuration paths. High-level
mode exit `C002F620` remains an admission boundary from the lifecycle audit;
it is not newly executed by this script. CPU IRQ disable still cannot be held
over these blocking paths. No common lock or full reopen point is established.

### Reset details that matter to identity

The real reset body calls memset on:

* `D+794`, length 0x54, zero (`314E`);
* busy array `D+760`, length 0x10, zero (`315A`);
* pointer at `D+54`, length 0x1C, zero (`3164`);
* pointer at `D+44`, length 0x20, zero (`316E`);
* bulk status `D+704`, length 0x18, zero (`317C`);
* resources `D+820`, length 0x38, **byte fill 0x80** (`3188`).

That last fill yields words `0x80808080`; it is not the scalar `0x80` store
used by EndTransfer. This audit records the bytes and does not infer a universal
resource-sentinel meaning from the names. Reset later conditionally restores
type/direction/parameter defaults at `3216/322E/3246` when configuration-entry
bit0 was clear. These are more identity changes than a pointer comparison sees.

Reset's pointed clears are not a blanket clear of every bulk TRB. The wait
audit already shows bulk HWO can remain set in its synthetic reset case.
Generation invalidation must not depend on reset clearing a particular HWO.

## 2. StartTransfer is already mutating before it can report failure

For the bulk path at `C01E3400(physical)`:

1. `3458` loads the **DMA** TRB pointer from `D+28+logical*4` into command
   parameters. The CPU pointer at `D+54+logical*4` is a separate table.
2. `346A` writes logical status1.
3. Command helper writes parameter MMIO at `331A`, `332A`, `333A`, then
   command/CMDACT at **`3380`**. Its preamble can already alter controller
   bits through `C01E2FD8`; the first parameter is not the first possible MMIO.
4. A completed command6 publishes the 7-bit resource index at **`33B2`**.
5. Successful bulk OUT sets busy1 at `3536`. On error, **`3512` writes
   status0 after the command helper returns**.

The nested scenario executes real StartTransfer → command polling → retry →
global teardown → EndTransfer → stop/platform → unwind. Synthetic hardware
holds command6 busy, completes nested command8, and reports the disconnect
condition. Start returns -4. Its `3512` status0 store executes **after** all
three global closes (teardown, stop, platform). Detecting -4 at the worker
cannot prevent or undo any of those writes.

Ordinary deadline expiry alone is not asserted to call teardown: it is the
retry's disconnect test in the reproduced busy-command path that does so.

## 3. What the observer ledger does — and deliberately cannot do

The host-side ledger starts with synthetic active tickets for logical 1 and 2.
Each ticket has a unique serial, logical endpoint, captured global epoch and
state. Global close invalidates all active tickets; per-endpoint close only
invalidates that endpoint. It never reopens on firmware run/configured stores.
Every nested global close increments the epoch; this is an evidence log, not
a proposed numeric generation protocol. Production nesting should be harmless
and must not reopen on an inner return.

`UC_HOOK_CODE` observes the listed actual instruction PCs **before execution**.
It changes only Python ledger objects. It does not change registers, branch
flow or emulated RAM. A separate memory hook logs CPU stores. Existing fixture
stubs supply clock, MMIO responses, syscall results and synthetic HWO outcomes.
Race injections are a separate, explicitly labelled harness action, not part
of the observer. Some intentionally call `admit` during a close to demonstrate
that this ledger offers **no admission enforcement**.

### Wait-status counterexamples with additional evidence

| Real Wait scenario | Return | Observer evidence |
|---|---:|---|
| Normal completion | 0 | No close; ticket remains active (not automatically declared completed by the ledger) |
| Reset plus completion bits | 0 | Device-reset branch and real reset invalidate old ticket despite successful Wait status |
| Explicit EndTransfer then HWO-clear | -1 | Per-endpoint close invalidates ticket before resource/status/wake mutations |
| Device bit1 with reset marker masking -4 | -1 | Device-bit1 branch invalidates ticket even though global teardown does not execute |
| Marker already set before observation, missing event | -1 | **Not detectable as a past close**: ledger saw no event; test leaves ticket active |

The last case is intentional evidence of incomplete history, not permission to
accept -1. An installed observer must start closed and establish provenance;
it cannot manufacture an active lifetime by sampling mode/configured/HWO.

## 4. Exact counterexamples to a lone global counter

### A. Per-endpoint reuse in one global epoch

Run real EndTransfer for ticket A/ep1: resource7 → scalar0x80. Synthetically
admit B on the same endpoint and same pointer; run real StartTransfer with a
synthetic command completion carrying resource7: resource0x80 → 7. **Pointer,
resource index and global epoch all equal A's old values.** The ledger only
distinguishes A/B because each admission has its own serial. Repeated real
init also republishes identical pointer values, across observed global closes.

Now suppose A was already completed, B owns ep1, and A's deferred cleanup calls
EndTransfer(1). The firmware ABI carries **only logical endpoint1**, not A's
identity. It reads B's current resource and ends B. The test supplies stale
cleanup context A; the ledger detects the mismatch and marks B invalid, but
cannot stop the firmware. A global-epoch equality check alone would accept
the stale cleanup because A and B were issued within the same epoch.

### B. Entry close versus resource capture/store

In real EndTransfer, after capturing resource7 and immediately before `368E`,
the harness synthetically admits B and puts resource9 in the same slot.
The next real instruction overwrites **B's resource with 0x80**; command8
still carries A's captured resource7. B is incorrectly active in an
entry-only observer because no second close occurs. This reproduces the
check-to-store gap without claiming such a schedule was observed on hardware.

### C. Nested teardown and old unwind

The busy StartTransfer scenario closes globally and stops the controller.
Immediately before old StartTransfer's `3512`, the harness synthetically
admits B and sets its logical status1. Old A's unwind writes **B's status0**.
No further close event occurs, so an entry-only ledger still lists B active.
Reopening after the last stop return is too early if an outer mutation frame
can still unwind. Tracking only “current epoch” loses the identity of that
outer frame and its outstanding writes.

### D. Closing does not cancel an in-flight submission instruction

At command's first parameter store `331A`, the harness closes A after its
synthetic admission. The real instruction stream proceeds to **CMDACT at
3380 in the closed epoch**, publishes a resource and sets busy. Invalidating
the ledger does not inhibit hardware submission. A pre-call generation check,
or a post-call check, is not a synchronization boundary.

## 5. Normal cleanup versus cancellation: evidence required

The observer can label an EndTransfer as **own completed retirement** only
when the harness supplies a matching active ticket **and** independently
marks that ticket completed. The positive control retires A without
invalidating ep2. External EndTransfer at the very same PC invalidates ep1.
This distinction is **not inferred from LR, task identity, HWO or return 0**.
Completion provenance is deliberately synthetic in this control; the wait
audit demonstrates why HWO/status alone cannot supply it.

A worker-owned outer call is not sufficient to exempt nested calls:
StartTransfer can trigger global teardown, which legitimately invalidates
all tickets. A Boolean “inside worker” or “own cleanup” flag would conflate
those cases. Kernel task identity and a nesting trace would help attribute
calls, but still do not identify which of several submissions on ep1 is meant.

One global monotonically increasing counter could issue unique submission
serials; the problem is not the number of counters. A lifecycle epoch alone,
without retained per-call tickets and current per-endpoint ownership, cannot
make these distinctions. Incrementing it for every unrelated endpoint operation
also invalidates unaffected transfers unless ownership is represented separately.

The minimum additional design evidence is an **active-ticket protocol**:

* Unique per-submission identity including lifecycle epoch, logical/physical
  endpoint, pinned descriptor/buffer and captured resource when assigned.
* Cleanup carries its original ticket; it must atomically match current
  ownership before resolving current tables or invoking stock EndTransfer.
  A stale cleanup must not end a replacement, even within the same epoch.
* Global closes invalidate all tickets, including the outer caller's, while
  nested frames retain their original ticket/context. Do not wait for the
  closing caller itself as though it were a separate task: nested teardown
  makes that a potential self-deadlock.
* Admission is synchronized with close; reopening requires **all older
  mutating frames to have drained**, plus a proven configuration-ready commit.
  That includes StartTransfer error unwind, not only stop/reset return.

These are requirements exposed by the tests, not an implemented universal state
machine. No common synchronization primitive, atomic ticket handoff, cancellation
join or complete ready/reopen hook is proven here.

## 6. Configuration readiness is still not a reopen marker

Real USB request9 dispatch is executed from `C01E0AE0` with synthetic request
values 0 and 1. For value1, the old configured byte remains nonzero while
DALEPENA is reduced to 3 and enabled endpoints are ended. The byte at `0C54`
is the request value truncated to a byte, not an unconditional boolean1.
An optional callback follows at `0C7A` (disassembled; null in this fixture).
Thus the value publication is neither an entry close nor an established final
configuration commit. Other callbacks/readiness work and all external callers
still need audit. Do not open a generation simply because this byte is nonzero
or DCTL has been set to run.

## 7. Coverage sensitivity and limits

Four mutations remove only observer coverage and must expose an unprotected
actual mutation: omit EndTransfer entry (resource store); observe init only
at later reset (DMA pointer publication); omit alternate-stop entry (DCTL);
omit configuration branch close (DALEPENA before EndTransfer). All four are
detected on both firmware images. Unmodified normal completion and ordinary
StartTransfer controls remain valid, guarding against an always-invalid oracle.

The standalone runner executes real init's **existing-task** branch, reset,
both stops, platform stop, EndTransfer, bulk StartTransfer, command loop,
retry and request9 dispatch. It stubs semaphore/IRQ APIs, memset/memcpy,
clock source, init's final helper, link/config ancillary helpers and
EndTransfer's final endpoint command helper. It does not emulate task creation,
interrupt scheduling, DWC3 effects, cache aliases/coherency or true hardware
parallelism. Init's alias addresses are mapped independently in Unicorn;
identical pointer publication is tested, not alias coherence.

The imported wait fixtures retain their documented stubs, including controller
stop; standalone stop and nested-start scenarios separately execute real stop.
Output distinguishes CPU stores from stubbed memset effects. The callback in
request9 is null in the executed fixture. No claim covers all firmware writers
or the live failure's cause. These boundaries identify where old submissions
must be invalidated **before teardown**, and why observation alone is insufficient.
