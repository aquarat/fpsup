# Finite retained-task allocator launcher

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Implemented and verified offline, 2026-10-23. The launcher requests a separate
64-KiB USER allocation, initializes it, enters the existing runtime-owned
wrapper, and returns with a **created but unattached** native task. It never
activates capture. This is a payload launcher, not another loader or boot pass.

## Source and ABI

All files added for this slice are new:

- `gyro/retained_launch.inc.S`: finite allocation/initialization/entry sequence.
- `fp_usb_shell/asm/fpl_retained_launch.S`: fp L service adapter using the existing
  `firmware/fpl_302.h` allocator/cache constants.
- `fp_usb_shell/fpl_retained_launcher.py`: offline builder and exact staging
  readback mask; no transport, live CLI or imports from tests.
- `fp_usb_shell/test_fpl_retained_launcher.py`: executable ARM/firmware tests.

The shared build contract was read before implementation. The shape follows
`gyro/gsup_launch.S`: appended payload, allocation, initialization, cache
publication, entry call and return. It does not adopt a shared published pool.
The allocator algorithm and native task algorithm are not copied: the short
stub calls audited `H_GET`/`H_ADDR`, then invokes the embedded shared runtime
wrapper built by `fpl_retained_relocation.template()`.

Entry receives **r0 equal to its own resolved address**, checks that value
against its PC, preserves r4-r11/LR, and restores the caller's original stack
phase. Firmware calls use an eight-byte-aligned stack, including when the
incoming stack was four-byte phased. No shared-settings argument is introduced.
An eventual generic `--boot-bin` integration can use this entry convention;
no card builder, loader/stage2 change or AutoRun change is included here.

## Sequence and extent checks

1. Validate the full launcher image extent, including result and embedded
   template, without arithmetic overflow in `[0x40000000, 0x80000000)`.
2. Refuse any nonzero staged attempt phase. Set irreversible intent before the
   first native allocation call. Check all six embedded reference words are zero.
3. Call `H_GET(stack_descriptor, 0, 0x10000, 0x10000)`, then `H_ADDR`.
   `H_GET` returns the descriptor pointer even on refusal; it is not a success
   boolean. Preserve all four returned descriptor words before calling H_ADDR.
4. Require descriptor `[address, 0, address, 0x10000]`. A matching zero-address
   descriptor is ordinary refusal and returns normally. Otherwise require
   64-KiB alignment, the entire extent inside the audited USER interval
   `[0x44400000, 0x46400100)`, no overflow, and no overlap with the full launcher
   image. Invalid results cause no payload write or task creation.
5. Zero the entire owned 64 KiB. Fill output `[owner+0x5000, owner+0x7c00)` with
   A5 sentinels. Fill only the six symbol-derived data references in the embedded
   runtime image: owner, state, state size, output, output size and capacity.
6. Copy the descriptor/result and retained-entry intent into `owner+0x400`.
   Publish D-cache then I-cache **after** these writes and before calling the
   embedded runtime entry with r0 equal to that entry's resolved address.
7. The unchanged runtime wrapper validates references, copies resident code/data,
   publishes D/I again and creates its native holder without attachment. On
   return, copy its raw phase into the launcher result and update the owned copy.

The embedded runtime template is byte-identical to the previous slice's zero-
reference template. Placement changes neither its instructions nor launcher
instructions. Camera-side writes initialize data words only. The launcher has
no join, free, destructor, activation or retry path.

## Ownership and staging boundary

The known image extent is checked explicitly. The entry ABI does **not** expose
the full enclosing loader allocation, so this launcher does not invent such a
parameter. Separation from other live allocations relies on the native USER
allocator's live list, including the loader's still-owned staging allocation.
Tests first reserve a 32-KiB staging allocation using actual `H_GET` on the same
synthetic heap, then execute the launcher's actual allocator calls on that list.
The allocator chooses a separate aligned block. This models the ownership
boundary; it is not a capture of live boot-time heap state.

After return, no resident code, native holder/body/vtable/name, capture reference
or ownership record depends on the launcher staging bytes. Tests poison the
**entire** 32-KiB staging payload, then externally activate, capture and observe
through the existing actual native-wrapper/query harness. Every later access or
execution in that poisoned extent is trapped.

The allocator itself records the caller address for allocation accounting, as
documented in `FPL_ALLOCATOR_AUDIT.md`. That diagnostic address value may name
staging; it is not a callable or dereferenced resident payload reference. The
tests establish no later staging access in the exercised lifecycle, not absence
of every address-shaped accounting value in native heap metadata.

No global boot identity or exclusion mechanism is added. The guard is one-shot
for this particular staged image. Reloading a fresh image is not authorized by
this implementation, and plausible addresses or zero reference words are not
proof of ownership of a previous task. Existing host/pending policy is unchanged.

## Result and uncertain outcomes

The result is eight words, initially zero, at the builder's `result` symbol:

| Word | Meaning |
| --- | --- |
| 0 | launcher phase |
| 1 | H_ADDR result |
| 2–5 | complete native allocation descriptor |
| 6 | raw retained-wrapper phase after entry returns |
| 7 | reserved, zero |

