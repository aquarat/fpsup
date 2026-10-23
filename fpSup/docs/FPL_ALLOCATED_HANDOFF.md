# fp L 3.02: separately allocated worker handoff (offline prototype)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-20. **A larger worker can replace the reviewed 3572-byte worker without
overwriting its allocation.** Real predecessor, candidate and stock allocator
instructions execute in Unicorn. The first relocation deliberately retains the
predecessor until heap reset. This is a bounded control-flow/ownership proof,
**not an installable feature or a hardware exception-recovery proof**.

Only new files were created:

- `fp_usb_shell/asm/fpl_allocated_handoff_prototype.S`
- `fp_usb_shell/test_fpl_allocated_handoff.py`
- this document

Production worker, swap tool, allowlist and card files were not edited. No live
allocator calls, camera/card access, commit or publication occurred. No AutoRun
change is proposed for this RAM experiment. A future packaged worker still uses
the shared loader; this is not another file loader or universal replacement ABI.

## Evidence and allocator lifetime

Read the full `SUP_BUILD_RULES.en.md`, `FPL_ALLOCATOR_AUDIT.md`,
`FPL_HEAP_PROBE.md`, `FPL_BOOTSTRAP_AUDIT.md`, and actual spawn/serve code and
`fpl_swapworker.py` / `asm/fpl_swapworker.S` before this design.

The allocator audit executes official MAIN SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
Its findings, used rather than replaced by invented allocation semantics:

| Operation | Lifetime obligation |
|---|---|
| `C001D740(desc,0,n,0)` | Initializes a 16-byte descriptor; return is descriptor even on refusal |
| `C001D7F0(desc)` | Returns payload address, zero on refusal; this is the success test |
| Descriptor | `{address, class, duplicate_address, requested_size}`; no payload zeroing |
| USER allocation | Ordinary mode-layout changes preserve it; explicit free or restart heap reset ends ownership |
| `C001D7A0(desc,2)` | Releases payload, retains descriptor storage, returns no useful success status |
| After free | All four descriptor words remain stale; invalidate owned pointer fields, never double-free |

The descriptor is not registered as a live stack object: allocation metadata
records the callsite, not a pointer that must remain on that caller's stack.
`worker.S:spawn` uses two stack descriptors, drops both, and never frees either
allocation. This establishes why the current pool and body survive spawn's
return. It does **not** give a later replacement permission to fabricate an old
descriptor and reclaim the original code.

The new prototype allocates in worker task context after the swap branch. Its
descriptor initially lives at temporary `STATUS+16`, outside both bodies. After
copy verification it copies that descriptor into a trailing ownership record in
the new allocation. That record remains reachable by the new body's base plus a
build-derived offset. It is safe to **retain** a descriptor inside its allocation;
future reclamation would first copy it into independently owned storage and free
from outside the allocation, after all references are retired. No such resident
reclamation is implemented here.

Prior heap-probe hardware evidence proves finite USER code execution/return/free
at two actual allocation addresses. It does not establish a larger-worker hot
handoff, cross-core cache coherence, or task/callback retirement. The native
allocator tests here use synthetic heap state and do not measure live capacity.

## Narrow transition and stack proof

Predecessors are exactly the two production reviewed images (SHA identifiers in
`fpl_swapworker.py`), both 3572 bytes with `serve=120`, `next_round=200`,
`no_swap=292`. The existing allowlist is not expanded. The test assembles these
through the existing hash/symbol guard, and tests relocation from each.

1. Exclusive staging owner prepares the prototype, exact old-body snapshot, and
   complete scratch candidate. Upload/readback and **D then I before executing
   the trampoline** remain host preconditions, as in the existing handoff.
   This offline harness maps the trampoline directly; it does not test that
   transport/publication phase.
2. The reviewed predecessor consumes SWAP magic at its next-round boundary and
   `BX`s to the trampoline. No borrowed shell handler is overwritten. `r4` still
   points at pool state. Exactly the 32-byte `serve` frame is on the task stack;
   nested dispatch/capture and transfer helper calls have returned.
3. Trampoline pushes its own 32-byte frame. It checks cookie, pool/room/body
   publication, state address/magic, consumed SWAP magic and expected swap
   address, then compares **all 893 predecessor words** to the expected image.
   This is a sequential comparison, not an atomic image snapshot; exclusivity
   is a prerequisite, discussed below.
4. Allocate class-0 RAM of the candidate's exact size. A zero H_ADDR resumes old
   `no_swap`, with no publication change and no writes to old code. No cache
   call, candidate branch or null-address copy occurs.
