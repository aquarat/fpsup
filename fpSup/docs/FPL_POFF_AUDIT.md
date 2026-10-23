# fp L 3.02: power-off manager audit (XC_PowerOffMgr)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Independent static audit, 2026-10-16, of the fp L power-off manager as the
shared stage2 journal (LH_RESTORE) design uses it. Question: do the inventory
addresses `POFF_MGR 0xC00239B8`, `POFF_ADD 0xC0024038`, singleton data
`0xC3075684` and the allocator channel calls `MEM_HEAP 0xC001CF78` /
`MEM_GET 0xC001D038` behave on fp L exactly as the fp 5.02 design assumes —
and can the journal block die before its callback runs?

No camera, card, commit or push. Shared docs, stage2, headers, builders and
tests were not edited by this audit. Reproducible evidence:
[`tools/fpl_poff_audit.py`](../tools/fpl_poff_audit.py) (verifies both image
fingerprints and refuses anything else); JSON evidence at
`~/.local/share/fpsup-research/fpl-poff-audit-2026-10-16/evidence.json`.

```sh
python3 -B tools/fpl_poff_audit.py \
  --fpl-main /private/FPL_V302/MAIN.bin --fp-main /private/FP__V502/MAIN.bin \
  --out /private/new-dir/evidence.json
```

Inputs: official fp L 3.02 MAIN (SHA-256 `fb8c2096…06d4b9`) and fp 5.02 MAIN
(`aaa5208a…20e622`, per `fp_usb_shell/firmware.py`). Evidence levels:
**static** (decoded firmware instructions/data), **offline execution** (real
instructions in Unicorn, synthetic memory, named stubs), and **carried-over
hardware evidence** (the fp 5.02 half of the design is proven on the fp
camera by the existing load chain; nothing new was run on hardware here).

## 1. Confirmed ABI facts

**`POFF_MGR 0xC00239B8` — verified.** `() -> mgr`: a guard-protected lazy
constructor of a **static object at `0xC3075684`** (constructed in place,
guard at `0xC30756FC`), returning it. Instruction-for-instruction identical
in shape to fp 5.02's `0xC0023A98` (data `0xC30756C4`); only the moved
address immediates differ. Executed offline: returns `0xC3075684` with the
vtable installed and state initialized.

**`POFF_ADD 0xC0024038` — verified, raw-equal to fp 5.02.** The full
112-byte body at `0xC0024038` is **byte-identical** to fp 5.02's
`0xC0024118`. `(r0=mgr, r1=obj, r2=forced) -> 1`:

- `forced != 0` → candidate list base `mgr+0x34`; `forced == 0` → `mgr+0x0C`;
- scans **10 word slots**, inserts `obj` in the first null one, returns 1;
- returns **0 when that list is full** (all 10 occupied) — the registration
  failure gate stage2 already checks.

Both behaviors executed offline through the real body, including the
11th-registration refusal.

**Manager layout (fp L, from the constructor `0xC0023868`):**

```text
+0x00  vtable 0xC0726CEC (base-then-derived double store; final value wins)
+0x08  byte: power-related config index
+0x0C  ordinary list: 10 words (memset 0x28)
+0x34  forced list:    10 words (memset 0x28)
+0x5C  event/sync object (C036DF58(obj, 0x1d)); the state setter signals it
+0x60  state word, constructed to 1
+0x64  last-notified state
+0x6C  0x384 tick budget
+0x78  C++ static-init guard
```

The embedded string `src/library/PowerOffMgr/src/XC_PowerOffMgr.cpp` at
`0xC0726CA0` names the class. The manager's own vtable `0xC0726CEC` has the
ordinary walker in **slot +0xC** (`[0xC0726CF8] = 0xC0023B70`) — the same
slot the registered objects are called through.

## 2. How the registered callback is invoked

Both list walkers call the object through **its vtable +0xC**, with
`r0 = obj` and `r1 = mgr->state` (re-read per object), and nothing else
deliberately set:

**Ordinary list — the walker `0xC0023B70` (manager vtable +0xC).** First
action of the function: publish the state change (`0xC0023DD8`), then for
each of the 10 slots at `mgr+0x0C`:

```text
ldr r1, [obj]        ; vtable
ldr r2, [r1, #0xC]   ; slot +0xC
ldr r1, [mgr, #0x60] ; current state
mov r0, obj
blx r2               ; obj->vt+0xC(obj, state)
```

Instruction-for-instruction identical to fp 5.02's `0xC0023C50`. Executed
offline with a stage2-shaped journal block: the routine at `X+12` was called
with `(X, 1)`.

**Forced list — the state request `0xC0023E58(mgr, state)`.** `state != 4`:
publish the new state (`0xC0023EE0`: writes `[mgr+0x60]`, signals the +0x5C
event) and then park in a 500 ms delay loop — the requesting context spins
until the shutdown elsewhere finishes. `state == 4`: walk the 10 slots at
`mgr+0x34` with the **same dispatch** (`obj->vt+0xC(obj, mgr->state)`), then
immediately `C011EEB0(2, 0)` (fp: `C0122610(2, 0)`), the final action.
Instruction-for-instruction identical to fp 5.02's `0xC0023F38`. Executed
offline (stopped before the final action): the routine was called with
`(X, 4)`.

**Stock use of state 4 — the `rebootf` command.** The shell command table
maps `rebootf` → fp L `0xC0406010` and fp `0xC0405DF8`; both bodies are
`POFF_MGR(); state request(mgr, 4)` — the forced path (`reboot` requests
state 3). This is the "fast path" the stage2 comment describes: on it the
manager runs the forced list instead of the ordinary one, which is why the
journal must be registered in **both** lists. Nine stock callers of
`POFF_ADD` exist on fp L (e.g. `0xC03612D8`, registering with `forced=0`).

