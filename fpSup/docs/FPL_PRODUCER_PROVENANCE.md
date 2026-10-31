# fp L native producer → lookup → DNG provenance — 31 October 2026

**Implemented and verified in finite debug-card trials:** opt-in FPLS v4 records
independent queue generations and joins actual native lookups to DNG consumers.
All93 DNGs from two six-second4/12fps takes joined; six whole files decoded.
Both original diagnostic card files were restored and independently read back
in full after a separate restart; stock-state verification passed.

This closes [v3's historical lookup gap](FPL_LOOKUP_PROVENANCE.md). It establishes
**software queue-publication timing**, not sensor exposure/readout or DMA
completion. Nominal FrameRate/TimeCodes remain untouched. Resident exposure is
[offline-only and deployment-refused](FPL_EXPOSURE_BOUNDARY.md). The active-take
native size-change hang remains unfixed; select native format/size/rate before recording.

## Native boundaries and identity

`producer_trace.S` replaces two words at each entry with an eight-byte jump:

| Entry | Displaced instructions replayed | Continuation |
|---|---|---|
| C031EBF8 writer | push {r4,r5}; mov ip,r0 | C031EC00 |
| C031EC58 lookup | push {r4,r5,r6}; mov ip,r0 | C031EC60 |

Original native leaves execute, retaining registers/results, stack alignment and
CPSR control/flags. Trace and leaf run with IRQ/FIQ excluded on the admitted
single CPU. Coherent timer5 before/after clocks bracket publication/lookup,
including instrumentation; they do not measure total overhead or uninstrumented
scheduling latency. Writer returns are `C0320D0C/C03210F4`. First publication
is SVC; subsequent ones IRQ. In IRQ, the recorded TCB identifies the **interrupted
task**, not an executing producer task. Consumer is SVC, return `C0310C70`, with
native facade saved pool/record/outer return `C038C8E8`.

`C062E4C0` conditionally programs DMA destination: normalizes aliases, applies
stride/layout flags at `30182380`, updates alternating-buffer slots. Native
instruction tests cover aliases/flags/toggle. Some producer paths skip it;
programming and later queue stores do not prove sensor integration/readout phase.

`producer_trace.c/.h` maintain independent saturating64-bit producer generations
and lookup ordinals. Native counter+1, including zero wrap, stays a label. Native
lookup retains strict unsigned maximum/fallback semantics. Records distinguish
hit, zero fallback, miss, stale shadow, invalid context, mismatch, bad clock and
exhaustion. Exhaustion refuses identity rather than wrapping.

Storage: ten native-slot shadows,64 publication records,64 lookup records with
immutable producer copies, checked per-TCB handoffs. Commit markers publish last.
Publication eviction and unconsumed-lookup loss are separate counters. Tests
exercise carry/exhaustion, duplicate keys, first maximum and stale startup.
Each lookup invalidates its previous task handoff. Export matches ordinal, pool,
record, task index, consumer caller SP, key and result, consuming exactly once;
it never searches older matching keys. Unexpected reentry invalidates shadows/
handoffs and rejects the outer trace. Pre-mask preemption tests order the completed
nested publication before the resumed writer.

## FPLS v4, installation and compatibility

V4 is640 bytes: trailer at decimal464 has eight header words then a144-byte lookup
record including64-byte producer copy. `lookup.actual` is historical;
`lookup.at_notify` is a later mutable snapshot. `producer_trace` reports available,
rejected/exhausted, publication evictions and unconsumed lookup losses. A native
test changes the ring after lookup and verifies the retained historical record
differs truthfully from the notify snapshot.

```sh
python3 -B fpSup/slit_scan/build_card.py --fp-main "$FP_MAIN" \
  --fpl-main "$FPL_MAIN" --out NEW_DIRECTORY --debug --recording \
  --queue-observation --lookup-observation --producer-observation
```

Producer observation requires v3 and is off by default. No new loader, task or
power-off object. The existing64KiB owner holds runtime/menu; a second owned64KiB
holds descriptor/guard at0, parameters400, code1000,500 task frames4000,20,012-byte
state8000 (offsets hex). Main owner+24/+28 links trace/export. Failed owners remain
retained; callback targets are not freed/recycled.

Four new original words plus six string words, drawing vtable and Vd callback
give **12 journal words** in the shared restore object. Admission rejects foreign
entries/second words and missing/duplicate journal coverage. Guard checks single
CPU and all500 saved TCB contexts, excluding the **whole** native writer/lookup
range `C031EBF8..C031ECC8`. An interrupted key/value store blocks arming. Owned
code is published first; both shutdown reasons restore declarations in tests.

A launcher-local bounded byte-LZ decoder expands FPUI into its original owner.
Source/output/backreference bounds are checked before callbacks/hooks publish;
decoded FPUI bytes match. Existing61,440-byte BIN and20,480-byte runtime caps stay.

| Component | Bytes |
|---|---:|
| Debug / plain BIN | 45,148 / 41,032 |
| Shared launcher | 39,440 |
| Main runtime / extra trace+guard | 19,880 / 5,368 |
| Packed / decoded FPUI | 12,599 / 30,848 |

## Finite live evidence

Complete originals were backed up before deployment; candidate files and owned
code/decoded FPUI/journal/hook targets were independently verified after ordinary
debug boot and each take. Selection changed while idle only. Native settings
remained UHD CinemaDNG8-bit nominal24, mode3/shutter0/0/ISO0.

| October31 trial | DNGs / joins | Producer generations in DNGs | Steady Vd |
|---|---:|---|---:|
| Six seconds,4fps | 23 /23 | 1–23 | 3.999998730Hz |
| Six seconds,12fps | 70 /70 | 26–95 | 12.000002250Hz |

There were25 then71 publications:96 total and93 lookups, zero rejections,
zero unconsumed losses, no exhaustion. Generations24/25/96 have no collected DNG
join; publication count is not file count. Historical lookups were hits with
valid clocks;11/16 distinct keys prove reuse. First writer return was `C0320D0C`,
later `C03210F4`. The64-publication ring reported32 evictions. Lookup retention
reused29 consumed slots without pending loss. All93 tags retain their producer
copies even after RAM publication eviction.

Whole first/tenth/last frames from both takes (8,448,512 bytes) decoded through
LibRaw/rawpy, raw3856×2170;87 others used128KiB prefixes. Original FrameRate
24000/1000 and TimeCodes remain. Normal stops left recorder idle, Vd empty,
timing restored, exposure unchanged. Both steady middles had no host traffic.

At12MHz publication brackets span70–113 ticks at4fps and66–130 at12fps;
lookup brackets135–217 and140–224. These are bounds, not point timestamps.
Frames4 onward show instrumented software timing:

| Quantity | 4fps | 12fps |
|---|---:|---:|
| Publication intervals | 249.962–250.0315ms | 83.2988–83.3677ms |
| Vd counter=native_value−1 after publication | 130.7698–130.8157ms | 43.4357–43.4871ms |
| Actual lookup after publication | 370.1249–370.3987ms | 123.3579–123.6132ms |

Vd residues are reconstructed backwards from notify-bounded samples using
consecutive ordinals and verified adjacent gaps<1s. Counter matching is an
explicit software-label comparison, **not a sensor-frame join**. Publication1→2
was55.98925/56.25192ms; first delivery229.16442/32.96583ms. Fixed offsets or
all-frame constant rates would erase startup behavior. Full raw evidence stays external.

## Artifacts, tests and verified restoration

| Artifact | SHA-256 |
|---|---|
| Debug BIN | `ebfcefbe2c3c24a0d90091155c649345df68cae119cf8329ba964a6d2ef782c0` |
| Plain BIN | `c4deeebd546def3124f0e15160f554ddb03ca73eb2745377c735b064abc71a78` |
| Shared launcher | `b593d57bc62967d02f9efa3b525cf9816d755033a5f50abba4c4fb5d77e367e0` |
| Debug AutoRun6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |
| Plain AutoRun6,564 | `a27965148c4175a4b2d853e9b38571fb6a8975182fd9eacb735401dedffe43f7` |

Historical retained checks:19 producer/boot/DMA/parser and12 native GTAG tests
passed. Earlier45 shared/default regressions passed; recording/boot checks passed
after splitting an initial aggregate run at its host timeout. Tests execute
original instructions with explicit allocator/MMIO/scheduler/cache models, not
sensor physics. Mutations cover replay, IRQ exclusion, whole-leaf admission,
journal coverage, compressed backreferences and stale notify snapshots. V1/v2/v3
and v4 launchers historically reproduced exactly. Exported-tree reruns are in
[validation](FPL_EXPORT_VALIDATION.md). Plain hardware boot remains untested.
The live debug manifest's admission prose predates a descriptive-string
clarification; its artifact hashes match. The plain manifest has the full text.

Both original files were independently read in full after replacement and again
after a separate software reboot/diagnostic AutoRun delay:

- BIN4,988: `1639fe95ba115564f0140fd0359fd4432bd9134fc601bcc2392a5b74b7995e36`.
- AutoRun8,116: `7a82fa534a0f901eada154cded5a3699fb06b6b2237c6b15dcced8f8883473d0`.

Stock checks passed both producer entry pairs, six string words, pages/drawing
vtable,2,198 variables, six native observers/three empty slots, empty Vd, idle
recorder, original mode/exposure, stock echo, original six-word journal in both
shutdown lists and eight empty MEM1 windows. No resident Slit scan menu/observer
remains. Stale post-reboot handles and temporary diagnostic I-cache echo ownership
were recorded; echo borrowing waited for stock. No daemon replacement was needed.

## Remaining sensor-phase question

Which integration/readout event belongs to each retained queue generation, and
how does its phase vary at startup/rate transition? These dark-scene trials lack
an independent optical time reference; IRQ masking perturbs software timing.
Corrected capture metadata remains blocked.

A useful next experiment is a uniquely time-coded optical pulse/LED sequence,
with physical light transition and camera Vd/sensor signal on a **common external
clock**, joining visible row transitions to retained generations at4/12fps,
including first and steady frames. Host/display timestamps alone add ambiguity
and cannot calibrate absolute capture time. This experiment has not been done.
Physical-power/no-shell/disconnected-USB acceptance, shutdown/failure/stress
coverage and the original catalogue `logo2.png` blocker remain. No release or
firmware persistence write is claimed.
