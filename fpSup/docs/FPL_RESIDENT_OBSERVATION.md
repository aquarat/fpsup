# fp L resident per-DNG observations — 30 October 2026

**Development source, not release acceptance.** An active-take native size change
caused a camera hang/shell loss. Physical recovery is required; the original card
has **not** been restored after that failure, and the test card remains installed.
Recorder state, final mode and cleanup are unknown. Detailed device recovery logs
and backup locations remain private. No source-export test establishes recovery.

This extends [resident recording](FPL_RESIDENT_RECORDING.md) with the existing
GTAG observer/parser in the same retained allocation/shared shutdown body.
It records timing state at DNG notification, **not** sensor-frame timing.
Automatic resident exposure compensation and corrected FrameRate/TimeCodes
remain **unfinished**.

## Implementation and FPLS format

- `fp_usb_shell/asm/fpl_gtagpf.S`, opt-in `SLIT=1,N=64`, reuses native
  Subject/attach, take builder, tag insertion, serialized-template parsing and
  notification. Default pattern/gyro paths are retained.
- `build_adapter.py` embeds observer code in owned runtime text. Parameter/object/
  vtable occupy owner+`2400/2500/2510`; retained zero source is +`2600`; the
  runtime reference is parameter+`120`. No pointer targets loader/USB staging.
- Pointers are prepared before D/I publication. The drawing owner attaches once
  while idle. A full nine-slot Subject refuses without attach, retry or timing
  activation. Registration survives repeated/Off takes; Off adds no new tag.
  This is not another task/logger/loader/filesystem writer.
- Shared shutdown marks the runtime shut down, removes only its own observer,
  then conditionally restores timing and replays the journal. Idle/empty-Vd
  shutdown also detaches. It adds no registration and frees no borrower;
  general in-flight callback quiescence remains unproved.
- `slit_scan/metadata.py` validates and reads observations without rewriting DNGs.
  Wrong extent/magic/version/complement and unwritten frame zero refuse.

FPLS v1 occupies 64 bytes in MakerNote GTAG `0x4653`: sixteen little-endian words:

```
magic='FPLS', frame_index, ~frame_index, bytes=64,
requested_index, active, owned_Vd_count, trial_timing04,
observed_timing04, observed_timing20, TickTimer_seconds, timer5,
last_Vd_timer5, cleanup_reason, sensor_association=0, version=1
```

Identity is the native mode-3 notify index. Register snapshots exclude IRQ/FIQ;
template stores are byte-safe and cache lines are cleaned before return.
`sensor_association=0` means **unknown**, even when active=1. The reader explicitly
labels stock nominal rate/timecode metadata. No whole-take slowed-rate stamping occurs.

## Live evidence and known failure

Both new card files and immutable owned extents were independently read back.
Ordinary boot registered five variables, the eight-word journal and one observer,
without a host RAM installer. Menu screenshots were inspected.

| Test | Observed result |
|---|---|
| 6-second 4 fps take | 24 notifications; 3.9999992 Hz; normal cleanup |
| 90-second repeated 4 fps take | 359 notifications; 4.00000046 Hz; 357 sampled intervals; normal cleanup |
| Repeated 4 fps, attempted GUI-variable Off | 40 notifications; 4.0000012 Hz; setter acknowledged but did **not** change private selection; ordinary stop cleaned up |
| Active-take native size transition | `menu SetMovRecSize 2` acknowledged, then all shell reads timed out; stop/restoration unverifiable |

The 90-second middle had no host traffic. Completed takes left idle recording,
empty early-Vd slot, inactive override and original mode3/shutter0/0/ISO0 exposure.
Observer counters advanced without reported skips/template mismatches. Capacity
was checked before each take; no user files were deleted. The last take's final
size/state is unknown. Logical USB recovery failed configuration (-110); a
reviewed daemon restart then failed interface claim (INVALID_PARAM). No blind
recording toggle/reboot was used, and these attempts did not restore the camera.

Whole sampled frames 1/10/24 from the first take decoded with LibRaw/rawpy:
8,447,488 bytes, 3856×2170, correct FPLS indices, FrameRate=24000/1000. Their
TimeCodes remained the nominal 24-fps counter, not corrected elapsed time.
Dark-scene tests establish timing/file integrity, not exposure calibration.