**Ordering between the lists.** They are walked by different code on
different paths, not sequentially by one loop: the ordinary list at each
notified state change (the walker is the manager's vtable +0xC, so it is
dispatched wherever the firmware virtually calls the manager — see
unknowns), the forced list only on the state-4 request, immediately before
the final power action. A journal registered in both lists can therefore be
called with several different `r1` values (at minimum its registration-time
notification, further state changes, and 4), and more than once — the
design's "writing original words back twice is harmless" holds, and the
callback must not assume a particular state value.

## 3. The stage2 journal contract is compatible

The stage2 block `{X+0: X-8, X+4: routine, X+8: journal, X+12: copied
routine}` was executed against the real walkers offline. Both walkers read
`[obj]` (= `X-8`), take `[X-8+0xC]` = `[X+4]` = the routine pointer, and
call it with `(X, state)` — exactly the contract. No other field of the
object is read, no destructor or unregistration is attempted by either
walker, and the object pointer is never dereferenced beyond the vtable slot.
The ordinary walk is the **first** thing its walker does, before the
shutdown actions in its second half; the forced walk is immediately before
the final action with nothing between. There is no code path that reads the
journal contents, frees the object, or requires any list entry to remain
valid after its callback returns.

## 4. Allocator channel path — verified

`MEM_HEAP 0xC001CF78`: `r0=class` → `[C30739D8 + class*4]`, with firmware
asserts on class 15 and on a null class-14 pointer at table+0x38 (the known
initialization prerequisite). `MEM_GET 0xC001D038`: `(r0=channel,
r1=bytes, r2=alignment, r3=optional actual-size out, [sp]=callsite)`, the
callsite defaulting to the saved LR when the stack word is 0; alignment
below 1 becomes 1 (and the core then replaces 64-divisible alignments with
64, per the allocator audit); allocation comes from the channel's list at
`channel+8`, refusal retries via the channel's fallback at `channel+0x20`;
returns the address or 0. Executed offline with stage2's exact call shapes:
`MEM_HEAP(0)` returned the class-0 channel; `MEM_GET(channel, 0x100, 0, 0)`
with a zero stack callsite returned a 64-byte-aligned block; an over-large
request returned 0. This is the ABI stage2's `lh_setup` already uses.

## 5. Can the journal block die before the callback runs?

**Static scan: no.** No function in the power-off path — the walker, the
state request, the setter, the forced walk, the query helpers
(`0xC0023F38`, `0xC00239F8`, `0xC00242D8`, `0xC0024230`, `0xC0024018`,
`0xC0023FA8`, `0xC0024130`) or the shutdown-task bodies
(`0xC01FDD88/DE30/F40`, which request states 1/2/5) — contains any call
into the allocator core (`C0010310..C0010E00`) or the channel/layout
management (`C001C000..C001F100`). The class-0 channel is only
reinitialized from the boot-time layout initialization and from
application-level mode switches (`0xC038273C`, `0xC03A2A04`, `0xC03BEEF0`,
`0xC05144AC`) — and the allocator audit already showed class-0 USER
allocations survive those (preservation callback, base-match reinit check).
The heap "starts again" at the next **boot** (warm restart), not during
power-off; the journal's write-back has to complete before the final
action, which the forced walk's ordering guarantees.

## 6. What this audit CANNOT prove statically

- **Who dispatches the ordinary walker.** There is no direct `BL` to
  `0xC0023B70` anywhere in the image; it is reached only through the
  manager's vtable +0xC. The setter signals an event object at `mgr+0x5C`
  and helpers post messages, implying a waiter task that virtually calls
  the manager, but its body was not identified. On fp 5.02 the same gap
  exists and the design is hardware-proven there — which is carried-over,
  not new, evidence.
- **That the power-switch path reaches the ordinary walker on fp L at
  runtime.** The state-1 requesters include the power-switch event handler
  (`0xC0021808`) and the shutdown task (`0xC01FDD88`), and the walker's
  state machine handles states 1..6, but the runtime link from request to
  walk is the dispatch above.
- **What the indirect vtable calls in the walker's second half do.** They
  run **after** the ordinary-list callbacks, but a complete subsystem
  teardown order cannot be enumerated statically; this audit proves none of
  them resets USER allocations, not that they are all benign.
- **Interrupt context, priority or CPU** of either walk; the journal
  routine must stay short and non-blocking, which the existing design
  already assumes.
- Nothing here validates live-camera behaviour, MMU/cache state at
  power-off, or that a real fp L power-off reaches state 4. The offline
  execution used synthetic memory and named stubs (guard acquire/release,
  constructor config/notify/registration helpers, trace helpers, the +0x5C
  signal, allocator telemetry); every fact claimed about the lists, the
  dispatch, the setter's field write and the allocator channel form came
  from real instructions.

Sensitivity checks: flipping one byte of `POFF_ADD`'s forced-list base in an
in-memory copy is caught (`POFF_ADD bodies are not raw-equal`); supplying
the fp image as the fp L input is refused by the fingerprint check.

## 7. Conclusion

**The shared stage2 journal design is supported by the fp L 3.02 firmware as
audited; no design change is required by anything found here.** The
inventory addresses are correct; the manager's callback contract is
identical to fp 5.02's (vtable +0xC, `(obj, state)`, both lists, forced
list on the state-4 fast path); the allocator channel calls have the exact
shapes `lh_setup` uses; and nothing in the power-off path resets USER
allocations before the callbacks. The remaining risk is the one the fp 5.02
port already carries — runtime dispatch of the ordinary walker — plus the
first fp L hardware trial, which is the next milestone's job, not a design
change.
