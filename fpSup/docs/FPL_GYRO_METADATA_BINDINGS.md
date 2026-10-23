# fp L 3.02: live Base metadata dependencies (offline)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Later passive live observation

The separate `fpl_metadata_snapshot.py` probe passed 13 offline tests and one
live trial. Both construction guards were 1 before/after; raw width/height were
3840/2160, format 0, focal 1050. Exactly 32 lens-name bytes were captured without
a NUL, correctly reported as limit-reached. No extra bytes were read to find a
terminator. Field units and cache freshness/coherence remain unverified.
Code/result guards, stock echo restoration and subsequent PONG passed. Evidence
and hashes are recorded under "Passive metadata snapshot" in the investigation
log. The static audit below remains separate from this limited live evidence.

2026-10-20. **The JSON is not a harmless descriptive header: current Base calls
geometry allocation/free, lens-cache access, focus virtual methods and a
distortion fit. Several ABIs now have concrete fp L counterparts, but the
unchanged JSON and binary header are not fp L calibration-valid.** A diagnostic
port should omit the Gyroflow lens profile and record explicitly raw metadata.

Scope: only this document and `tools/fpl_gyro_metadata_audit.py`. No firmware,
card, production source, device, API, commit or deployment operation. Read with
[recording bindings](FPL_GYRO_RECORDING_BINDINGS.md),
[path bindings](FPL_GYRO_PATH_BINDINGS.md) and [IMU bindings](FPL_GYRO_BINDINGS.md).
This is a metadata supplement, not a new claim about loader/hook safety.

## Reproduce and interpret the evidence

Official decompressed MAIN images, CPU base `C0000000`:

| Image | Bytes | Full SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

```sh
ROOT=/path/to/firmware
python3 -B tools/fpl_gyro_metadata_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" --self-test
```

Requires Capstone; missing images/dependency fail. The tool emits **31 bounded
ARM correspondences**, every instruction/operand in those bounds, exact checks
on selected direct calls and materialized singleton addresses, and **17 negative
cases**. Eight negatives change first/code/last byte or truncate each image.
Five deliberately bypass fingerprints and test field displacement, internal
branch, external call, singleton literal and MOVW field-constant checks.
Three more mutate Base's source-relative reads/constants to catch double-offset
or block-relative format mistakes; one replaces the singleton's static-address
return with a pointer dereference. The audit reads (never imports/executes) the
three Base source files and reports their SHA-256 values alongside the checked
source-to-ABI field table. Guard acquire/release bodies are compared too.

Discovery used instruction-pattern searches over the actual images followed by
callee/literal inspection. No address was obtained by applying a neighboring
symbol's delta. The shared normalizer preserves registers, memory displacements,
ordinary constants and internal branch destinations; it masks external branch
targets and MOVW/MOVT immediates. Selected masked values get explicit checks;
the full hashes cover all remaining bytes. The emitted listing makes unpinned
masked values visible. Bounded windows are not recursive callee validation.

**Ambiguities were real:** the 16-byte focus wrapper alone has 122 fp L matches;
the 32-byte distance wrapper has 37. The full 0xE0 wrapper cluster and the
position/distance dispatch bodies disambiguate them. The correction singleton
shape has two candidates: only `C0043ED8` calls the matching constructor
`C0046C30` and uses the checked base `C307A81C` and size/slot `74B4`.
Generic geometry smart-pointer destruction has two matching implementations;
the native caller window identifies `C022C028`, while the query itself calls
the equivalent local implementation `C0438A40`.

## What is actually live

Source references refer to the current checkout, not historical profilegen:

* `gyro/gcsv_task.S:200,366–444,787–788`: Base writes its 20-byte binary header,
  then calls `gcsv_json_write`; JSON and distortion sources are included.
* `gyro/gcsv_json.S:422–509`: `j_dims` first performs a kind-2 geometry query;
  only if that produces no plausible dimensions does it read settings.
* `gyro/gcsv_json.S:531–551`: dimensions, sensor mode, cached lens name/focal,
  then **`pg_dist_focal` overrides the nominal focal** if plausible.
