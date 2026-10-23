# fp L recording format → recorder states: bounded offline audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Finding and boundary

**The concrete MOV start branch is the nonzero word at recording-settings
snapshot `+0xC`. It requests state 4 (`RECSTART`), not state F.** Its helper uses
the literal `MOV` for path generation. A separate RECSTART result handler returns
5 (`REC`) for result zero. The REC stop-request handler calls the MOV stop helper
and still returns 5; this is not a completed-stop indicator.

The `MenuItemMovieRecFormat` snapshot method writes this `+0xC` field, preserving
0/1 and replacing unsigned values greater than 1 with 1. Thus **effective value
1 selects the proven MOV branch**. Effective zero selects a shared raw/still
request helper; *within that helper*, accepted request type 1 selects F, whose
RTTI is `MovRecFuncStateCinemaDng`. Zero alone does **not** prove state F: request
classification is another condition. No GUI label-resource table associating
every input enum with a human label was resolved here. In particular, raw input
2 is neither established as CinemaDNG nor a third effective format.

This audit closes a causal local selection branch, not physical record-button
delivery or asynchronous IO. Runtime descriptors selecting the initial, stop,
and result thunks remain unobserved. These are explicit remaining edges, not
invented event IDs. No camera access was performed.

## Reproduce

```sh
python3 -B tools/fpl_recording_format_audit.py --self-test
```

Requires Capstone and Unicorn, with the official extracted images under
`$HOME/.local/share/fpsup/firmware/`, or explicit `--fp` and
`--fpl` paths. Both **whole images** are fingerprinted before execution:

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 `FP__V502/MAIN.bin` | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 `FPL_V302/MAIN.bin` | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

All addresses below are fp L CPU addresses, base `C0000000`. Output records
17 normalized fp/fp L correspondences, exact table/string checks, 26 actual-ARM
scenarios and 7 rejected instruction mutations. Correspondences retain changed
branch targets/materialized addresses in JSON; normalized equality alone does
not establish hardware behavior. The script imports existing audit utilities
read-only. It creates no firmware/card output.

## Settings identity, storage and publication

1. `SetMovRecFormat` at `C0BE3484`, command-table entry at `C0BE1828`, identifies
   handler `C03FDB08`. Numeric parsing calls setter `C00593F8`; query calls
   `C0059430`. Both obtain the menu item through owner virtual slot `+190`.
   This command supplies a number, not evidence of that number's label.
2. Menu constructor `C00A4238..C00A4280` passes key **66** to `C00A5820` and
   installs `C073F7C8` at object+C. RTTI string `C073F810` explicitly names
   `MenuItemMovieRecFormat`. Slot +18 → `C00A5190` → `C00B4998`; key 66 indexes
   `C0743934` to `C00B2220`. That property locator calls
   `C00882F0 → C0086E78`, then adds **7BC**.
3. Settings owner `C31ACF94` uses byte +B264 to choose block +A880 versus +4F54
   under a lock. The property's backing word is that selected block +7BC.
   Menu access has validation/cache paths: the snapshot test injects the
   **effective** getter result, not the raw backing word. `C00A4288` can also
   force a requested zero to one depending on another property. Its full policy
   is outside this audit.
4. Menu table +14 → `C00A4310`. It reads the effective value twice via
   `C0066470`, tests the second value unsigned against 1, and writes the first
   value or fallback 1 to output+C at `C00A43A8`. Tests assume the two reads are
   stable; they do not prove atomicity against another settings writer.
5. Publication is not inferred from equal offsets. `C008D498` copies **5E4**
   bytes from `C0021B20 → C0021B60`, calls `C008D508` on the copy, and publishes
   it through `C0021B70`. The non-propagating `C008D508` arm calls item virtual
   +14; its propagating arm walks dependencies through `C008D260`, eventually
   calling the same non-propagating arm. Dependency-list membership itself is
   not emulated.
6. `C0021B70` gets `C0022BA8`'s object and calls its vtable +10. Constructor
   `C0021BE8` installs `C0726260`; +10 is `C0021CA8`, which copies **5E4** bytes
   to its `[object]` destination. Both this destination and the context
   singleton's +5C pointer originate in `C0021A20`, returning **C3074BA8**.
