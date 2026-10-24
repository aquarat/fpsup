# fp L formatter reservation contract (offline M3 slice)

> **Update 23 October (live):** with the owner accepting card loss, an N=560
> test take was run with the one-shot observer `fp_usb_shell/asm/fpl_gtag560.S`
> (not the fail-closed gate described below, which still does not exist). The
> final header carried exactly the 560-byte GTAG with H = StripOffsets =
> `0x13800`. Details: [roadmap implementation](FPL_ROADMAP_IMPLEMENTATION.md).

## Late population / fixed-delta / event 0x2B investigation

**Recommendation: do not arm a live N=560 take under the requested fail-closed
conditions.** The final leaf population pass is now mapped and emulated, and
the failure notification is proved to enqueue an event. The earlier interval
from our observer's position through the remaining native observers and
recording-state callbacks is not closed. Therefore neither a verified total
late delta nor synchronous before-first-card-frame cancellation is established.
This does **not** prove that a code hook is logically unavoidable; it rules out
using the three finished prefixes as sufficient fixed-delta evidence, and rules
out treating the examined 0x2B producer as a synchronous cancellation barrier.

### Metadata writes in the final population pass

`C06A2858` calls the three producers below. With the captured left +88=1,
`C06A2874..7C` skips `C06A3350`. The test executes this dispatcher and all three
producer bodies; geometry getters, settings getter, DataPool serializer and
tag-add boundaries are explicit stubs recording the requested ABI. Native
storage/sizing/removal remain separately tested against the real reconstruction.

| Producer and native add site(s) | IFD / tag / type / count | Size implication |
| --- | --- | --- |
| `C06A2F18`: 2F90, 2FB8 | root 0100, 0101 / LONG / 1 | inline dimensions; fixed request lengths |
| 2FF0, 3038 | root 0102, 0103 / SHORT / 1 | inline bit depth/compression; fixed request lengths |
| 3100, 3128, 3158 | root 0111, 0116, 0117 / LONG / 1 | uncompressed strip offset placeholder, rows, byte count; fixed lengths |
| 31C0, 31F8 | root C61D / LONG / 1; C61F / LONG / 2 | white level inline, crop-origin payload 8 bytes |
| 3280, 32AC | root C65A, C65B / SHORT / 1 | fixed inline constants 0x11 and 0x15 |
| `C06A3750`: 381C, 383C, 385C | private IFD selector 8, tags 101F/201F/301F / SHORT / 4 | conditional on settings singleton's value ==1; three 8-byte payload requests, not proved absent by the capture's root/Exif layout alone |
| `C06A32B8`: 333C | MakerNote 0200 / UNDEFINED / 0x4000 | fixed 16,384-byte request. At 331C, calls DataPool virtual +C to fill its temporary buffer with capacity 0x4000; contents are opaque in this test. |

Addresses abbreviated in the middle column of the first field above have prefix
`C06A`. These are **requested lengths**, not proof of net growth. Replacement
can add zero, grow, shrink or introduce an entry depending on the incoming graph.
The add wrapper still has the known allocation-failure semantics.

The mode-dependent branches are material:

* `C06A2FFC/3040` checks descriptor byte +4. The compressed branch substitutes
  root 0142/0143 LONG[1] and 0144/0145 LONG[descriptor+18] for strip fields;
  array counts are runtime values. The capture's Compression=1 supports the
  uncompressed result, but an observer gate would have to bind this native
  descriptor, not just a UI label.
* With left +88=0, `C06A3350` populates IFD selector 6 (including image dimensions,
  compression/tile or strip tags, white level/crop, CFA 828E and additional
  strip offsets/counts for indexed child IFDs). This path is excluded only by
  the captured +88=1, not universally.
* `C06A3750`'s private-IFD condition must also be bound to native state. Its three
  writes cannot be silently dropped from a claimed total-delta proof.

The remaining earlier write frontier is explicit: build notify iterates all
nine slots at `C0053618`; attaching into an empty slot does not prove it is last.
`C038A350` then hands off the DataPool, and the recording path has indirect
state/provider dispatches, including `C0379090..A8`, before the final writer.
Their complete live target/graph mutation set is not captured or emulated here.
Consequently this table is a complete map of the selected final leaf pass,
**not an invented complete map of every write since our observer ran**.

### What delta can actually be measured

For the final graph reconstructed from frame 1:

```
size with those 11 root tags and MakerNote 0200: 0x135C4
size after native removal of exactly those tags: 0x0F52C
difference:                                    0x04098 (16536)
```

That difference is `11*12 + 8 + 12 + 16384`: the **all-absent** hypothesis with
the private-IFD branch excluded. If all those entries already exist at identical
lengths, replacing them contributes zero; partial presence gives other deltas.
Thus **0x4098 is not the measured observer-to-final delta**. Frames 1/70/141
provide only the final size, not the initial builder size/contents. Identical
final layouts cannot distinguish these histories. Nor does the last nonzero
byte identify the end of zero-valued payloads. A safe fixed-delta argument needs
the incoming graph and every intervening writer bound to the same mode/state.

### Is there a later no-hook callback?

Between return from `C06A2858` at `C06A29F4` and padding at `C06A2A18`, the native
sequence is builder vtable +C dispatch (size) followed immediately by rounding.
There is no second Subject call in that interval. The following Subject mode 2
at `C0379188` is after serialization/length publication. DataPool virtual +C at
`C06A331C` runs **inside** the last producer, before it adds MakerNote 0200, so
it is not an after-population notification either.

The builder's RAM vptr and its size slot are potential interception mechanisms,
but substituting a private vtable is itself a hook with lifetime, reentrancy and
restoration obligations. No existing registered application callback after the
last population step was established. This is a bounded call-path result, not
a proof about all firmware callbacks.

### Failure callback and event 0x2B

`C0377410` merely stores a callback pointer at object+C. `C0377428` loads that
pointer, calls its vtable+C if nonnull, then returns. Four recording-worker
registration call sites are `C03818F8`, `C0381904`, `C0381910`, `C038191C`.
They do not install a serializer-size veto.

`C0385978` constructs a 0x168-byte event: +4=0x2B, +C=reason class (5 for input
reason 0), +E8=argument1 and +E4=argument3. It calls `C03A9798` at `C0385A84`.
The latter checks event-pool availability, copies the event and calls queue
routine `C036DB60` at `C03A9894`, then returns 1. With no pool room it returns 0
at `C03A983C`. No consumer completion is awaited. The replay proves event bytes,
queue handoff and pool-exhaustion refusal; the queue consumer is explicitly not
executed. Mutation 0x2B -> 0x2A loses the reserved-pool admission and is detected.

One actual producer call, `C037E6B8`, is after buffer/header processing and tests
buffer+FE8, then reports reason 4/argument3=3 and returns through its worker
continuation. This is particularly unsuitable as proof that no frame has reached
the card. The state at C358EAC0 may eventually handle a queued failure, but no
audited polling flag or synchronous path from this event to before-first-frame
card exclusion is established. The prior state-method audit remains applicable.

**What is left behind:** a successfully enqueued event copy and potentially
in-flight recording work. No tag removal, builder reset, file deletion or
rollback is performed by this producer. Event-pool exhaustion can leave even
the notification unsent. Exact file count/trailer/cleanup after consumption
cannot be asserted without the consumer/state and card-I/O ordering proof.

### Concrete outcomes and recovery limits for an unproven N=560 trial

* Expected: metadata/H/StripOffsets=0x13800, exactly one valid 560-byte GTAG.
* Unexpected extra metadata can move H to **0x13C00** with StripOffsets also
  0x13C00. If actual placement follows that offset and all bounds hold, this can
  be a valid shifted-strip DNG rather than corruption. It falsifies the
  padding-only claim and is detectable by prefix plus live owner reads. At
  measured +128=0x15400 it still leaves 0x1800 headroom; this is not proof of
  allocation ownership or correct image placement.
* Offset/placement disagreement can give a decodable header with shifted or
  corrupted image data; a prefix alone cannot certify the pixels. Full frame
  read/decoding would be required to assess it.
* Missing storage can leave absent/malformed GTAG metadata despite successful
  bookkeeping. Structural validation and exact payload comparison detect it;
  native readback/rollback must run before writing to prevent it.
* A queued failure can leave zero files, some complete frames, or an incomplete
  take; this investigation does not establish which. MOVON/MOVOFF timeouts do
  not distinguish these outcomes.
* Growth beyond real destination/headroom can cause a RAM overwrite before a
  host check, with a stalled shell/recording task or corrupted take. A later
  prefix check cannot undo that overwrite. Native assertions can also stop work.

