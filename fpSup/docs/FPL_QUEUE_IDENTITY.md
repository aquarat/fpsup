# fp L native queue identity and exposure lifetime — 31 October 2026

Development measurement, **not corrected frame metadata or automatic resident
exposure compensation**. Supported recording remains UHD CinemaDNG 8-bit
nominal24, selected before the take. The active-recording native size-change
hang remains unfixed; do not change native format, size or rate during a take.

This is the v2 stage record. [V3](FPL_LOOKUP_PROVENANCE.md) adds exact consumer
keys and notification clocks; [v4](FPL_PRODUCER_PROVENANCE.md) subsequently joins
historical native lookups to independent software queue generations. Sensor
exposure/readout association remains unqualified.

## Concrete native queue seam

Against the fingerprinted official fp L 3.02 MAIN:

- `C031EBF8(owner, buffer)` writes a ten-entry ring: keys at `owner+13C`, values
  at `+164`, cursor at `+18C`. Values are counter+1 from `owner+10`. Owner:
  `C343B6C4`; construction guard: `C343B858`.
- `C031EC58` selects the greatest unsigned matching value. A miss or zero value
  returns the current counter. Reused keys and fallback preclude unique identity.
- `C038C810` passes frame-record+4C through `C0310C58 -> C031E210 -> C031EC58`.
  `C038C8EC` writes the result to DataPool+4004 before notification at `C038C918`.
  DataPool vtable `C07333D4`, slot1C, calls `C0053CB0` for `{pool+4,pool+4004}`.
- `C03193A0` advances the counter through `C031E300/C031E2E8`. `C0325798`
  registers dispatch `C0325940` through `C01232E8 -> C0121DE8` in `C31D6DF0`,
  called by IRQ body `C0121E60`. The slit callback is in `C31D6DD8`, called by
  `C0121D18`. Instruction order does not establish relative hardware IRQ phase.

`queue_binding.py` checks bounded native instructions and the DataPool vtable.
Its tests execute writer, lookup, pair getter and lookup-to-notify handoff,
including repeated keys, ring wrap and a miss equal to a valid result. Mutations
bypass the image fingerprint and fail on instruction/dataflow effects.

## Bounded FPLS v2 measurement

`--recording --queue-observation` uses the existing owned allocation, Vd callback
and GTAG observer. It adds no hook, loader, task or setter. Omitting the option
retains v1 bytes. The 512-byte recording reservation contains a 16-entry ring;
before changing timing each Vd writes `{native_counter, timing04_before, timer5,
owned_Vd_ordinal}`. An absent construction guard produces counter `FFFFFFFF`.
Cursor publication follows stores; each take clears the ring and cursor.

V2 is **336 bytes**. The first64 bytes retain v1 fields except length/version:

| Offset (hex) | Field |
|---|---|
| +40 | DataPool sequence, valid only with flags1 |
| +44 | Vd ring cursor |
| +48 | Native current counter at notification |
| +4C | Flags1: constructed owner and exact DataPool vtable; 0: omitted |
| +50 | Sixteen 16-byte raw ring entries |

Copying uses local IRQ/FIQ exclusion; tags are byte-safely written/cache-cleaned.
The reader returns the published ring tail chronologically. Association remains0;
FrameRate, TimeCodes and exposure metadata are not rewritten. Counter equality
is a measurement candidate, not permission to label a sensor frame.

## Exposure lifetime: a concrete earlier save

Ordinary power-off settings object `C31AB174`, vtable `C0733A30`, callback
`C0075FE8` calls `C0055120 -> C0055588` then `C0055120 -> C0055320`. Registration
at `C0076064` is ordinary list0; the object precedes the shared journal callback
and is absent from the forced list. Native-walker execution with modeled save
effects observes **prepare-save → save → shared-restore**. Restoring in the
shared callback, even before its masked section, is too late.

