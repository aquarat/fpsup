# fp L 3.02 Auto ETTR / timelapse deflicker groundwork

2026-10-26. **Offline reference implementation and static integration audit.
Not an in-camera feature or a bootable product.** All changes are confined to
`fpSup/ettr/` and this document. No camera, daemon, deployment, reboot, shared
loader/UI or slit-scan source was used or modified by this work.

## Implemented and tested

`ettr/core.py` implements:

1. Full-frame linear RAW statistics, normalized independently as
   `clamp((DN-black[c])/(white[c]-black[c]), 0, 1)`. No WB, JPEG or tone curve.
   R/G1/G2/B stay separate. For each channel of N samples, discard exactly
   `floor(N*ignore_fraction)` largest samples; protect the next-largest value.
   Take the maximum tail across channels. Report clipped counts even when the
   ignore allowance intentionally permits clipping. Zero ignore protects all
   samples, including hot pixels; there is no hidden hot-pixel suppression.
2. `correction_EV = -log2(max_channel_tail) - reserve_EV`. Black/unavailable
   measurements hold exposure. Saturation means the true excess is unknown;
   repeated bounded recovery is required, not a claimed exact one-shot solution.
3. A next-exposure planner over caller-supplied shutter and ISO tables, preserving
   aperture. It chooses the brightest allowed non-overshooting pair, preferring
   lowest ISO when equivalent. Reports photon EV (shutter), gain EV (nominal ISO),
   remaining error and blocked/quantized/recovery state separately. ISO is not
   photon exposure and its gain ratio is a model, not fp L calibration.
4. Start-to-start interval budget: `shutter <= interval - overhead`. Overhead
   must include measured readout, RAW write, metering, setter latency and settling;
   the default two seconds is a planning placeholder. An impossible interval or
   already-outside-budget current exposure is rejected, not silently scheduled.
5. Bounded per-frame EV changes, asymmetric fast downward response, absolute-target
   smoothing without integral windup, deadband and strictly increasing frame IDs.
   Every decision uses supplied **actual** exposure, never assumes a previous plan
   was applied. Mode/generation changes require a new controller; aperture changes
   are rejected. Native ownership and asynchronous acknowledgements remain the
   future adapter's responsibility.
6. Post deflicker: fixed percentile target, or a centered moving mean of scene EV
   after removing shutter/nominal ISO. The latter retains slow light ramps while
   removing discrete exposure steps. Bounded corrections have explicit limit flags.
   No method can recover clipped detail or reliably distinguish composition changes
   from illumination using a single global percentile.

`ettr/dng.py` and `python -m fpSup.ettr` provide a read-only DNG adapter, nominal
EXIF exposure, SHA-256 association, JSON plans and optional XMP Exposure2012 hints.
LibRaw unpacks/linearizes CinemaDNG first; metering `tifffile.asarray()` directly
would instead use the fp L 8-bit companded codes. The exact DNG DefaultCrop is
applied relative to ActiveArea, preserving odd-origin CFA alignment. The test
fixtures have padded 3856x2170 rasters and a 3840x2160 default crop at (8,5).
LibRaw's own even-aligned crop reported (8,6)/3840x2159 on one fixture, so it is
not substituted for the DNG rectangle.

Levels are LibRaw's unpacked-domain black/white; fractional DNG black values can
be rounded by LibRaw. The report includes DNG BaselineExposure but does not bake
it into the RAW-relative correction. RAW-developer defaults/tone curves require
rendered validation. Outputs are created only in a fresh explicit directory;
existing RAWs or sidecars are never overwritten. Ordered frame inputs and known,
positive manual EXIF exposure/aperture are required by this initial adapter.

### Verification

From the repository root:

```sh
PY=python3  # environment with numpy, rawpy and tifffile
"$PY" -B -m unittest -v fpSup.ettr.test_core
python3 -B -m fpSup.ettr.audit_firmware \
  --main /path/to/firmware/FPL_V302/MAIN.bin \
  --self-test
```

**Result: 26 behavioral tests passed**, plus the fingerprinted firmware audit's
eight command bindings and seven negative cases. Two additional in-memory
algorithm mutations were caught by the relevant behavioral tests: replacing
maximum-channel protection with minimum-channel protection, and removing interval
shutter filtering. The source files were not changed for those mutations.

The controller/DNG adapter received a separate review and rerun of the 26
behavioral tests and firmware self-test; all passed, including the seven
negative firmware cases. The mutation checks and real-DNG smoke results below
were recorded during the original implementation validation.

The behavioral suite covers analytic channel calibration, isolated red/green
highlight protection, exact ignore boundaries, tiny highlights, black/nonfinite
frames, actual-setting validation, interval exhaustion, ISO ceilings, bounded
recovery, hysteresis, scene transitions, closed-loop convergence, unapplied-plan
repetition, stale frames, immutable aperture, exposure-step removal, gradual scene
ramps, invalid sidecars, crop geometry and no-overwrite output behavior.

