# fp L shared gyro drain: latched-head coherence experiment

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Later implementation and live follow-up

The optional seam is now implemented in the shared drain; the strict capture
and default fp Base retain identical bytes. `fpl_gyro_latched.py` and its
finite assembly implement the conditional batch ledger. Independent rerun:
57 combined ARM/host/coherence tests pass. The external OG boot-entry test was unavailable in that checkout;
it is now supplied by the imported upstream research tree.

First live run completed twenty observations, copied 1142 records, and reported
1142 conditional-prefix records with **proven_valid_records = 0**. One batch
observed head movement; all conditional window checks passed. Capacity drops
and copied padding errors were zero. Host echo bounds span about 478 ms.
Code/state/output guards, mutable-word ledger checks, echo restoration and PONG
passed. Evidence: `fpl-live-2026-10-20/shared-gyro-latched-first/`; full hashes
are in the investigation log. No recording, hook/task installation or card
write. The assumptions and counterexamples below still apply.

## Original offline experiment (before the follow-up above)

2026-10-20. **The original experiment was offline only.** Production
`gyro/gyro_drain.S`, capture assembly and host runner are unchanged by this
experiment. Nothing here is installed or authorized for a live trial.

## Decision

A compile-time, caller-owned **latched head** is a useful diagnostic extension:
copy only through the validated pre-head, rather than including whichever head
the shared drain happens to reread. Normal forward movement during the copy need
not automatically reject that batch. However, the proposed overwrite-window
test is **conditional**, not proof that a batch is coherent or lossless.

Keep the strict probe available alongside the opt-in conditional diagnostic.
The prototype deliberately demonstrates corrupt output that passes
the modulo-window test after a hidden full lap. Do not turn the proposed
`conditional_window_pass` disposition into an unconditional `valid` flag.

The historical test record reports that the strict live probe completed three observations,
appended 164 records, then stopped when the fourth observation changed from
771780484 to 771780492 (one record). Duration was about 66 ms, padding and drops
were zero, and echo/PONG/guards were good. This report motivates the experiment;
it is not live verification of the prototype or a measured scheduling bound.

Bindings and publication-order evidence are in [FPL_GYRO_BINDINGS.md](FPL_GYRO_BINDINGS.md).
The actual shared source loads its head with **`ldr r5, [r8]`**, not `[r4]`.

## Exact indexing

Let `R = 0x2E00644C`, `N = 600`. Record storage index `j`, for `0 <= j < N`,
occupies `R + 4 + 8*j` through `R + 11 + 8*j` inclusive. Components are signed
halfwords at offsets 0, 2 and 6; offset 4 is padding, replaced by gyro tag zero
by the shared producer.

The published head is the **address of the second word of the last completed
record**, not the next write pointer:

```text
head(j)  = R + 8*(j+1)
index(H) = (H-R)/8 - 1
valid(H) = 8 <= H-R <= 4800 AND (H-R) mod 8 == 0
```

Zero, `R`, `R+4`, an unaligned value and `R+4804` are invalid heads. The last
valid head is `R+4800`, for record 599. An unarmed diagnostic cursor is `-1`,
not zero. Never use the sentinel as a source address.

For a previous accepted cursor `C`, latched pre-head `H`, and post-head `Q`,
write their indices as `c`, `h`, `q`:

```text
d = (h-c) mod 600              observed pending record count, 0..599
a = (q-h) mod 600              observed producer advance during this batch
target interval = c+1, ..., c+d  (indices modulo 600)
slack = 600-d
```

The source starts at `C+4`. At or beyond `R+4804`, the shared drain resets it
to `R+4`, exactly as its current code does. Example: `c=598`, `h=1` gives
`d=3` and storage indices `[599, 0, 1]`. A head advance from 598 to 2 gives
`a=4`, not a negative delta.

`C=-1` establishes `C=H` and copies nothing. `d=0` means **no observed delta**;
it can also mean 600, 1200, ... actual writes since the previous observation.
Neither case demonstrates producer freshness or that the producer is stopped.

## Why strict inequality matters

For `d>0`, the first requested slot is `c+1`. Starting after the latched head
`h`, the producer reaches that slot on its **`slack+1`-th write**. The preceding
`slack` writes go outside the requested interval.

It is tempting to accept `a <= slack` by counting only completed records. That
is wrong: the producer writes both words **before publishing the head**. When
the post-head shows `a=slack`, its next, not-yet-published record may already be
overwriting the first requested slot. The conservative whole-batch criterion is:

```text
0 < d < 600
a < 600-d
```

This reserves room for one in-progress, unpublished record. With `d=4`, slack
is 596: 595 published advances plus the next partial write remain outside the
interval; 596 published advances plus a partial next write can corrupt its
first record. With `d=599`, slack is 1: only zero observed completed advances
passes. The next in-flight write still targets the one excluded slot.

The test is intentionally independent of copy speed and per-record progress.
It does not try to rescue a batch on the argument that a threatened record
"was probably copied already". No whole-batch post-head test establishes that
ordering. On a window failure, all newly appended records remain tentative;
the previously accepted conditional prefix is retained in the report.

### Assumptions required even when the window passes

1. Actual production since `C` has not hidden one or more full laps before `H`.
   Otherwise the starting unread history is already lost.
2. Actual production from `H` through the final observation is represented by
   `a`, not `a + 600*k` for any positive `k`.
3. A single sequential producer writes in ring order, publishes a head only
   after the record is complete, and has at most the next record in progress.
4. CPU reads observe those data/head publications with the necessary ordering
   and visibility. Static coprocessor instruction order is **not** hardware
   cache/coherency evidence. A stale observed head can invalidate the argument.