The host helper now re-reads **all three settings after all setters finish**.
Immediate per-setter checks could pass before the final mode setter changed the
already-verified shutter. A final mismatch raises and retains the pending recovery
marker. Tests model coupling without camera I/O or speculative corrective writes.

The subsequent [offline exposure controller](FPL_EXPOSURE_BOUNDARY.md) finds a
quiescent save-slot ordering candidate, but native deferral/common serialization
remain unqualified. `build_card.py --exposure` explicitly refuses deployment.

## Historical verification and artifacts

```sh
python3 -B fpSup/slit_scan/build_card.py --fp-main "$FP_MAIN" \
  --fpl-main "$FPL_MAIN" --out NEW_DIRECTORY --debug --recording --queue-observation
python3 -B fpSup/slit_scan/metadata.py FRAME.DNG
```

Use the Cortex-A9 compiler and external official images described in
[export validation](FPL_EXPORT_VALIDATION.md).

| Debug artifact | Bytes | SHA-256 |
|---|---:|---|
| fpSup.BIN | 56,276 | `cc8da06c254509cd549a5a40dfd28cb74a8d51024a84ce6674a38bd63473d2fa` |
| AutoRun.txt | 6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |
| launch.bin | 50,648 | `2513c8c6132fa050990cbe9acbbcfb1995821f8ce8f9dadb31dd58b05663f8ae` |

Runtime18,704/20,480; FPUI30,848/31,744; owner64KiB. Plain hardware boot was not
tested. AutoRun is unchanged for each shell configuration. Omitting queue
observation reproduces v1 launcher SHA-256
`52aebc6ccdfdd55586e9f4a97c74dcd4e1e314543bbf2e2846baf971c68d6218`.
Historical stage checks: 52 product, 54 shared, 14 native GTAG/parser and six
host-helper tests passed, followed by an additional ordinary boot/idle-shutdown
case. These overlap later suites and are not additional export-test totals.

Ordinary debug-card boot verified immutable extents, 2,203 variables, the
eight-word journal and one owned observer. Two six-second October31 takes
yielded23/69 notifications at4.00000114/12.00000488Hz. All92 tags parsed; six
whole DNGs (8,447,488 bytes, raw3856×2170) decoded; others used128KiB prefixes.
A64KiB prefix was insufficient because the tag begins at72638. FrameRate remains
24000/1000, association0. The first take reused number033 after recovery and
is not the failed October30 take. Both steady middles had no USB traffic.

Sequences1086..1108 and1948..2016 are consecutive, but only frame1 of each take
already finds an equal counter in its Vd ring. Frame1 has cursor9/current=sequence+1;
frame2 also has cursor9, and later cursors advance with files. Frames2 onward
have current=sequence and no equal ring counter yet. The file/Vd offset changes
from8 to7. Neither equality nor a fixed offset establishes capture timing.

Normal stops restored idle recorder, empty Vd slot, original timing and
mode3/shutter0/0/ISO0. Both original diagnostic files were fully read back after
replacement and again after a separate restart. Stock pages/string words/drawing
vtable, 2,198 variables, six native observers/three empty slots, idle recorder,
empty Vd, original mode/exposure, stock echo, six-word journal in both shutdown
lists and eight empty MEM1 windows passed. No resident Slit scan menu remained.
Original BIN4,988 SHA-256:
`1639fe95ba115564f0140fd0359fd4432bd9134fc601bcc2392a5b74b7995e36`;
AutoRun8,116 SHA-256:
`7a82fa534a0f901eada154cded5a3699fb06b6b2237c6b15dcced8f8883473d0`.

Raw evidence and operational logs remain external. Latest restoration is recorded
in [v4](FPL_PRODUCER_PROVENANCE.md). Physical/no-shell/disconnected-USB, repeated
power-switch/previous-card boot and optical common-clock sensor-phase acceptance
remain open. Original catalogue `logo2.png` remains unavailable.