A mere valid shifted strip is a file-level deviation that can be retained and
examined without changing camera state. For memory corruption or an interrupted
write, **recovery without harm cannot be guaranteed**: owner-authorized cold
recovery may restore volatile state, while the take/card filesystem may need
inspection. There is no evidence here of a deliberate persistent-settings write,
but that does not turn unchecked RAM writes into a harmless test. Preserve the
existing timeout, quiescence, staging and recovery rules; do not bypass markers.

An N=560 live take **now** would rely on an unproved fixed-delta/mode argument
and would have **no proved synchronous cancellation**. It is not justified under
the requested constraints. Arming remains blocked; the worker upload/MOVON
procedure below is not enabled by these findings.

### Verification

New `test_fpl_formatter_late.py`: six tests covering complete selected final-pass
request tracing, compressed/private-mode changes, omitted-MakerNote mutation,
native size/removal delta, real event construction/enqueue, pool exhaustion and
event-ID mutation. **77 tests passed, zero skips** (269.248 s), including all
prior regressions and default fp release-byte equality. Expanded MAIN/DATA audit
passed. With the fixture/toolchain environment documented below:

```sh
python3 -B -m unittest -v test_fpl_formatter_late test_fpl_formatter_rollback test_fpl_formatter_route test_fpl_formatter_dng test_fpl_formatter_take test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

Logs, audit and source hashes:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-late-population/`.

## Padding-only transaction and native rollback investigation

**Latest status: arming remains blocked, including N=560.** A synchronous ARM
transaction primitive now proves native entry readback and tag removal on the
reconstructed final graph. A final-builder/live-destination insertion point and
a take-cancel continuation are **not** proved. The primitive's refusal is a
return to its test caller, not a demonstrated refusal by the CinemaDNG state
machine. In particular, N=561 is rejected before insertion in this test, but no
claim is made that an installed callback would prevent MOVON or a stock take.

### Native points investigated and caller handling

| Point | Exact evidence | What the caller does / conclusion |
| --- | --- | --- |
| Final recursive size | `C06A29F4` calls late metadata population `C06A2858`; `C06A2A08` calls builder virtual +C. | Size is available before `C06A2A18` rounds/zero-fills and before `C06A2C90` serializes. No observer invocation or evidenced refusal branch exists between this size return and padding. A gate here still needs an insertion route and valid destination evidence. |
| Writer returns zero | `C06A294C..74` returns zero on the null-destination path after optionally populating metadata. | At `C03790CC..E0`, r0 is copied to buffer+14C and owner+C, **without a test**. A new replay executes these stores with r0=0. This proves no immediate error branch, not that all downstream code tolerates zero. Do not use zero H as cancellation. |
| Native tag lookup | `C00BAA10`: compares entry+8 tag at `C00BAA3C..44`, returns entry pointer or zero. | Read entry type/count at +A/+C, value object at +10, copied data pointer/length at value+8/+C. Compare all N copied bytes, not just F_ADD_TAG r0 or observer bookkeeping. |
| Native tag removal | `C00BAA98`: searches tag; `C00BAAD8` releases matching entry via `C00B9A80`; `C00BAAE4` erases vector index via `C00BA538`. Vector erase shifts slots and decrements count at `C00BA598..5A0`. | Direct MAIN BL callers `C00C5380` and `C00C5604` advance their tag-list cursors after calling; neither tests a status. Removal itself has no useful checked-success contract. Verify tag absence and recomputed size afterward. Do not infer success from r0. |
| Builder reset/destruction | `C00B54A8` installs its destructor vtable, releases root at `C00B54D0`, clears builder+8 at `C00B54D8`, then performs base cleanup and optional free. | This is a destructor, not a take-abort API. Calling it on the live builder would invalidate subsequent writer use; no caller cancellation is established. |
| CinemaDNG state `C358EAC0` | Getter `C038B3D0`; constructor `C038B470` sets id 0xF and dispatch table `C0BC24AC` at +10. Getter's direct MAIN caller `C0388B28` registers it at owner+134. | State method +14, `C038B620`, calls `C039AD50`, branches on its result, sets state+18 or calls `C03A94E8(...,2)`, then returns **0xF on both paths**. This is not an evidenced arbitrary-error/take-abort API. No connection from tag failure or writer size to a synchronous cancellation was found in these audited windows. Full event/state-machine cancellation remains unproved. |

The search scanned aligned direct BL references to the native remove routine
and state getter across the exact MAIN image, then inspected the callers and
the state's dispatch table. This is bounded evidence, not a claim that no abort
mechanism exists anywhere in the firmware. Audit windows retain the instructions.

### Why repeated stock frames do not close the mode-0 gap

Main's hash-recorded frames 1, 70 and 141 have identical IFD structure and H,
with nine changing bytes and zero trailing padding. This supports a stable
**finished** header for that take. The last nonzero byte 0x135BC does not change
the metadata extent 0x135C4: trailing zero payload bytes still occupy storage.

The observer can call native `C00B6510` to measure its **current** builder, and
can inspect the copied entry synchronously. It cannot equate that current size
with the final 0x135C4 without another proof: `C06A2858` still runs later and
calls `C06A2F18`, `C06A3750` and `C06A32B8`. No captured mode-0 builder graph or
complete bound on those later mutations is available. A counterexample test
accepts 560 on a final-sized fixture, then performs another native six-byte
insertion: metadata becomes 0x13812 and H becomes 0x13C00. That extra test tag
is not claimed to occur live; it demonstrates why an earlier check alone cannot
certify the later builder. Stable finished frames are not a native freeze barrier.

### Experimental synchronous primitive — exact proof boundary

`test_fpl_formatter_rollback.py` assembles an isolated ARM transaction into
emulator RAM. ABI `(builder, MakerNote IFD, immutable source, N)` assumes a valid,
owned, nonconcurrently mutated graph. **It is not an installer or observer.**