5. Copy and word-compare the entire candidate, including initialized mutable
   fields. Populate its retained descriptor/token/predecessor record. Execute
   `C000E91C` then `C000EABC`, DSB/ISB. Recheck current WCODE_PTR against old.
6. Store new base to `C37588C4` (WCODE_PTR), one aligned 32-bit store, followed by
   DSB. Pool and room are untouched. This is the publication linearization point,
   **not** a claim that the candidate ran. A subsequent temporary status pointer
   is only a diagnostic hint; a crash before that hint cannot undo publication.
7. Pop trampoline's frame, then pop predecessor's `serve` frame, restoring SP to
   task-entry SP. `BX new+serve`; new serve pushes its own one 32-byte frame.
   Branching rather than calling leaves no trampoline return address on stack.
   The inherited task LR is preserved. Failed preconditions pop only the
   trampoline frame and branch to old `no_swap`, retaining old serve's frame.
8. Candidate resets upload tuple and MEM1 windows using its actual serve code,
   then writes `ENTERED=2` to its record at the first `next_round`, with DSB
   before and after the acknowledgement store. That is
   candidate-origin evidence; a prepared/publication marker is not equivalent.

The candidate is specifically the existing scratch USB guard variant plus a
24-byte PC-relative entry acknowledgement and a 32-byte retained record. It is
**3884 bytes**, not the production 3572 or guard-only 3828 bytes. Build-derived
offsets in this run: serve 120, next_round 200, no_swap 316, arm_out 3168,
guard_pins 3844, ownership record 3852. No candidate offsets are assumed equal
to the predecessor's except as checked for this particular source.

The safe point is a **worker call-stack boundary**, not a global USB quiescence
claim. Fault paths can leave cleanup for the next arm. The test preserves
state+8 and executes the candidate's actual EndTransfer-on-fault path before
StartTransfer. USB reconfiguration races documented in `FPL_USB_LIFECYCLE.md`
are not solved by allocation or this guard candidate.

## Retention, rollback, and identities

**Never free the original body in this transition.** Its original descriptor
was discarded; the task's saved entry can still name its serve routine, and
there is no proven enumeration/retirement of all copied callback pointers or
other observers. Retention avoids executing or returning into freed storage
even if such references exist. It does not prove those observers are serialized.
Repeated larger updates would consume more USER memory; there is no unlimited
update/reclamation claim. The first bounded experiment needs one extra block.
The candidate's MEM1 write-window exclusion follows the newly published code
base; it no longer automatically protects the retained old block. A future
host must refuse writable grants over retained allocations and reverify the
old immutable body before any reverse transition. Retention is not write
protection, and the prototype supplies no new global window policy.

Retain the new block after publication as well, including when the host loses
the reply or the candidate fails. Never free based on timeout or WCODE_PTR
alone. Rollback, if the candidate is still serving, must be a separately reviewed
candidate-next-round → retained-old-serve transition with its own unwind and
generation checks. The prototype does not implement that reverse transition.
An unrecoverable exception/hang after publication has **no automatic rollback**:
the retained old bytes are necessary but not sufficient to regain execution.
The existing cold-boot/card recovery remains the fallback; this task did not
exercise it. A no-reboot guarantee for arbitrary candidate faults would require
an independently established supervisor/exception recovery path, absent here.

Identity has two layers:

- The predecessor is immutable: compare the entire reviewed 3572-byte body.
- The candidate has mutable `guard_pins[2]` and an ownership record. A live
  whole-allocation hash will differ from the uploaded template. Verify every
  byte outside those **exact build-derived regions** against the fixed candidate,
  and validate the ownership record separately: `{base,0,base,size,token,old,
  phase,reserved=0}`. Do not mask arbitrary words or accept user-supplied masks.
  Pins are runtime state, not a code-version identifier. Runtime descriptor,
  token and predecessor are immutable after construction; only phase changes.

The prototype uses a fixed test-only 32-bit token. A production request needs
an unpredictable transaction identity persisted before arming, tied to exact old
and new images and allocation records, with a boot-generation policy. Address
equality alone permits ABA after allocator reuse or heap reset. Keeping both
allocations prevents their ordinary same-boot reuse, not reuse after restart.
Current firmware publication exposes **no independent boot generation**. The
existing host's random completion cookie gives probabilistic evidence, not a
mathematical proof that a boot did not occur. Do not advertise the prototype
cookie as a boot ID; deterministic cross-boot reconciliation remains a gap.

