# fp L failed-start event delivery and unwind

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23, offline. **Failed-start notification has concrete consumers and
cleanup calls, but neither submission nor consumption proves terminal recording
state or IO quiescence.** The main session's passive runtime observation now
resolves the event-to-method edge for that observation: **event 2B → direct
thunk C03ABD20 → state vtable +A0**. Initializer provenance and stability across
boots remain unresolved.

This continuation owns only this document and
`tools/fpl_recording_failure_audit.py`. The completed
[recording-state coverage](FPL_RECORDING_STATE_COVERAGE.md) remains unchanged.
This audit performs no device/card access, hook installation, production changes,
commits or pushes; it reads the main session's saved passive observation offline.

## Reproduction and evidence

```sh
ROOT="$HOME/.local/share/fpsup/firmware"
python3 -B tools/fpl_recording_failure_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" --self-test \
  --live-descriptor "$HOME/.local/share/fpsup/observations/recording-event-descriptor.json"
```

Defaults use `Path.home()`. Requires Capstone and Unicorn; missing dependencies
or images fail. Output is JSON containing correspondence, assumptions and traces.

| Official MAIN at C0000000 | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

Passed **21 bounded fp/fp L correspondences, 66 actual-ARM fp L scenarios,
19 negatives**. Whole-image fingerprints are checked first. The shared
normalizer preserves field offsets/constants/internal branches and reports
external calls/materialized literals separately. Owner, runtime descriptor
address, relevant file-backed vtable slots and state RTTI get exact checks.
No recursive callee certification or complete CFG is claimed: `incompleteCFG`.
`--live-descriptor` validates the saved address/words, exact firmware version
identity and recorded post-read PONG, and emits its SHA-256 without private paths.
Without that option, replay still uses the reported constant row but does not
claim to have validated a saved observation file.

All addresses/offsets below are hexadecimal unless explicitly decimal.

## Producer → submit: what can be lost

The established raw owner calls `C0377428(owner, request-id, 0, error)` on
nonzero start status. It loads owner+0C; a null callback bypasses the call
entirely. That branch does **not** synthesize a reliable false/status result:
r0 still contains the owner. A callback-entry counter cannot count these losses.

Installed callback table `C0BC1A5C`, slot +C, targets **C0385978**. It constructs
a zeroed **168-byte** event, with:

| Event offset | Value |
|---|---|
| +4 | 2B |
| +C | 5 for callback-kind r2=0 |
| +E4 | error argument (early 1/3 or late 2 in the studied start) |
| +E8 | request identifier, originally request+10FC |
| +8 / +165 | zero from initialization |

`C0385A7C → C0388BA8` obtains **XC_MovRecFunc at C358D9C0**: the accessor
materializes C358D990 and returns +30 after its initialization guard. Constructor
`C0388A10` installs table **C0BC203C**, whose +14 slot is the worker
**C0388BF8**. This generic class name does not identify MOV file format.

`C0385A84 → C03A9798(owner,event)` then:

1. Obtains a resource count through the object published at **C2F2F838**,
   virtual slot +14. Event IDs 2B/30 use threshold zero; others use one.
   Count must be **unsigned greater than** the threshold.
2. Insufficient count increments **C35A9D78**, releases its guard and returns
   zero at `C03A983C`, without queuing.
3. Otherwise allocates 168 bytes at `C03A984C → C03AC518`. A nonnull result
   receives an event copy at `C03A9864 → C0014DAC`.
4. **Null allocation still reaches the queue call with r2=0.**
5. `C03A9894 → C036DB60` submits through owner+8. Its return is ignored;
   `C03A9898` unconditionally returns **one**, including queue-call failure.

Thus return one is not delivery acknowledgment. Whether the underlying queue
API takes ownership on each failure and whether a failed send leaks an allocation
are unresolved; do not infer those effects from the wrapper. The initialized
pool and guard are synthetic assumptions in execution tests.

## Worker routing and request correlation

`C0388BF8` is a persistent loop, not a callable one-event function. At
`C0388C38` it receives through `C036DBD8`. Nonzero receive status retries;
zero with a **null event pointer also retries** without dispatch. Each loop
obtains a gate from `C03896A0`; when this gate is nonzero it releases the event
via `C03A9958` at `C0388C8C` and loops, without state-handler cleanup. The gate's
meaning is not certified as shutdown, defer or error.

With gate zero, the callback's +165=0 bypasses another flag-dependent override.
The worker writes its own pointer to **event+F8** at `C0388D4C`, runs an
event-history/helper call `C0388EC8`, then routes using **owner+144**:

* State **8**, or event 2B with state outside {E,F,10,11}, goes through
  **C0381C68**. Subtype 5 calls **C03840A8** with an output-state pointer.
  The result is written back to owner+144 at `C0388DA0`.
* Event 2B in states **E/10** first calls **C03840A8** at `C0388DE8` with
  a null output-state pointer. A zero result branches directly back to the
  receive loop at **C0388DF4**: no state dispatch or owner+144 write there.
* Other cases reach the per-state table dispatcher **C038AEC0**. Its returned
  state is stored at **C0388E7C**; differing old/new state also invokes entry/
  exit helpers. These helpers are not a media-completion contract.

### Resolved observed descriptor, and explicit correction to the earlier model

`C038AEC0` indexes **C2F2F508 + event-id*10**. For 2B, read the **16 bytes
at C2F2F7B8**. The dispatcher indexes using **event+4**, not row[0]. Its descriptor
fields are +4=`this` adjustment, +8=signed method selector and +C=direct target
or vtable-field offset. For a nonnegative
selector it loads a table at adjusted-object + descriptor[+C], then indexes
descriptor[+8]*4. It also calls state-table **+B8** afterward.

The main session's single sequential passive read observed:

```text
C2F2F7B8: 0000002B 00000000 FFFFFFFF C03ABD20
```

Saved evidence SHA-256:
`b8c117640e9db78fa2154ad4a37438b3df2e25079dcbb745bbe385b3b78c7d70`.
The record identifies model w91c1, xc V90, release 3.02.0.V90, firmware git
`13aa621060efff11aaba9b21ad925005302605cf`, and post-read **PONG 89**.
This is not an atomic snapshot of all dispatch/state objects and not an
all-boot stability claim. This audit did not perform another live read.

Exact executed route with those words:

1. `C038AEF4` loads +4=0, so adjusted `this` is the original state object.
2. `C038AF04` compares signed selector **-1** with zero. `BGE` is not taken;
   `C038AF10` loads the direct target from +C.
3. **C038AF40 → C03ABD20**. The thunk preserves `(state,event,movie-owner)`;
   `C03ABD30` loads `[state+10]`, adds **A0**, loads the method and calls it
   indirectly at **C03ABD48**.
4. For installed CinemaDNG table **C0BC24AC**, +A0 is **C038BE68**;
   subtype 5 calls **C038BFB0**. On return the dispatcher still invokes +B8
   (`C038CA70` for CinemaDNG) before returning the state result.

**Correction:** the original synthetic `[0,0,28,10]` row was an explicitly
hypothetical *virtual-descriptor* route, not the live row. It reaches the same
+A0 method but **skips the real direct thunk**. It must not be reported as live
table content or as execution evidence for `C03ABD20`. Earlier statements that
the CinemaDNG +A0 edge remained conditional are superseded for this observed
row. The generic/non-DNG routes and IO-quiescence limits are unchanged.

Row[0]=2B is consistent with an event-ID label, but **this dispatcher never
reads it**; its global meaning is not established by the indexed consumer.
A neutral replay changes only row[0] to zero and preserves the direct route.
The saved-observation validator nevertheless requires the exact observed row.

**Packaged-DATA follow-up:** [FPL_DATA_DISPATCH_PROVENANCE.md](FPL_DATA_DISPATCH_PROVENANCE.md)
resolves the packaged bytes for row 2B and matches the archived observation.
The following MAIN-only provenance limitation is historical; the actual loader
execution and absence of runtime mutation remain unproved.

**Earlier MAIN-only finding:** C2F2F508 is beyond the official MAIN
extent. Neither image contains the exact packed row or its corresponding packed
direct-target word. Aligned MOVW #BD20 candidates in fp L pair with unrelated
MOVT values, not C03A; the table-address search likewise did not recover a
trustworthy initializer. These bounded searches do not exclude encoded,
relocated or decompressed initialization, nor prove immutability.

For the retained hypothetical CinemaDNG execution scenarios, the descriptor is explicitly
injected as `[0, 0, 28, 10]`: no `this` adjustment, vtable at +10, slot +A0.
This assumption is recorded separately in JSON and is **not evidence that the
live descriptor has those values**. New live-row replay executes the signed
negative branch, direct thunk, state virtual method and return filter.

## Common subtype-5 failure cleanup

