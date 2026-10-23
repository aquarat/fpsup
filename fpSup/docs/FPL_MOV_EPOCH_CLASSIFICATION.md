# Offline MOV epoch classification

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

`tools/fpl_mov_epoch.py` is a small, single-epoch diagnostic state machine.
It installs nothing and reads no camera. It distinguishes:

* `local_finalization_observed`: the required sequence is complete **within
  the bounded synthetic audit model**.
* `inconclusive`: incomplete, contradictory, misordered or unassociated
  evidence. This does not assert that recording or finalization failed.

Every result includes the evidence scope, preserved raw events, refusal
reasons, final state and explicit false claims for hardware certification,
durability, quiescence and resource retirement. A positive synthetic result
is not a hardware completion certificate.

## Association is a separate requirement

Event 30 contains no request token. An owner address, writer address and a
software epoch label do not establish that a callback belongs to the newest
recording. A late callback can reuse exactly those addresses. Sequence numbers
can detect some loss/reordering but cannot authenticate a capture or prove
absence of earlier pending callbacks.

Accordingly, public `classify(events)` and `--events FILE` **always refuse
causal association for imported events**. They still diagnose sequence errors.
Fields such as `epoch`, `proof`, `causal_association` or `evidence_scope` are
retained as raw data, never trusted. There is no public `verified=True` switch,
and no implemented live-capture verifier. Exporting a successful synthetic
replay and importing its events does not retain its association status.

`replay_audit(data, **case)` is the only supported positive-classification path.
It fingerprints official fp L MAIN, executes the existing stop audit's `run`,
and checks its `validate` assertions. That closed model has one injected epoch,
one writer and no competing starts/stale callbacks. The adapter supplies a
**synthetic** owner identity; it does not execute or prove the real recorder
owner binding. The model's association assumptions justify a diagnostic result
only inside that model. The private transition function is also exercised with
handcrafted tests; neither calling it nor constructing matching JSON proves
anything about hardware. This is a diagnostic boundary, not a security API.

## Explicit state machine

```text
await_start
  start(owner, writer)
await_message2
  message2 received/handled by that writer
await_finalizer
  finalizer_return(r0=0, flags & 0x1F == 0)
await_raw1
  raw_status(1), same owner/writer association
terminal
```

All refusals are sticky for the submitted batch. Successful-looking evidence
later in the batch cannot erase a gap, overlap, error or identity mismatch.
There is no automatic reassignment or resynchronization to a new epoch.

* Finalizer return must follow a unique observed message 2; send/attempt alone
  is insufficient. Raw status 1 must follow that return.
* `event30(result=1)` never advances the state. Raw 2 is refused even though
  it also maps to event-30 result 1.
* Nonzero R0 or flags masked by `0x1F` refuse the gate. Flags outside that mask
  do not independently indicate failure on this examined firmware path.
* Missing evidence at end is inconclusive. Sequence gaps, duplicates, reversal,
  explicit `gap` or `association_unknown` events are inconclusive.
* A second start, even with a new software label, poisons this single-epoch
  batch. Any evidence following its terminal boundary is conservatively
  refused as late/duplicate evidence; it is not silently assigned elsewhere.
  In particular, this tool does not merge later asynchronous event-30 delivery
  into an already terminated batch.
* Duplicate semantic events remain refused even if a caller renumbers them.
  A stale callback that looks numerically identical cannot be identified by
  this state machine; that is why arbitrary imported traces cannot pass.

## Input fields and observations still unavailable live

Imported JSON is an array of event objects. Each uses `seq` (integer), `kind`,
`owner` and `writer` (nonempty string identifiers). Additional fields are
preserved. Supported kinds are `start`, `message2`, `finalizer_return`,
`raw_status`, `event30`, `gap` and `association_unknown`. Unknown/malformed
events are retained and refused. A sequence number means input ordering only.

The minimum real observations needed to support the proposed gate would be:

| Evidence | Required content |
|---|---|
| Start/association boundary | Actual recorder owner, writer task instance/lifetime, configuration binding, serialized start, and evidence excluding pending older callbacks |
| Message 2 handling | Actual second-mailbox receive/dispatch, command word+4=2, same writer and configuration, ordered capture reference |
| Finalizer return | Return to **C070E47C** from C070ED80, **R0**, **[SP+18]** flags, writer/configuration identity and ordering |
| Terminal callback | **Raw R0=1 at C070E4BA**, before conversion, associated with that writer/owner |
| Capture continuity | Capture origin, event ordering/loss accounting, overlap detection and lifetime boundaries sufficient to reject stale association |

These fields and their continuity/association proof **have not been obtained
live by this work**. The existing passive descriptor observation establishes
an event-30 dispatch target, not the observations above. No meaningful hardware
certification follows from handcrafted traces or from merely filling these
fields with plausible values. A real capture association verifier remains
unimplemented; this tool deliberately does not accept such claims on trust.

The audit adapter maps actual synthetic receive log entries to `message2`
and actual bounded callback invocations to `raw_status`. Its
`finalizer_return` comes from **`finalizer_mock`**, with injected R0/flags,
not execution of the real full finalizer or a live C070E47C observation.
Its `start` is an injected single-epoch boundary, not an executed start path.
Each mapped event retains its audit-log index where applicable; the result
also retains the full original audit row, executed PCs and firmware SHA-256.

## Run and verification

```sh
# Diagnose an imported JSON array; association stays unproven:
python3 -B tools/fpl_mov_epoch.py --events path/to/events.json

# Run the bounded normal-stop model (requires official MAIN, Capstone, Unicorn):
python3 -B tools/fpl_mov_epoch.py --audit-replay

python3 -B -m unittest discover -s tools -p 'test_fpl_mov_epoch.py' -v
```

`--fpl` overrides the default official MAIN path used by the existing audits.
The replay API accepts only pipeline fault-injection parameters, not mutation
or finalizer-suffix modes. Existing audit files are unchanged.

Verification: **10 test methods**, including nine bounded audit scenarios:
normal stop; missing message 2; failed message-2 send; finalizer error;
remainder-write error; missing message 3; failed message-3 send; failed initial
send; and an unset started latch. The normal synthetic case alone passes.
Without the official MAIN file, the audit integration class explicitly skips;
the handcrafted state tests alone are not equivalent coverage.

Transition tests additionally exercise error flags, absent registers, raw-2
conflation with event 30, overlapping starts, duplicate/out-of-order evidence,
gaps, late events, owner/writer mismatches, invented proof tags and raw-event
preservation. All ten methods, including the replay cases, passed locally.

Even the positive classification makes **no durability, task-quiescence or
permission-to-free claim**. The callback precedes task exit, and the audited
close wrapper ignores its underlying release return. See
[FPL_MOV_STOP_FORWARDING.md](FPL_MOV_STOP_FORWARDING.md) for those boundaries.