An aligned store is atomic as a single word; **compare then store is not CAS**.
There are deliberately no claims of atomicity for old-body comparison, the
three-word publication tuple, or pointer plus record updates. One owner must
exclude other hosts, writers, swaps, reset and teardown through this transition.
The existing file lock excludes only local cooperating tools. A final pointer
recheck is an error detector, not cross-host serialization. Firmware allocator
IRQ guards protect individual allocations, not this whole handoff.

## Pending/completion protocol required before live support

This is a design, not an added host command. Preserve the current no-retry rule:

1. Fsync an exclusive pending record before changing SWAP_ADDR or SWAP_MAGIC.
   Include schema/candidate identity, predecessor identity, original publication,
   exact scratch layout, request token and expected record offsets. After any
   uncertain arm reply, retain it; do not rearm or restage.
2. Read WCODE_PTR and classify without changing code or invoking alloc/free:

   | Observation | Meaning / action |
   |---|---|
   | Old pointer, no ack | Could be unstarted, refused, or allocated but not published; keep pending |
   | Old pointer, allocated PREPARED record | Candidate may be about to publish; no free/retry |
   | New pointer, PREPARED=1 | Publication happened, candidate execution unproved; no free/retry |
   | New pointer, ENTERED=2 | Entry observed, but transport health and full identity still need checking |
   | Unknown pointer/token/boot | Stop reconciliation, retain evidence; do not dereference stale arbitrary addresses |

3. Only mark completed after consistent before/after publication observations,
   independently verified immutable candidate spans and ownership record,
   cleared SWAP magic, stock echo, correct pool/room, restored read-only MEM1
   inspection windows, and a fresh successful protocol exchange/round progress.
   ENTERED alone is not a transport-health result. No host address derived from
   an unvalidated pending file is a memory-access authority.
4. Refusal/abort needs a separate terminal-result schema before automatically
   clearing pending. This prototype writes temporary failure status 3 for
   allocation/copy failure, but makes no host cleanup decision from that alone.
   A host cannot infer absence of an allocation from absence of an ack.

The test's `STATUS`, trampoline and source buffers occupy synthetic staging
addresses matching the general scratch area. They are **not a new production
reservation**. After completed handoff the retained record is in the new block,
so temporary staging is not its permanent storage. Reusing staging before proven
completion can still destroy the only running trampoline or descriptor. A live
integration must keep the existing pending/staging exclusion and account for
other hosts. Merely adding a candidate hash to the allowlist does none of this.

Unpublished copy-verification failures are different: the same trampoline,
still outside the new allocation, invokes real H_FREE(desc,2), invalidates its
stale address fields, and resumes old code. The candidate has never run or been
published, so no new code references exist. Tests check allocator accounting
returns to the baseline that still owns the predecessor (high-water retained).

## Reproduction and measured proof

```sh
cd fp_usb_shell
PATH="$HOME/.local/share/fpsup-toolchain/bin:$PATH" \
  python3 -B -m unittest -v test_fpl_allocated_handoff
```

`FPL_MAIN` optionally selects the official image path; its complete hash is
checked. Default is the durable private path used by the allocator audit.
Compiler is `~/.local/share/fpsup-toolchain/bin/clang`. Assemblies are made in
fresh temporary directories under the session's TMPDIR and removed by the test;
there is no installable binary/card output. Durable deliverables are the three
new source/document files. The candidate can be regenerated by `candidate()`.

**Result: 5 tests passed**, including both reviewed predecessor images,
preserved fault state, old-body mismatch, request-token mismatch, actual
allocator exhaustion, copy corruption with native free/accounting recovery,
and interruption snapshots at PREPARED, PUBLISHED, entering serve and ENTERED.
Every successful run reaches the new guard worker's actual arm_out and firmware
StartTransfer call from a distinct **stock-allocator-returned** address. All
old-body bytes remain unchanged. New pins really mutate, so the split identity
oracle exercises an actual live-state difference, not an artificial hash mask.

Three single-instruction/literal mutations are required to fail: omitted stack
unwind, I-cache call replaced with D-cache call, and publication STR replaced
with NOP. All were rejected by the independent oracle. Publication write hooks
check one four-byte store after D/I and before candidate execution.

