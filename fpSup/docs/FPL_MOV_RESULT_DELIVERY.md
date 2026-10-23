# fp L MOV result delivery: event 30

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Main-session live follow-up — October 23

Independent audit rerun passed 15 correspondences, 25 ARM/Thumb cases and six
mutations. The extended bounded decoder self-test also passed. An exact
16-byte read at `C2F2F808` returned `[30,0,FFFFFFFF,C03ABBD0]` (hex).
The decoder accepted this unadjusted direct result thunk; exact firmware
identity and subsequent PONG were verified. This closes the indexed target
for this observation, superseding the unobserved-row boundary in the original
offline findings below. It does not prove actual queued delivery or close.
Private evidence: `dispatch-30.bin`, `dispatch-30-provenance.json` and
`dispatch-30-decoded.json` under the October 23 live research directory.

## Finding

**Packaged-DATA follow-up:** [FPL_DATA_DISPATCH_PROVENANCE.md](FPL_DATA_DISPATCH_PROVENANCE.md)
independently re-extracts the official DATA payload and matches its row 30 to
the archived observation above. This adds packaged initial-value provenance,
not proof of loader execution, runtime immutability or queued delivery.

**The MOV engine's installed notification callback constructs recorder event
`0x30`; its converted status is written to `event+0xE0`.** It enqueues through
`C03A9798` on the same recording owner used by the observed start/stop routes.
This producer proof justifies **one 16-byte passive row read at `C2F2F808`**
(`C2F2F508 + 30*10`, hexadecimal; end exclusive `C2F2F818`).

The expected candidate is direct thunk `C03ABBD0` → state-table +98, but **the
row-30 target has not been observed**. Nothing here infers that target from
neighboring rows. Existing observed rows 23/24 establish start/stop dispatch,
not result dispatch. No new camera access was performed.

Two important distinctions are now concrete:

* Engine status **0** is emitted on a start body's locally successful branch.
* Engine status **1** on a non-error worker exit **and status 2 on its error
  exit both map to recorder result 1**. Therefore recorder result 1 cannot by
  itself distinguish those exits or prove a successful durable file close.
* The result event carries **no request token**. The outward notification gets
  the token from recording-owner slot 2 at notification time, not from the
  result event. No stale-result/request-ID equality check was found on this
  examined path.

## Ownership, installation and callback provenance

All addresses below are fp L CPU addresses. Recorder singleton getter
`C0388BA8` returns owner **C358D990**. Constructor `C0388A10` installs a callback
subobject at **owner+E8**, with table **C0BC208C**, and writes the owner pointer
at **owner+EC** (callback object+4):

```text
C0388A44..50: callback.vtable = C0BC208C; callback.owner = owner
C0388B8C..94: C06AE568(C06AE258(), owner+E8)
C06AE568:    C06AEC68(C06AEC30(), callback)
C06AEC68:    notification_singleton[+8] = callback
```

The engine singleton is **C38D283C** (`C06AE258`); its notification singleton is
**C38D28B8** (`C06AEC30`). The callback table's **+C**, image word at **C0BC2098**,
is **C0389BB8**.

The MOV engine configuration routine `C06AE620` builds its argument block at
SP+1C. `C06AE8F0..8F8` stores **C06AECB8** at SP+70, hence argument **+54**.
It passes that block through Thumb wrapper `C070BD58` to `C070D220`.
`C070D350..356` copies 80 bytes to **C38D5D7C** (global C38D5C00+17C), retaining
the callback at configuration+54. This is the field loaded by the engine's
emission sites below; the audit does not assume every indirect callback points
there merely because its offset matches.

`C06AECB8` receives the raw engine status in R0. It performs status-dependent
flag/event signaling, checks notification singleton+8 for null, converts the
status via `C06AF038`, then calls callback virtual **+C** with the converted
status in R1. Null callback means no recorder enqueue.

### Status conversion is explicit, not inferred from the consumer

The converter has an embedded byte jump table at `C06AF058..63`:

| Engine input | Converted callback status / event+E0 |
|---|---|
| 0 | 0 |
| 1, 2 | 1 |
| 3, 9, 10 | 2 |
| 4 | 3, suppressed by recorder callback |
| 5, 6, 7, 8 | 4, 5, 6, 7 respectively |
| 11 | jump-table arm falls through to assertion |
| >11 unsigned | assertion |

The assertion path is `C0011100`, followed by a self-loop if it returns. The
callback's `CMP R4,#3` at `C0389BF0` suppresses converted value 3, not raw engine
3. This distinction is exercised and mutation-tested.

## Actual event construction and enqueue

`C0389BB8..C0389C30` saves R1 as the converted status. For values other than 3:

```text
event = SP+10; memset(event, 0, 168)
C0389C10/14: event[+4]  = 30
C0389C18:    event[+E0] = converted_status  // SP+F0 minus event base SP+10
C0389C1C:    R0 = callback[+4]             // recording owner
C0389C24:    C03A9798(owner, event)
```

The subtype at +C, request-like +E8 and token-like +F4 all remain **zero**.
`C03A9798` explicitly treats event 30 like 2B for its pool reservation rule,
allocates/copies the **168-byte** event, and submits through
`C036DB60(owner+8, [owner+8], copied_event, 0)`. The new tests execute this
whole enqueue body under synthetic sufficient pool capacity, successful
allocation and a stubbed mailbox send. This establishes the concrete owner
and copied payload, not real scheduler delivery or pool availability.

