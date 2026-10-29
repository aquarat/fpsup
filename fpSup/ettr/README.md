# Auto ETTR / timelapse deflicker reference core

**Offline groundwork, not an installed fp L feature.** No USB, camera calls,
firmware writes, loader, menu patch or capture engine is included. Integration
evidence and remaining work: [FPL_ETTR.md](../docs/FPL_ETTR.md).

## Run from the repository root

Use a Python environment with numpy, rawpy and tifffile:

```sh
PY=python3
"$PY" -B -m unittest -v fpSup.ettr.test_core
"$PY" -B -m fpSup.ettr /path/to/frame.DNG
"$PY" -B -m fpSup.ettr /path/to/frame0001.DNG /path/to/frame0002.DNG \
  --deflicker --target-ev -4 --output /path/to/NEW-analysis-directory --xmp
```

Input order is chronological order; a shell glob must sort accordingly. Inputs
are read-only. The output directory must not already exist. The CLI writes one
report and numbered JSON sidecars, plus optional XMP development hints. Numbered
names avoid collisions between takes; JSON maps every output to a source path
and SHA-256. To use an XMP in a RAW developer, explicitly associate/copy it to
the correct image's sidecar name. Existing development settings are not merged.

Plan next exposures using **explicit accepted actuator values**, ascending:

```sh
"$PY" -B -m fpSup.ettr /path/to/frame.DNG \
  --shutters 1/8000,1/6400,1/5000,1/4000,1/3200,1/2500,1/2000,1/1600,1/1250,1/1000,1/800,1/640,1/500 \
  --isos 100,200,400,800 --interval 3 --overhead 2
```

The example is a constrained planning table, **not a verified fp L setting
table**. The input's actual exposure must be in it. Camera binding must read
back accepted quantized shutter/ISO, pair them with the measured frame, and
construct a new controller when mode/aperture/generation changes. The CLI uses
nominal EXIF; it cannot determine modified slit-scan effective exposure.

`--ignore-fraction .001` ignores 0.1% **per CFA channel**. Zero protects every
sample (including hot pixels). `--reserve-ev .5` targets half a stop below
white. `--percentile .5` meters the median for deflicker; a black/clipped median
is an error, not a large guessed correction. Another percentile is an explicit
artistic choice, not an automatic workaround. DefaultCrop is honored before
statistics; odd origins preserve CFA channel alignment.

`--trend-window 1` uses a fixed percentile target, like Magic Lantern post
deflicker. Odd values >1 smooth the exposure-normalized scene-EV curve and
preserve gradual lighting changes. It is a centered, offline window. All frames
must have constant aperture and comparable composition. Moving subjects,
flickering displays and sensor gain transitions can violate that assumption.

## Library surface

- `core.meter_raw`: full-frame, linear-domain per-channel statistics, independent
  G1/G2 protection, calibrated black/white, exact integer highlight-ignore budget.
- `core.Controller.plan`: causal, bounded shutter/ISO planning; immutable aperture,
  absolute-target smoothing, deadband, fast clipped-highlight recovery, interval
  budget and frame freshness. Returns separate photon/gain EV and residual error.
- `core.deflicker`: bounded RAW-relative development corrections and limit flags.
- `dng.analyze`: LibRaw linearization, DNG crop/EXIF, source hashes. No WB/tone curve.
- `audit_firmware`: fingerprinted, static fp L command/observer evidence, including
  seven negative cases. Requires Capstone (available in system Python here).

```sh
python3 -B -m fpSup.ettr.audit_firmware \
  --main /path/to/firmware/FPL_V302/MAIN.bin \
  --self-test > /path/to/audit.json
```

There is no SNR/noise-model optimizer, dual ISO, bulb controller, continuous RAW
buffer reader or freestanding ARM build. Python is the tested reference for the
future native core. Output XMP exposure is RAW-relative: DNG BaselineExposure,
developer profiles, highlight recovery and tone curves affect rendered output;
check a developed sequence before claiming visual deflicker.
