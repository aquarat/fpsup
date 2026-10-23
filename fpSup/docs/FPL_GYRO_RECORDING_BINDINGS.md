# fp L 3.02: current Base recording bindings (offline)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-20. **The current START and STOP sites have concrete fp L counterparts:
`C03792D0` and `C038C69C`. Neither is an exposure timestamp or an all-modes
recording detector.** The complete shipping Base is not ready to enable: its
path/metadata assumptions and installation/lifetime still need work.

This audit changes only this document and `tools/fpl_gyro_recording_audit.py`.
No device access, card build, hook installation or production change was made.
The optional shared-drain/latched-diagnostic work belongs to another session.

## Reproduction and strength of evidence

Read alongside [FPL_GYRO_BINDINGS.md](FPL_GYRO_BINDINGS.md) and
[FPL_PORT.md](FPL_PORT.md). Inputs are official decompressed MAINs at CPU base
`C0000000`, not whole update containers:

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

```sh
ROOT=/path/to/firmware
python3 -B tools/fpl_gyro_recording_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" --self-test
```

Passed **34 bounded ARM correspondences, three stock-word pairs and ten negative
cases**. The tool shares the earlier audit's Capstone normalizer: registers,
memory offsets, ordinary constants and internal branch destinations are retained;
external branch destinations and MOVW/MOVT immediates are masked and reported
separately, including unchanged ones. The JSON records every direct branch/call
and materialized immediate in each bound. This is reproducible correspondence,
not a global uniqueness proof or recursive validation of every callee. Names
ending `_prefix` deliberately qualify partial coverage.

Eight negatives mutate first/code/last bytes or truncate each image, and are
rejected by size/full SHA-256. Two more bypass fingerprinting deliberately and
change fp L's START state-field offset and STOP's internal branch target; the
structural comparator itself rejects both. External-call and literal mutations
are rejected by the full hash, not by normalization alone. Missing Capstone or
images fails rather than silently skipping evidence.

Initial discovery used instruction-pattern searches, then actual disassembly of
both images, enclosing recorder functions and their direct-call/literal chains.
No address here was selected by adding a neighboring symbol's relocation delta.

## What current Base actually consumes

`build_base_card.EDITIONS['base']` compiles `gcsv_task.S` with
`FPGYRO_EDITION_BASE`; it includes `writer_core.inc.S`, `ring_task.inc.S`,
`imu_stream.inc.S`, the shared drain, accel producer, and `rec_trigger.S` twice.
There is no separate current Base task implementation. `gsup_launch.S` allocates
or reuses the published pool, copies the body to +44000 and calls its boot entry.
The pool/veneer ownership objections in the earlier audit still apply.

The actual `gsup_boot` arms **accel, START, STOP only** for Base. The fourth
still/cine orientation hook and `F_MODE_GET`/level-gate initialization are under
`WANT_MODE_HOOK`, which Base does not define. Base nevertheless calls
`gcsv_json_write` after its 20-byte binary header, so sensor-mode, timing,
geometry, dimensions, lens and distortion dependencies are still live.

Important stale-source traps:

* The deployer's opening prose mentions a Vd frame hook; its actual producer
  table and Base boot do not install one. `rec_trigger.S`'s frame-latch prose
  describes older instrumentation, not a current per-exposure record.
* `EXPOSURE_FN=C030C7F0` is defined in `ring_task.inc.S` but is not called by
  current Base. The old exposure/header fields are not a requirement for the
  20-byte header. Do not port a dead callback to satisfy that comment.
* The active timing dependency is the JSON's computed frame rate/readout, not
  a hardware frame-time latch. Position in the sample stream supplies its clock.

## Recorder commit sites and stock bytes

All addresses below are ARM instruction addresses (no Thumb bit).

| Current hook | fp 5.02 | fp L 3.02 | Stock word | Little-endian bytes |
|---|---|---|---|---|
| accel success | `C050D4C8` | `C0509730` | `E3A02000` | `00 20 A0 E3` |
| START, after audio start | `C03790B8` | `C03792D0` | `E5DB25CE` | `CE 25 DB E5` |
| STOP, after audio branches join | `C038C484` | `C038C69C` | `E3500000` | `00 00 50 E3` |

These are **journal candidates**, not permission to patch them. Current
`build_base_card.hook_sites()` emits the original four-byte word for each actual
`imu_stream_deploy.PRODUCERS` entry. Stage2 journals those sections before
`gsup_boot` changes them at runtime; restoration must cover the entire eventual
overwrite extent if a future fp L placement mechanism uses more than one word.
The stock word alone says nothing about branch reach or callback quiescence.

### START correspondence

Enclosing step: fp `C0378A50`, fp L `C0378C68`, **0x7D8 bytes** normalized
instruction-for-instruction, through the return. Prologue saves r11/lr and makes
a 0x26C-byte frame. This is not the old monitor-audio hook at fp `C01FBA28`.

