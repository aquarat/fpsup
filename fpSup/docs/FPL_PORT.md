# fp L 3.02 development port

This is an experimental shared-code port, not a released fp L product card.
The downloadable fp products still target firmware 5.02. Firmware images and
raw camera observations are not included.

## Latest development: native queue provenance and notification timelines

**31 October recovery verified:** battery removal recovered the earlier hang;
the original diagnostic pair and stock state were independently verified after
restoration, including after the latest producer trial. No resident Slit scan
menu/observer remains. The active-take native size-change hang is **unfixed**;
do not change native format/size/rate during recording.
[Recovery](FPL_RESIDENT_OBSERVATION.md) · [Latest evidence](FPL_PRODUCER_PROVENANCE.md).

- **USB-host slit-scan capture is live-tested:** 4/6/8/12 fps, short-exposure
  compensation, fixed ISO, single UHD RAW-frame and DNG-sequence export,
  interruption restoration and hash-checked resume. Optical moving-bar evidence
  confirms scan slowdown. [Capture guide](../tools/slit-scan-camera/README.md)
  and [results with example images](FPL_SLIT_SCAN.md).
- **Ordinary debug-card boot and native recording are live-tested:** the owned
  menu installs without a host RAM installer. Off/4/6/8/12 fps, repeated keys,
  wrap and reentry passed; opt-in recording measured all four rates on UHD
  CinemaDNG 8-bit nominal24. Off, unsupported-mode refusal, repeated takes and
  normal-stop restoration passed. [Boot](FPL_STANDALONE_BOOT.md) and
  [recording](FPL_RESIDENT_RECORDING.md).
- **Opt-in FPLS v2/v3/v4 diagnostics are live-tested:** v2 measures native queue
  labels; v3 adds exact consumer keys/coherent notification clocks; v4 joins all
  93 DNGs from finite 4/12fps trials to actual historical lookups and independent
  producer generations. Six whole DNGs decoded. These are software publication
  bounds, not sensor exposure/readout timestamps. The read-only host timeline
  preserves gaps, transitions, nominal metadata and unknown capture time.
  [Queue](FPL_QUEUE_IDENTITY.md) · [Timeline](FPL_LOOKUP_PROVENANCE.md) ·
  [Producer provenance](FPL_PRODUCER_PROVENANCE.md).
  Optical common-clock sensor-phase qualification and capture-metadata correction
  remain open. **Resident exposure is offline-only:** the controller is absent
  from card runtime and `--exposure` refuses deployment. Native request deferral
  and settings serialization remain unqualified.
  [Exposure boundary](FPL_EXPOSURE_BOUNDARY.md).
  No-shell hardware, disconnected USB, physical power cycles, shutdown quiescence
  and broader stress acceptance remain open. Catalogue reproduction still lacks
  the original `logo2.png`. This is not a release.
- **Auto ETTR/deflicker is offline groundwork:** RAW metering, bounded exposure
  planning, DNG analysis and JSON/XMP sidecars. Native RAW ownership, calibration,
  settling, controls and still/interval capture integration remain unfinished.
  [ETTR guide and firmware audit](FPL_ETTR.md).

Six illustrative JPEGs are included; camera metadata is removed from the native
menu screenshots. Raw captures, operational manifests and firmware stay external.

## Architecture and current evidence

- One loader, stage2, worker and container implementation, with explicit
  firmware profiles. Default fp bindings retain their established behavior.
- The restricted ordinary headless shell builder uses
  `--camera fp-l-3.02 --fpl-shell`. The explicit `--fpl-ui-boot` profile admits
  the narrow product boot entry and optional no-shell build. Recording additionally
  uses `--fpl-slit-recording`. Pre-placement admission and one shared journal
  protect declared string/drawing/Vd sites. Fast and arbitrary product combinations
  remain unsupported. Ordinary debug-card boot has live evidence; plain/no-shell
  boot has only emulation evidence.
- Historical fp L hardware trials verified shell execution, bidirectional RAM
  transfers, card upload/download readbacks and the reviewed same-size worker
  handoff. Unattended reboot recovery and arbitrary worker replacement remain
  unresolved. Historical trial evidence does not certify a newly built card.