5. Descriptor/ring identity and the producer epoch remain continuous. Endpoint
   checks cannot detect a teardown/restart or pointer ABA that restores identical
   values between observations.

Under these assumptions the copied interval cannot have been overwritten during
the copy, including by an unpublished next record. The available head observations
do **not** establish the assumptions. A 20-ms yield is neither an upper bound on
the next scheduling gap nor a proof of sample rate. A timestamp alone would not
fix this without independently justified rate and scheduling/visibility bounds.

Consequently the unconditional proven-valid record count is always zero in this
prototype. "Conditional prefix" means the bounds and observed-window checks
passed, subject to the assumptions above; it is useful diagnostic provenance,
not a capture guarantee. The strict existing probe has these hidden-lap and
coherency limitations too, even when pre-head equals post-head.

## Optional shared-source seam

The experiment generates a temporary copy of the **actual** shared drain,
replacing only its head-load site with:

```asm
#ifdef GYRO_LATCHED_HEAD_PTR
    movw r5, #:lower16:GYRO_LATCHED_HEAD_PTR
    movt r5, #:upper16:GYRO_LATCHED_HEAD_PTR
    ldr  r5, [r5]
#else
    ldr  r5, [r8]
#endif
```

The optional pointer names one owned, word-aligned latch in staging, written
before the call and unchanged during it. It is **not** a firmware head address.
With the option absent, emitted instructions are unchanged. The prototype
compiles both the real current capture and real default Base writer with this
temporary branch disabled and compares their complete bytes to unmodified
sources. This supplements the earlier frozen default Base-byte regression.

The owned descriptor view remains necessary: the real drain also rereads
`GYRO_DESC_PTR` and `P+0x60`. Its diagnostic override points at an owned view
containing only the validated, exact ring address. A later real descriptor
change is detected by post-validation, never followed by the drain.

Before each batch validate the supplied previous cursor (or `-1`), real
`P=0x2E006004`, real `R=0x2E00644C`, and pre-head. Afterward reread and validate
the real chain and post-head; require the drain's consumed cursor to equal the
latched pre-head. Preserve both pointer observations. Invalid initial inputs
prevent any sample reads. Invalid post-inputs invalidate the tentative batch.

The prototype wrapper is a **single finite ARM call**, not a new polling task
or camera runner. Its bounded adapters append at most the configured capacity;
all observed source reads stay within the exact ring and permitted descriptor
words. It saves callee registers and maintains 8-byte stack alignment. Tests
permit no payload stores to firmware memory. Simulated producer stores are
performed separately by the test fixture.

## Cursor and prefix ledger

The reporting prototype records, per batch:

- Cursor supplied to the drain, latched pre-head, observed post-head and actual
  cursor returned by the shared drain.
- Both real descriptor/ring snapshots; status for unavailable/invalid pointers,
  invalid heads or an invalid previous cursor.
- Observed `d`, modulo `a`, slack, requested/observed count, appended count,
  capacity drops, and bad padding among **copied** records only.
- Output interval `[start,end)`, disposition and conditional-prefix contribution.

**Next cursor is `H`, never `Q`.** Samples written after the latch belong to the
next batch. Using `Q` skips them. The ledger rejects a next input cursor that
does not equal the previous accepted batch's consumed head.
The ledger starts unarmed by default. An offline test can explicitly supply a
previous cursor seed, which is recorded in the report; it is never inferred
from the first batch. A new production invocation must start unarmed.

Shared `g_gcount` counts `d`, even when capacity limits the append to `k<d`.
The drain consumes through `H` regardless of the copy result; the `d-k` tail is
explicitly dropped, not pending. The prefix can include the first `k` records
if the window passes, but the proposed finite diagnostic stops on capacity loss
instead of pretending the next output is a continuous stream. With zero
capacity the shared drain copies nothing and reports the whole delta dropped.

On an invalid/window-failed batch, keep the raw tentative bytes and metadata,
stop continuation, and leave the conditional-prefix length at its prior value.
The report's prior accepted cursor is provenance, **not permission to resume**
after that error. Any later separately initiated capture must explicitly rearm.
No attempt is made to identify a valid sub-prefix inside a rejected batch.

The Python ledger accepts at most 20 supplied batches. It is an offline report
specification, not production assembly and not a live host execution path.
Production adoption would need a new bounded per-batch metadata layout and a
matching decoder; the current strict decoder correctly rejects moving heads.
Do not weaken that decoder in isolation.

## Reproduction and scope of evidence

From `fp_usb_shell/`:

```sh
PATH=/path/to/arm-toolchain/bin:$PATH \
  python3 -B -m unittest test_fpl_gyro_coherence
```

All generated ARM sources/objects use temporary directories under the harness's
session `TMPDIR`. The new test imports the offline assembler and Unicorn, not
the camera transport or runner. It does not emit an installable product card.
**Offline result: 12 tests passed** on 2026-10-20 with the command above.

The executable cases cover movement between latch and drain, movement during
copy, source and post-head wrap, unarmed/equal heads, the strict slack boundary
with a partially written unpublished record, invalid pointers/heads/cursors,
publication changes, capacity exhaustion, cursor/prefix provenance, source and
destination bounds, finite return and call ABI. Hidden laps before and during
the batch deliberately produce changed data while the conditional test passes.

Two negative controls are executable: removing the latch causes the shared
drain to copy beyond the validated pre-head and fails provenance; changing the
real shared source's source increment from eight to zero fails the independent
sample oracle. This is not a Python reimplementation standing in for the drain.

**Remaining review gates:** optional shared-source seam; exact production
metadata size/overlap and lifecycle; decoder migration with explicit conditional
wording; real publication visibility; any evidence capable of bounding hidden
laps. No live results for this prototype, no atomicity/losslessness claim, and
no production edits or commits are part of this work.