The consumer's previously established event-2B generic bypass does not apply
to ID 30. Its normal dispatch edge is `C0388E74 → C038AEC0`; a live row is
still required to establish which target that indexed dispatch selects.

## Engine-side meaning of start 0 and stop-related 1

### Start emission

Thumb **C070DD10..C070DEC8** prepares the engine's start configuration and
accumulates status in R5 from initialization/start calls, including
`C0723030`, conditional `C0722F20` and `C00D12B0`. At **C070DEA0**, prior
nonzero status skips the final call. Otherwise `C0723250(0)` returns the final
status. At **C070DEAC**, nonzero skips the notification; zero loads
configuration+54 and calls it with **R0=0 at C070DEB0/2**.

This is positive start-side production evidence for converted result zero,
separate from RECSTART's result-zero → REC consumer branch. It establishes
local engine acceptance after these calls, not sensor output or media
durability. The test executes only this final decision/emission suffix with
an explicit synthetic ABI frame and injected prerequisite/final statuses;
the full start body has a verified fp correspondence but is not fully emulated.

### Worker-exit emission

Thumb worker **C070E318** receives work from the second mailbox. It starts
with R4=0. A received message's word+4 equal to **3** exits processing through
`C070E496`; error branches (for example `C070E3B8`, `C070E426`, `C070E46E`,
`C070E490`) set R4=1 and also exit there. The tail drains that mailbox until a
nonzero receive result, sets engine state 3 via `C070D670`, then:

```text
C070E4B2: if R4 == 0: configuration[+54](1)  // C070E4B8/BA
          else:       configuration[+54](2)  // C070E4C2/C4
```

Both convert to event-30 result **1**. The error arm then has an additional
wait loop at `C070E4CE`; the notification precedes that loop. The new tests
execute the emission suffix and actual callback chain for both R4 values,
ending before the post-notification wait/task-exit operations.

The top-level stop helper calls `C06AE400`, which invokes stop-request wrapper
`C070BD78 → C070D5F8`, waits through `C06AEC88`, and later calls
`C070BD80 → C070D688`. `C070D5F8` constructs an internal command with word+4=1
for the first mailbox. **The complete inter-worker command-1 → second-mailbox
message-3 forwarding chain and filesystem-close semantics are not proved in
this narrow audit.** The source of the two worker-exit status literals is
proved; eventual scheduling, waits, IO completion and durable close remain
outside the boundary. In particular, result 1 is not a unique success code.

## Request/token correlation

The observed start producer places its input token in event+F4. THR's start
method passes that token to `C038A600`, whose prefix calls
`C03A9A08(owner,2,token)`. This setter stores it at **owner+E4**, because the
slot base is owner+DC and slot 2 is +8. Do not confuse this owner field with
an event field at the same numeric offset.

For outward notification kinds **F, 11, 13**, `C0397098` takes the path at
`C0397150..7170`, calls `C03A99E0(owner,2)`, and writes the loaded value at
SP+174. Its outgoing block starts at SP+4, so this is **notification+170**.
The outward submission is `C03A0E58`, a different queue path from the recorder
result enqueue. Tests exercise all three kinds with stored tokens 42 and 77.

Consequently correlation is **owner-slot/state/order based**, not a token
carried by the result callback. Changing the stored slot changes the outward
token in the test; no matching result-event token exists to reject a delayed
result. This is a limitation of the examined chain, not proof of a runtime
race: serialization/re-entry policies elsewhere may prevent overwrites.

## Reproduce and coverage

```sh
python3 -B tools/fpl_mov_result_audit.py --self-test
# Only after a separately authorized passive host capture:
python3 -B tools/fpl_recording_dispatch_table.py \
  --capture "$HOME/path/to/dispatch-30.bin" --address 0xC2F2F808
```

Defaults use `$HOME/.local/share/fpsup/firmware/`.
Both full MAIN fingerprints are checked:

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

**15 normalized correspondences, 25 ARM/Thumb scenarios, 6 semantic mutation
rejections.** JSON retains operand differences, executed PCs, event fields
and notification tokens. Code mappings are read/execute-only; data is synthetic.
All execution uses explicit code bounds, named external stubs and a
3,000-instruction cap per phase. Thumb→ARM→Thumb callback transitions execute.

Cases cover raw engine statuses 0..12, null callback, start prior/final failure
and success, both worker-exit outcomes, and the six token/notification-kind
combinations. Every case executes the actual callback-subobject constructor
stores and registration functions first. Only those constructor stores are
executed, not the entire owner constructor. Queue/resource/OS/IO effects are
stubbed; no task or recording is started. Converter jump-table bytes are
validated separately from code disassembly.

Mutations change event ID, status destination, suppression condition, start
literal, stop literal and notification token slot. They must fail semantic
assertions rather than escape the bounded CFG. The synthetic tests do not
install a hypothetical row 30 or claim it has been captured.

## Minimal next passive evidence

The decoder now additionally accepts **exactly 16 bytes at C2F2F808**, after
this producer proof; it refuses a 32-byte read there and refuses bridging
rows 2F→30. The earlier 23/24 policy remains available. It fingerprints the
official MAIN and verifies the event-30 producer bytes as well as the thunks.

Main can separately authorize that single indexed read and retain host bytes,
version and liveness provenance. A direct negative-selector row with target
`C03ABBD0` and zero this-adjustment would close the callback→indexed thunk
join for that observation. Other content must be decoded as observed, not
forced to the expected target. No whole-table or neighboring-row read is
needed or justified by this audit.