* `gyro/gcsv_json.S:614–656`: computes readout/fps/crop/focal-pixels and calls
  **`j_dist_prepare` / `j_dist_emit`**. The opening prose saying coefficients
  are zero and that everything is integer-only is stale.
* `gyro/gcsv_dist.S`, `gyro/distfit.inc.S:32–72,128–223`: focus-position and
  distance calls, direct correction-memory reads, interpolation, VFP doubles,
  magnification adjustment and the local fit are live. Local math is not a
  new firmware entry-point dependency. VFP execution/context remains relevant.
* `gyro/gcsv_json.S:695–752`: a second file object at log-object page +800,
  `clip_path('j')`, manager/volume selection or SD fallback, ctor/open/write/dtor.
  These path/file dependencies remain live even for a raw-only replacement.
* `gyro/gcsv_task.S:306–315`, `gyro/ring_task.inc.S:243–246,372–373`:
  `SETTING_FORMAT = 4C`, `FORMAT_CDNG = 0` controls sidecar folder nesting;
  dimensions are **singleton-relative** +40/+44 (live-block-relative +0/+4);
  format +4C is live-block-relative +C. Fallback adds **16/10** unconditionally.

Thus settings **format** is a path dependency, not an input used to change the
JSON's hardcoded `CinemaDNG` label or to condition its dimension padding.
`EXPOSURE_FN` is not a current JSON dependency. Base does not acquire exposure
timestamps merely by calling these metadata functions.

## Concrete callable bindings and accessed fields

All addresses in this table are ARM, no Thumb bit. Offsets are hexadecimal.

| Role | fp 5.02 | fp L 3.02 | Evidence / accessed fields |
|---|---|---|---|
| Settings singleton | C0206E98 | **C0203B70** | returns static object C31F865C / C31F6A7C directly, not a pointer loaded from it |
| Settings constructor | C0206D98 | **C0203A70** | calls context owner/get, copies 5E4 bytes to object+40 |
| Settings live block | C0207088 | **C0203D60** | returns object+40 |
| Context owner/get | C0021C00 / C0021C40 | **C0021B20 / C0021B60** | base C3075194, pointer at +5C, not the context bytes themselves |
| Sensor current-mode wrapper | C032C720 | **C032C7C0** | raw mode id; selector argument 0 |
| Timing / geometry row | C0320FC8 / C0321028 | **C03250E0 / C0325140** | timing u16 +4/+6/+8; geometry u32 +4/+8/+44 |
| Lens cache accessor | C03341C8 | **C03343E0** | returns **C3465794** (fp C3464980) |
| Lens cache constructor | C03341A0 | **C03343B8** | initializes cache; accessor is not simply an unconditional pointer return |
| Lens refresh | C0334208 | **C0334420** | invokes mapped name/focal producer; not called by Base |
| Name/focal producer prefix | C03344B0 | **C03346C8** | 60-byte copy to +24, NUL at +60; parsed word stored at +68 |
| Focus position wrapper | C035FD48 | **C035FF60** | owner then position dispatch |
| Focus distance wrapper | C035FE08 | **C0360020** | preserves incoming position, passes as r1 to distance dispatch |
| Focus owner / ctor | C0360128 / C03600E8 | **C0360340 / C0360300** | owner C3480880 (fp C347FA6C); +0 backend pointer, +4 sentinel |
| Focus position dispatch | C0360160 | **C0360378** | backend object's vtable slot **B4** |
| Focus distance dispatch | C03602F8 | **C0360510** | backend object's slot **A8**; sentinel result becomes 7FFFFFFF |
| Geometry query | C0437140 | **C0437358** | (&out, kind=2, live context, selector=3) |
| Query context prefix | C0436B80 | **C0436D98** | first 1E0 bytes, including kind-2/context+C selection |
| Query result allocate | C0438B60 | **C0438D78** | allocates **C0 bytes**, pointer written through output holder |
| Query result construct | C0438A78 | **C0438C90** | installs dispatch pointer at result+BC |
| Query result move | C04386B0 | **C04388C8** | transfers pointer and clears source holder |
| Query result free | C022EDB0 | **C022C028** | (&holder,2); pointee+BC table slot +8, r1=3 |
| Query's local free | C0438828 | **C0438A40** | same bounded destructor shape; used on temporary holder |

