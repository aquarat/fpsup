# fp L slit-scan capture

A USB-host-controlled High Jello-style capture tool for **SIGMA fp L 3.02**.
The sensor scans slowly while each row has a short exposure, bending moving
objects. Optical slowdown has been measured on the development camera.

## Use the browser

With the existing fp L shell daemon running, launch from the repository root:

```sh
export FPSHD_SOCKET="$HOME/.cache/fpsup/fpshd.sock"
python3 -B fpSup/tools/slit-scan-camera/server.py --bind 127.0.0.1 --port 8128
```

Open **http://127.0.0.1:8128/**. Put an ARM assembler toolchain on PATH and use
a Python environment with the dependencies used by `fp_usb_shell/armasm.py`, plus rawpy/Pillow for
browser previews. No second USB daemon is created. Server defaults to loopback
when `--bind` is omitted; it is intended for a trusted local network.

1. Set the physical selector to **CINE**. Select **UHD, CinemaDNG, 8-bit, 24 fps**.
2. Fix framing and focus; provide enough light for a short exposure.
3. Click **Check camera**, select scan rate, estimated row exposure and ISO.
4. **Take photo** saves one UHD CinemaDNG-derived RAW image. **Record video**
   saves a numbered DNG sequence. Photo mode also uses a short movie take;
   it is not full-resolution STILL capture.
5. Download the result links. Outputs remain under
   `~/Pictures/fpSup/slit-scan/<capture-id>/` (override with `--output`).

The scan-rate choices are 4/6/8/12 fps, with approximate full-height active scan
times of 235/157/118/78 ms. These are timing-model estimates, not shutter times.
4 fps has the strongest distortion. The browser offers 1–30 seconds of exported
video. Capture has additional settling/restoration frames and download time.
The CLI supports up to 480 exported frames; this maximum is emulated, not yet
a long-recording hardware acceptance result.

**Stop** interrupts capture and runs restoration. Settings are restored to the
values read immediately before that take. Keep the selector/mode unchanged
during capture. A mode change aborts the timing override without replaying old
timing into the new mode.

## Outputs and timing

* `images/photo.DNG` or `images/000001.DNG`, …: selected steady-state frames.
* `capture.json`: requested settings, measured cadence, source folder/frame
  indices and estimated effective exposure.
* `images/manifest.json`: source/export SHA-256 hashes and frame identities.
* `preview.jpg`: browser preview when rawpy/Pillow are installed.
* `records.bin`, `timing.json`, `payload.bin`, `manifest.json`, `events.json`:
  timing evidence, exact RAM payload and restoration log.

Each exported file's private GTAG must agree with its camera frame number.
Selection leaves twelve Vd events on each side of the timing transition; the
tested optical results confirm middle frames are slowed. This is conservative
settling, not a calibrated per-row timestamp-to-DNG exposure association.

Exports correct **FrameRate** to measured cadence and renumber **TimeCodes**
from zero at that rate. Raw pixels are unchanged. Camera originals retain stock
24 fps metadata and include preroll/postroll. The existing EXIF ExposureTime
still describes the stock shutter setting; use `capture.json` for the effective
row-exposure estimate. Firmware shutter quantization is read back and included
in that estimate. The compensation has been checked for brightness consistency,
not calibrated as a precision exposure measurement.

## CLI

From `fpSup/fp_usb_shell/`, with the same environment:

```sh
python3 -B fpl_slit_scan.py check --out ~/Pictures/fpSup/check-1
python3 -B fpl_slit_scan.py photo --fps 4 --iso 800 --out ~/Pictures/fpSup/photo-1
python3 -B fpl_slit_scan.py video --fps 8 --frames 48 --out ~/Pictures/fpSup/video-1
```

`--shutter 1000` requests approximately 1/1000-second effective row exposure;
500 and 250 are also available. `--card-only` skips downloading. To download
later or resume an interrupted export:

```sh
python3 -B fpl_slit_scan.py export --out ~/Pictures/fpSup/video-1
```

Completed exports are hash-verified before reuse; changed files are refused.
The camera take must still exist for missing frames. Outputs from the earlier
development export format (without corrected timecodes) are refused rather
than overwritten.

After a killed process or transport failure, a pending marker blocks all other
staging tools. Reconnect the existing daemon and run:

```sh
python3 -B fpl_slit_scan.py recover --out ~/Pictures/fpSup/recovery-1
```

Recovery checks ownership and publication, removes this tool's Vd callback,
stops the take, detaches its frame observer, and restores saved exposure.
It retains the marker if any of those steps cannot be confirmed. The camera-side
timing override ends after a bounded callback count even if the host dies;
the recording/GTAG observer still require recovery. Recovery across a camera
reboot is intentionally refused when worker publication changes.

## Status

Live-checked: all four rates; single-image export; eight-frame 8 fps sequence;
four-frame 4 fps browser sequence; repeated captures; automatic setting
restoration; interruption during an active override; decoded DNGs and export
metadata. Native-instruction tests cover the emitted callback, bounds,
restoration, mode changes and mutation failures.

This is a usable **USB-host feature**. Native camera menu selection has passed
a separate temporary RAM trial. Standalone timing/recording integration,
`.sup` packaging, power-off/boot acceptance and full-resolution STILL capture
remain unfinished. This tool does not install a boot payload.
See [`../../docs/FPL_SLIT_SCAN.md`](../../docs/FPL_SLIT_SCAN.md) for evidence.