7. Recording-settings constructor `C03A9B28` obtains that same
   `C0021B20 → C0021B60` pointer and stores it at owner+4. Singleton
   `C03A9B88` returns **C35A9D7C**; `C03AB458` loads owner+4. Thus the selection
   branch reads the published context, whose format word is nominally
   **C3074BB4**. Owner+C is instead a copied settings structure returned by
   `C03AB478`; do not confuse its address with the format field's offset.

The constructor/publication chain is static evidence, not a saved runtime
pointer observation. `C0310AC8` reads another singleton's word zero through
`C031E210/C031E260`; its comparison with 2 is **not a format getter proof**.
Likewise live settings+B8 used by request classifier `C0397D48` is not this
menu's format field.

## One initial MOV selection branch

State object layout here is identity at +C and dispatch table at +10:

| State | Singleton constructor/getter | Installed table | Evidence |
|---|---|---|---|
| 1, THR | `C038B0E8` | `C0BC30F0` | passes 1 to `C03A9A80` |
| 4, RECSTART | `C038B1F8` | `C0BC2EB4` | passes 4; named RTTI |
| 5, REC | `C038B250` | `C0BC2CC4` | passes 5; named RTTI |
| F, CinemaDNG | see existing failure/state audits | `C0BC24AC` | `C0BC2484` RTTI |

`C03ABAB8` dispatches state table **+74**. In THR this is `C0393F78`:

```text
save current identity as next state
C039A268(...)
snapshot = C03AB458(C03A9B88())
if snapshot[+C] == 0:
    C0398078(current, event[+4], &next, 1, stack_arg=0)
else:
    if C038A600(state, event[+F4]) != 0: next = 4
    else: notify 11/13; return fallback C0396CD8(...)
return next
```

This is a **returned transition request**, not a write to active owner+144.
The established consumer `C0388BF8` handles transition publication/filtering;
the new tests end at thunk return rather than claim a fabricated descriptor
delivered the event. The event+F4 token is explicitly forwarded to the MOV
helper. The test's event+4 sentinel `1234` is not a firmware event ID.

MOV helper `C038A600..C038A9DC`:

* Records token via `C0388BA8 → C03A9A08(owner,2,token)`.
* Requires `C001CF18()==2`; otherwise returns zero. This mode check is not a
  user-format enum association.
* Performs path/audio/recording preparation. At `C038A8B4..C038A8D0`, gets
  `C0389E28 → C038A250`'s path provider and invokes its virtual +C with
  **`C0BC216C = "MOV"`**. This is positive consumer/string evidence for MOV,
  not a guessed interpretation of state 4's name.
* Calls `C06AE2E0` at `C038A8F4`. Nonzero reaches the suffix that publishes
  status bytes, sets recording-settings owner+5F0 to 1, and returns 1.
* Zero at this *late* submission edge does **not** return ordinary failure:
  it notifies, asserts at `C0011100`, and loops at `C038A960` if assertion
  returns. Tests stop at the assertion boundary. Early zero return and late
  fatal refusal must not be conflated.

The zero-format branch's `C0398078` includes a byte jump table at
`C039819C..C03981AB`; linear disassembly across that data is not a complete CFG.
Its accepted request-type-1 arm reaches `C0398970..78`, selecting F. Other
request types select other states. The test injects that raw helper's next-state
output as F solely to test caller propagation; it does **not** execute or prove
the entire raw selection/IO chain. Existing DNG audits retain that separate
coverage.

## Asynchronous result and stop counterpart

Result thunk `C03ABBD0` calls state table **+98**:

* RECSTART → `C0392D88`: event+E0 zero sends notification F and returns **5**.
  Nonzero calls `C038A9E0`, notifies failure, invokes fallback and returns **1**.
  These are result-consumption semantics; result production/delivery and media
  durability are not proven by directly executing this method.
* REC → `C0391DE0`: bounded switch over event+E0, with byte table
  `C0391E48..4F`. Value **1** calls stop helper, fallback, resets audio and
  monitor state, and returns fallback's state. Other tested values 0,2..8 keep
  state 5 (some notify). Value 8 exercises the out-of-range arm. This identifies
  a terminal-looking local result branch, not a durable-close acknowledgement.