### Settings, query dimensions and cache semantics

The singleton materializes **C31F6A7C into r4** at C0203B74/C0203B78 and
returns it with **`mov r0,r4` at C0203BB0**. There is no final `ldr r0,[r4]`:
the address denotes the static object, not a pointer-publication word. Its
constructor is lazy, so calling the accessor can construct that object.

The constructor's actual fp L calls at **C0203AA0/C0203AA4** obtain the context;
**C0203AAC–C0203AB4** copy 5E4 bytes to **singleton+40**. The live-block getter
`C0203D60` takes the singleton pointer and returns **singleton+40**.
But **Base `gcsv_json.S:485–492` calls the singleton accessor directly**, then
adds `SETTING_DIMS=40`. It does **not** call the live-block getter first.
Similarly `gcsv_task.S:308–313` reads singleton+`SETTING_FORMAT=4C` directly.

| Raw field | Singleton-relative | Live-block-relative (copied context-relative) | fp L address |
|---|---|---|---|
| width | +40 | +0 | **C31F6ABC** |
| height | +44 | +4 | **C31F6AC0** |
| format | +4C | +C | **C31F6AC8** |

These are two descriptions of the **same** words. Adding +40/+44/+4C to the
getter's returned live block would double-add 40 and read the wrong fields.
The audit checks the actual Base source sequence, singleton literal and direct
return, and the getter's +40 transformation together. This supports only the
named raw fields, not equality of all state structs. Settings are a managed
copy; this does not establish that they are the current encoded raster, or
atomic with the sensor/lens snapshot.

The query context prefix reads context+0/+4 into its descriptor+0/+4;
kind 2 and context+C==0 select context+8 rather than +24. Other accessed context
fields in this bound are +14, +1C/+20, +AC, +180/+184, +334/+33D,
+394/+39C/+3AC/+3B0, +58C/+594/+598/+59C and +5B4. They are local code
correspondences, **not a declaration that fp/fp L context layouts are globally
identical**. The query then follows a selector and indirect dispatch
`[[selector+8]+14]`, builds its result and transfers ownership.

Base reads result words +0/+4 and releases the holder with flag 2, including
the null-result case. The native matching caller's exact free call is **C04377B4** with
`r0=sp+4,r1=2` immediately preceding it. (See the emitted
`geometry_free_caller_window` for the full ordered window.) The destructor
dispatches through result+BC, slot +8, with r1=3; flag 2 does not delete the
stack holder itself. Allocation/free ABI is mapped, but the selector's virtual
implementation, successful kind-2 raster for every mode and runtime lifetime
are not recursively certified here. The existing fp observations in the source
comments are not fp L observations. Prefer no query in the smallest diagnostic.

The lens accessor materializes cache **C3465794** and guard **C3477208**.
The matched native producer copies **3C bytes** into cache+24 and terminates
at +60; Base copies only the first **32** bytes and trims spaces. The nominal
focal word is cache+68 = **C34657FC**. At fp L **C0334738–C0334770**, the
copy destination and parsed focal store are explicit. This proves those cache
locations, not a whole lens-state layout or the optical accuracy/units of a
reading. Base's JSON emitter also does not escape quotes/backslashes in lens
names. A diagnostic string should be bounded and JSON-escaped.

The focus wrappers are **not established bus-free**: their downstream methods
are virtual. Owner construction itself calls the backend accessor and slot 80
to get its sentinel. The distance adapter's **7FFFFFFF** sentinel is different
from Base's threshold **07FFFFFF**; preserve that distinction when analyzing
its infinity heuristic. Method shape does not prove units, latency, locking or
that it is safe to call synchronously from a recording callback.

## Correction cache: mapped storage, not transplanted calibration

New concrete correspondence:

| Role | fp | fp L |
|---|---|---|
| Correction owner | C00467B0 | **C0043ED8** |
| Owner base literal | C307BC38 | **C307A81C** |
| Constructor | C0049590 | **C0046C30** |
| Update body | C00495C0 | **C0046C60** |
| Single-source population | C0053010 | **C0050648** |
| Store four doubles | C0047298 | **C0044938** |

This is address-and-field evidence, not an assumed common data relocation:

1. Owner accessor calls the matched constructor and materializes its own base.
2. Update at fp **C0049660/C0049670**, fp L **C0046D00/C0046D10** explicitly
   forms **owner+11B8** and passes it in r2 to the matched population body.
3. That body stores parsed focal words at block+4*i; axis words at block+3C
   plus 4*index; three groups of four doubles at block+480/+4A0/+4C0 plus
   **96*index**. The 0x30-byte store routine writes d0..d3 at +0/+8/+10/+18.
   The population body explicitly computes a rounded `2^24 / value` axis.
4. Therefore corresponding **first-block locations** used by current Base are:

| Source constant | fp | fp L corresponding storage |
|---|---|---|
| DIST_FOCAL | C307CDF0 | **C307B9D4** = owner+11B8 |
| DIST_AXIS | C307CE2C | **C307BA10** = block+3C |
| DIST_TABLE | C307D270 | **C307BE54** = block+480 |

**Do not substitute these three addresses and call the fit validated.** Native
population is multidimensional: counts at block+5A00/+5A01/+5A02 and a plane
count 3 at +5A03 drive indexing. Base reads only one focal word, exactly five
axis entries and five three-plane nodes. The native body does not establish
that this slice is the active zoom/aperture/focus slice for every lens. Its
alternate two-source population branch, lens-present/cache freshness, plane
interpretation and the DNG opcode correspondence are not fully audited here.
The locations are RAM, outside file-backed MAIN: no runtime coefficient, axis
value or focal calibration was extracted or copied from these images.

## Smallest diagnostic metadata and exact remaining gates

**Smallest useful subset:** an explicitly diagnostic record with firmware/image
identity, raw sensor mode id, raw sample counts/tags and lifecycle counters.
No lens-profile JSON is required to observe recording-aware raw IMU collection.
Optional additions after initialization checks: raw settings width/height/
format and bounded cached lens name/nominal focal, with `units: "unknown"` and
source-field labels. They require no geometry allocation, focus virtual call,
correction interpolation or firmware bus transaction from the metadata path.
These are design recommendations, not production edits made by this audit.

Do not label raw settings dimensions as the encoded raster; do not label a
nominal focal word as measured/calibrated optics. If timing/geometry rows are
later logged, retain their raw fields and mode id: unknown ids fall back to
row zero, sentinel 77 means current mode, and row contents are runtime data
(see the recording audit). Sampling several managers is not an atomic snapshot.

### Next passive diagnostic: design only, no constructing calls

The next probe may add the following fixed-address reads, **without calling any
firmware accessor**, including the settings/lens singleton accessors. No geometry
query, focus conversion, refresh, allocation, free, distortion read or calibration
belongs in this subset. The implementing session must establish its read context
and firmware identity; this document does not implement or deploy that probe.

| Group | Construction guard (u32) | Raw payload, only when guard permits |
|---|---|---|
| Settings | **C31F70B0** = singleton C31F6A7C+634 | u32 width **C31F6ABC**, u32 height **C31F6AC0**, u32 format **C31F6AC8** |
| Lens cache | **C3477208**, independently materialized by C03343E0 | at most **32 bytes** from **C34657B8** = cache C3465794+24; u32 focal **C34657FC** = cache+68 |

Guard evidence: singleton code passes its guard to `C0013090`, then calls its
constructor only if that routine returns nonzero, then calls `C00131E4`.
The audited acquire body compares the **whole first word to 1**, not merely
bit zero. Release stores **1** to that word on both inspected paths. The lens
accessor returns the static cache with `mov r0,r4` at C0334418 as well.
No pointer should be loaded from either static object base to locate these fields.

