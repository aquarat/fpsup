# Runtime-owned retained wrapper (offline)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Implemented 2026-10-23 after reading the full shared build contract. **One
runtime-owned image now executes at unrelated staging and owner placements
without per-address instruction fixups.** The fixed/default image remains
byte- and symbol-identical, including the archived live prototype.

## Changes and interface

- `gyro/retained_task.inc.S`: opt-in `RT_RUNTIME_OWNED=1`, mutually exclusive
  with compile-time `OWNED`. Native holder/body/query logic stays shared.
- `fp_usb_shell/asm/fpl_gyro_task_retained.S`: the existing fp L service adapter
  accepts the opt-in through preprocessing; fixed mode remains its default.
- New `fp_usb_shell/fpl_retained_relocation.py`: pure offline `template()`,
  `initialize()`, `reference_offsets()` and `verify_resident()` helpers, with
  no transport, test imports, allocator, live CLI or card builder.
- New `fp_usb_shell/test_fpl_retained_relocation.py`: 11 actual-ARM tests using
  the existing native fp L constructor/worker/query harness.

The only new parameter word is `runtime_owner`, stored inside the resident
wrapper portion of the template. The existing five-word capture runtime table
supplies state address/size, output address/size and capacity. `RT_CAPTURE_REFS`
is a compile-time **symbol offset**, derived from that capture build, not a
per-placement address or runtime configuration framework.

`template(cancel=False, sleep_reason=0)` produces zero-reference bytes once.
`initialize(artifact, staging, owner)` changes exactly six symbol-derived data
words: the owner word and existing capture table. It refuses already initialized
reference words. It neither assembles again nor patches instructions. This is
an offline simulation of initialization by a future allocation-owning caller;
address checks do not establish allocator ownership or authorize another trial.

The fixed 64-KiB layout remains:

| Owner offset | Purpose |
| --- | --- |
| `0x0000` | retained control/holder/body/vtable |
| `0x0100` | native query observation |
| `0x1000` | resident wrapper, including copied owner value |
| `0x2000` | runtime-reference capture image, 4096 bytes |
| `0x4000` | capture state, 2048 bytes |
| `0x5000` | output reservation, 11264 bytes, capacity 1200 |

The owner word is currently at image offset 5180; callers must obtain it from
symbols. The capture table offset differs between normal/cancellable builds.
Neither offset is a placement address.

## Entry and resident validation

Runtime entry requires r0 to equal its actual PC-resolved entry address, matching
the shared loader ABI. Echo argv is not accepted. The diagnostic echo trampoline
already supplies the target address in r0; it was not changed here.

Before any owned-memory access/write or native call, entry checks:

1. Its full `0x3000` staging-image extent lies in the USER-address domain
   `[0x40000000, 0x80000000)`, without overflow.
2. Owner is 64-KiB aligned, with its entire 64-KiB extent inside the audited
   fp L USER allocator interval `[0x44400000, 0x46400100)`.
3. Owner extent and staging image do not overlap.
4. All five capture references exactly describe the owner-relative layout above.

After validation, the original attempt guard is set and the resident wrapper
and capture are copied. Entry checks the **copied owner word** against its
validated owner before body setup/cache publication/native create. A mismatch
leaves the attempt retained and makes no native call. The caller must keep the
source immutable during this operation; this check is not a concurrency lock.

Each resident owner load is PC-relative and compares the copied value with the
64-KiB base containing the executing resident code. Thus commands/callbacks
refuse a corrupted owner instead of following it into other memory. The owner
word contains a value, not a pointer to the staging parameter block. All native
holder/body/vtable/name and capture references are derived inside owned storage.

There is no incompatibility with the native holder ABI: it already accepts
holder/body pointers. The change replaces address acquisition, not native object
layout, query format, signed status semantics, ONCE, DONE or completion logic.

## Publication, readback and lifetime

Before entry, the caller must own/initialize the reservation and publish the
initialized staging image with D-cache then I-cache maintenance. The emulator
assumes that initial publication; the offline helper performs no cache or camera
operation. Entry retains its existing D/I publication of the copied resident
bytes before native create. No resident reference may survive in loader staging.

The six initialization offsets are **not** the post-execution mutable mask.
`verify_resident()` compares the entire resident wrapper, including the owner
word, exactly with initialized bytes. Capture readback allows only its existing
six mutable words, plus `g_cancel_request` when explicitly opted in. Capture
runtime references remain immutable. Tests mutate every byte of the default
8192-byte resident extent to verify this exact distinction.