`C03840A8` resolves **event+E8** through
`C0374438 → C03755D8`. This is an actual request lookup, not a pathname match.
If lookup is null, it returns one for state F/11, otherwise zero, before the
subtype handler. A late event can therefore miss its request; no generation or
duplicate-event rejection is established here.

For subtype 5 and a found request:

1. `C03841F4 → C03848E0(event,request)` examines **event+E4**.
2. Nonzero error **3** selects notification class **5**; other nonzero errors,
   including **1 and 2**, select class **6**, via `C0397250`.
3. Calls, in order:
   * `C0377560 → C0377838`: request raw-owner stopping (+78 in the prior audit).
   * `C0374438 → C0375390(request[10FC])`.
   * `C0377560 → C0377948(request[10FC])`.
   * `C0374438 → C0375248(request[10FC])`.
4. Returns zero at `C0384D48..54`. These are concrete cleanup requests, not
   proven successful destruction. `C0375390` and `C0375248` themselves have
   owner+190 bypasses; `C0377948` involves request/virtual worker operations.
5. **Error 2 additionally calls C0396CD8** at `C0384234`. If the caller
   supplied an output pointer, its returned state is stored through it at
   `C0384250`. With the E/10 worker prefilter's null output pointer, no such
   store occurs.

Consequences: E/10 failure handling can perform these requests and loop with
owner+144 **unchanged**. Generic routing can propagate a state returned by
`C0396CD8` for error 2; that callee's semantics remain unresolved. No single
terminal state value is proved by the common handler alone.

On the E/10 zero-result prefilter branch, the worker also bypasses its normal
post-dispatch event-release site `C0388EC0`. This is a control-flow observation,
**not a proved leak**: ownership/retention in real callees still needs resolution.

## Resolved observed CinemaDNG route and format boundary

The movie owner installs state objects at owner+F8+4*state. Established identities:

| State | Binding / table | Proven type |
|---|---|---|
| 4 | `C038B1F8`, table C0BC2EB4 | MovRecFuncStateRECSTART |
| 5 | `C038B250`, table C0BC2CC4 | MovRecFuncStateREC |
| E | `C038CB90`, constructor `C038CC30`, table C0BC27E4 | MovRecFuncStateCONT |
| F | `C038B3D0`, constructor `C038B470`, table C0BC24AC | MovRecFuncStateCinemaDng |
| 10 | `C038B420`, constructor `C0390800`, table C0BC2AE4 | MovRecFuncStateINTERVAL |

**CONT and INTERVAL are not renamed MOV.** No directly verified MOV-format
selection → state-ID route was established in this task. Generic class-name
`XC_MovRecFunc`, REC/RECSTART names and the path formatter's MOV extension are
insufficient. The actual worker routes event 2B in states 4/5 through
`C0381C68 → C03840A8`, **before the descriptor dispatcher**. The live direct
row therefore does not imply that every recording format enters C03ABD20.
Six additional real-ARM cases exercise those state-4/5 routes for errors 1/2/3.

CinemaDNG's **table +A0 → C038BE68** checks subtype 5 and calls **C038BFB0**.
With the observed direct row and the established CinemaDNG table:

* It looks up event+E8. On missing request it clears control bytes +2/+3
  through `C03A9508`. If state+14 is not sentinel **80000000**, it calls
  `C038C5D8(state,-1,event-owner)`; otherwise returns state+0C.
* On a found request, `C038CA18` checks state+20 and raw-owner+78. If neither
  says stopping and state+14 is sentinel, it can first set state+14 to zero.
  **Sentinel alone therefore does not guarantee bypass of the stop call.**
* For nonzero event+E4 it clears the same control bytes, calls
  `C0377948(request[10FC])`, saves request+1100, and calls
  `C0375248(request[10FC])`. Errors 1/2/3 also call `C037DF20 → C037E0F8`;
  error 4 has a separate skip branch outside this test matrix.
* If state+14 is nonsentinel, **C038C16C → C038C5D8** receives the saved
  request+1100 token, not event+E8. Otherwise the handler returns state+0C.
* Table +B8 → `C038CA70` returns the supplied result unchanged. The worker
  publishes it at owner+144, then reaches the normal event release.

The earlier audit establishes `C038C5D8` retry and terminal-bypass ambiguity.
This continuation does not improve that to IO quiescence. In modeled failures,
stop returns injected state F; owner+144 stays F. A concrete return/publication
point is established, **not a unique terminal state or completed close**.

## Execution assumptions and negative tests

