# Retained diagnostic admission and discovery (M2 slice)

Offline implementation, 2026-10-23. The existing launcher has an **opt-in**
owned-reservation interface. Fresh staging cannot allocate a second instance
through the same reservation. The default launcher and embedded runtime remain
byte-identical. Native activation remains an independent operation.

**Status:** executable product-side contract and discovery parser, with ARM
tests; **not an integrated fp L publication provider or completed M2 milestone**.
No camera, socket, card, reset, pending-marker, commit or release operation was
performed. The existing live retained instance is outside this interface.

## Investigation: why neither existing location is sufficient

- `fp_usb_shell/card_build.py` publishes the worker-owned pool through its
  existing firmware triplet. `camera/worker.S` owns transport buffers, fault,
  upload and window state there. Neither source assigns a retained diagnostic
  reservation. A pass-2 section at an apparently unused offset would overwrite
  duplicate intent on every load; being zero does not grant ownership. This
  patch neither claims that pool nor changes the worker/profile.
- `fp_usb_shell/v3/sloader.h` describes `SL_SVC_AT` at an fp-specific site. The
  table exposes claims, holder/self and an entry-time freshness comparison.
  `sloader.c` publishes the table while entries run, then clears the word. It
  cannot serve as post-boot retained discovery as currently implemented.
- v3 suppresses duplicate kept `sup_id` entries within its loader's books, a
  useful eventual integration point. Its `boot_id` is a microsecond timestamp;
  the header's uniqueness comment is not proof against reuse/wrap/restart.
  `done_at_start` equality also is not independent boot evidence. No current
  fp L binding of these services is assumed here.

## Proposed narrow provider contract

The composition owner must supply one resident ARM function explicitly via
`fpl_retained_launcher.build(admission_provider=address)`. There is deliberately
no inferred address or live provider implementation in this patch. The entry
ABI remains **r0 = own resolved address**; no table is passed through that ABI.
The launcher calls the configured provider with:

```
r0 = launcher start; r1 = complete launcher image end
returns r0 = reservation address; r1 = current epoch; r2 = authority (exactly 1)
```

The provider must preserve AAPCS registers and establish all of these facts:

1. It owns a live allocation containing a distinct, eight-byte-aligned 64-byte
   reservation dedicated exclusively to this diagnostic. It is not worker
   scratch, staging, stack, or an unclaimed firmware/BSS/IMU word.
2. It initializes the reservation **once per independently established boot**,
   before exposing it, and preserves it across repeated entries/fresh staging.
   Provider calls, lifetime and reset are serialized. No entry or host parser
   clears a reservation, even after allocation refusal or task completion.
3. It independently knows that the allocation belongs to the current boot.
   Matching pointers, epoch values, zero bytes, or matching retained records
   are not that authority. If this cannot be established, return r2 != 1.
4. It provides a post-boot discovery route to this same reservation with the
   same independent ownership authority. A retained numeric address alone is
   insufficient. Provider code itself must have an established resident lifetime.

The provider owns allocation initialization and reset, not the launcher. It
must not return stale storage with authority merely because a header matches.
This boundary is explicit and mocked in tests, not a firmware function claimed
to have been found. A future v3 adapter can use loader-owned books/allocation
and duplicate-ID exclusion once fp L lifetime/reset behavior is evidenced.
It need not create a generic registry.

No firmware word is patched by this implementation, so there is no new stock
word to journal. Any future adapter that publishes through a firmware site must
declare that site and its actual stock initial value through the shared journal
before runtime writes, test power-off restoration, and refuse ambiguous warm
state. A pass-2 initializer that resets this slot on every entry is forbidden.

## Reservation ABI, version 1

All words are little-endian. The format version describes the struct, not a
payload hash or paired AutoRun version. There is no runtime BIN pairing.

| Offset | Meaning |
| --- | --- |
| 0 | magic `0x5241444D` |
| 4 | struct version 1 |
| 8 | provider epoch, nonzero correlation value, **not boot proof** |
| 12 | state |
| 16..47 | the existing eight-word launcher result |
| 48..63 | reserved zeros |

Initial value is magic/version/epoch, then thirteen zero words. States:

- **0:** unused, only the provider may initialize this state.
- **1:** exclusive allocation intent; no owner pointer is ready to dereference.
- **2:** validated owned descriptor/result and identity copied, runtime entry
  intended; native initialization may be incomplete or have asserted.
- **3:** runtime entry returned; does not establish successful native startup.
- **4:** ordinary allocation refusal, retained permanently for this boot.
- **5:** invalid allocation descriptor/overlap, retained without owner access.