Stop thunk `C03ABAF0` calls state table **+78**:

* REC → `C0391C28`: calls `C038A9E0(state,0)`, clears control selector 3 through
  `C03A9508`, returns existing state **5**, regardless of helper return.
* RECSTART → `C0392C60`: also calls the stop helper; chooses control selector
  2/3 from event+164 and returns **5**. This case is statically described, not
  among the new executed cases.

Stop helper `C038A9E0..C038AB78` invokes `C06AE400`. Its zero-return path clears
settings owner+5F0 and returns 1. Nonzero additionally resolves the path using
**`C0BC21B8 = "MOV"`**, calls `C03BE2C8(...,3,path,0)`, clears +5F0 and returns
1. Both returns are local; the encoder's scheduling/waits, follow-up work, and
file finalization remain outside the emulated boundary. Owner+5F0 is therefore
not a durable recording-complete flag.

Do not substitute the previously observed **event 2B** descriptor for these
three unobserved thunk deliveries. As established in
`FPL_RECORDING_FAILURE_UNWIND.md`, states 4/5 route 2B through the generic
handler, whereas F uses its separate path. The saved 2B row proves neither
the initial request's event number nor the MOV result/stop rows.

## Execution coverage and negatives

All tests execute stock ARM in Unicorn with read/execute-only image mapping,
synthetic data/stack RAM, a 5,000-instruction cap, and rejection of every code
edge outside explicit bounds or named stubs. JSON lists each executed PC and
stub argument tuple.

* **4 snapshot cases:** effective 0,1,2,FFFFFFFF, through the real
  `C008D508` non-propagating dispatch and installed menu +14 method. Effective
  getter/access-context calls are injected; the +1C constant getter executes.
* **6 selection cases:** snapshot 0,1,2 × helper rejection/acceptance, through
  the real +74 thunk and THR method. Both large start helpers are stubbed here;
  accepted raw classification writes a synthetic F. Value 2 tests the branch's
  nonzero behavior, not an otherwise-valid menu state.
* **3 RECSTART result cases:** E0=0,1,7, through real +98 thunk/method.
* **2 REC stop cases:** both `C06AE400` outcomes, executing the real +78 thunk,
  REC method and whole stop helper, with named external stubs.
* **9 REC result cases:** E0=0..8, executing the switch including actual byte
  table indexing; stop-helper/fallback/IO effects are injected.
* **2 MOV start suffix cases:** injected submission return at `C038A8F8`,
  synthetic post-prologue stack/register frame; ends at local acceptance or
  assertion. This is not execution from the start helper's entry.

Seven mutations must fail semantic assertions: snapshot clamp condition,
format-selection branch, requested RECSTART number, helper-acceptance branch,
RECSTART success state, start busy publication, stop follow-up condition.
Mutation rejection by an unmodelled edge is not counted as a semantic success.
No tests execute a scheduler, real encoder, filesystem, GUI or hardware.

## Smallest next passive evidence

No further live observation is authorized or attempted by this task. For a
separately authorized recording observation, capture these **together**, with
firmware identity and event ordering:

1. Displayed format label; key-66 menu effective/backing values; settings
   owner `C35A9D7C` +4 pointer and its +C word (nominal `C3074BB4`). This checks
   enum labeling, validation and live publication rather than assuming them.
2. At initial selection, state identity/table, event+4/+C/+F4, snapshot+C,
   `C038A600` return and returned next state. Observe owner+144/+148 before/after
   consumer publication; distinguish returned 4 from committed 4.
3. Read only the corresponding **16-byte descriptor rows** at
   `C2F2F508 + 16*event_id` once actual IDs are known. Establish delivery to
   `C03ABAB8`, `C03ABAF0`, `C03ABBD0` (or their actual alternatives). Do not
   guess event IDs from slot numbers or overwrite the table.
4. Pair start-result E0 with 4→5; pair stop request, `C06AE400` outcome,
   +5F0 clear, subsequent REC result E0 and committed departure from 5.
   Media-close completion still needs an independently identified completion
   observation; none of these alone supplies it.

These observations would settle the remaining causal joins without another
broad state survey or changing established recording/failure audit files.