- Finite gyro diagnostics use the shared drain. Retained native-task and
  runtime-relocation variants exercise ownership, native completion and staging
  lifetime. They are not continuous, calibrated or recording-aware loggers.
  Conditional ring prefixes always retain `proven_valid_records: 0`.
- The retained launcher is exercised through the actual shared loader, stage2
  and entry trampoline in emulation. Both passes, return ABI, cache publication,
  staging poisoning and retained execution are checked. Allocator/task/backend
  models and hardware limitations are documented; no hardware boot acceptance
  is implied. Native storage reclamation remains unsupported.

## Guides and technical evidence

- [Current export tests, known failures and fp artifact comparisons](FPL_EXPORT_VALIDATION.md)
- [Current feature-parity roadmap and upstream source pins](FPL_PARITY_ROADMAP.md):
  Gyro2, strict ELF extraction and UI sources are now available in the imported
  research tree. Source availability is distinct from build reproduction.
  Priorities are shell recovery, resident admission/headless v3, then calibrated
  Gyro2; the entire legacy Base logger is not a prerequisite.
- [Development tool usage](FPL_TOOLS.md)
- [Shared capture and cancellation](FPL_RETAINED_TASK_NEXT_STEP.md)
- [Shared retained native wrapper](FPL_SHARED_RETAINED_TASK.md)
- [Runtime relocation](FPL_RETAINED_RELOCATION.md)
- [Allocation launcher](FPL_RETAINED_LAUNCHER.md)
- [Shared boot-chain test and artifact hashes](FPL_RETAINED_BOOT.md)
- [Gyro coherence limits](FPL_GYRO_DRAIN_COHERENCE.md)
- [Recording-state coverage](FPL_RECORDING_STATE_COVERAGE.md)
- [Recording format selection](FPL_RECORDING_FORMAT_STATES.md)
- [Failure unwind](FPL_RECORDING_FAILURE_UNWIND.md)
- [Bounded dispatch](FPL_RECORDING_DISPATCH_TABLE.md)
- [MOV result delivery](FPL_MOV_RESULT_DELIVERY.md)
- [MOV stop forwarding](FPL_MOV_STOP_FORWARDING.md)
- [Offline epoch classification](FPL_MOV_EPOCH_CLASSIFICATION.md)
- [Sensor timing feasibility](FPL_SENSOR_TIMING_FEASIBILITY.md)

Technical audit notes retain bounded findings and historical test results.
Private operational logs, device identifiers and raw observations are excluded.
An audit requiring archived observations must be supplied those external inputs;
the notes are not substitutes for the inputs.

## Offline reproduction

Use Python 3, Unicorn, Capstone and an ARM-capable `clang`/LLVM toolchain on PATH.
Obtain and extract the official firmware separately. Images are checked against
their expected sizes/hashes by the relevant harnesses. No firmware input is
copied into this repository.

```sh
export FPSUP_FPL_MAIN=/path/to/firmware/FPL_V302/MAIN.bin
export FPL_MAIN="$FPSUP_FPL_MAIN"
export FPSUP_FP_MAIN=/path/to/firmware/FP__V502/MAIN.bin
cd fpSup/fp_usb_shell
python3 -B -m unittest test_fpl_gyro_capture test_fpl_gyro_capture_host test_fpl_gyro_latched test_fpl_gyro_coherence test_fpl_gyro_latched_relocation test_fpl_gyro_latched_cancel test_fpl_gyro_task test_fpl_gyro_task_retained test_fpl_gyro_task_host test_fpl_retained_bindings test_fpl_retained_relocation test_fpl_retained_launcher
python3 -B -m unittest test_fpl_retained_boot test_fpl_retained_launcher test_fpl_shell_card test_card_packaging
python3 -B -m unittest test_boot_chain test_loader_hook test_splash
```

The first two commands overlap; their combined unique set is 179 tests.
Missing external inputs may produce explicit skips in optional firmware tests
or errors in required native-firmware harnesses. Neither is firmware validation.
Some tools also require independently extracted DATA/container or archived
observations via explicit CLI arguments. Their integrity checks remain enabled.

See `SUP_BUILD_RULES.en.md` for the shared load-chain contract. Offline evidence,
historical hardware observations and release acceptance are separate claims.