1. Require N exactly **560**, native baseline size **0x135C4**, and no existing
   GTAG (never replace/delete someone else's tag).
2. Call native `C00B6B20`. Ignore its return value for admission.
3. Native lookup, verify UNDEFINED/count, nonnull value object/data, length 560,
   and compare every copied byte against the immutable source.
4. Require recomputed native size exactly **0x13800**. Return accepted only then.
5. Otherwise call native removal, verify tag absence and native size restored to
   the baseline. Return refused. If rollback verification fails, return a
   distinct broken-rollback status; **no safe live continuation is claimed**.

Tests execute both primitive instructions and official lookup/add/remove/size/
serializer instructions. Heap/copy/guard boundaries retain the explicit earlier
stubs. Successful insertion and allocation-failure rollback are followed by
native serialization and a byte-for-byte comparison with the reconstructed
baseline. Freed addresses are recorded by the harness, not recycled; allocator
concurrency/lifetime is not simulated. The test compares reconstructed output
before/after, not its relocated IFD layout against raw capture bytes.

Fault/mutation cases: value-object allocation failure, payload allocation failure,
entry allocation failure, wrong baseline size, N=561 refusal before allocating,
and NOP of native vector erase (rollback verification must report failure).
The existing route suite covers full Subject without slot overwrite and the
return-zero-does-not-cancel mutation. Native writer-result publication is also
replayed with zero. Default fp code is unchanged.

Verification: **71 tests passed, zero skips** (219.944 s); expanded MAIN/DATA
audit passed, as did the default fp release-byte comparison. Using the existing
fixture/toolchain environment, from `projects/gyro2-sup`:

```sh
python3 -B -m unittest -v test_fpl_formatter_rollback test_fpl_formatter_route test_fpl_formatter_dng test_fpl_formatter_take test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

Logs, audit and source hashes:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-padding-rollback/`.

**Not proved:** that the primitive is called after the last metadata mutation,
that its pointers/bounds refer to the live owned allocation, that rollback
failure or refusal prevents recording, or that observer teardown is quiescent.
There is no executable live gate to arm yet. The smallest remaining proof is a
usable synchronous final-builder boundary before `C0697018`, tied to actual
destination/headroom and a caller continuation that honours refusal. The native
remove primitive solves tag rollback, not that control-flow/ownership problem.

### Live procedure delta

Supersedes the two-take worksheet below: the next candidate experiment is
**N=560 only**, and N=561 is an offline pre-arming refusal test. Keep all preflight
reads and timeout/restoration rules below, but perform **no arming writes and no
MOVON for this experiment** until the missing boundary is proved. A full Subject,
wrong baseline, missing copied data or failed rollback must prevent arming;
post-start host reads are not an acceptable substitute.

When that proof exists, one short take should yield metadata/H/StripOffsets all
0x13800, GTAG type 7/count 560 and exactly the selected bytes, with measured
+128 still 0x15400 and 0x1C00 remaining headroom. Use the existing frame-1
`--prefix --size 0x20000` download procedure only after verified idle, detach,
quiescence and echo restoration. N=561 must not be scheduled as a live follow-up
under this padding-only design. No new cold-recovery or marker-bypass procedure
is introduced.

## Smallest test-tag take: route assessment (offline)

**Status: native hookless attach is evidenced, but no route meeting the requested
fail-closed live conditions is yet evidenced. Do not arm the current observer
probe or start the proposed test take.** The smallest missing piece is a
synchronous, fail-closed pre-write gate over the final builder and actual
destination/headroom, with a proven rollback/cancel continuation. It must run
before padding as well as serialization. Merely observing mode 2 or returning
zero from an observer is insufficient. This is a missing firmware-control proof,
not a need for the blocked far-hook work.

### Candidate comparison

| Candidate | Evidence / timing / context | Restore and present limitation |
| --- | --- | --- |
| Native Subject observer | `C0054E28` returns `C31AB0D0`; `C00CF208(subject,obs)` searches nine pointer slots and stores into the first empty one. `C0053618` synchronously calls `[obs.vptr+0xC]`. Build event 0/type 3 is sent at `C0053000` inside `C0052F30`, called by take construction `C038A36C`. Mode 2 follows header construction at `C0379188`; mode 3 is in the frame path `C038C918`. | Registering via borrowed echo runs in the shell task; callbacks run inline in the notifying take/frame caller, **not** in the shell task. Exact scheduler task identities are not established. Restore only our verified slot to its saved zero after callback quiescence; keep observer/code/source storage live until then. Full-slot attach asserts. No take-veto return value. |
| RAM vptr replacement | Writer obtains builder from DataPool virtual +2C at `C06A290C..1C`; calls builder virtual size +C at `C06A29F8..2A08` and serialize +10 at `C06A2C7C..90`. Captured left leaf has a RAM vptr field at leaf+14 pointing to `C2E4A5B0`. | These are dispatch sites, **not an evidenced persistent writable callback slot**. The builder/leaf belongs to a take; its publication, replacement timing and lifetime before first write are unproved. A private copied vtable/vptr substitution would itself be a hook requiring separate proof. Restore the exact saved vptr only while its generation is still owned and quiescent; do not overwrite the shared image vtable. No such hook is supplied here. |
| One `F_ADD_TAG` call between takes | fp L `C00B6B20(builder,5,0x4653,7,N,source)`; count/source are stack arguments. The real builder is `DataPool+45D0`, obtained by `C0053D80`; the factory constructs the pool during start. | `C358E9D8+8` is the formatter, **not a TIFF builder**; +10 is serialized bytes. Earlier idle capture had an empty owner. No next-take builder lifetime/publication is evidenced between takes. Calling in the shell task would also race recording-task mutation unless exclusion is proved. Restore echo; copied tag storage needs native rollback/destruction, not just pointer restoration. Reject this candidate for now. |

All addresses above are fp L 3.02. None uses fp `F_WRITE_AT` or the fp callfn
slot. The blocked v3 files were neither read nor changed.

### Why the existing observer cannot enforce refusal

1. Native attach can provide a slot, but its lock does not prove a callback has
   finished when the host later clears it. The dispatcher has no matching lock
   in the audited iteration. A staging lock protects host clients, not camera
   callbacks.
2. `C0053660..6C` interprets callback return zero as **clear this observer slot**,
   then continues iteration. `C0053004..18` continues the factory after notify.
   There is no evidenced cancel/error propagation from this seam.
3. The shared observer increments its bookkeeping even when the value allocation
   fails. A fresh replay now demonstrates this with N=561: the observer remains
   attached, native writing returns, and strict header validation refuses the
   resulting missing-data tag. Nonzero add return is not admission.
4. Mode 0 is not a final-size gate. `C06A29E8..F4` calls `C06A2858` to populate
   metadata **after** the build notification and before final sizing. A mode-0
   size calculation cannot certify the later serialized extent. Mode 2 is too
   late to prevent the first write.
5. `C0697018` zeroes padding before used-row publication; the reservation assertion
   is not a sufficient pre-write guard. The serializer's nominal third argument
   is not an enforced destination capacity (see prior guard-overwrite test).

### New Unicorn route tests

`projects/gyro2-sup/test_fpl_formatter_route.py` builds the existing shared fp L
observer with capacities 560 and 561, invokes actual native attach and mode-0
notify, then native insertion, sizing and serialization on the real-prefix
reconstructed graph. The configured 1234 Hz is just a way to saturate the
explicit test cap at the harness's 25 fps; **not a calibration or proof that
the unchanged shared observer always requests exactly N in every live mode**.
A live trial should use a fixed-N experiment callback or verify the rate
calculation before arming. It must not install the probe's emulator callback.

Tests check exact UNDEFINED count and all-zero payload, H=0x13800/0x13C00,
StripOffsets=H, and admission under 0x15400. Fault injection fails the value
allocation. A machine-code mutation changes the observer return from one to
zero: native dispatch removes the slot, but the added tag remains and the
subsequent native writer still emits H=0x13C00. A full-nine-slot test asserts
without overwriting any slot. These prove both reachability and the refusal gap.
Guard/lock/context/heap/memcpy/memset boundaries are inherited explicit stubs;
no concurrent camera task or complete recording state machine is simulated.

Executed: **65 tests passed, zero skips**, including default fp release-byte
equality and the expanded official MAIN/DATA audit. From `projects/gyro2-sup`,
using the fixture/toolchain environment in the commands below:

```sh
python3 -B -m unittest -v test_fpl_formatter_route test_fpl_formatter_dng test_fpl_formatter_take test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

Evidence/logs:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-test-tag-route/`.

### Main's live worksheet — blocked at arming

The minimum experiment is **two separate short CinemaDNG takes**, first N=560,
then N=561, with no settings changes between them. There is no evidenced
single-frame stop command; retain frame 1 of each take and stop as soon as a
frame exists. Do not promise exactly one recorded frame.

**Before any write**, main can collect the following using the resident worker's
existing word-read interface (`fpl_getfile.Backend.words(address, count)`):

* `version`: require w91c1 / 3.02.0.V90; save MCAPS and publication words
  `C37588BC` (3 words), and recheck they agree using `fpl_getfile.layout`.
* `C0BD2544` (1 word): require echo handler **C03D9BB8**.
* `C31AB0D0` (9 words): snapshot the complete Subject list twice; require stable
  values and at least one empty slot. Follow each nonzero observer/vptr only in
  verified readable ranges. Do not treat slot availability as quiescence.
* `C358E9D8` (6 words): save owner, formatter, H, source, state. Idle/stable owner
  is required, but zero fields are not a way to obtain the next builder.
* Save registry `C3520D88` and relevant buffer records using the existing
  take-capture reader. For each candidate record save +4, +4C, +68, +128, +12C,
  +14C; later require the pre-retreat form +4C=+68+0x15400, not base+0x1C00.
* Inspect the staging pending marker and resolve it through the existing main
  workflow. Never delete it or use `permit_pending=True` to make this experiment
  proceed. Hold the normal staging lock across any eventual staging use.

**Arming/write ledger (design requirements, not an executable recipe):**

| Write | Required restore |
| --- | --- |
| Upload experiment code, parameters, observer/vtable and immutable N-byte source into a proven exclusive worker-window reservation; save original bytes and read back uploads. | Keep storage reserved throughout both callback lifetime and teardown. After quiescence, restore saved bytes or release according to the reservation owner. `fpl_getfile` uses pool+0x10000 onwards and must not overwrite a still-attached observer there. |
| Borrow echo `C0BD2544` for cache publication `C000E91C`, then `C000EABC`, then an audited install/getter wrapper, verifying every word and each reply. | Restore **C03D9BB8**, read back; wrapper and parameters must be read back before execution. This is the fp L getfile pattern, not fp callfn. |
| Native attach adds one observer pointer at the chosen empty `C31AB0D0+4*i`. | Saved value is **0**; verify the slot still contains our observer, then clear it only after proven quiescence. Never restore an entire old nine-word snapshot over other observers. |

There is currently **no admitted wrapper/placement/quiescence and pre-write
refusal gate**, so the exact arming writes and `key MOVON` are deliberately
blocked. Do not use the offline test's `45000000/46000000` addresses on camera.
If main needs an executable procedure now, the answer is no: these missing
proofs cannot be substituted with a post-start read or a successful echo reply.

Once that gate is implemented and independently tested, the intended order is:

1. Install N=560 only after the above checks and verify exact copied payload,
   final-size bound and destination evidence in the synchronous gate.
2. Send `key MOVON` **once**, without automatic retry. Observe recording state,
   gate status, owner H, left ledger +20/+24/+40 and buffer fields above.
   Expected metadata=0x13800, H/StripOffsets=0x13800; remaining headroom=0x1C00.
3. Send `key MOVOFF` once after a frame exists. Establish idle and callback
   quiescence, detach and restore echo/storage before borrowing getfile staging.
4. Download the newly listed take's frame 1 (derive path from card listing, do
   not reuse A001_001 by assumption):

   ```sh
   python3 -B fpSup/fp_usb_shell/fpl_getfile.py \
     '\CINEMA\<new-take>\<frame-1>.DNG' '<new-local-prefix>' \
     --size 0x20000 --prefix
   ```