The 66 scenarios execute stock instructions; writes are confined to synthetic
RAM and the modeled rejection counter. Firmware image pages are read/execute.
All executed addresses must lie in explicit bounds or an explicit stub.
Submit cases must return; consumer cases stop on the next arrival at the loop
head, after exactly one injected queue item, within 10,000 instructions.

* **15 submit cases:** errors 1/2/3 × ordinary, resource rejection, null
  allocation, queue failure, null callback. Actual callback, getter and submit
  execute. Pool/guard/allocation/queue services are synthetic; bounded memset/
  copy stubs preserve the exact event fields. Check E8/E4 correlation, counter,
  queue null pointer and return behavior.
* **18 common/generic consumer cases:** errors 1/2/3 × states 8/E/10 ×
  request found/missing. Execute worker, generic router, common result handlers.
  Check lookup key, error classes, cleanup order, late-error extra processing,
  routing and release-site differences. `C0396CD8` is stubbed to return the
  input state; these tests do not establish its real transition.
* **12 hypothetical DNG cases:** errors 1/2/3 × request found/missing ×
  stop-eligible/stopping configuration. Real state handlers, predicate and
  byte-clear routine execute. Stop-eligible means state+14=0/raw+78=0;
  stopping means sentinel/raw+78=1. Cleanup services and stop are stubbed.
  Runtime descriptor → +A0 is injected as described above.
* **2 bypass cases:** worker gate nonzero releases without cleanup; null queue
  item loops without dispatch.
* **12 live-row DNG replays:** the same error/request/stopping matrix, now
  executing the observed negative-selector direct route and real C03ABD20.
  Oracles check direct-branch/thunk entry, absence of the hypothetical virtual
  descriptor branch, cleanup ordering and resulting state.
* **1 neutral row[0] replay:** verifies that this field is not consumed by the
  dispatcher, without treating the modified row as observed evidence.
* **6 live-row generic replays:** errors 1/2/3 in RECSTART/REC states 4/5;
  verify generic cleanup routing bypasses descriptor dispatch.

Stubs preserve registers except r0/PC; memory operations and injected queue item
are explicit. RTOS ordering, deallocation, request lifetime, nested callbacks,
media effects, stop completion and concurrent failure delivery are not modeled.

Negatives: **8** full-image first/code/last-byte/truncation failures; **6**
execution-only mutations bypass fingerprints/normalization (callback subtype,
request-id field offset, submit result, DNG subtype comparison, common error
class comparison, error-2 processing comparison); **2** static-only mutations
to runtime descriptor literal / DNG vtable target; **3** additional direct-route
mutations (selector -1→0, direct pointer to the +A4 thunk, thunk slot A0→A4).
All 19 negatives are rejected. The accepted row[0] variation is not counted as
a negative.

## Actionable passive observation gate

Before attributing a live callback to a successful unwind, observe **a sequence**:

1. Callback registration/null status at raw-owner+0C; callback entry
   **C0385978** with request-id/error arguments.
2. Submit result at **C03A989C**, rejection counter **C35A9D78**, allocation
   pointer at **C03A9850**, and queue-call result before **C03A9898** overwrites
   it. Avoid labeling return one “delivered”.
3. Dequeued nonnull event at **C0388C58**, event {+4,+C,+E4,+E8}, worker gate,
   current state **[C358D9C0+144]** and event owner assignment **C0388D4C**.
4. Preserve the observed descriptor **C2F2F7B8..C2F2F7C7** as evidence for
   this boot and correlate selected state table and **C03ABD20/C03ABD48** with
   the event. The descriptor read is complete for this observation; repeated
   boots/configurations would need separate evidence, not an all-boot inference.
5. Common error handling **C03841F4/C0384D48**, or DNG error branch
   **C038C090/C038C16C**, with lookup result and request+10FC/+1100. Record
   missing/duplicate/unpaired IDs rather than treating every event as a take.
6. Observe published state at **C0388DA0/C0388E7C**, prefilter bypass
   **C0388DF4**, event release and the previously documented stop retry/finalizer
   evidence separately.

These are research addresses, not approved patch sites. The other diagnostic
work must independently establish reachable placement, exact restoration,
callback lifetime and bounded record transport. No file creation/cleanup calls
should be added merely because these observations expose a failure branch.

Remaining blockers: event descriptor initialization/stability; MOV-format
state selection; pool/queue ownership on failed submit; request lifetime and ID
reuse; real cleanup effects and `C0396CD8` transitions; stop completion, shutdown
and media-removal ordering. The actionable next result is correlated passive
evidence across those points, not a recording-aware writer enablement.
