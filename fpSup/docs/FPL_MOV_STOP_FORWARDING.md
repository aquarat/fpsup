# MOV stop: command forwarding and local finalization

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Finding

The offline forwarding edge is resolved: **first-mailbox command 1 latches a
stop request; once the first worker's started latch is set, it sends second-
mailbox message 2 (finalization), then message 3 (exit)**. On the successful
FIFO path, remainder writing and finalization return before the writer emits
raw engine status 1. The established callback chain converts that to recorder
event **0x30**, result **1**.

**Result 1 is not evidence of successful finalization or durable storage.**
Missing message 2 can still produce raw status 1; writer error status 2 also
converts to result 1. The concrete file-release wrapper ignores the underlying
release return. No physical flush or durable-storage acknowledgment is proved.

This audit is offline only. The prior observed descriptor
`[30,0,FFFFFFFF,C03ABBD0]` and its provenance remain in
[FPL_MOV_RESULT_DELIVERY.md](FPL_MOV_RESULT_DELIVERY.md). No additional row
read is needed to join event 30 to state-table slot +98.

All addresses and offsets below are hexadecimal, except test counts and byte
sizes explicitly identified as such.

## Queue identities and command flow

`C070C188` creates eight mailbox handles through `C01F5124` and stores them at
`C302CFF8 + 4*i`. These are handle slots, not addresses of message buffers:

| Role | Handle slot | Pool |
|---|---|---|
| First/acquisition worker | `[C302CFF8]` | configuration+80 = C38D5DFC, 8-byte commands |
| Second/writer worker | `[C302CFFC]` | configuration+94, 24-byte messages |

Configuration is `C38D5D7C`. Thumb send wrapper `C070C2E0` calls ARM
`C01F55C8`; receive wrapper `C070C2F8` calls `C01F53F4`. FIFO behavior is an
explicit harness assumption, not independently established kernel semantics.

1. **Request, `C070D5F8..D658`:** requires engine state 2, checks pool
   availability, allocates/copies an 8-byte command with word+4=1, sends the
   first mailbox, and sets engine state 3. Pool unavailability returns 1.
   A send error is ignored: request return 0 does not prove delivery.
2. **First worker, entry `C070D890`:** polling slice `C070D922..D96A`
   receives/copies the command. Command 1 sets `[SP+30]=1`; it does not
   immediately forward. Command 2 takes a distinct abort path.
3. **Latch gate, `C070D9EE..D9FE`:** requires both started `[SP+1C]` and
   stop-requested `[SP+30]` to be nonzero, then calls `C070DCB8(4)` and
   branches to cleanup at `C070DC80`. The harness injects the started latch;
   it does not execute the acquisition/start loop that establishes it.
4. **Forwarder, `C070DCB8..DD10`:** stores reason 4 at configuration+11C,
   calls acquisition-stop `C070DEC8`, emits raw callback 4, then calls
   `C070E148` and `C070E198`, in that order. Raw 4 converts to 3 and is
   suppressed by the recorder callback. The two constructors send message
   2 and message 3 respectively to `[C302CFFC]`.
5. **Wait:** the forwarder polls `C070C218` using task handle
   `[C302CF40]`, waiting for status 10. The harness forces that status;
   its sequential schedule is not a proof of real task termination timing.

Both constructors return 1 on unavailable pool capacity and ignore send
returns. The forwarder ignores their returns too. Thus issuance order alone
does not guarantee that both messages reached the writer.

## Writer ordering relative to event 30

Writer `C070E318..E4EA` receives from the second mailbox at `C070E35E`.
Message 3 jumps directly to exit/drain at `C070E496`. Message 2 dispatches
through `C070E440`:

```text
message 2
  C070E456 -> C070EAF0: remainder write
  C070E478 -> C070ED80: finalizer
  return to receive loop
message 3
  C070E496: drain queued messages until receive returns nonzero
  C070E4AC: set engine state 3
  C070E4B8/BA: raw notification 1 when R4 == 0
  C070E4C2/C4: raw notification 2 when R4 != 0
  C070E4D8: task exit call C01F52D4
```

A nonzero remainder/finalizer return with error flags `&1F` invokes
configuration+78 cleanup, sets R4=1 and takes the exit/drain path. Draining
is not finalizing queued work. The error arm emits its notification before
the additional peer-stop loop at `C070E4CE`.

The prior result audit executes `C06AECB8 -> C06AF038 -> C0389BB8 ->
C03A9798`: **raw 1 and raw 2 both yield event+E0=1** on the same recorder
owner. The new audit records raw callback invocations instead of reexecuting
that already audited event producer. Neither callback invocation nor enqueue
proves asynchronous consumer delivery.

Executed counterexamples:

| Injected condition | Writer behavior |
|---|---|
| Message 2 pool unavailable or its send fails; message 3 delivered | No finalizer; raw 1; exit |
| Message 2 delivered; message 3 unavailable or send fails | Finalizer called; next blocking receive waits; no terminal notification |
| First send fails | Request returns 0 and sets state 3; writer waits |
| Remainder write fails with flags | Finalizer skipped; cleanup; raw 2 |
| Finalizer fails with flags | Cleanup; raw 2 |

## Concrete file operations and their limits

The configuration-building stores at `C06AE938..E980` install these callbacks:

| Configuration slot | Function | Relevant role |
|---|---|---|
| +64 | C06AFB20 | Open-like callback |
| +68 | C06AFC58 | Close/release wrapper |
| +6C | C06AFCB0 | Write callback |
| +70 | C06AFEF0 | File virtual +38 operation, followed by source release |
| +74 | C06AFFA8 | Additional file callback |
| +78 | C06B0010 | Error cleanup |

The executed **finalizer suffix**, starting at `C070EF1C`, calls +70 with
temporary ID `[SP+4]` and original ID configuration+1A4. `C06AFEF0` resolves
both slots and calls `C03666D0`, which invokes the temporary object's virtual
**+38** with the original slot as argument. For valid resolved handles, it
then releases the original/source ID through `C06AF9E0`, even when that
virtual operation returned zero. Nonzero virtual-operation return maps to
callback success 0; zero maps to failure -1. Invalid handle resolution takes
an earlier failure path, outside the executed scenarios.

On +70 failure, the suffix sets flag 8 and skips its normal temporary/
destination close. On success it calls +68 at `C070EF3A` on the temporary ID.
A nonzero close callback would set flag 2. Any flag `&1F` invokes +78 at
`C070EF68`. The cleanup implementation is mocked, so the failure scenario's
remaining destination slot describes the state before any real cleanup effect.

Concrete close chain:

```text
C06AFC58 -> C06AFC88 -> C06AF9E0
  slot = manager + 64 + 12*ID  (12 decimal bytes, ID < 14 hex)
  C0366238:
    if slot object exists: object.vtable[+8](object, 3)
    slot object pointer = 0
```

`C0366238` ignores the virtual release return; `C06AFC88` returns zero.
The audit injects underlying release returns 0 and 1: both still clear slots
and follow the successful close-wrapper path. This proves local calls and
slot release, **not successful physical close**. Virtual +38 is not named
“flush” or “merge” here: its concrete implementation and storage guarantees
remain unresolved. No fsync-equivalent or media-durability barrier was found
in this bounded trace.

## Reproduction and exact execution boundary

```sh
python3 -B tools/fpl_mov_stop_audit.py --self-test
```

Requires Capstone and Unicorn. Default images are under
`$HOME/.local/share/fpsup/firmware/`; `--fp` and `--fpl`
override paths. Both full fingerprints are checked before execution:

| Image | Bytes (decimal) | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

Verified: **13 fp/fp L normalized correspondences, 15 ARM/Thumb scenarios,
6 semantic mutation rejections**. JSON includes operand differences and every
executed PC. Correspondence masks relocatable operands; it is not independent
proof that every relocated external target has equivalent semantics.

Execution uses official fp L instructions in read/execute mappings, synthetic
data, explicit allowed ranges and a 5,000-instruction bound per phase:

* Actual stop request, command-poll slice, latch gate, forwarder, message
  constructors, mailbox wrappers and writer body execute. Mailbox initializer
  is compared statically; distinct handles 101/102 are synthetic.
* OS sends/receives use synthetic FIFO lists. Empty blocking receive stops as
  `would_block`; nonblocking empty receive returns -50. Pool availability,
  allocation/copy, command recycling, configuration getters, state access,
  acquisition stop, task status/exit and peer-stop effects are mocked.
* Writer scenarios stub remainder write and the entire finalizer with explicit
  return/flag injection. They contain only messages 2/3, not media-data work.
* Separate suffix scenarios execute the real +70/+68 wrappers, virtual-call
  wrapper and slot-release code, with synthetic valid handles and stubbed
  virtual operations. They stop at `C070EF6A`, before the finalizer epilogue;
  they do not execute its earlier construction/write stages or prove its full
  returned status. They are not a full end-to-end filesystem emulation.
* Nine base pipeline cases plus two independent writer-send failures and four
  finalizer suffix cases cover the outcomes above. Mutations change command 1,
  message 2, message 3, the stop-latch destination, terminal raw status and
  slot clearing. Each fails a semantic assertion, not a CFG escape.

## Next exact actionable gate for a recording-aware shared logger

**Implement and offline-test an epoch-scoped `local-finalization-observed`
gate before treating a MOV stop as clean.** Its required evidence is:

1. One locally tracked recording epoch/owner; no overlapping start overwrites.
   Event 30 has no request token, and outward notification uses owner slot 2.
2. Observed message-2 handling and return from `C070ED80` at **C070E47C**,
   with **R0=0 and `[SP+18]&1F == 0`** for that writer/epoch.
3. Later **raw engine status 1 at C070E4BA**, for the same epoch. Raw 2,
   absent finalizer evidence, dropped evidence or mismatched epochs must not
   satisfy the gate. Event 30 result 1 alone cannot substitute for raw status.

For this next offline logger-state test, replay the audit's missing-message-2,
failed-message-2-send, finalizer-error and delayed/missing-message-3 cases;
require that none is classified as a clean completed epoch. Keep “local
finalization observed” distinct from “durable file saved.” Any future observer
installation requires separate authorization; none is installed by this work.

This gate supports logger classification and stopping collection, not permission
to free shared worker resources: the raw notification precedes task exit and
does not prove quiescence. Resource retirement needs separately established
worker/task completion. Durable-storage claims additionally require resolving
the concrete file virtual methods and their flush/completion contract.