5. Parse root/Exif/Sigma MakerNote, require exactly one GTAG 0x4653/type 7/count
   560, all N test bytes equal the planned immutable source, StripOffsets equals
   captured H, and run strict header admission with measured bounds. Save hashes,
   listings, pre/post reads and recording status. Do not assume new prefixes
   have the stock fixture hash.
6. Only after clean teardown and a passing first take, repeat with N=561.
   Expected metadata=0x13802, H/StripOffsets=0x13C00, remaining headroom=0x1800;
   padding=0x3FE. Capture any actual differences instead of forcing the expected
   layout. Recheck +128 remains 0x15400 for this mode.

**Timeout/abort:** MOVON/MOVOFF replies previously timed out despite keys landing.
Never retry a start blindly. With a responsive shell, read state first; if
recording, request MOVOFF once and verify idle. If state cannot be established,
do not detach/reuse staging. A failed add, missing copied bytes or oversized
final extent must be refused synchronously by the missing gate, not by waiting
for the host to send MOVOFF. If echo/shell stops replying, stop issuing calls,
preserve pending/ownership evidence and assume the observer and borrowed echo
may still be live. Host software cannot guarantee restoration in that state.
Main must use the owner-authorized fp L cold-recovery procedure; a warm restart
is not proof that a borrowed slot or callback was cleared. After recovery verify
version, worker publication, stock echo, Subject list and idle owner anew before
releasing old staging. Do not automatically reboot or clear a retained-task marker.

## Real DNG prefix and added GTAG (23 October)

`FPL_DNG_PREFIX` is an external 0x20000-byte capture, SHA-256
`23e847a480b9c10336dfb397b467410762c66d94f28fac12c4a30a44c972501d`.
`audit_formatter.load_dng_prefix()` verifies length and hash. The focused tests
skip explicitly when absent and reject changed bytes. No capture is stored here.
This section supersedes earlier statements below that no DNG was downloaded.

### Native origin of H

The reconstructed builder contains all 60 root, 47 Exif and 99 MakerNote entries
from the capture. Native generic constructors, Sigma constructor `C00BD0B0`,
tag insertion `C00B6B20`, recursive sizing and serialization execute against the
official image. Sigma version 0x0401 and child links are explicitly reconstructed.
Allocation/memcpy/memset backends are emulator stubs, as in earlier probes.

The baseline builder size `C00B6510` returns **0x135C4**. In the left writer:

* `C06A29F8..2A08` invokes the builder's size virtual slot +C.
* `C06A2A14` supplies alignment **0x400** to `C0697018`.
* `C0697028..34` computes `(size+alignment-1)/alignment*alignment` using native
  unsigned arithmetic; `C0697038..48` zeroes the padding.
* `C06A2A20..34` publishes the result through `C06971A0`, used row 0.

These exact fragments execute in the test: size **0x135C4**, used H **0x13800**,
zero padding **572 bytes**. H is computed, not copied from the 0x18000 reserved
row. Reservations 0x18000 and 0x5400 are explicitly seeded from the measured
layout; other used rows/body words are zero. `C0720758` sums used words, and
`C06A2AD0..2AFC` updates root StripOffsets through the native tag adder. The
resulting serialized scalar equals H for every tested N. A rounding-instruction
mutation (0x400 -> 0x200) changes baseline H to 0x13600, proving sensitivity.

**Reconstruction boundary:** generic native serialization places ordinary root
values before child IFDs. It therefore puts Exif at 0x5D68 instead of the real
0x4356 (the difference is the 6674-byte DNGPrivateData payload). The native
output matches every original tag type/count/payload and total extent, but is
not byte-identical to the capture. Inline unused tail bytes are not payload.
The live builder's exact object representation/layout remains unproved; the
tests do not silently treat this reconstructed graph as a captured graph.

### Payload limits

For a newly added UNDEFINED GTAG with **N > 4**:

```
metadata(N) = 0x135C4 + 12 + align_up(N, 2)
H(N)        = align_up(metadata(N), 0x400)
```

The 12 bytes are the extra IFD entry. N=1..4 is inline and adds only 12 bytes;
these sizes cannot hold Gyro2 data. N=0 is not an admitted GTAG. No arithmetic
formula here licenses unchecked 32-bit overflow or serializer writes.

| Bound | Largest N | H at limit | H at N+1 |
| --- | ---: | ---: | ---: |
| Existing 572-byte padding | **560 (0x230)** | 0x13800 | 0x13C00 |
| Measured +128 = 0x15400 | **7728 (0x1E30)** | 0x15400 | 0x15800 |
| Header reservation = 0x18000 | **18992 (0x4A30)** | 0x18000 | 0x18400 |

The first H increase occurs at N=561. The measured frame headroom binds before
the reservation: it allows 7168 more payload bytes than the no-growth limit.
The +0x5400 reservation row is not extra frame-header headroom. At N=18993 the
native size is 0x18002 and used-row publication asserts against the reservation;
the serializer itself must still be guarded before writing. For N=768, H is
0x13C00. StripOffsets moves with H under the replayed zero-other-used-row state.

### Parser and admission checks

`test_fpl_formatter_dng.py` executes the unchanged shared `gyr2.S` take_start
path through observer mode 2. On the actual prefix it reports no GTAG; strict
host admission reaches `native tag absent`. On native augmented headers it
finds the same aligned GTAG span as `fsg2.gtag_area`, across odd/even padding,
headroom and reservation boundaries. All other original payloads are checked.
The strict TIFF admission validates those spans with explicit owner bounds;
`formatter_contract.recording_layout` accepts H <= measured +128 and refuses
the larger headers even when the source reservation can contain them. The
larger synthetic arena used in emulation is not a camera allocation claim.

Verification: **61 tests passed, zero skips with fixtures present** (122.666 s).
Missing-prefix skip and mutated-prefix rejection passed; official MAIN/DATA
audit and default fp release-byte equality passed. Logs and source hashes:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-real-dng/`.

Run from `projects/gyro2-sup`, with the FP_MAIN/FPL_MAIN/FPL_DATA/FPL_CONTEXT/
FPL_TAKE and toolchain PATH assignments in the take-replay command below, plus:

```sh
export FPL_DNG_PREFIX="$HOME/.local/share/fpsup-research/fpl-live-2026-10-23/cdng-take-1-files/A001_001_20261023_000001.DNG.prefix-0x20000"
python3 -B -m unittest -v test_fpl_formatter_dng test_fpl_formatter_take test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

### What a live test-tag take must confirm

Confirm the actual builder accepts/copies the UNDEFINED tag, the captured
MakerNote count/payload and metadata extent grow as above, used H and
StripOffsets move together, and +128 still supplies sufficient pre-retreat
headroom. N=560/561 straddles the first rounding boundary; N=768 predicts
metadata 0x138D0 and H=0x13C00. Reparse the downloaded frame and verify original
metadata plus the GTAG span. Also establish the real runtime object layout,
allocation lifetime and atomic active-buffer identity. This offline replay does
not execute the full geometry-dependent writer or prove those ownership facts.