Real instructions: audited descriptor/channel/list allocator, predecessor,
trampoline and larger guard candidate. Synthetic: class-0 64 KiB heap, pool,
stack and ready peripheral state. Stubbed: allocator telemetry, cache services,
EndTransfer; stop at StartTransfer before hardware effects. No MMU/cache/DMA,
concurrent writer, real power-off or CPU exception recovery is emulated.

Candidate template SHA-256:
`bb7919787b96abf8d6ac0828d08f8ea6ea2a815880d742c146e4b0e81eeffe5f`

Prototype assembly source SHA-256:
`a7bf12b4c80cf3710cddd62dbc7da504f79d04889b108601434832995bdd0574`

These identify this offline experiment, not a runtime loader pairing or release.
**Next gate:** explicit ownership/boot-generation and pending-host integration,
candidate-specific lifecycle review and reverse-transition proof, then separately
authorized hardware verification. Allocator lifetime itself is not the blocker;
global serialization, retirement and exceptional recovery remain unestablished.

## Follow-up: responsive-candidate reverse transition (2026-10-20)

The reverse-transition proof previously listed as outstanding above now has a
**new offline-only prototype**, not production host support:

- `fp_usb_shell/asm/fpl_allocated_reverse_prototype.S`
- `fp_usb_shell/test_fpl_allocated_reverse.py`

The forward prototype, production worker, allowlist and host tools were not
edited. This follow-up appended documentation and added those two files only.
No camera/card operation, live allocator call, commit or push occurred.

### Exact preconditions and immutable identity

The reverse test imports **the existing forward test's `candidate()`**, rather
than recreating the guard transformation. It pins its 3884-byte template hash
`bb7919787b96abf8d6ac0828d08f8ea6ea2a815880d742c146e4b0e81eeffe5f`
and exact symbols: serve 120, next_round 200, no_swap **316**, guard_pins 3844,
ownership record 3852. Changing the candidate requires a new review; the reverse
stub is not a version-independent ABI. Each retained old image is built through
the production hash/symbol guard, with the reviewed 3572-byte body and serve 120.

The current pool and both code allocations are still owned in the same boot.
The candidate is responsive enough to reach its exact next_round with its one
32-byte serve frame and `r4=pool+0x1000`. The staged reverse code, expected images
and request record have been fully read back and published D/I before arming;
this transport precondition is not emulated by the reverse suite. Exclusive
ownership of these scratch bytes lasts through completion reconciliation.

After the actual candidate consumes SWAP magic and branches, the reverse stub
checks current publication `{pool,1 MiB,new}`, state address/magic, consumed
SWAP magic, reverse stub address and a separate reverse-request token. It checks
candidate record phase is ENTERED=2, then compares its entire initialized image
against the prepared expected snapshot **excluding only three words**:

- `guard_pins[0]` and `[1]`, the exact two runtime TRB-pointer words;
- ownership-record phase at `record+24`, already validated separately.

All remaining record words are compared, not masked: descriptor
`{new,0,new,3884}`, forward ownership token, original predecessor address and
reserved zero. The expected snapshot is constructed from the pinned template
and this explicit owned allocation record, not accepted as an arbitrary runtime
mask/image. The complete original old body is compared word for word as well.
The token and current WCODE_PTR are rechecked after cache calls. These are
single-owner checks, still **not CAS or cross-host synchronization**.

### Stack, publication and failure paths

The reverse stub pushes its own 32-byte frame. After successful comparisons it
calls D-cache then I-cache publication and executes barriers. It publishes OLD
to `C37588C4` with one aligned four-byte STR and DSB, then writes a temporary
old-address **hint** to STATUS+4. Neither store is an old-worker acknowledgement.
It pops both its own and the candidate serve frames, preserves the original task
LR and tail-branches to `old+120`. The unchanged old serve pushes one replacement
frame and clears the upload tuple and all eight MEM1 windows. The test poisons
both regions before reversal and observes their actual reset instructions.

No allocation, descriptor query or free routine is called. In particular the
**3884-byte candidate remains retained**, including its descriptor, forward
token and phase. Its entire image is byte-identical after a successful reverse
round; its acknowledgement remains 2 and cannot identify the direction of the
most recent handoff. The old code remains byte-identical too. Keeping the new
block avoids premature free of potential references; this is not a proof that
all such references are retired or that retained bytes are write-protected.

On any mismatch before publication, only the reverse stub's frame is popped,
and execution resumes at **candidate+316**, not predecessor+292. Tests stop at
that exact instruction and check SP, r4, incoming fault and unchanged windows /
upload tuple. They establish the failure continuation, not a new post-failure
USB lifecycle guarantee. A mismatch caused by an external publication writer
does not cause the stub to overwrite that writer's publication on abort; global
concurrent-writer recovery is outside the single-owner model.

