# Shared retained native wrapper

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Implemented and checked offline, 2026-10-23. The existing fp L wrapper now lives
once in `gyro/retained_task.inc.S`; `fp_usb_shell/asm/fpl_gyro_task_retained.S`
is its thin firmware adapter. This extraction preserves default bytes and all
symbol offsets. It does not establish fp Base wrapper/query compatibility or
change Base's mailbox writer or teardown.

## Compile-time inputs

The core requires all six explicit bindings; omitting any fails assembly:

| Binding | fp L adapter | Interface |
| --- | --- | --- |
| `RT_CREATE` | `0xC036E320` | native holder constructor |
| `RT_ATTACH` | `0xC036E3D0` | attach body and wake |
| `RT_REF_TSK` | `0xC01F54CC` | direct task reference |
| `RT_REF_FLG` | `0xC01F5460` | direct flag reference |
| `RT_DCACHE` | `FW_DCACHE` | publish data cache |
| `RT_ICACHE` | `FW_ICACHE` | invalidate instruction cache |

Cache constants come from the existing `firmware/fpl_302.h`, included directly
by the model-specific adapter. `firmware/loader.h` defaults to fp Base, so using
it without an explicit model would be misleading here. The four native bindings
remain explicit adapter macros; no duplicate cache address map or runtime
dispatch framework was added. Alternate adapters include the core directly.

Existing `OWNED`, `CAPTURE_FILE`, and optional `SLEEP_REASON` inputs retain their
semantics. The sleep diagnostic defaults to disabled (zero); a supplied reason
is a diagnostic expectation, not a universal native wait-state invariant.

## Preserved contract

`entry`, `activate`, `body_entry`, `identity`, `sample`, and `observe` now have
one shared implementation. The entry copies resident bytes into the caller's
zeroed, 64-KiB-aligned owned reservation and publishes caches before creating
the native holder. Resident references do not point into recyclable staging.
Create/attach attempts and the callback ONCE guard are never rearmed. Capture
can still be the opt-in cancellable core from the previous slice.

The native object layout, vtable slot, priority and stack size are unchanged.
Signed query return bits, before/after identity snapshots, optional sleep
evidence and finite query count are unchanged. DONE is not native completion.
The constructor can still assert synchronously; a holder alone does not prove
successful task start. Direct queries do not wait on an object, but carry no
wall-time deadline. Completion, cancellation or uncertainty never authorizes
reclamation. There is no join/free/destroy/rearm/resume operation in this core.

The checked host workflow, diagnostic echo trampoline, pending interlock and
native retained assembly behavior are unchanged. This work did not operate a
camera, manipulate the pending marker, allocate live memory, write a card,
commit or publish. No AutoRun change is needed.

## Verification

Independent reproduction of the focused command below passed **55 tests**
after delivery (bindings, retained native task, host workflow and cancellation).
The 142-test full run and build comparisons below are the implementation agent's
reported checks; they are distinct from that independent focused rerun.

**142 fp L tests passed**, including the 25 host tests and four focused binding
tests. The latter prove:

- each missing service binding independently fails assembly;
- direct core assembly with fp L bindings matches the adapter's complete bytes
  and symbol map;
- synthetic alternate addresses dispatch all six services, bridge into actual
  fp L firmware routines, and preserve one-shot capture/native completion;
- individually reverting any binding to its old literal trips the execution
  oracle, rather than merely changing an unexamined literal pool.

Synthetic bridges test binding selection only, not another firmware ABI.
Existing actual-firmware signed-status, identity, completion-order, constructor
failure, queued-wake and forbidden-lifecycle mutation tests remain in the suite.
Temporary mutation fixtures expand the adapter and mutate the real shared core;
they do not maintain a second implementation.

Before/after builds at owners `0x46000000` and `1162870784`, each with sleep
diagnostic 0 and 1, have identical bytes and complete symbol maps. Saved baselines
are in this session's temporary directory under `retained-before/`.

Read-only verification of
`/path/to/observations/gyro-retained-task-first/`
confirmed all **24** artifact sizes/hashes, rebuilt the exact archived prototype,
and re-decoded control, three observations, wrapper and full capture readbacks.
The result remains 997 conditional-prefix records and zero proven-valid records.
Archived provenance fields were not rewritten.

| Artifact | SHA-256 (unchanged) |
| --- | --- |
| Archived retained prototype | `c2c8c9a5a075ba65a63fe4485f111e3559c544f2462782f6dfe891cfe6a52725` |
| Base `gcsv_task.S`, `FPGYRO_EDITION_BASE=1` | `5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38` |
| GCSV `gcsv_task.S`, default | `c6e9f98bffaf057768bd099c587d903f031f378bc656692fdc17fb0bb07472bb` |

Commands from `fp_usb_shell/`, with the ARM toolchain on PATH:

```sh
python3 -B -m unittest test_fpl_retained_bindings test_fpl_gyro_task_retained test_fpl_gyro_task_host test_fpl_gyro_latched_cancel
python3 -B -m unittest test_fpl_gyro_capture test_fpl_gyro_capture_host test_fpl_gyro_latched test_fpl_gyro_coherence test_fpl_gyro_latched_relocation test_fpl_gyro_latched_cancel test_fpl_gyro_task test_fpl_gyro_task_retained test_fpl_gyro_task_host test_fpl_retained_bindings
```

The first command passed 55 tests; the full command passed 142. Tests require
Unicorn, the ARM assembler and the private official fp L image used by the
existing native harness. No dependency was missing in these runs. Base/GCSV
were assembled offline before and after with `armasm.assemble`; no card was
packaged. Shared gyro regressions were not rerun for this wrapper-only extraction:
the previous 108-pass/3-fail/1-skip result was independently confirmed by main
against committed baseline `the pre-integration development baseline`. That is baseline context, not a new pass.

Remaining evidence gaps are unchanged: fp Base native wrapper/query proof,
safe reclamation, live cancellation visibility, unconditional coherence,
calibration and recording association. None is implied by sharing source.