fp L's actual sequence:

* `C0379204 → C0203B70` obtains CameraMgrSetting; `C0379210 → C0203D60`
  returns its live block (+40). `C0379218` reads live-block byte **+E0**;
  zero branches at `C0379220` to **C0379340**, bypassing this START site.
* `C0379298 → C04408B8` gets the file manager;
  `C03792A8 → C04408F8` gets volume with r1=0.
* `C03792B4 → C01F7B78` gets the audio recorder;
  `C03792CC → C01F7BB8` starts it, with r1 from stack +24 and r2 from +28.
  Its fp counterpart is `C01FB338`; the 0x1D0-byte start body also matches.
* **C03792D0** executes `ldrb r2,[r11,#5CE]`; `cmp r2,#0` and a conditional
  branch follow. The shared START hook must replay that load exactly.

r11 here is not an assumed fp L record structure: actual code at `C0378FD8`
calls `C0021B20`, then `C0378FE4` calls `C0021B60`, assigning its result to
r11 at `C0378FEC`. Those functions materialize **C3075194** and return its
word at **+5C**, hence the pointer-publication word **C30751F0**. The fp
chain is `C0021C00/C0021C40`, owner `C30751D4`, pointer `C3075230`.
The recorder also reads r11+5C4 and r11+14. Only these accessed offsets and
this chain are established, not equality of the whole settings structure.

This site is downstream of audio-start return; the caller does not test that
return before the displaced load. It is consequently **not proof of successful
media opening**, nor first sensor exposure. Audio-disabled/non-file paths skip
it. Establish supported modes before using it as the sole take gate.

### STOP correspondence

Enclosing step: fp `C038C3C0`, fp L `C038C5D8`, **0x238 bytes** normalized
through its return. At fp L:

* `C038C674` reads the same live-block +E0 gate. If nonzero,
  `C038C684 → C01F7D88` stops the audio recorder (fp `C01FB508`).
* The alternate path calls `C01F7B78` then `C01F8198` (monitor restart).
* Both paths reach **C038C698 → C0399368** (fp call target `C0399150`).
  **C038C69C** is `cmp r0,#0`, consumed by `beq` at `C038C6A0`.

There are earlier bypass/error paths in the enclosing function; this is not an
entry-wide event. The shared STOP hook drains before clearing `T_WANT`, invokes
the close routine, restores r0 and replays the comparison so the following
conditional sees the stock result. START sets `T_WANT`, captures ring head and
resets the raw cursor before calling open. Their counters/latches count callback
entries; those counts alone do not prove a paired successful take. These hooks
perform synchronous lifecycle work, unlike a finite observation-only latch.

## Sensor mode and frame-time metadata

| Role | fp 5.02 | fp L 3.02 | Evidence |
|---|---|---|---|
| current sensor mode wrapper | `C032C720` | `C032C7C0` | 0x14-byte body |
| mode getter | `C03212F8` | `C0325410` | returns object word +4 |
| sensor instance wrapper | `C0322E88` | `C0326E48` | materializes initialization descriptor |
| singleton accessor | `C03255F8` | `C0329E08` | materializes `C343B588` / **`C343C4C0`** |
| sensor ctor | `C03255B0` | `C0329DC0` | writes dispatch table at object +D0 |
| timing row accessor | `C0320FC8` | `C03250E0` | 0x60-byte body; stride 0x20 |
| geometry row accessor | `C0321028` | `C0325140` | 0x60-byte body; stride 0x64 |
| timing index | `C0320BA0` | `C0324CB8` | searches mode ids; count from descriptor +4 |
| geometry index | `C0320B38` | `C0324C50` | searches mode ids; count from descriptor +C |

The current-mode wrapper calls `C0326E20` with r0=0, then `C0325410`.
**The selector is not identical:** fp `C0322E48` selects a second sensor object
for argument 1; fp L `C0326E20` unconditionally calls `C0326E48`. This audit
does not mark the selectors as normalized matches. The actual Base argument 0
chain leads to the singleton above. fp L's instance wrapper materializes
`C2F2E71C` (fp `C2F1E654`); these are beyond the supplied MAIN's file-backed
extent and must not be decoded as bytes at MAIN+offset. Initialization and
runtime table contents need their own evidence.

The two row accessors substitute current mode for sentinel **0x77**. Both index
searches default to **index zero if no id matches**. A non-null row is therefore
not validation of an arbitrary mode id. Timing comes from `[[object]+0]`;
geometry from `[[object]+8]`. Accessor shape and row stride correspond, but
that does not prove physical units or that fp and fp L mode numbers mean the
same sensor readout.

