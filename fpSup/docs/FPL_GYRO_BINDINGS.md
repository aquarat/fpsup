# fp L 3.02 Base gyro: concrete idle-sampling bindings

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Shared producer milestone (offline)

`fp_usb_shell/asm/fpl_gyro_capture.S` now calls the actual shared
`gyro/gyro_drain.S`, with a diagnostic descriptor override in
`imu_stream.inc.S`. The fp default remains byte-identical (Base body 13,896
bytes, SHA-256 `5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38`).
This finite observer uses owned code/state/output, a payload-local descriptor
view, and twenty nominal 20-ms delays. It installs no producer hook or task.

Independent review and rerun: 12 ARM tests pass. They cover ABI/register
preservation, bounded writes, wrap, initial cursor, invalid and racing
publications, partial capacity, padding accounting, repeated entry reset and
a shared-source mutation. Equal heads after a whole lap deliberately produce
"no observed motion", not a false no-loss guarantee. A changed head during
drain invalidates the batch; earlier copied bytes remain diagnostic only.

The 840-byte synthetic-layout artifact has SHA-256
`1830a6d42266056991de2d7d80068c0b0563076bce1b310ad629433c8e436253`.
Its address-dependent hash is not a live deployment hash. The host runner
`fpl_gyro_capture.py` adds verified staging, exact five-word mutation masking,
output guards and echo restoration; the combined ARM/host suite passes 28 tests.

**Live follow-up:** the first finite capture copied 164 records using the shared
drain, then correctly stopped with `stale_during_drain` when the fourth
observation's head advanced during copying. Three observations completed;
padding errors and capacity drops were zero. Echo, code guards, output guards
and PONG verified afterward. This proves partial live producer execution, not
a complete, atomic or lossless capture. Exact evidence/hashes are in the
investigation log under "Shared gyro producer live trial".

2026-10-20, **offline static audit only**. The current Base producer and the
stock raw-ring accessor have concrete fp L counterparts. This is enough to
design a read-only idle snapshot; it is **not** a runnable Base port, a recording
test, or proof of fp L timing/scales/physical axes. No camera, card, download,
commit or production-source changes were made.

**Later live follow-up:** the main session's finite passive probe read the
expected descriptor/ring and accel cache on the idle camera. The full-ring copy
was correctly marked stale because its head advanced by two records. This
qualifies live address/layout availability only, not a recording port or atomic
sampling. See `FPL_USB_DIAG_2026-10-19.md`, "First passive IMU read".

## Inputs and reproduction

Read `FPL_PORT.md`, `FPL_ALLOCATOR_AUDIT.md`, `FPL_WORKER_STATE_AUDIT.md`,
`gyro/build_base_card.py`, `gsup_launch.S`, `gcsv_task.S`, both stream/task
includes and deployers, and the actual `accel_hook.S`/`gyro_drain.S` consumers.
Official MAINs load at `C0000000`:

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

```sh
ROOT=/path/to/firmware
python3 -B tools/fpl_gyro_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" \
  --self-test
# Optional --disassembly /private/new-file.txt; exclusive-create, firmware stays private.
```

Requires Python Capstone. Passed: **14 bounded normalized instruction matches**,
switch-table equality, hook-word checks, full embedded-image equality and its
ring-publication literals; **8 negative fingerprint cases** (first/code/last-byte
mutations and truncation for each image) rejected. Full hashes are checked before
creating output. The tool does not import the live deployers.

Method: ARM instruction-pattern search initially located the complete sample
routine, model constructor and motion loop; then call edges, materialized
globals, vtable entries and bounded ARM/Thumb disassembly established the map.
The reproducible tool checks the resulting bounded correspondences, not a global
uniqueness claim. It preserves register choices, memory offsets, normal immediates
and internal branch offsets; masks external branch targets and MOVW/MOVT
immediates and reports their actual operands separately. The tiny axis setter
has multiple identical matches: **its caller edges**, not its bytes alone, identify
it. No universal relocation delta is assumed. Matching code does not prove
the semantics of every external callee; the optional listing exposes those edges.