**Latest correction:** the actual CinemaDNG take has a kind-3 sentinel right
leaf and left `+88=1`. See [Actual-take reconciliation](#actual-take-reconciliation).
The earlier `(0,0,0)` replay describes the pre-rewrite context, not construction
during the take. Native recording control writes snapshot `+44=2`.

**Follow-up:** see [Selection, lifetime and transfer edges](#selection-lifetime-and-transfer-edges)
below. The subtraction and conditional leaf implementations are now resolved;
selection of an actual CinemaDNG instance and live frame ownership remain open.
The first-slice results below retain their original acceptance boundary.

## Acceptance boundary

The bounded fallback is complete: execute native leaf/composite constructors,
ledger allocation/initialization, and the resolved allocation-size virtual edge.
**No complete mode-selected CinemaDNG graph, recording, or actual RAW boundary
has been established.** `0xB000` below is a native initializer result on a probe
graph, not a camera-mode capacity. No fp `0x15400` assumption is used.

Files:

- `projects/gyro2-sup/audit_formatter.py`: exact MAIN/DATA audit and disassembly.
- `projects/gyro2-sup/formatter_contract.py`: offline snapshot/admission helper.
- `projects/gyro2-sup/test_fpl_formatter.py`: native constructor and contract tests.

## Inputs and provenance

Official fp L 3.02 extraction, externally stored under
`~/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/`:

| Input | Bytes | SHA-256 |
|---|---:|---|
| MAIN.bin | 49310208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |
| DATA.bin | 238080 | `758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8` |

MAIN loads at `C0000000`; DATA starts exactly at MAIN's end, `C2F06A00`, and
ends at `C2F40C00`. The extraction's `analysis.json` records those addresses and
verified compressed/container sums. The audit independently enforces hashes,
sizes/load boundary, vtable words and key caller operands.

DATA word `C2F3F90C` supplies the ledger-pool pointer `C3824BF4`. The provider
itself is BSS/runtime state: loading DATA does **not** initialize that pool.
The harness explicitly installs a test provider vtable there, extending mapped
BSS through `C3900000`. Availability (`+14`) and allocation (`+C`, size in r1)
are Python stubs; provider startup and physical memory availability are unproved.

## Native graph construction and size contract

The harness chooses two base leaves and one base composite; firmware constructs
their fields. This composition is a **probe**, not output from the mode factory.

1. `C0696E10` constructs each leaf, installs vtable `C2E48BF0`, and calls
   `C06976F0` to obtain its 0x4C-byte ledger. The resulting pointer is stored at
   leaf `+C` and `+10`.
2. `C06976F0` asks the provider for availability. Zero availability yields null
   on these official inputs. Otherwise `C06987B8` requests 0x4C bytes; null
   allocation reaches assertion `C0011130`, which stops the test.
3. `C06986F8` copies the 19-word MAIN initializer at `C2E48F50`: 18 zero words
   and vtable `C2E48FD8`. It changes the final word to `C2E48F44`; the factory
   subsequently changes it to `C2E491C4`.
4. `C0696BB8` constructs the composite with children at `+0/+4` and vtable
   `C2E48BA8` at `+8`.
5. Native reservation initializer `C0720C28`, invoked on the first base leaf,
   sets reservation rows to `[5000, 0, 1000, 5000, 0]` (hex), with corresponding
   used rows `[5000, 0, 0, 0, 0]`. The second leaf retains its zero ledger.

Both base vtable `C2E48BA8` and factory-selected vtable `C2E4A65C` have slot
`+10 = C0696CE8`. The test executes the base object's resolved slot and checks
the native trace through `C0696EB8` and `C06979F8`. The latter sums **five
reservation words** at ledger offsets `20,28,30,38,40` (hex). Composite result:
`0xB000`. The selected factory is audited, not executed.

Do not conflate that sum with body size or serialized length:

- `C0697978` separately sums four body rows at `0,8,10,18` (hex).
- `C06970E0` aligns a body-size input upward to four bytes; input `FFFFFFFF`
  wraps to zero in native execution.
- `C0697178` writes a reservation row. `C06971A0` writes a used row, **then**
  asserts if used exceeds reserved. A failed assertion can leave an invalid row.
- Native reservation sums also wrap: adding `FFFFFFFF` to the other leaf makes
  the composite return `AFFF`. The host's nonwrapping sum refuses this graph.

## Caller ownership and unresolved edges

Audited official instructions establish these separate interfaces:

| Caller | Evidence / remaining dependency |
|---|---|
| `C0378F74..84` | Calls `[[r7+8]+10]`: resolved reservation accessor above. |
| `C0378F98..A0` | Passes that result to template allocator `C038A4A0`. |
| `C0378FC0..D4` | Calls preparation slot `[[r7+8]+1C]`; composite tables resolve this to `C0696DB0`, but full preparation is not executed here. |
| `C03790AC..C8` | Separate leaf virtual slot `[[object+14]+2C]` obtains serialized length. No selected leaf instance is proved by this probe. |
| `C03790D0..E0` | Publishes serialized length to recording object `+14C`, then template owner `+C`. |
| `C038C974..7C` | Loads recording `+4C` and `+14C` into r0/r1 for `C0010CB8`; subsequent code forwards the descriptor to `C00F8440`. RAW-destination provenance remains unresolved. |

Factory `C06A2618` depends on parameter containers, geometry queries, pool
startup and specialized leaf nodes. Constructing those from guessed fields
would not evidence a recording mode. This slice therefore does not assign a
mode name or identify reservation size with RAW start. The generic IFD size
accessor used in the write test is **not** the unresolved leaf `+2C` accessor.

## Admission and owned-memory serialization

`snapshot(read, call, root)` records the composite, leaf fields and complete
ledger bytes. It checks nonnull/aligned probe-arena pointers, the known vtable
slot, used ≤ reserved, a nonwrapping total, and agreement with native execution.
`admit()` compares snapshots, requires a nonnull 64-byte-aligned allocation whose
size equals the native reservation, and delegates independent IFD-size/prefix/
RAW bounds to the prior capacity helper. `raw_start=None` always refuses.

The arena range check is **not an ownership map**. Callers supply readable/live
objects and allocation facts. The snapshots detect changes to this bounded
graph, including same-total used-row changes; they do not capture the separate
IFD tree or arbitrary mode metadata. A caller must freeze all relevant metadata
through measurement and writing. There is no resident guard, concurrency lock,
allocator registry or camera discovery in this helper.

The write test executes native `C038A4A0` with the measured `B000` request. Its
memory-manager backend returns test-owned emulated memory, with alignment 64 and
manager kind 12 verified. Actual `C00BAC20` then serializes the synthetic
MakerNote IFD into that returned allocation. The prior native IFD accessor
measures 786 bytes; a 90-byte prefix places the end at 876. Entry count/type/
offset and canaries at both the measured end and allocation end are checked.
The prefix is reserved, not a full emitted DNG envelope in this test.
RAW offset 4096 is an explicit **synthetic fixture bound**, not firmware evidence.
Null template allocation is rejected before serialization.

Stubbed dependencies inherited from `NativeTags`: heap mutexes/backend, free
backend (recorded, not recycled), base-destructor cleanup, memcpy, diagnostic
logging, template memory-manager lookup/allocation. Native ledger constructors,
row accessors, sum routines and template allocation wrapper execute. Unknown
execution fails; calls are instruction-bounded and verify stack/callee-saved
register restoration. No media operations are needed or claimed.

## Verification

Executed: **31 tests passed, zero skips**: 10 formatter tests plus the existing
21 capacity/observer tests. Coverage includes constructor provenance, empty
provider/null ledger, allocation assertion, null owner, arithmetic wrap,
used-row assertion, same-total metadata change, missing RAW evidence, bounds,
and guarded native IFD writing. An in-emulator instruction mutation NOPs
`C0696D00` (first-child sum contribution), invalidates Unicorn's translated cache,
and demonstrably breaks the independent contract. Official inputs stay intact.

Exact test command (from repository root):

```sh
cd projects/gyro2-sup
FP_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FP__V502/MAIN.bin" \
FPL_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin" \
FPL_DATA="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/DATA.bin" \
PATH="$HOME/.local/share/fpsup-research/reference-builds/2026-10-23-m0/bin:$PATH" \
python3 -B -m unittest -v test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

Standalone audit (same directory):

```sh
python3 -B audit_formatter.py \
  --main "$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin" \
  --data "$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/DATA.bin"
```

Default fp Gyro2 remains release-exact, verified by the observer regression:
`2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3`.

Remaining gate: establish a selected native CinemaDNG instance, its preparation
and serialized-length implementation, actual allocation lifetime and RAW
destination/boundary, then bind frozen IFD metadata to that ownership evidence.
This slice supplies neither a real fp L DNG nor full-recording admission.

## Selection, lifetime and transfer edges

### Runtime selection: exact stopping point

The follow-up does **not** establish a supported CinemaDNG mode instance. It
establishes conditional branches and the exact runtime inputs that are missing.
The earlier base probe must not be renamed a recording mode.

The setup caller obtains `C0203B70()`'s singleton at `C31F6A7C`, then
`C0203D60()` returns its `+40` context snapshot, `C31F6ABC`. The constructor
`C0203A70` copies **0x5E4 bytes** there from the runtime context returned by
`C0021B20 → C0021B60`. The latter loads `[C3075194+5C]`. Context startup
`C0021A60` initially points it at `C3074BA8`, runs `C0022920`, and has a
conditional `C0021EC8` path through another runtime object's virtual method.
These are BSS/runtime objects, not initialized DATA words containing a selected
recording mode. Later live changes have not been replayed by this harness.

The native defaults routine `C0022920` is executed, not inferred from zeroed
BSS. Its branch-input triplet is `(0,3,1)` for `(+44,+30,+C)` (hex offsets).
That triplet chooses `C06A2438`, not the TIFF-family branch. Treating defaults
as a selected CinemaDNG configuration would therefore be unjustified.

With `p` the snapshot passed to the factory, native `C06A2490` branches as follows:

| Predicate | Native edge |
|---|---|
| `p[44]==2` OR `p[30]` is 0 or 1 | Allocate 0x8C; eventually install leaf vtable `C2E4A5B0`. |
| Above, with `p[44]==2 && p[C]==0` | Constructor edge `C06A3FC8`. |
| Other case in that branch | Constructor edge `C06A40A0`. |
| Neither outer predicate | `C06A2438`, allocates 0x20 and installs `C2E4A4B0`. |

The companion selector `C06A25C0` returns the `C0697510` sentinel if `p[44]==2`;
otherwise it uses `C06A2438` when `p[30]==0`, or the sentinel for other values.
Factory `C06A2618` also needs its parameter-container allocation, geometry
provider and leaf/composite allocators before it installs `C2E4A65C`.

Tests execute both selectors for explicit **synthetic predicate values**.
Geometry (`C0437358`), selected constructors, their allocation and temporary
wrapper cleanup are stubs recorded as edges. The returned opaque allocation is
not a constructed formatter graph; only the native vtable publication is asserted.
An allocation failure skips construction. Mutating the outer comparison changes
the expected constructor edge and is detected. No numeric predicate is labelled
as a camera mode or claimed reachable through a supported UI setting.

**Missing selection input:** an evidenced, named CinemaDNG recording state with
the full 0x5E4-byte snapshot at `C31F6ABC` (especially words at `+C/+30/+44`
and the parameter container at `+1C`), plus initialized geometry/provider objects
and the mode-transition provenance producing it. MAIN/DATA alone as loaded here
do not supply that runtime state. A validated offline reconstruction could
supply it later; no capture is requested or performed by this increment.

### Preparation and serialized-length implementations

Both selected leaf vtables are now explicitly audited:

| Leaf vtable | Prepare `+10` | Serialize/length `+2C` |
|---|---|---|
| `C2E4A4B0` | `C06973C8` | `C06A1D58` |
| `C2E4A5B0` | `C0720418` | `C06A28D0` |

Composite prepare `C0696DB0` calls left `+10` with the header allocation base,
then right `+10` with `base + left reservation`. Native `C0010C98` is plain
32-bit addition. The base-leaf prepare simply stores the pointer at leaf `+4`;
this complete base-composite path executes in the tests. The selected
`C0720418` additionally gets reservation-row-4's offset through `C0697298`,
then calls `C06A1270` on its embedded geometry/descriptor state. That selected
state is not constructed or emulated here.

The `+2C` functions are **writers with side effects**, not pure size getters:

- `C06A1D58` queries the input object's virtual `+20`, writes JPEG marker
  `FFD8`, adds tags, serializes through the returned builder's virtual `+10`,
  updates ledger use, and handles additional marker blocks. It returns r7,
  established on its primary-builder path. This explains the JPEG-family label;
  it does not name a recording mode.
- `C06A28D0` starts at leaf `+4` plus reservation-row-0 offset. Depending on
  leaf byte `+88`, it queries the supplied object's virtual `+2C` or `+24`.
  It updates body ledgers, calls `C06A2858`, measures the returned builder via
  virtual `+C`, and passes that measurement to `C0697018` with alignment **0x400**.
  `C0697018` rounds up and zero-fills the padding; this is native alignment
  evidence, not an fp-derived capacity. The resulting size is held in sl,
  used-row 0 is updated, and StripOffsets/TileOffsets/TileByteCounts-related tags
  (`111/144/145`) are inserted before invoking the builder's serializer `+10`.
  The function returns sl at `C06A2C98`. Other branches can return zero.

The full writer paths still require builder objects, geometry and descriptor
arrays behind leaf virtual slots `+58/+60`. Tests execute the TIFF-family early
failure path for both input-getter alternatives, with a missing builder and
zero destination, and observe return zero. This is a failure-path probe, not a
successful selected serialization. The complete bodies are retained in the audit.
Because they mutate tags, metadata must be frozen **after** format-specific
updates; a reservation snapshot taken before them is insufficient.

### Header allocation lifetime and frame destination

`C038A4A0` obtains memory manager kind 12 and allocates with alignment 64,
publishing the source pointer at singleton `C358E9D8+10`. It asserts if that
field was already nonzero. `C038A508` gets the same manager, passes the pointer
to `C001D2B8`, then clears `+10`. The native release wrapper executes in tests;
the allocator/free backend remains a recorded host stub.

Direct unconditional ARM BL references in the exact MAIN image:

- Allocation: `C0378FA0` in setup.
- Release: `C03791C0`, conditional on setup-local object byte `+78` being nonzero.
- Release: `C039722C`, in `C03971F8` cleanup when the wrapper's first word is
  `0x13`; it first releases associated objects via `C038A3F0` and `C038A478`.

The audit enumerates these direct references; it does not exclude indirect or
Thumb callers. The per-frame descriptor fragment reads the existing source
pointer through `C038A530`; it neither allocates nor frees it. Repeated execution
of that fragment demonstrably reuses the pointer. **This does not prove the
whole recording session's lifetime or the absence of indirect/concurrent frees.**
The test deliberately reallocates the same address after native release to show
why pointer equality alone cannot prove continuity of ownership.

The native DMA descriptor at `C038C964..C038C994` is now unambiguous:

```
source      = template_owner[0x10]
length      = recording[0x14C]
destination = recording[0x4C] - length     // C0010CB8: SUB, wrapping uint32
```

These three words are forwarded to `C00F8440`. The test executes the exact
fragment and arithmetic; its DMA sink records the descriptor rather than
performing hardware I/O. Consequently `recording[4C]` is the absolute boundary
at the **end of the destination header**, not an offset into the source template.
The source allocation's size cannot establish destination headroom.

Additional audited producers of field `+4C` include:

- `C0381E44..54`: recording `+68` plus `+128` via native addition.
- `C037EAA0..BC`: choose nonzero `+12C`, otherwise `+68`.

Which producer applies, the live raw/frame allocation's base/end, and its
lifetime remain runtime facts. The arithmetic proves the consumed boundary,
not the size or ownership of the memory preceding it. Underflow is demonstrated
natively and rejected against independently supplied frame bounds.

### Frozen IFD / ownership contract

`formatter_contract.py` now adds `Ownership`, `FrozenTransfer`,
`freeze_transfer()` and `admit_transfer()`. This is a bounded offline evidence
interface, **not** a product-mode admission path:

- Requires explicit live source size, generation token and frame allocation
  extent. No ownership evidence means refusal. Generation must change on
  release/reallocation even when the pointer is reused; the helper cannot
  discover that epoch from a pointer or MAIN/DATA.
- Freezes a **flat, childless native TiffIfd**: object, pointer vector, each
  entry, owned value object and complete value bytes. Child/next IFD graphs,
  duplicates and incomplete values are refused. Native size is independently
  checked against entry/value sizes. This restricted reader is not a new FSG2
  format and does not accept a full DNG tree by assumption.
- Binds that snapshot and the formatter ledger to owner `+8/+C/+10`, recording
  `+4C/+14C`, the explicit allocation generation and frame extent. Published
  lengths must equal measured IFD plus prefix. Source and destination allocations
  must be distinct, and `[raw-length, raw)` must fit the live frame extent.
- Rechecks the frozen snapshot before bounded reserialization/copy. Same-size
  payload changes, changed publication, freed source and same-address new
  generation all refuse. This detects changes; it does not provide an atomic
  lock against a write occurring after the final check.

The positive fixture publishes its synthetic measured length, freezes metadata,
reserializes the native MakerNote IFD into the actual emulated owner allocation,
checks both end guards, rechecks metadata and compares the exact native DMA
descriptor. It supplies synthetic frame ownership explicitly. It does not
execute the selected leaf writer or claim a complete DNG or media transfer.

This interface is appropriate only after final format-specific tag updates and
length publication. It cannot justify a first unrestricted execution of the
mutating selected writer. That still requires a proven selected instance and
its pre-write size/bounds contract.

### Follow-up verification and remaining bound

**Executed: 42 tests passed, zero skips** (11 new edge tests plus the prior 31).
The expanded exact MAIN/DATA audit passed, including the leaf slots, subtraction
operand, release publication and direct ARM caller inventory. Default fp Gyro2
release-byte equality passed. Evidence and source hashes are retained externally:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-formatter-edges/`
(`tests.log`, `evidence.json`).

Run from `projects/gyro2-sup` with the same explicit images/compiler adapter:

```sh
FP_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FP__V502/MAIN.bin" \
FPL_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin" \
FPL_DATA="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/DATA.bin" \
PATH="$HOME/.local/share/fpsup-research/reference-builds/2026-10-23-m0/bin:$PATH" \
python3 -B -m unittest -v test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

New focused tests are in `test_fpl_formatter_edges.py`. They include conditional
selection/default initialization, failed allocation, missing serialized-builder
paths, preparation, release/reuse, same-size IFD mutation, null/mismatched
ownership, frame underflow and machine-code mutations of selection and SUB→ADD
DMA arithmetic. Mutations affect emulator memory only, with cache invalidation.

Remaining input is specifically the selected context/geometry/builder state,
the provenance and live extents of recording `+68/+128/+12C/+4C`, and allocation
lifetime/serialization synchronization. Until supplied or reconstructed with
evidence, the conditional edges and synthetic ownership tests are the acceptance
boundary; no actual CinemaDNG mode is asserted.

## Replay of the owner's live context capture

The owner's read-only 2026-10-23 context capture now supplies the previously
missing selector input. This increment remains offline; camera actions belong
to main. External capture directory:
`~/.local/share/fpsup-research/fpl-live-2026-10-23/cdng-context/`.
Its README and SHA256SUMS identify `snapshot_C31F6ABC.bin` (0x5E4 bytes), SHA-256
`18a6c33800357a14e71cfd5d16e0ab3c052a000b5d509f868a59b01b21d2cd25`.
The captured source `C3074BA8` is byte-identical; the owner observed
`[C3075194+5C]==C3074BA8`. No capture is copied into the repository.

`test_fpl_formatter_live_context.py` loads only `FPL_CONTEXT` and enforces this
exact size/hash. If the path is missing/unset it skips with an explicit reason;
wrong bytes fail, rather than skip. The native selectors receive all captured
bytes unchanged, including `(p[44],p[30],p[C])=(0,0,0)`, dimensions 3840×2160,
and `p[1C]=2530` (hex). Given the owner's format evidence that `+C==0` is non-MOV:

- **Left:** `C06A2490 → C06A40A0`, allocates 0x8C and publishes vtable
  `C2E4A5B0`. It does **not** take `C06A3FC8`. Native constructor
  `C0720198` sets leaf kind `+8=1`; prepare is `C0720418`, writer/length is
  `C06A28D0`. This earlier-snapshot edge sets byte `+88=0`; **it is not the
  actual-take constructor** (see reconciliation below).
- **Right:** `C06A25C0 → C06A2438`, the 0x20-byte leaf with vtable
  `C2E4A4B0`, kind `+8=0` via `C07207B8`; prepare is `C06973C8`, writer/length
  is `C06A1D58`. **This pre-rewrite prediction does not match the actual take's
  right leaf**, which is the sentinel.
- Factory `C06A2618` would compose those leaves under vtable `C2E4A65C` once
  geometry and construction succeed. Selector replay records geometry/wrapper,
  allocation, constructor and cleanup stubs explicitly; it does not manufacture
  complete selected leaf objects from the captured context.

**Factory prefix replay goes further natively:** `C06A2618 → C0697830 →
C0698740 → C06988B0 → C0697D88` constructs the actual 0x134-byte parameter
object in emulator-owned memory. The distinct provider comes from official
DATA `[C2F3F908]=C3828E54`; only its availability/allocation virtual methods are
stubbed. Native constructors and pair-copy routines execute. Replay stops
explicitly on entry to `C06A4440`, the runtime geometry construction boundary,
before substituting geometry results. Allocation failure reaches the native
assertion. No completed factory result is claimed.

**Correction to the earlier missing-input wording:** snapshot `+1C` is not a
pointer to a parameter container. The factory passes the **address** `p+1C` to
its parameter constructor. `C02E9B80` copies the two words at that address into
value descriptors; native replay verifies they appear in the constructed object
and its `+30` descriptor. `0x2530` is a numeric pair member; **do not dereference
address 0x2530**. The real runtime parameter object is instead reachable from
the completed composite's `+C`, described below.

### Word-read plan for main during a take

All offsets/addresses below are hexadecimal. `word(x)` means a read only, never
a firmware call. First read fixed globals; dereference dynamic pointers only
after main confirms the entire requested span is in its known readable RAM map.
Null, unaligned, low scalar values and all-ones/sentinel values are not pointers.
Code/vtable words are identity evidence, not functions to invoke.

**1. Template owner (fixed, no pointer chase):** owner is `C358E9D8`.

| Absolute word | Meaning |
|---|---|
| `C358E9E0` | owner `+8`: composite formatter pointer F |
| `C358E9E4` | owner `+C`: published serialized header length H |
| `C358E9E8` | owner `+10`: source template allocation S |

F/S can be null before setup or after release. H is meaningful only with live
setup/publication and S; it is **not** the source allocation size. Record all
three again after the dependent reads to detect a changed snapshot. Equality
does not prove atomicity or prevent a same-address free/reallocation.

**2. Formatter/leaf chain, only when F is validated live RAM:**

```
L = word(F+0)       Rleaf = word(F+4)
word(F+8)          expected composite vtable C2E4A65C
P = word(F+C)      parameter object, not snapshot[+1C]
```

For **each** validated leaf address read words at `+4,+8,+C,+10,+14`:
prepared header pointer, kind, current ledger, reference ledger, vtable.
Expected for the earlier captured input only: L kind 1 / vtable `C2E4A5B0`,
Rleaf kind 0 / vtable `C2E4A4B0`. The actual take instead has right kind 3 /
vtable `C2E490F0`. The setup caller asks `C06972C0(F,1)`, which compares child
`+8` values and returns the matching child; it does not read `[F+14]`.
**The `+14` vtable belongs to the leaf.** Read L `+88` as an aligned word and
use its low byte (0 for the earlier edge; **1 in the actual take**).

If valid, read each ledger's 19 words (`+0..+48`) to preserve reservations and
used values. For validated P, capture its 0x134 bytes, especially `+0/+4`,
`+30/+34`, `+40`, `+8C`, `+D8`, `+124`, `+130`. These are fields/value pairs;
do not recursively dereference them without separate provenance. Pointer fields
may refer to pool objects outside a worker's allowed read windows even though
the firmware itself can access them.

**3. Recording buffer object feeding `C038C810`: fixed registry route.**

`C0374438()` returns registry base **`C3520D84`**. Native `C03755D8(base,i)`
checks unsigned `i < 60` and returns:

```
record_i = word(C3520D88 + 4*i),  i = 0..5F
```

Thus the fixed pointer table is **96 words at C3520D88..C3520F04**. It can be
read without dereferencing any buffer pointer. In the actual CinemaDNG handler:
`C038BFC4..D4` gets `i=event[+E8]`, looks it up in this registry, then the same
result is r5 at `C038C1D4..E8` and passed as r1 to `C038C810`. That function
preserves r1 in r5; its `+4C/+14C` are the fields consumed by the DMA fragment.
`C038C1D4..DC` copies owner H into that buffer's `+14C` immediately before use.

There is **no proved fixed-global current-event index** in this increment. If
main has the event object from separate evidence, its `+E8` selects one table
entry. Otherwise read the table, then read the following fields of each nonnull,
validated candidate buffer; preserve the slot index with every record. Do not
guess a unique active buffer from a matching length alone.

| Buffer-relative words | Purpose |
|---|---|
| `+4C` | absolute RAW/header-end boundary consumed by DMA |
| `+14C` | published header length for this buffer |
| `+68` | base used by the audited RAW-address producers |
| `+128` | offset added to `+68` in one producer |
| `+12C` | alternate pointer chosen when nonzero in another producer |
| `+138` | additional formatter pointer field used on another preparation path; record, do not assume equal to F |
| `+10FC` | buffer key used by surrounding registry operations; retain as correlation evidence |

`C03790D0` stores the setup length into its buffer argument r4; the setup
function `C0378C68` receives that object as r1. Per-frame selection above is the
proved fixed-registry path to buffers of that contract. Setup and frame reads
must be correlated, not assumed to be the same live slot at different times.

Compute locally, without reading frame pixels:
`destination = buffer[4C] - buffer[14C]` with **nonwrapping** arithmetic.
Compare length to owner H and retain S separately. Do not dereference destination,
`+68`, or `+12C` merely because arithmetic produces a number; the extents and
lifetimes of those allocations remain to be established. The five field words
alone do not prove available headroom.

**4. State identity (optional fixed reads):** `C358EAC0` is the
MovRecFuncStateCinemaDng state object. `C358EAD0` (its `+10`) is initialized to
vtable `C0BC24AC`; `C358EAD4` (`+14`) is a state/status word, initially
`80000000`; `C358EADC` (`+1C`) is initialized to `FFFFFFFF`. Neither word is a
proved current recording-buffer pointer/index. **Do not treat this state object
as the buffer and read its +4C/+14C.** Use the registry above.

The fixed words are within known fp L firmware BSS, but transport allowlists
are separate. Dynamic F, leaves, P, ledgers and buffer objects can be null,
released, stale or outside a transport's mapped/readable window; following them
blindly can fault. They are meaningful during initialized setup/an actual take,
not guaranteed before/after. Stop a chain on an invalid or changing pointer;
main should retain before/after owner/table words with the captures. This plan
requires only word reads and local arithmetic, no pointer calls or writes.

### Replay command

Executed: **47 tests passed, zero skips with the capture present**; expanded
MAIN/DATA audit passed and default fp release bytes remain exact. A separate run
without `FPL_CONTEXT` produced the expected single class-level skip with reason.
Logs, audited windows and source hashes:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-live-context-replay/`.

From `projects/gyro2-sup`:

```sh
FP_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FP__V502/MAIN.bin" \
FPL_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin" \
FPL_DATA="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/DATA.bin" \
FPL_CONTEXT="$HOME/.local/share/fpsup-research/fpl-live-2026-10-23/cdng-context/snapshot_C31F6ABC.bin" \
PATH="$HOME/.local/share/fpsup-research/reference-builds/2026-10-23-m0/bin:$PATH" \
python3 -B -m unittest -v test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```

## Actual-take reconciliation

External fixture: `FPL_TAKE` names the owner's `cdng-take-1/take.json`, SHA-256
`e48e8c0473f98b1dab39c3cc30a33bd2266d2e16b1010d7b3ba31635da8b4ff7`.
`audit_formatter.load_live_take()` enforces that fingerprint before parsing.
Tests skip with a reason if absent, fail for changed bytes, and never install
the capture in the repository. The owner's README reports 141 DNGs of 8447488
bytes; the file contents were not downloaded. Three RAM snapshots have stable
owner words but **changing registries during each read**, so are not atomic.

### Corrected native construction path

The earlier test was a valid replay of the earlier snapshot but an invalid
prediction of mid-take construction. There is a concrete native rewrite:

```
C039E01C..28: read/save current snapshot +44
C039E040:    C0203B70() -> singleton C31F6A7C
C039E044:    C0203D70() -> mutable snapshot C31F6ABC
C039E04C:    r2 = 2
C039E050:    [snapshot+44] = r2
```

There is also a conditional write of 2 at `C039C5CC..DC` for selector r7=3.
This increment executes the first rewrite fragment over the exact earlier
hash-checked snapshot and then executes both selectors. It does not claim a
captured PC trace identifying which control entry ran during the take. Either
way, the static `(0,0,0)` snapshot cannot be assumed immutable across start.

With the rewritten `+44=2` and unchanged `+C=0`:

- `C06A2490 → C06A3FC8`, **not C06A40A0**. `C06A3FEC` stores byte 1 at left
  `+88`. Its native base `C0720120` sets kind 1 and reservation row 4 to `5400`;
  `C06A2838` sets reservation row 0 to `18000`. Factory publication still gives
  vtable `C2E4A5B0`. These native constructors/row writes are executed in tests.
- `C06A25C0 → C0697510`, which returns **C3824B7C**, exactly the live right
  pointer. This is a real sentinel object, not null. Its native singleton
  constructor calls `C0697558(object,3,800)`; the latter installs vtable
  **C2E490F0**, kind **3**, and a zero-reservation ledger. The test executes that
  constructor with explicit allocation-provider stubs.

The constructor test stubs auxiliary parameter acquisition `C0697770`, embedded
descriptor initialization `C06A1428`, and geometry copy `C02E9C10`. It executes
the size ledger constructor, native flag/reservation writes and the sentinel's
parameter-object constructor. This is enough to explain both live mismatches;
it is not a replay of every geometry dependency. A mutation that NOPs the
snapshot rewrite restores the earlier constructor edge, demonstrating why the
old prediction differed. Old replay tests are renamed to identify their
pre-take scope rather than assert they predict the live graph.

### Live ledger and prepare replay

The take's captured composite/leaf/ledger words are placed at their captured
addresses in emulator RAM. Only captured fields are restored; absent geometry
is not invented. Native composite reservation slot `C0696CE8` returns:

```
left  = 18000 + 5400 = 1D400
right = 0
total = 1D400
H     = 13800 <= total
```

Native composite preparation `C0696DB0` dispatches through the **actual captured
leaf vtables**, assigning left `+4=S` and right `+4=S+1D400`, matching all three
captures. Left preparation `C0720418` executes up to the explicit descriptor
dependency stub `C06A1270`; right preparation is native `C06973C8`. This avoids
replacing the selected leaf vtables with the old base-leaf probe.

### The two buffer forms are different pointer phases

`C0381E44..54` loads buffer `+68` and `+128`, adds them with `C0010C98`, then
publishes the result at `+4C`. This establishes the pre-retreat RAW boundary:

```
raw = base + measured_headroom
header_destination = raw - H
```

`C037E5C8..D0` tests buffer kind at `+4` for 1. In that branch,
**C037E5EC..5FC reads +4C/+14C, subtracts H and stores back to +4C**. It then
selects formatter leaf kind 1 and calls its `+4C` method with buffer `+10`.
This is the in-place retreat from RAW boundary to header-start pointer in the
processing path `C037E310`, not another establishment of header headroom:

```
before: +4C = base + 15400
after:  +4C = base + 15400 - 13800 = base + 1C00
```

Both exact arithmetic/publication fragments execute in tests with live buffer
fields. Thus the earlier suggestion that the second form was “not yet prepared”
is unsupported and superseded: a native producer yields it **after retreat**.
Subtracting H again from this form would land `11C00` below base. The test
deliberately rejects such a second header placement.

This proves the native phase transformation, not the timestamp/active DMA
status of every sampled slot: `+4` was not captured and the registry changed
while reading. The complete event ordering and allocation lifetime remain open.
It is also possible to encounter stale/torn combinations; they must refuse.

### Admission extension

`recording_layout(read, recording, serialized_bytes=H, frame_bytes=extent)`
requires all of:

- published `+14C == H`, `0 < H <= +128 < extent`;
- nonwrapping base/extent and `+4C == +68 + +128`;
- no unsupported alternate `+12C` path.

It returns the measured base/headroom/boundary/length/destination/extent tuple.
`freeze_transfer(..., require_recording_headroom=True)` binds this tuple to the
existing frozen IFD/owner/generation checks and checks its base against the
supplied frame allocation. Existing generic flat-IFD tests retain their explicit
synthetic bounds; captured full IFD metadata is still unavailable.

The **15400 value comes only from this take's +128**, not an fp constant and
not a universal limit. All 34 sampled buffer records classify as 4 pre-retreat
layouts accepted by this layout check and 30 retreated forms refused. Captured
bases have spacing in multiples of `810400`; tests use that observed stride
as an offline extent hypothesis, **not proof of an allocation's live extent**.
Production admission still needs allocator/lifetime evidence and frozen full
IFD metadata. H is measured here, not recomputed from a downloaded DNG.

Tests include changed fixture hash, insufficient headroom, context-rewrite
mutation, retreat-publication mutation, native prepare agreement, and binding
headroom changes to the frozen-IFD contract. The live-ledger replay calls native
accessors directly on captured BSS words; the older host probe snapshot retains
its explicit arena convention and is not claimed to accept the full live graph.

### Take-replay command

Executed: **55 tests passed, zero skips with both external captures present**;
the expanded MAIN/DATA audit and default fp release-byte equality passed.
With `FPL_TAKE` absent the new class skips explicitly. Logs and source hashes:
`~/.local/share/fpsup-research/reference-builds/2026-10-23-m3-take-reconciliation/`.

From `projects/gyro2-sup`:

```sh
FP_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FP__V502/MAIN.bin" \
FPL_MAIN="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin" \
FPL_DATA="$HOME/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/DATA.bin" \
FPL_CONTEXT="$HOME/.local/share/fpsup-research/fpl-live-2026-10-23/cdng-context/snapshot_C31F6ABC.bin" \
FPL_TAKE="$HOME/.local/share/fpsup-research/fpl-live-2026-10-23/cdng-take-1/take.json" \
PATH="$HOME/.local/share/fpsup-research/reference-builds/2026-10-23-m0/bin:$PATH" \
python3 -B -m unittest -v test_fpl_formatter_take test_fpl_formatter_live_context test_fpl_formatter_edges test_fpl_formatter test_fpl_tag_capacity test_fpl_observer
```