Incoming pool identity, task ID and fault count are preserved. For an incoming
fault flag of 1, the old worker itself calls EndTransfer before arming OUT; only
its subsequent successful reply_done clears the fault flag. Nothing in the
reverse stub clears or synthesizes those worker counters. Runtime hooks also
reject any return into scratch after old serve is entered.

### Completion belongs to the unchanged old worker

Old code has no entered/generation acknowledgement, so the reverse proof runs
it **through a real command round**, not merely to its first instruction or arm.
The firmware USB stubs deliver a fresh framed request at OUT completion, collect
the actual worker-generated IN frames, and complete IN waits. The old worker's
real frame parsing, reply construction, CRC calculation path, wait_done and
reply_done execute. The independent oracle requires:

- the retained old body was entered with task-entry SP and inherited task LR;
- a successful MCAPS response, with all 112 payload bytes checked (pool, size,
  XFER_MAX and eight zeroed windows), or ping response for the identified image;
- matching sequence/command, success status, fragmentation flags and valid CRCs;
- actual old reply_done advances `served` from 7 to 8 and returns to old
  next_round with exactly one 32-byte serve frame.

Both reviewed images pass MCAPS. The PONG image also emits `PONG`; the older
reviewed image emits its expected empty ping acknowledgement, explicitly not
mislabelled PONG. The test does not substitute a trampoline status for any of
these observations. USB/DMA hardware and cache services remain simulations.

Interruption tests stop at three distinct points:

| Stop | Published body | STATUS hint | Old served/replies |
|---|---|---|---|
| Immediately before publication STR | Candidate | 0 | 7 / none |
| Immediately after publication STR, before DSB/hint | Old | 0 | 7 / none |
| At old serve, before executing its first instruction | Old | Old | 7 / none |

Candidate record phase is 2 in **all three**. Thus old pointer, candidate phase
and even the reverse hint together cannot establish old-worker operation. Lost
host replies leave the reverse pending record in place. A future host must
combine consistent publication/identity observations with a newly sequenced
successful old-worker operation (and restored inspection windows), under the
same exclusive transaction/boot assumptions as forward handoff. A stale response
or pre-existing served count is not fresh completion evidence. The prototype
does not implement host reconciliation or an automatically cleared pending file.

### Verification, scope and remaining gates

```sh
cd fp_usb_shell
PATH="$HOME/.local/share/fpsup-toolchain/bin:$PATH" \
  python3 -B -m unittest -v test_fpl_allocated_handoff test_fpl_allocated_reverse
```

**10 tests passed: 5 forward and 5 new reverse tests**, with subcases for both
retained images, MCAPS/ping, preserved fault cleanup, interrupted publication,
and 14 mismatches covering publication, reverse request, old image, candidate
immutable bytes, every ownership-record word and phase. Changed guard pins are
accepted as runtime state. Four deliberate mutations must fail and do:
omitted unwind, omitted publication store, I-cache replaced with D-cache, and
the old-body mismatch branch replaced with NOP. That last mutation is exercised
with a mismatching old expected image and is rejected for reaching old serve.

The reverse suite uses synthetic separately owned mappings for old and candidate;
it does not re-execute an allocator. The existing forward suite independently
executes the real allocator and establishes that ownership model. The combined
run is **two bounded proofs, not an uninterrupted allocator→forward→reverse→
forward integration soak**. Candidate/old/frame instructions execute in Unicorn;
cache, firmware CRC and USB completion services are simulated. No hardware MMU,
DMA, power-off, exception or cross-core model is claimed.

Reverse assembly source SHA-256:
`1e81b988260b2f4f1990c5a05e8f569f4ba5a983d3d4bc8ffe1478b1272b1793`

Reverse test source SHA-256:
`0f8fd8da0460b7ef648f12167af59b2b58807012a2efeb74ee934caedf10e40a`

Builds use the durable clang, fresh temporary assembly directories and no
installable output. This is **responsive-candidate rollback only**: a hung or
faulted candidate that cannot reach next_round cannot use this mechanism.
Boot-generation identification, cross-host exclusion and real exceptional
recovery remain gaps. A later forward handoff from restored old code would
need a fresh transaction and revalidation; no retained-block reuse protocol,
unlimited lifecycle, reclamation or arbitrary-candidate support is proved.