Per-group bounded snapshot procedure:

1. Read and retain `guard_before` as u32. If **0**, emit status
   `not_ready`; if **neither 0 nor 1**, emit `initializing_or_unknown` with
   the raw word. In either case omit that group's payload; do not initialize,
   wait, poll or repair it. Only **exactly 1** permits payload reads.
2. Apply the implementation's acquire/read ordering (on this ARM target, an
   appropriate memory barrier), copy the fixed payload once into probe-owned
   storage, then order reads before taking `guard_after`. Do not call the guard
   functions: acquire can lock/construct and release would mutate firmware state.
3. If `guard_after != 1`, discard the copied payload and report `guard_changed`.
   Otherwise report `constructed_cache_observed`, **not** `valid_lens`,
   `fresh`, `recording_raster` or `atomic_snapshot`. Store both guard words.
   A construction guard does not protect later settings updates/lens refresh;
   even two equal guard reads cannot exclude a torn payload or changes between
   groups. No retries are required for this passive diagnostic.
4. Preserve width/height/format and focal as **raw unsigned words**, with
   `units: "unknown"`, `calibrated: false`, and the exact field addresses.
   No 16/10 padding, scaling, enum reinterpretation, focal conversion or
   plausibility-based substitution. A zero focal/name must remain an observed
   empty cache, not proof that no lens is mounted.
5. Bound name reads to the first 32 bytes (Base's limit, not the producer's
   full 60-byte field). Record the byte length, whether a NUL was seen, and
   `limit_reached` if no NUL occurs in the bound. Prefer raw bytes as hex plus
   an optional escaped display string; do not assume UTF-8 or read further for
   a terminator. If displaying trimmed spaces, retain the original bytes too.

Proposed record fields are `firmware_identity`, `settings_snapshot` and
`lens_snapshot`; each group includes `status`, `guard_address`, `guard_before`,
`guard_after` when sampled, and `consistency: "unverified"`. Accepted payloads
carry the raw fields above and `units: "unknown"`. This deliberately records
cache observations, not a Gyroflow lens profile or calibrated stream header.

Unchanged shipping Base remains blocked by these **specific** metadata issues:

* **Physical sensor calculations:** 72 MHz; 6000 active columns; 35.9 mm;
  zero binning→1; covered-width cap; mode-number interpretation; readout
  direction `TopToBottom`; fps/readout formulas and no zero/overflow issues
  across fp L modes. ABI correspondence proves none of those numeric inputs.
* **Raster/format correctness:** kind-2/selector-3 virtual query chain and actual
  returned dimensions; fallback's unconditional 16/10 padding and bounds
  640×360..8192; hardcoded CinemaDNG text even for other formats. Raw settings
  field correspondence is not a validated per-mode raster contract.
* **Lens/calibration:** nominal focal units and cache validity, exact active
  correction slice/counts, alternate population path, plane choice, infinity
  and distance interpretation, focus backend locking/latency, and fp L optical
  validation of the local fit/magnification model. The existing fp 40 mm lens
  measurements and coefficients are not transferable calibration evidence.
* **Binary-header calibration:** `gcsv_task.S:366–444` embeds sample period
  400085400 ps, gscale 0.000137923, ascale 2^-10 and orientation `xyz` (negated
  axes). Record layout and identical IMU code do not measure fp L clock drift,
  sensitivity or body-axis alignment. Omitting JSON alone does **not** make
  that unchanged header calibrated. A diagnostic reader must explicitly treat
  counts/index as raw rather than silently trust these constants.
* **Output claims and lifecycle:** change hardcoded `fp`, `sigma_fp_mode`,
  `calibrated_by` claims before an fp L deliverable; verify escaping/buffer
  bounds, query object ownership and call context, snapshot consistency and
  file-write failure handling. Hook-installation/quiescence and all-mode take
  gating are separate unresolved gates in the recording/IMU audits.

No uishare/v3 dependency was added. No equality of complete sensor, lens,
settings or correction state is claimed.