**Association blocker:** those notifications saw Vd counts 9/17/31. Nine file
index increments (1→10) corresponded to eight Vd increments. A fixed offset
between file and Vd indices is contradicted by this take. Buffered sensor frames
need a capture-boundary identity carried through the native queue before any
preroll/transition/restored-frame metadata correction. The observer records the
uncertainty instead of inventing that identity.

## Exposure research, not automatic compensation

`bindings.py:exposure_probe_source` emits finite task-context calls. Official-image
command edges/arguments are checked by `ettr.audit_firmware`; shutter getter ABI
is **r0=out[2], r1=settings**, not a scalar getter. ABI tests cover all readbacks.

| Setting | Setter | Getter |
|---|---|---|
| Mode | C00559D8 | C0055A10 |
| Shutter | C0055BA0 | C0055BE8 |
| ISO | C0056158 | C0056190 |

Finite live probes read originals, set mode1/1/6400/ISO800, then restored
shutter0/0/ISO0/mode3. Native/shell getters agreed and echo was restored.
Setting mode1 also changed shutter0/0 to 1/25; restoring shutter0/0 changed mode
back to3. Restoring one scalar is insufficient. Immediate imager status reported
shutter99977/gain6400 despite settings readbacks of 1/6400/ISO800: neither recording
exposure nor settling was established.

Native setters dispatch through settings virtual methods/notifications
(`C0064A70 → C0075788`, conditional notification at `C0075874`). They are not
IRQ/shared-shutdown MMIO writes. A proved task-context rollback boundary and
settings-save ordering are needed before borrowing exposure settings. The existing
host `fpl_slit_scan.py` workflow remains the measured compensation reference.
The live hang blocked further qualification; no precise calibration is claimed.

## Build and exact provenance

```sh
python3 -B fpSup/slit_scan/build_card.py --fp-main "$FP_MAIN" \
  --fpl-main "$FPL_MAIN" --out NEW_DIRECTORY --debug --recording
python3 -B fpSup/slit_scan/metadata.py FRAME.DNG
```

Supply fingerprinted official images externally. Select the native SHOOT 2 rate
before recording; supported timing is UHD CinemaDNG 8-bit nominal24 only.
**Do not change native format/size/rate during a take. Stop and verify idle first.**

| Camera-tested observation build | Bytes | SHA-256 |
|---|---:|---|
| fpSup.BIN | 55,804 | `2333957cc265c3c2d795d76270c77ad73ea5ca74f201b2858fa8c4b35e8e5845` |
| AutoRun.txt | 6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |
| launch.bin | 50,176 | `52aebc6ccdfdd55586e9f4a97c74dcd4e1e314543bbf2e2846baf971c68d6218` |

Runtime 18,232/20,480; FPUI 30,848/31,744; BIN 55,804/61,440 bytes.
Undeployed plain BIN: 51,688 bytes,
`b428208bc71fce6727469f4998dd407e51eab52a25182da142c9e671f28c8464`;
plain AutoRun: 6,564 bytes,
`a27965148c4175a4b2d853e9b38571fb6a8975182fd9eacb735401dedffe43f7`.
Final overlap-guard additions rebuilt a launcher byte-identical to the tested
build. AutoRun remains unchanged within each ordinary shell configuration.
Generated cards, firmware and raw captures are excluded from this source export.

## Offline results and remaining gates

Development checks: 45 product, 54 shared-chain/drawing/packaging, 12 native
GTAG/parser tests and three targeted shutdown-review checks passed without skips.
The latter are targeted cases from the recording suite, not three additional
unique tests. [Export validation](FPL_EXPORT_VALIDATION.md) records fresh runs.
Native add/serialize/notify instructions execute; scheduling, DMA, MMIO progression
and hardware cache effects are modeled. Boot tests poison freed staging.
Transition-state, observer-removal, timing-restoration and admission mutations
are detected. None models or clears the observed live size-change failure.

Catalogue reproduction is **blocked** by the unavailable original `logo2.png`,
after the fingerprinted official fp image satisfied the earlier image dependency.
Derived logo renders are not substitutes. No catalogue/site/release was changed.

Physical recovery and independent original-pair/stock-state restoration come first.
Then outstanding acceptance includes no-shell cold boot, physically disconnected
USB recording, roughly ten no-record power-switch cycles, previous-card retained
image and post-record restart, shutdown quiescence, optical calibration at all
rates, capture-boundary frame identity, exposure rollback before settings persistence,
failed-start/storage-error cleanup and broader stress. No destructive media test
was performed. General v3/M1/M2/Fast gates remain open.