## Current producer, not historical comments

`build_base_card.EDITIONS['base']` assembles **`gcsv_task.S` with
`FPGYRO_EDITION_BASE=1`**, including the same writer core and producers as GCSV.
There is no current separate `ring_task.S` implementation. Preserve this design.

The deployer's opening description still names the old `C00D0794` gyro hook and
`C050D498` accelerometer hook. Its **actual `PRODUCERS` table** and assembly use
`C050D4C8`, after lock release. `accel_hook` calls `gyro_drain` first, then appends
the accelerometer record. It does nothing when `T_WANT==0`; simply arming the
shipping hook while idle will not produce a diagnostic stream. `DRY_RUN` suppresses
file operations, not all allocation/task/lifecycle effects. Do not use it as a
synonym for read-only sampling.

## Exact binding table

Addresses are instruction addresses; **Thumb callable pointers require bit 0**.
Names below are descriptive roles, not exported vendor symbols.

| Role | fp 5.02 | fp L 3.02 | Evidence / ABI |
|---|---|---|---|
| IMU model constructor | `C0043410` | `C0041020` | 0x178-byte normalized match; constructs both sensor drivers |
| MMA8452Q driver constructor | `C050D028` | `C0509290` | `(this, lock, bus-object, axis-mode)`; stores bus at +20, mode at +24 |
| Accelerometer cached getter | `C050D1E8` | `C0509450` | `(this, output-axis-objects)`; locks, copies cache, unlocks; does not fetch new data |
| Accelerometer sample routine | `C050D250` | `C05094B8` | `(this, output-axis-objects)`; entire routine corresponds, including switch table |
| Axis-value setter | `C050C5D0` | `C0508838` | `(axis-object, signed-value)`; stores 32-bit value at +0 |
| Cache/publish point (inside lock) | `C050D498` | `C0509700` | three `ldrsh` loads and calls to axis setter |
| Unlock call | `C050D4C4` | `C050972C` | both call `C00102D0` |
| **Current producer site** | **`C050D4C8`** | **`C0509730`** | `E3A02000`, `mov r2,#0`; success only, r4 still cache pointer |
| Old body-motion/GyroData loop | `C00D0738` | `C00CCFE8` | waits on firmware object, fetches processed values, feeds detectors |
| Old hook callsite | `C00D0794` | `C00CD044` | BLX to processed getter below; not a raw-sample callback |
| Processed gyro getter (Thumb) | `C01EC6F8` | `C01E8F78` | `(out_i32[3])`; reads floats at P+34/38/3C and converts; status 0/4/900 |
| **Raw ring accessor (Thumb)** | **`C01EC8C0`** | **`C01E9140`** | `(out_pair[2], out_ring_pointer)`; described below; no lock or allocation |
| Coprocessor pointer-publication callback (Thumb) | `C01EDE98` | `C01EA718` | r2=message pointer; publishes message+4/+8/+C, sets an event flag |
| Embedded-image load-once routine (Thumb) | `C01EDF18` | `C01EA798` | installs callback, copies/starts image; **not a sampling API** |
| TickTimer, microseconds (ARM) | `C002B6E0` | `C0029320` | `() -> us`; unique masked match; callees `C002B4E0/C002B440` ↔ `C0029120/C0029080` identical but for globals `C30781A4→C3076D98`, `C2EFABC8→C2F09408` (24 October). Used by the per-frame gyro block; not yet called live |
| Thread create / attach / join | `C036E108 / E1B8 / E1F8` | `C036E320 / E3D0 / E410` | bounded bodies match; not required for a host-read snapshot |

### Accelerometer objects and layouts

The model constructor uses a model-static block at fp `C307B4BC`, fp L
`C307A0B0`: image pointer/size at +0/+4, gyro driver at +8, accel driver at
**+28** (fp `C307B4E4`, fp L `C307A0D8`). It passes **axis-mode 5** to the accel
constructor in both images. This is a static initialization value, not proof
that no later mode change is possible.