Read-only real-DNG smoke inputs are two external slit-scan frames,
`000001.DNG` and `000002.DNG`. SHA-256:

- `48d3896d3b1457530451ce9bbc00501344098fcf86a6556ffc12c141e0a2f585`
- `b2fadf425da3e2162bae5ed7e97ec888a10a90b92de723689bf66142c2345257`

Their median is below black, and default deflicker correctly refuses it. Explicit
90th-percentile metering produces corrections +1.51419742 and +1.58458675 EV,
and JSON/XMP sidecars. With an explicit short-shutter table and 0.5 EV maximum
upward step, both nominal next-shot plans choose 1/2500, ISO100, f/2.8 from
1/3200 (a +0.356144 EV shutter step). The original source hashes still match.
This tests decoding and output, **not** a representative timelapse or camera-loop
result. These files were captured by the USB slit-scan workflow; EXIF
1/3200, ISO100, f/2.8 is nominal, not calibrated effective slit-scan exposure.

## Concrete fp L native seams

The audit reads the official decompressed MAIN at base C0000000, 49,310,208 bytes,
SHA-256 `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
It validates command-name/table/handler links, setter/getter calls, argument
registers and selected histogram/interval instructions. Seven negative cases
reject two image mutations and five structural mutations **with the fingerprint
check bypassed**. This is static disassembly, not Unicorn or runtime verification.
No fp 5.02 address delta was used to derive these bindings. DATA was not needed
for the bounded MAIN findings; runtime initialization/state is not thereby proved.

### Exposure/drive/interval settings

All addresses below are ARM entries. Common owner accessor: **C0055120**.
Ordinary shell setters call `(owner, value, 1)`; the final flag's broader semantics
are not established. Shutter calls `(owner, numerator, denominator, 1)`.

| Command | Handler | Setter | Getter |
| --- | --- | --- | --- |
| SetExpMode | C03FAD18 | C00559D8 | C0055A10 |
| SetShutterSpeed | C03FAE68 | C0055BA0 | C0055BE8 |
| SetIso | C03FB378 | C0056158 | C0056190 |
| SetDriveMode | C03FB7B8 | C0056470 | C00564A8 |
| SetIntervalRecHour | C03FB898 | C00565A0 | C00565D8 |
| SetIntervalRecMin | C03FB908 | C0056638 | C0056670 |
| SetIntervalRecSec | C03FB978 | C00566D0 | C0056708 |
| SetIntervalRecNum | C03FB9E8 | C0056768 | C00567A0 |

The shutter getter has a **hidden result buffer**: shell uses `r0=sp`, `r1=owner`,
then prints two words from the stack. It is not a scalar-return getter. Hour,
minute and second shell arguments are truncated with UXTB before the setter;
do not send unvalidated large integers. Config setters go through native property
objects, not direct sensor registers; their `OK` print does not establish accepted
sensor state. Getter readback and later frame-correlated sensor state are required.

Prior camera evidence in [FPL_SLIT_SCAN.md](FPL_SLIT_SCAN.md) and
`fp_usb_shell/fpl_slit_scan.py` shows the shell path accepting mode 1, rational
short shutter and fixed ISO in **UHD CinemaDNG CINE**; it verifies readback and
`imager mode_now`. That is evidence for that mode/context, not a native ETTR task,
STILL exposure, long shutter, interval timing or every ISO step. The previous
fp-only research's setter limitations do not override this newer fp L evidence.

### Native interval/still support exists; start/finish contract remains open

- MAIN contains `XC_StillRecFunc` RTTI at C0BC13BC and
  `XC_StillRecIntervalTimerObs` at C0BC3900. Its associated virtual entry at
  **C0BC38EC points to C0399B48**.
- C0399B48 reads/decrements a two-word state fetched through C00178D8/C0017AC8,
  writes it back via C0017E38, and on a zero path builds a 0x168-byte event with
  **+4=0x2E, +0xC=0xA**, then calls **C0388BA8 → C03A9798**. This is a concrete
  timer-to-native-recorder-dispatch seam to investigate, **not an approved call
  recipe or a proved still-capture request/completion API**.
- Embedded UI expressions at C2DA0150/C2DA0310 test `driveMode == 6` when showing
  interval count. This supports a candidate interval enum; legal transition,
  remaining drive-mode values and start semantics need confirmation.
- `GIMBAL_StartStillCapture` / `GIMBAL_StopStillCapture` strings exist at
  C0D052C8/C0D052E4. No callable binding is claimed from those names alone.
- No native still RAW-frame lifetime, shot filename/close notification, busy/error
  state or interval start/stop API has been verified here. Do not substitute a
  CINE record-button toggle or CinemaDNG frame export for native STILL capture.

### RAW histogram/data and sensor exposure

**The display histogram is the wrong sensor.** fp L
`HistogramDataProviderRec`'s virtual slot at C2E07CD8 points to **C059F270**,
which fetches a descriptor through **C0423E60 → C0424040**. The adjacent histogram
routine **C059F378** uses a four-byte pixel stride (`lsl #2`) and **byte** sample
loads at C059F414 into bins. This corroborates the old fp rendered-image finding
on actual fp L bytes; it does not supply Bayer RAW clipping statistics.