No rearm, task reuse, join, free, destruction or marker operation is added.
Duplicate entry still encounters the retained attempt guard; native failures
retain it. The future caller owns the actual allocation and boot identity; a
fresh template or plausible address is not permission to reuse a previous owner.
All referenced objects/storage remain retained for the boot. Native synchronous
constructor assertions, unknown start outcomes and lack of wall-time bounds
remain unchanged. Optional sleep diagnostics still default to disabled.

## Executed verification

Main independently reran the relocation, binding, retained-native, host and
cancellation suites after delivery: **66 tests passed**. The full 153-test run
and artifact comparisons below are the implementation agent's checks.

**153 fp L tests passed**, including 11 relocation tests and the existing
25-test checked host workflow. The relocation tests cover:

- The same template at `(staging, owner)` pairs
  `(0x48010000, 0x44500000)` and `(0x51030000, 0x45A00000)`. Zeroing only the six
  data words reconstructs the identical template. The second run poisons the
  first placement; both also poison historical placements and staging after
  return. The memory/execution oracle traps references to them.
- Actual fp L native creation, attach, callback, reference kernels and completion,
  including queued wakes, preserved one-shot capture, signed -18/-42 query
  statuses and identity-change rejection. Scheduler/allocation/cache boundary
  mocks are the existing harness's; this is not a live task run.
- Invalid/unaligned/out-of-USER/overflowing owner references, staging overlap and
  invalid domain, wrong entry r0, and malformed capture references: no owned
  write, cache call or native creation before rejection.
- Copied-owner corruption before create, resident-owner corruption before
  commands/callback, retained constructor failure, and rejection of reference
  changes in readback. Removing reference validation or the resident-owner check
  causes the independent mutation oracles to fail.
- Cancellable capture through the relocated native wrapper; DONE precedes native
  completion, queued wakes do not rerun capture, and results remain retained.
- Poisoned unused owner gaps and output tail remain intact.

Four fixed builds (owners `0x46000000` and `1162870784`, each with sleep diagnostic
0 and 1) match the saved pre-extraction bytes and complete symbol maps. Base/GCSV
binaries also match their saved baselines. All 24 archived artifact sizes/hashes
and raw task/capture decodes were reverified read-only; the archived prototype
was rebuilt exactly. Its result remains 997 conditional-prefix records and zero
proven-valid records; archived provenance flags were not rewritten.

| Image | SHA-256 |
| --- | --- |
| Runtime zero-reference template, default | `bb91e947d2461ed808ad50192836eab2c227444ec4880e088ed6b59c30b0422c` |
| Runtime zero-reference template, cancellation | `3aae1276779af5ee08b3e4023bb10d6f21ecf8212e25b5e81024b6d1062cf9a7` |
| Archived fixed prototype (unchanged) | `c2c8c9a5a075ba65a63fe4485f111e3559c544f2462782f6dfe891cfe6a52725` |
| Base binary (unchanged) | `5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38` |
| GCSV binary (unchanged) | `c6e9f98bffaf057768bd099c587d903f031f378bc656692fdc17fb0bb07472bb` |

From `fp_usb_shell/`, with the ARM toolchain on PATH:

```sh
python3 -B -m unittest test_fpl_retained_relocation
python3 -B -m unittest test_fpl_gyro_capture test_fpl_gyro_capture_host test_fpl_gyro_latched test_fpl_gyro_coherence test_fpl_gyro_latched_relocation test_fpl_gyro_latched_cancel test_fpl_gyro_task test_fpl_gyro_task_retained test_fpl_gyro_task_host test_fpl_retained_bindings test_fpl_retained_relocation
```

Offline build API (no device/backend is opened):

```python
from fpl_retained_relocation import template, initialize
artifact = template()
first = initialize(artifact, 0x48010000, 0x44500000)
second = initialize(artifact, 0x51030000, 0x45A00000)
```

These addresses are synthetic test placements, not proposed camera allocations.
Builds used temporary directories; baseline files are under the session's
`retained-before/` temporary directory. No dependency was missing in the executed
tests. Shared gyro regressions were not rerun: their prior independently
baseline-confirmed result is 108 passes, three failures and one missing-image
skip. No loader/stage2/AutoRun code or card packaging changed.

This remains a boot-integration prerequisite, not a boot-integrated product.
Actual allocation and ownership admission, full loader-staging allocation
separation, boot context verification and any subsequent live trial remain for
separate work. The current checked host workflow and pending interlock are
unchanged. No camera operation, live allocation, card write, marker change,
commit or push was performed.
