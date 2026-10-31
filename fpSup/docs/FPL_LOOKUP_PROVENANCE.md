# fp L consumer-key and notification-clock provenance — 31 October 2026

**V3 stage record:** opt-in per-DNG keys/queue diagnostics and a read-only JSON
notification timeline. [Subsequent v4](FPL_PRODUCER_PROVENANCE.md) supplies actual
historical lookup results and independent producer generations. Neither stage
establishes sensor capture time or corrects FrameRate/TimeCodes. Resident exposure
remains [offline and refused](FPL_EXPOSURE_BOUNDARY.md).

## Exact consumer key and mutable snapshot

First producer: descriptor+38 passes through `C0320D00 -> C0320D08 -> C031EBF8`,
also reaching buffer programming at `C03208B4 -> C062E4C0`. Subsequent producer
retains incoming r1 in r4 at `C0320DC0`, programs at `C0320E6C -> C062E4C0`, and
passes r4 via `C03210E8 -> C03210F0 -> C031EBF8`. Native writer counter+1 is not
a unique generation or timestamp. Tests execute both actual argument paths.

Consumer `C038C810` uses record+4C as key and stores result in DataPool+4004
before type3/mode3 notification. Existing Subject observer recovers the key:

| Relative to observer incoming SP | Checked native value |
|---|---|
| LR | C0053660, observer-call return |
| +20 | C00530C8, Subject caller LR |
| +36 | Consumer saved r4, same DataPool |
| +40 | Consumer saved r5, bounded/aligned record |
| +60 | C038C91C, notify caller LR |

This is one checked call chain, not generic stack walking. SVC, bounded native
TCB/stack and all returns must match; foreign/direct notifications refuse.
Under local IRQ/FIQ exclusion, ten keys/values and cursor are copied.
`lookup_snapshot()` reproduces unsigned strict-maximum semantics and distinguishes
hit, miss-fallback and zero-value-fallback **at notification time**. Matching
slots and agreement with the earlier native result are reported. Reuse/wrap do
not become unique identity. A native execution test changes the ring between
lookup and notification and observes disagreement. Even agreement cannot prove
the earlier hit; a preempted writer may be between separate key/value stores.
V3 leaves historical lookup unobserved, generation/timestamp null, association false.

## Coherent notification clock

V1/v2 independently read seconds/timer5; they are not a coherent clock. Native
`C0029120` corrects seconds for pending IRQ bit5 and retries rollover. V3 uses a
finite two-read sample with refusal: verify timer/IRQ publications against
`2D810000/2D810080`,12MHz scale, read counter/seconds/pending/counter while masked,
reject wrap/out-of-range, add1 second for pending bit5. No allocation, native
call, wait, retry loop or filesystem operation was added. Actual timer setup and
pending correction have instruction tests. Pending=1/rollover refusal are
emulation evidence; these hardware takes did not exercise pending=1.

## Format and host processing

`--recording --queue-observation --lookup-observation` selects **464-byte v3**.
Omit the last switch for exact v2 bytes; omit both for exact v1. No new loader,
task, hook, allocation or journal word; existing eight-word journal,64KiB owner,
512-byte recording reservation,20KiB runtime and60KiB loader caps remain.

First336 bytes retain v2 except length/version. Added offsets are hexadecimal:

| Offset | Meaning |
|---|---|
| +150 | Flags0 absent,1 exact key,3 key+notify snapshot |
| +154/+158 | Key/cursor (cursor only with flags3) |
| +15C | Reserved0 |
| +160..187 / +188..1AF | Ten keys / ten values, physical slots |
| +1B0/+1B4/+1B8/+1BC | Valid0/1, corrected unsigned seconds, ticks0..11,999,999, pending0/32 |
| +1C0..1CF | Reserved0 |

Association stays0; tags are zero-initialized, byte-safely written/cache-cleaned.
Source reservation owner+2400..27D0 is checked against other extents.