Current JSON consumes timing halfwords +4/+6/+8 and geometry words +4/+8/+44.
It assumes **72 MHz**, **6000 active columns**, **35.9 mm**, and fp-specific
padding and calibration to compute fps/readout/crop. None is established here
for fp L. Do not report those computations as measured frame/exposure times.
There is no need to invent an fp L Vd hook to port the currently active Base.
For a minimal recording-aware experiment retain raw mode id as diagnostic data
and leave calibrated timing/JSON claims gated until independently validated.

The unused exposure wrapper was inspected, not adopted: fp `C030C7F0` calls
`C0319E68` then `C0319F10`. Their fp L bodies correspond at `C031DF80` and
`C031E028`; the latter dispatches through sensor object +D0, slot +3C.
Several top-level wrappers share that short instruction shape, so this report
does **not** claim a unique fp L `EXPOSURE_FN` or its units. This is unnecessary
for today's Base and remains unresolved for a future exposure latch.

## Writer services: mapped versus not certified

The earlier loader/USB port already establishes static file manager, volume,
constructor/destructor/open/close bindings and allocator/cache services. Its
live file transfers are not recording-coexistence tests. This audit reruns the
following bounded correspondences, without invoking any service:

| Role | fp 5.02 | fp L 3.02 |
|---|---|---|
| manager / volume | `C0444658 / C0444698` | `C04408B8 / C04408F8` |
| ctor / dtor | `C0365E90 / C0365ED0` | `C03660A8 / C03660E8` |
| open / close | `C0365FB0 / C0366020` | `C03661C8 / C0366238` |
| write / seek / stamp | `C03660E8 / C03661E0 / C0369310` | `C0366300 / C03663F8 / C0369528` |
| thread create / attach / join | `C036E108 / C036E1B8 / C036E1F8` | `C036E320 / C036E3D0 / C036E410` |
| thread destroy | `C036E168` | `C036E380` |
| mailbox create / send / receive | `C01F88A4 / C01F8D48 / C01F8B74` | `C01F5124 / C01F55C8 / C01F53F4` |
| mailbox delete | `C0682FA4` | `C0680C54` |
| CameraMgrSetting singleton | `C0206E98` | `C0203B70` |
| live settings block getter | `C0207088` | `C0203D60` |

Write/seek/stamp, destruction and mailbox entries are **bounded prefixes**, not
full recursive filesystem/kernel audits. Thread destroy dispatches an indirect
destructor with r1=3 and optionally deletes the holder; indirect targets and
task quiescence remain a lifecycle proof obligation. The shared writer waits
for queued STOP, joins, deletes its mailbox, destroys the thread and closes
through the file destructor. An API-address match does not establish lock
ordering, cancellation, shutdown or media-removal behavior on fp L.

The settings singleton materializes fp L **C31F6A7C** (fp C31F865C), and the
live getter adds **40**. Base reads dimensions there and applies its own
bounds/padding. The getter match validates the address chain, not the meaning
of every dimension/format field.

Still unresolved for an **unchanged shipping Base**, even with these bindings:

* `take_path` directly uses fp SD/SSD path managers `C3438400/C3438398`,
  fields +8/+C/+10/+2C and the AutoRstFlg byte +5D5 of the settings pointer.
  The settings-pointer chain is mapped above; fp L manager identities and the
  reset/high-water arithmetic are **not validated**. Do not infer them from
  adjacent globals or name an fp L take using fp offsets without further proof.
* Camera format +4C, dimensions and DNG padding; cached lens name/focal fields;
  `F_LENS_INFO`, geometry query/free and distortion/focus tables. Base's live
  JSON path still consumes these. Context owner/get are mapped above, but its
  geometry consumer and output semantics remain outside this audit.
* Allocation descriptors, ownership of existing published pool, writer buffer
  layout, reachable veneers, cache publication, journal restoration followed
  by callback quiescence, and power-off/media lifecycle. Keep owned allocations;
  never use the embedded IMU image as a near-branch arena.
* Calibration: neither sensor period, scale, physical axes, frame clock nor
  first-exposure offset follows from instruction matching.

## Smallest next recording-aware shared-logger slice

1. Reuse the existing shared producer/drain and owned diagnostic state. The
   three candidate sites above are sufficient to investigate the **audio-file
   branch**; explicitly count START/STOP and skipped/duplicate/unpaired cases.
2. Keep the observation bounded and restore the exact stock extent, with a
   separately established reachable placement and in-flight lifetime protocol.
   First characterize events/mode ids and ring progress; do not synchronously
   create a writer or label them exposure boundaries merely because the fp
   shipping hooks do so.
3. Only then add the shared writer lifecycle and validate card/SSD naming,
   failure handling, repeated takes and shutdown. If JSON is temporarily gated,
   make that an explicit shared feature boundary in later work; this audit does
   not silently remove it from the definition of Base.

This narrows the binding problem without proposing a copied fp L logger or
enabling any hook. A successful finite idle drain is valuable evidence, but
does not settle these recording and lifetime questions.