The launcher checks authority before dereferencing the returned slot. It checks
alignment, extent, staging overlap, magic/version/epoch and initial zeros, then
claims state 0→1 using LDREX/STREX. Contention refuses without retry. Any occupied
or corrupt reservation refuses without dereferencing its alleged owner.
Duplicate staged result is phase **7**; unavailable authority/invalid header is
phase **8**. These phases are opt-in additions; existing default phases remain.

After allocation, the launcher additionally excludes reservation/owner overlap.
It copies its result to `owner+0x400` as before, and adds four identity words at
`owner+0x440`: magic, format version, slot address, epoch. It copies the result
into the reservation before publishing state 2 with a DMB. D/I publication
still precedes runtime entry. After native return, both result copies are
updated before state 3. Native assertions retain state 2 and the descriptor.
Loss before a validated descriptor leaves state 1, deliberately non-discoverable
as an executable instance. Nothing frees, joins, retries or automatically starts
capture. A lost reply/completion never resets intent.

## Discovery without speculative owner dereferences

`fp_usb_shell/fpl_retained_admission.py` contains pure offline parsers, no
transport, marker handling or live reset. The intended reader sequence is:

1. Independently verify provider current-boot ownership; obtain slot and epoch.
2. Read the slot twice and call `candidate()`. It rejects incomplete/unknown
   state, torn data, bad extent, descriptor, version, epoch or reserved fields
   **before returning any owner address**. Without current-boot authority it
   rejects even perfectly matching records.
3. Read the validated owner's result and identity, re-read the slot, and use
   `discover()` to verify stable slot/result/identity correspondence.
4. Before any separately authorized activation, use the existing native signed
   query and stable task/holder identity checks. Task-start failure can leave
   wrapper phase 2, so discovery intentionally reports
   `native_start_verified=False` and `activation_authorized=False`.

The boolean `current_boot_verified` is an explicit caller assertion, not a
verification algorithm and never derived by these parsers from byte equality.
Future live tooling must supply its evidence, rather than default it to true.

## Tests and compatibility

`test_fpl_retained_admission.py` reuses the native allocator/wrapper fixture.
Its provider owns a separate synthetic allocation with the first 64 bytes
reserved exclusively. Provider authority and boot reset are **modelled**, not
inferred from firmware or camera observations. Allocator and native task kernel
instructions execute; telemetry, task backend/scheduling and cache effects
retain the prior fixture's explicit mocks.

Checks include both incoming stack phases; created-unattached discovery;
fresh unrelated staging after complete old-staging poisoning; duplicate refusal;
authority absent with an invalid/unmapped pointer; stale/corrupt/premature
publication; invalid provider extent/epoch; malformed descriptor and reservation
overlap; allocation refusal; native constructor assertions and dormant startup;
lost initialization; stable-but-corrupt and torn discovery snapshots; and a
new-emulator boot/reset model. The model intentionally reuses the numeric epoch
to demonstrate that equality does not prove a reboot. A mutation removing the
exclusive intent store fails the independent pre-allocation oracle.

From `fpSup/fp_usb_shell/`, with the ARM toolchain on PATH:

```sh
python3 -B -m unittest test_fpl_retained_admission test_fpl_retained_launcher test_fpl_retained_boot test_fpl_retained_relocation test_fpl_retained_bindings
```

Result: **39 tests passed**, including 11 new admission tests. `git diff --check`
also passed. No shared-load-chain source changed; the existing focused boot
tests ran as part of that command.

Default launcher SHA-256 remains
`081b3a58e806a5081798e309aa4f1790e094102d950a8d9e6380fa61b6c070d5`;
the runtime template is unchanged. Fixed wrappers, shared capture and fp Base
sources are untouched. The legacy default remains staging-local admission;
its preserved bytes must not be advertised as fresh-staging duplicate-safe.
Opt-in builds have their own changed layout calculated by the existing helper.

## Exact scope and next gate

Changed: `gyro/retained_launch.inc.S` (conditional hooks only),
`fp_usb_shell/fpl_retained_launcher.py` (explicit opt-in build argument).
Added: `gyro/retained_admission.inc.S`,
`fp_usb_shell/fpl_retained_admission.py`,
`fp_usb_shell/test_fpl_retained_admission.py`, and this document.

No USB worker/profile, v3/Gyro2 build tool, shared loader/stage2/entry trampoline,
port log or roadmap edit is part of this slice. No AutoRun update is required
by a runtime hash/version pair. Actual composition needs an evidenced provider
and an explicit dependency/reservation owner before this opt-in can be offered.
Next gate: implement that fp L provider under the composition owner's control,
prove current-boot ownership and power-off/warm-reset behavior, then run the
actual shared boot chain with that provider and post-boot discovery. Hardware
acceptance and activation of a new instance require separate authorization.