```sh
python3 -B fpSup/slit_scan/metadata.py FRAME.DNG
python3 -B fpSup/slit_scan/metadata.py --timeline FRAME1.DNG FRAME2.DNG > delivery.json
```

Supply one take in ascending frame order; duplicate/reset/reversed indices
refuse. `fpls-notify-timeline-1` reports integer elapsed notification ticks,
intervals/rates at12MHz, gaps, unknown clocks and observed state segments.
Intervals across gaps never become per-frame rates; unknown/backward/reset clocks
break continuity, unsigned seconds wrap is explicit. V1/v2 raw fields do not
become clocks. Transitions remain notify-state segments, not sensor preroll or
postroll. Original stored nominal metadata is retained; capture time stays null,
exposure association unknown. No DNG rewrite, guessed file/Vd offset, constant
capture-rate replacement or timecode renumbering occurs. The existing host
capture/export workflow is unchanged and not silently reused on unqualified frames.

## Artifacts and historical evidence

Use the external inputs/Cortex-A9 compiler in [validation](FPL_EXPORT_VALIDATION.md):

```sh
python3 -B fpSup/slit_scan/build_card.py --fp-main "$FP_MAIN" \
  --fpl-main "$FPL_MAIN" --out NEW_DIRECTORY --debug \
  --recording --queue-observation --lookup-observation
```

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Debug BIN | 56,836 | `ca2b5769107f0811bfad5275c0972aaa66ee9f6eed84f8273aaad76fd97f6bb6` |
| Plain BIN | 52,720 | `37634298a164a89efc37656d2bda370c8026a458bd6757a1e05b6cd51948685b` |
| Shared launcher | 51,208 | `ffdd63e5bfb89a907c646742094efa41e312539f9b24b6fe52b87305e4651053` |
| Debug AutoRun | 6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |

Runtime19,264/20,480; FPUI30,848/31,744. Plain is offline-only. Corresponding
AutoRun stays byte-identical to v2; restoring the original diagnostic card still
requires both original files. Historical checks:62 product/native-queue/host,
18 GTAG/parser and54 shared regressions passed without skips. A first GTAG run
hit its120s host timeout; the complete300s rerun passed. These overlap later
export suites. Native paths, poisoned staging, bounds, idle shutdown, foreign-Vd
refusal and mutations of key loads/fallback/stack/admission are covered.

Two six-second October31 takes yielded23/69 DNGs at3.999997714/12.000011625Hz.
All92 tags had valid keys/snapshots/clocks. All snapshots recomputed matching
hits;23 had multiple same-key slots (11/16 distinct keys). Sequences1244..1266
and2669..2737 do not themselves prove historical lookup/producer completion.
First delivery intervals were229.125/73.096ms; later intervals ranged
249.7714..250.2483/83.1585..83.5908ms. Timelines preserve these differences,
without attributing them to capture, buffering or notification scheduling.

Six whole DNGs (8,447,488 bytes, raw3856×2170) decoded;86 others used128KiB
prefixes. Nominal FrameRate24000/1000 and TimeCodes remain. Both normal stops
restored idle/empty-Vd/original timing with mode3/shutter0/0/ISO0 unchanged.
There was no native mode change during recording or USB traffic in steady middles.

Original diagnostic pair was restored and fully read back before and after a
separate restart/AutoRun delay. Stock UI/hooks/observer slots,2,198 variables,
empty Vd, idle recorder, original mode/exposure, stock echo, original journal in
both shutdown lists and empty MEM1 windows passed; no resident menu/observer
remained. Original hashes are in [v2](FPL_QUEUE_IDENTITY.md); latest restoration
is in [v4](FPL_PRODUCER_PROVENANCE.md). Raw evidence stays external.

V4 resolves the historical lookup/producer gap, but software queue time still
does not establish sensor exposure/readout. Optical common-clock phase,
physical-power/no-shell/disconnected-USB acceptance remain open. The active-take
native size-change hang remains unfixed.