Accelerometer driver: size **0x28** (destructor's sized delete); +0 lock pointer,
+4 enabled/status byte, +14 driver vtable, +18 embedded object, +20 bus object,
+24 axis selector. Vtable fp `C0CFC64C`, fp L `C0D0C930`: +20 cached getter,
+24 fresh-sample routine. The sample path calls through bus object's vtable
at +18, slot +10, requesting six bytes from register 1. Nonzero bus result
returns 1 without publishing. Success assembles big-endian signed 16-bit axes,
arithmetic-shifts each by 4, applies one of nine axis transforms, stores cache,
copies into the output axis objects, releases the lock, then returns 0.

Cache: fp **`C377790C`**, fp L **`C37772F4`**, three signed halfwords at +0/+2/+4.
Mode 5 is the direct x/y/z case in the matched switch; other cases permute/negate.
The output is **three 8-byte axis objects** at +0/+8/+10 (hex): value word +0,
vtable word +4. It is **not** a six-byte buffer. Calling the fresh routine would
perform device I/O and mutate stock caches; an initial read-only snapshot should
read the existing cache instead. Three independent reads are not an atomic
three-axis snapshot; cache reads alone also cannot distinguish repeated equal
samples from no new sample.

## Raw gyro: pointer chain and embedded producer

Global pointer **fp `C31E3FCC` → fp L `C31E23CC`** holds P. The processed getter,
raw accessor and publication callback independently materialize this address.
The callback takes P from `[r2+4]` only if the global is zero; neighbouring
globals at -4 and +4 similarly receive `[r2+8]` and `[r2+C]`. It then signals a
firmware event. This is initialization/publication, **not** a per-sample hook.

Raw accessor (`C01E9141` as a callable Thumb pointer):

```text
r0 = writable 8-byte output pair; r1 = writable 4-byte output pointer
P absent: return 4, outputs untouched
P present, either output NULL: return 900 (0x384), outputs untouched
success: out_pair[0] = [P+64], out_pair[1] = [P+68]
         *out_ring_pointer = [P+60]; return 0
```

It copies pointers/words, not samples, and does not validate the returned ring.
The meanings of P+64/+68 are **not established here**; do not call them length
or rate. For purely passive inspection the pointer chain can be read directly,
without executing this API. P+34/+38/+3C are processed float values; they are
not the raw signed-halfword ring.

The embedded image is **identical over all 0x6200 bytes**, fp `C072CA40`, fp L
`C072A4C0`. Its vector table and Cortex-M Thumb code establish the raw layout
independently of logger comments:

* Embedded local `04D6` loads P-local=`6004` (literal `05D8`). `04E2..04E8`
  stores ring-local=`644C` OR `2E000000` at P+60. Its message publishes the
  same aliased P. Expected CPU-visible P=`2E006004`, R=`2E00644C` follows from
  these instructions; **read the runtime pointers**, rather than hardcode them.
* Embedded `092C..09DC` produces samples. It clamps three converted values to
  signed 16-bit; combines two in a word and shifts the third left 16.
  `09AA` compares the word cursor against **0x4B0 (1200 words)**, resetting
  to zero at wrap. It writes two words after the ring header and publishes
  `(R_local + word_cursor*4) | 2E000000` at `[R_local]` **after** both stores.
* Thus R+0 is a published **address**, data is R+4, span **0x12C0 = 600 × 8**,
  total ring storage **0x12C4**. Each record has signed halfwords at +0/+2/+6,
  **zero padding at +4**. Base replaces padding with tag 0; its accel record
  uses the same layout and tag 1. These labels do not establish physical axes.
* After the first record head is R+8; at the final record it is R+12C0.
  It denotes the second word of the last completed record, not a direct pointer
  to the next data record. The shared drain correctly copies from old head+4,
  wrapping at R+4+12C0. A startup zero head must not be dereferenced.

The embedded local data at 6004/644C is **coprocessor runtime memory**, not
permission to use MAIN+6004 or the embedded image's zero area as scratch.
Static publication order is not a hardware cache/coherency proof. A repeated
head can mean no movement **or an entire lap**. At the fp-assumed ~2500 Hz the
ring laps in ~240 ms; fp L rate and worst idle observation gaps remain unmeasured.

## Initial read-only idle experiment boundary

For later separately authorized work: snapshot the global P, P+60/+64/+68,
R header/data and accel cache using existing read transport; validate nonzero
pointers, range, alignment and head progression before decoding. Read the head
around the data copy and retain both values plus host request times. Reject
inconsistent snapshots; this cannot prove zero loss or exact interleaving.
Do not start/stop/reinitialize the stock IMU or replace its callback to discover
whether it is already running. Missing P or a stationary head is a result.

Continuous idle capture needs a bounded observer integrated into the **shared**
producer/drain, with owned output memory, explicit cursor reset and error counts.
The shipping take gate and resource creation cannot simply be enabled to obtain
that observer. No camera-side observer is supplied by this audit.

## Critical unresolved dependencies for eventual shared Base

1. **No code cave.** The fp cave and `CAVE_BUMP=C072E060`/arena endpoint are
   inside IMU-owned image storage. fp L has no approved corresponding veneer
   arena. `gsup_boot` currently uses eight-byte near veneers because an ARM BL
   cannot reach ordinary USER RAM. A measured new hook address does not solve
   branch reach, preservation of displaced instructions, atomic publication,
   cache maintenance or unhook-while-in-flight safety.
2. **Pool ownership.** `gsup_launch` currently reads fp `C3757A7C`, assumes an
   existing pool is usable, copies to +44000, and loses its temporary allocation
   descriptor. fp L's publication is `C37588BC`; its worker has pool-relative
   state. Reuse must check capacity/identity/layout and not overwrite worker,
   staging or swap storage. Keep state in owned allocations, not adjacent BSS.
   Follow the allocator audit's descriptor/free contract; no self-free.
3. **Lifecycle.** Idle mode changes, playback, repeated bootstrap, IMU stop/load
   and power-off can invalidate pointers/cursors or stop callbacks. Need observed
   initialization/teardown ordering and hook restoration before freeing code or
   buffers. Existing loader journals do not alone prove callback quiescence.
   Autonomous reboot/power-off remains unresolved in the current port record.
4. **Recording is intentionally unmapped here.** START/STOP sites, path managers,
   settings/metadata/lens accessors, mailbox services, all writer/thread teardown
   calls and allocation lifetime need their own complete binding/lifecycle audit.
   Three matched thread wrappers are not a recording certification. Base still
   writes metadata JSON and includes dependencies beyond raw gyro production.
5. **Calibration is not portable evidence.** Do not inherit fp's period
   `400085400 ps`, gyro scale `0.000137923`, accel scale `2^-10`, orientation
   `xyz` (negations), callback-gap measurements, or video timing as fp L facts.
   Identical embedded code and matched accel initialization support a hypothesis;
   physical mounting, clock rate, configuration, bias, axes and motion response
   need live measurement. File-format compatibility does not validate values.
6. **Source/comment drift.** Current Base emits a 20-byte header; old README
   text and `ring_task.inc.S` describe 64 bytes. The deployer retains obsolete
   fixed-cave reset/rate paths. Use actual shared source/edition flags and a
   firmware profile, not copied scripts or historical addresses. Production
   changes and build-contract verification belong to the subsequent port slice.

**Conclusion:** the concrete fp L passive-read targets are `C31E23CC` (gyro
descriptor pointer), its +60 ring pointer and `C37772F4` (accel cache). The future
shared producer's candidate success site is `C0509730`. None of these static
bindings establishes live idle availability, lossless timing, physical axes,
record association, or safe executable placement.