The prior fp-only design is
`research/imx410/SIGMA_FP_AUTO_ETTR_GAIN_AR_RESEARCH_2026-08-31.md` and its sparse
RAW overlay core is `research/display/raw_false_color_core.c`. Neither its
IMX410 gain tables nor fp absolute addresses establish fp L calibration. Sparse
overlay sampling can miss tiny highlights; this offline implementation uses
every cropped RAW sample. A native bounded full-tail scan/histogram worker needs
a verified completed-frame descriptor and lifetime, format/packing, CFA, stride,
black/white values, cache visibility and exposure attribution first.

Existing fp L sensor audit [FPL_SENSOR_TIMING_FEASIBILITY.md](FPL_SENSOR_TIMING_FEASIBILITY.md)
maps **C0328A08 `setShutter_Async`**, conversions C0328B78/C0328CE8, and downstream
MMIO/packet paths. It is not a general safe actuator API. Prefer mapped settings
setters plus accepted-value readback over independent sensor register writes.
The live slit-scan evidence shows why a stock shutter number alone is insufficient
when row timing changes. Never let two controllers own exposure/timing concurrently.

## Magic Lantern functional reference

Reviewed 2026-10-26; algorithmic inspiration, no ML code copied:

- [ETTR guide](https://wiki.magiclantern.fm/ettr): shutter/ISO adaptation preserves
  aperture; Always-on updates the next shot, Auto Snap can take another shot,
  on-demand live view meters before capture.
- [Actual ettr.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/dev/modules/ettr/ettr.c):
  RAW percentile/highlight-ignore targeting, max-RGB or optional clipping
  projections, bounded shutter and ISO, interval minus overhead, exposure-settle
  waits, clipped-tail recovery, and optional SNR/dual-ISO logic.
- [Post Deflicker help](https://wiki.magiclantern.fm/camera_help_cc#post_deflicker)
  and [module](https://github.com/reticulatedpines/magiclantern_simplified/tree/dev/modules/deflick):
  percentile-based development correction saved as XMP/UFRaw, commonly median to
  -4 EV. Fixed-percentile normalization also flattens deliberate lighting changes.

This implementation deliberately protects every CFA channel; it does not expose
ML's green/any-channel clipping relaxation or claim SNR/dual-ISO optimization.
Our ignore fraction is **per channel**, not ML's per-pixel RGB projection.
Quantile and default reserves must be presented with that distinction in the UI.

## In-field integration still required

1. Add ETTR Off / Meter / Next-shot / Timelapse and deflicker Off / Fixed target /
   Scene trend controls via the existing composable native UI. Display RAW-valid,
   clipping/ignored fraction, limits, settle/busy, next shutter/ISO and residual EV.
   Expose reserve, highlight ignore, fastest/slowest shutter, ISO bounds, interval
   and measured overhead, smoothing, percentile and correction bound. Aperture is
   shown but never actuated by this controller. Enum/value validation must use
   the current mode's actually accepted native settings.
2. Establish manual exposure/ISO ownership and native still/interval start, cancel,
   busy, error and durable shot-completion events. Preserve user aperture; pause
   on user settings/mode changes rather than fighting stock AE. Reject brackets,
   auto ISO, unsupported bulb/continuous drive and uncalibrated timing combinations
   until their contracts are proved.
3. Meter completed RAW or demonstrably exposure-equivalent live RAW; correlate
   frame sequence, exposure generation and actual shutter/ISO. Do heavy work in
   the existing resident-task model, not Vd IRQ or the loader entry. Sensor gain/
   conversion changes require new black/white and response calibration.
4. Apply one bounded plan between shots; read back accepted settings and wait for
   proven settle/frame attribution. Re-meter on ambiguous acceptance; never retry
   capture toggles blindly. Interval deadline misses must be explicit skip/stop
   outcomes, with no accumulating queue of old exposure requests.
5. Write shot-associated correction metadata after the actual capture, using the
   same frame's statistics and durable native file naming. Confirm XMP behavior
   in a target developer, then validate a daylight-to-night timelapse, highlights,
   moving subjects, user cancel, card-full/write errors and power-off cleanup.
6. Port/reference-test the pure algorithms in freestanding native code and package
   through the **existing shared loader/product entry**. This directory supplies
   no new load chain and makes no standalone camera-feature claim. Loadable code,
   journaled hooks, owned memory, power-off and Unicorn acceptance are still due.