Phases: **0** fresh; **1** allocation attempt; **2** returned descriptor/address;
**3** ordinary refusal; **4** invalid input/result; **5** retained entry intent;
**6** entry returned. Phase 6 is not a runnable-task or successful-start claim.
The native constructor still ignores a task-start status and can assert
synchronously. The tests include dormant task-start failure and native assertion
paths. There is no automatic activation or waiting for startup.

The owned result copy is at `owner+0x400`, before entry can register references
with native code. A constructor assertion leaves phase 5 and the descriptor in
owned memory. Once descriptor/extent validation succeeds, memory remains retained
even if native initialization is uncertain. If execution is lost earlier, only
the staged intent and whatever descriptor words have been returned are available;
the launcher does not guess an address or attempt recovery. A second dispatch of
the same staged image never allocates again. No durability beyond the lifetime
of that staging allocation is claimed for pre-owned records.

`verify_staging()` permits changes only in the 32-byte result and the six
symbol-derived embedded reference words. It is a byte-integrity mask, not a
semantic result validator. Tests separately check descriptor/result values,
owned copies, untouched staging tail, all unused owned gaps and output sentinels.

## Executed checks

After delivery, main independently reran all **11 launcher tests** successfully
and reviewed the allocator/initialization/entry assembly. The combined run and
artifact comparisons below are the implementation agent's reported checks.

**11 launcher tests and 164 combined fp L tests passed.** The same 13,312-byte
blob executed at both actual synthetic loader allocations:

| Staging allocation | New aligned owner |
| --- | --- |
| `0x444f0080` | `0x44500000` |
| `0x459f0080` | `0x45a00000` |

No host reassembly or instruction fixup occurred between placements. Tests cover
both stack phases; correct self-address r0 and rejected argv; real allocator
refusal; malformed descriptor/class/duplicate/size; alignment, domain, overflow
and overlap rejection; zero-input-reference admission; full-image end/carry
checks; duplicate/lost attempts before and after native entry; cache ordering;
native assertions; dormant startup; and cancellable capture after independent
external activation. Mutation tests remove cache publication, corrupt entry r0,
skip zero initialization, replace sentinels, or bypass descriptor validation;
each fails an independent executable oracle. Every staging byte is mutation-
checked against the exact readback mask.

The USER descriptor, allocator list/lookup/alignment and IRQ-guard instructions
execute from the fingerprinted official fp L MAIN. The allocation setup uses
the existing allocator-audit fixture, not a second implementation. The retained
native constructor/worker/query kernels also execute actual firmware. Explicit
mocks remain for allocator telemetry/static guards, native task backend/scheduler
boundaries and privileged cache effects. This is not MMU/cache or boot-context
hardware verification. No dependency was missing in these executed tests.

Four fixed wrapper builds still match their saved bytes and complete symbol
maps; Base/GCSV binaries are unchanged. All 24 archived artifacts and raw
task/capture readbacks were checked read-only, and the exact archived prototype
was reproduced. The archived conditional-prefix result remains 997, proven-valid
zero, with provenance fields unchanged.

| Artifact | SHA-256 |
| --- | --- |
| Default launcher | `081b3a58e806a5081798e309aa4f1790e094102d950a8d9e6380fa61b6c070d5` |
| Cancellable launcher | `a5ac34362827edd167bfa00e47ca8227151ea0b48fc5ea3072564b594be53b8d` |
| Default embedded runtime template | `bb91e947d2461ed808ad50192836eab2c227444ec4880e088ed6b59c30b0422c` |
| Cancellable embedded runtime template | `3aae1276779af5ee08b3e4023bb10d6f21ecf8212e25b5e81024b6d1062cf9a7` |
| Archived fixed prototype | `c2c8c9a5a075ba65a63fe4485f111e3559c544f2462782f6dfe891cfe6a52725` |
| Base binary | `5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38` |
| GCSV binary | `c6e9f98bffaf057768bd099c587d903f031f378bc656692fdc17fb0bb07472bb` |

From `fp_usb_shell/`, with the ARM toolchain on PATH:

```sh
python3 -B -m unittest test_fpl_retained_launcher
python3 -B -m unittest test_fpl_gyro_capture test_fpl_gyro_capture_host test_fpl_gyro_latched test_fpl_gyro_coherence test_fpl_gyro_latched_relocation test_fpl_gyro_latched_cancel test_fpl_gyro_task test_fpl_gyro_task_retained test_fpl_gyro_task_host test_fpl_retained_bindings test_fpl_retained_relocation test_fpl_retained_launcher
```

Offline build API:

```python
from fpl_retained_launcher import build
blob, symbols, runtime_artifact = build()
```

Builds use fresh temporary directories. No card was packaged or booted. Shared
gyro regressions were not rerun for these new standalone files; the prior
independently baseline-confirmed result remains 108 passes, three failures and
one missing-image skip, not a new passing claim.

Remaining gates: actual loader/boot integration and live context, activation
admission/ownership policy for such integration, lifecycle reclamation,
unconditional coherence, calibration and recording association. No camera
operation, live allocation, host CLI change, pending-marker operation, card
write, commit or push was performed.
