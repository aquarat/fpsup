# fp L resident Slit scan recording — 30 October 2026

**Opt-in development backend, not release acceptance.** The ordinary debug card
connects native menu selection to 4/6/8/12 fps timing on **UHD CinemaDNG, 8-bit,
nominal 24 fps only**. The later [observation stage](FPL_RESIDENT_OBSERVATION.md)
adds per-DNG diagnostics and a 90-second take, but an active-take native size
change hung the camera. Physical recovery and original-card restoration remain
pending. Do not change native format/size/rate during recording; stop and verify
idle first. Mode-change cleanup in emulation is not live mode-change acceptance.

## Build and operation

```sh
python3 -B fpSup/slit_scan/build_card.py \
  --fp-main "$FP_MAIN" --fpl-main "$FPL_MAIN" \
  --out NEW_DIRECTORY --debug --recording
```

Use external fingerprinted official images and an ARM compiler on PATH.
Without `--recording`, the [ordinary menu-only build](FPL_STANDALONE_BOOT.md)
remains available. Without `--debug`, the no-shell variant is built; that variant
has only emulation evidence. The launcher/controller/menu/drawing wrapper/shared
loader and two placement passes are the same components, with no extra worker,
installer, Fast path or power-off object.

Select Off/4/6/8/12 **before** a take. Native key callbacks only change private
RAM selection. The drawing task qualifies an idle→recording transition; a late
selection never activates timing halfway through a take. Off, unsupported mode,
changed selection and runtime failure disable the override.

**Exposure settings are untouched:** appropriate short exposure is manual;
resident automatic compensation is unfinished. DNG FrameRate and displayed fps
stay nominal24. Preroll exists. The current source includes a diagnostic observer,
but frame-exact sensor association and rate/timecode correction are unfinished.
Dark-scene recording checks establish timing and decoding, not optical exposure
calibration. Earlier optical evidence is in [slit-scan results](FPL_SLIT_SCAN.md).

## Bindings and cleanup

- Native recording status is the **byte** at `C30338CC`, not adjacent flags.
  `C3033A40` is the application word: CINE=2, menu=5. A stock live take showed
  status 0→1→0. Native accessor tests detect the incorrect word-load mutation.
- `C0055120()` obtains settings; getters `C00594C8`, `C0059560`, `C0059690`,
  `C0059728` return supported format/quality/size/rate `0/4/3/12`. Finite native
  calls matched shell getters, and the resident drawing task matched them.
  Getters never run in key/Vd callbacks. Menu preview permits app5; activation
  independently requires app2. Unsupported selections reassert Refused.
- The owned veneer at +`1800` calls `slit_vd(owner+8000)`; recording state is at
  +`8200`, within the original 1-KiB runtime reservation. Its first six words
  form the shared shutdown ABI.
- IRQ/FIQ-excluded publication requires empty `C31D6DD8`, dispatcher enable=1,
  recording status=1 and exact MMIO pair `020B047B/165B0000`. Only the eighth
  owned Vd changes `30100004`. The bounded callback makes no firmware calls.
  Timer5 uses the proved 12-MHz one-second counter; 32 intervals remain in RAM.
- IRQ cleanup covers Off/selection, command/phase/error/controller state,
  recorder/app status, foreign MMIO and a drawing heartbeat older than two
  seconds. Drawing cleanup additionally checks native mode getters. Stock timing
  is restored only while both registers match this trial; only the owned callback
  is cleared. This modeled behavior did **not** prevent the live size-change hang.
- The shared admission/journal covers eight words: six string words, drawing
  vtable and early-Vd slot. `shutdown.S` extends only the existing shared restore
  body. It validates owned descriptor/state/veneer, sets shutdown first, conditionally
  restores timing, clears the callback and then replays the journal. Both shutdown
  lists retain one object. The later stage also removes the owned observer.
- No native borrower is freed and no callback targets staging. Retention is not
  general shutdown quiescence proof. Crash/battery removal runs no cleanup callback.

## Historical live results

No post-boot RAM installer was used; full immutable owned extents and both journal
registrations were independently checked. Short takes included five steady seconds
without host traffic. Normal starts/stops used key pulses, not timing writes.

| Test | Measured Vd Hz | Result |
|---|---:|---|
| 4 fps | 4.000001 | normal-stop restoration |
| 6 fps | 6.000003 | normal-stop restoration |
| 8 fps | 8.000010 | normal-stop restoration |
| 12 fps | 11.999983 | normal-stop restoration |
| FHD unsupported | no callback | Refused, no timing activation |
| Off | no callback | no timing activation |
| 12 fps reenabled | 12.000008 | restarted and restored |
| 12 fps repeated | 11.999992 | restarted and restored |

Whole sampled DNGs at each rate decoded with LibRaw/rawpy: 8,447,488 bytes,
3856×2170 raw pixels, 8-bit stored data, FrameRate=24000/1000. This earlier build
had no injected GTAG. No full clip enumeration/frame-count equivalence is claimed.
Idle FHD→UHD restoration recovered `0/4/3/12`; exposure remained mode3/shutter0/0/ISO0.
Stock state and the complete original pair were verified after this stage's reboot.
That historical restoration was superseded by the later failed active-take trial.

| Historical recording debug artifact | Bytes | SHA-256 |
|---|---:|---|
| fpSup.BIN | 53,816 | `b61eba09cc7751f487ed202aa8a065410858b9af7cd075f712cb4ebf9f16f575` |
| AutoRun.txt | 6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |
| launch.bin | 48,248 | `91a0c652efdd2720bdcdf306be19cec186a0bdc071d55650b6d1836350fd7690` |

Runtime 16,304/20,480; FPUI 30,848/31,744; BIN 53,816/61,440 bytes.
Undeployed plain BIN: 49,700 bytes,
`2e09410d6bf2e0bf950c2e19d2ced76130b13352db13843b780436e52b51103f`.
AutoRun is byte-identical to stage one in each shell configuration. Current
observer-enabled hashes are in the next stage, not this historical table.

## Verification limits

Initial recording-stage product/shared/packaging runs passed 40/46/8 tests;
later summary, native-mode and foreign-slot checks extended coverage. See
[current export validation](FPL_EXPORT_VALIDATION.md) for rerun commands/counts.
Fixtures execute owned runtime, native registry/key/IRQ dispatch and both shared
shutdown reasons, with emitted admission/MMIO-store mutations. Mode getters,
allocators, scheduler, cache effects and timing are modeled, not emulated silicon.

Catalogue rebuilding remains blocked on original `logo2.png`, after the official
fp MAIN satisfied the missing image dependency. Derived logos are not substitutes.
No release or site update occurred. No-shell hardware, physical USB disconnection,
power cycling, previous-card retained-image boot, shutdown quiescence, live forced/
storage-error/failed-start cleanup, broader stress, sensor association and exposure/
metadata automation remain open. Active-take native size change is a **known live
failure**, not merely an untested gate. General v3/M1/M2/Fast gates remain open.
