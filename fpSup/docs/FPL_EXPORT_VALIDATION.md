# fp L development export validation

## Ordinary boot, resident recording and FPLS export — 2026-10-30

Baseline: public feature tip `ae437bab723ffc65f2d0a6b5a704f43c0e7d2fd7`.
These are offline exported-tree checks, distinct from historical live evidence.
**The active-take native size-change hang remains unresolved; physical recovery
and original-card restoration are pending.** This source export is not a release.
See [current observation status](FPL_RESIDENT_OBSERVATION.md).

| Exported-tree suite | Result |
|---|---|
| Product bindings/recording/boot/runtime/adapter/controller/menu/native actions | **46 passed** |
| Shared boot-chain/loader-hook/splash/fp L shell/UI restore/draw/packaging | **54 passed** |
| Native FPLS and existing GTAG/parser | **12 passed** |

**112 unique tests passed, no skips or expected failures.** The three targeted
idle-shutdown/foreign-borrower/removal-mutation checks reported by the development
handover are already within the recording suite, not three additional unique
tests. The final source includes one more product test than the earlier 45-test
handover run. Emitted-byte negative controls cover admission, cache publication,
timing restore, observer removal and transition observation. Modeled scheduler,
DMA, MMIO progression, allocation and cache effects do not establish live acceptance.

Reproduce with Python 3, Unicorn, Capstone and an ARM compiler on PATH; set
`FP_MAIN`, `FPL_MAIN`, `FPSUP_FP_MAIN="$FP_MAIN"`, `FPSUP_FPL_MAIN="$FPL_MAIN"`,
`FPL_DATA` and `FPL_DNG_PREFIX` to external inputs:

```sh
# fpSup/slit_scan
python3 -B -m unittest -v test_bindings test_recording test_boot test_runtime \
  test_adapter test_controller test_menu test_native_actions
# fpSup/fp_usb_shell
python3 -B -m unittest -v test_boot_chain test_loader_hook test_splash \
  test_fpl_shell_card test_fpl_ui_restore test_fpl_ui_draw test_card_packaging
# projects/gyro2-sup
python3 -B -m unittest -v test_fpl_gtagpf_slit test_fpl_gtagpf
```

All image/fixture checks remain enabled; nothing was copied into the export.

| External input | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 MAIN | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 MAIN | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |
| fp L 3.02 DATA | 238,080 | `758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8` |
| Archived DNG-prefix fixture | 131,072 | `23e847a480b9c10336dfb397b467410762c66d94f28fac12c4a30a44c972501d` |

The compiler was Zig 0.17.0 (executable SHA-256
`5165c9a2d17938a8173839b3adf81d025b558d38d9e9711237a6fa5b8d8bb3f7`).
The M0 target adapter ran all suites. For exact live-build reproduction, use
the Cortex-A9 adapter: translate `armv7-none-eabi` to `arm-freestanding-eabi`
and add `-mcpu=cortex_a9`, preserving other compiler arguments. The M0 adapter
does not add that CPU to the C invocation, so its runtime is 148 bytes smaller;
its artifact hashes are **not** the live-build hashes.
The complete 46-test product suite also passed with the Cortex-A9 adapter,
without skips; those repeated cases are not added to the unique-test total.

Both Cortex-A9 exported-tree builds reproduce the observation-stage launcher,
debug/plain BIN and AutoRun hashes in [the provenance table](FPL_RESIDENT_OBSERVATION.md)
exactly. The alternate M0 build also passes build/extent guards: debug BIN
55,656 bytes (`57b3b536d599d92dc979fdd98aef44b8f2326258d00532db893cb8687418a237`),
plain BIN 51,540 bytes (`6bfdd5eddfb21a74db73c40acd9b120cffdd7b29cc71706eb3000bc640bd23f0`),
shared launcher 50,028 bytes (`12fbc394305d8200c5466c09069e04620ce53606c23cac9fa151c374525cac21`).
No rebuilt card was deployed or distributed.

Existing non-SLIT pattern and gyro observer machine code is byte-identical to
the public baseline for fixed `PARAM=0x4b001000,SRC=0x4b002000`:

| Variant | Bytes | SHA-256 |
|---|---:|---|
| Pattern, N=560 | 1,568 | `2c216b76b96f7e56e24965ce84be70c1ac60e1e8c3575f1e6be9a7388a580f42` |
| GYRO=1, N=1584 | 2,576 | `f2f1d9b78481b871ddfaf2f5e71959f710260b20e52db6cbf778b62deee238ff` |

Additional read-only parser checks used three external whole DNGs (8,447,488
bytes each): frame indices 1/10/24 returned Vd counts 9/17/31 and unknown sensor
association. Six in-memory mutations (magic, zero frame, complement, size,
association and version) were rejected. These were targeted parser checks, not
additional unittest cases or new camera/decoder tests. Input SHA-256 values:

- Frame 1: `20a328568ca8a151310e620182bf317ef2d0810efb05febbdfe5ca14ac8389ba`
- Frame 10: `f923dc7460418cfd94e995a547ea956afd240289afa7e0872b92544a880a37c2`
- Frame 24: `267b2210e9af5c0c79ee697602311f30a975ca82ac4aeb6ee52340eeff84abad`

Catalogue reproduction remains blocked on the unavailable original `logo2.png`;
the development attempt reached that blocker with fingerprinted external firmware.
No replacement image, catalogue acceptance or release claim is made. Other
outstanding gates include physical recovery, no-shell/disconnected-USB hardware,
power cycling/previous-card boot, shutdown quiescence, failure/storage cleanup,
sensor-frame association and resident exposure/metadata correction.

The export preserves 20 implementation/test files byte-for-byte from the frozen
development snapshot; 23 source fingerprints also match the final live-build
provenance. Documentation is condensed/sanitized, with historical restoration
clearly separated from the current failure. No new images, firmware, binaries,
raw captures, private logs, toolchains or private ancestry are included. Previously
approved illustrative images are unchanged. Review is by the exporting agent,
not a separate independent reviewer; inherited public history is outside its scope.

## Slit-scan/native menu and offline ETTR export — 2026-10-29

Baseline: published feature tip `582b7f61a6c2cd8b7f3025ef81a59c9ff8f91a9f`.
Tests ran in the sanitized export tree with external official fp 5.02 and
fp L 3.02 MAIN images, an ARM compiler on PATH, and Python dependencies
Unicorn, Capstone, NumPy, rawpy, Pillow and tifffile.

| Suite | Result |
|---|---|
| Slit-scan capture/Vd, UI/CPU/guard/resident/restore/draw/capture, card packaging, fp L shell card and shared boot-chain/loader-hook/splash | **93 passed** |
| Menu/controller/native action handlers/page adapter/runtime | **25 passed** |
| Offline ETTR/deflicker behavioral suite | **26 passed** |
| Optical scan measurement | **2 passed** |
| Default-fp shared UI applier, composition and mutations | **30 passed** |

**176 tests passed, no skips or expected failures in these runs.** The ETTR
static firmware audit also verified eight command bindings and rejected all
seven negative cases. This targeted validation does not supersede the older
unrelated failures recorded below or establish hardware release acceptance.

Reproduce after setting `FP_MAIN`, `FPL_MAIN`, `FPSUP_FP_MAIN` and
`FPSUP_FPL_MAIN` to the external official images:

```sh
# fpSup/fp_usb_shell
python3 -B -m unittest test_fpl_slit_scan test_fpl_vd_probe test_fpl_ui test_fpl_ui_cpu test_fpl_ui_guard test_fpl_ui_resident test_fpl_ui_restore test_fpl_ui_draw test_fpl_ui_capture test_card_packaging test_fpl_shell_card test_boot_chain test_loader_hook test_splash
# fpSup/slit_scan
python3 -B -m unittest test_menu test_controller test_native_actions test_adapter test_runtime
# Repository root
python3 -B -m unittest fpSup.ettr.test_core
python3 -B -m fpSup.ettr.audit_firmware --main "$FPL_MAIN" --self-test
# fpSup/tools
python3 -B -m unittest test_fpl_scan_measure
```

The inherited default-fp UI harness initially errored because it hard-codes
`out/seg0_c0000000.bin` and does not consume `FPSUP_FP_MAIN`. Its pinned hash
matches the official fp MAIN. All 30 tests then passed with only its input
paths redirected in memory, preserving the image hash and all assertions:

```sh
# fpSup/uishare
python3 -B - <<'PY'
import os, pathlib, unittest
import test_ui_apply as test
import build_fpui
test.SEG0 = build_fpui.P.SEG0 = pathlib.Path(os.environ['FP_MAIN'])
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(test))
raise SystemExit(not result.wasSuccessful())
PY
```

Publication review covers complete outgoing blobs and commit metadata. Personal
paths, LAN addresses and operational directory listings are omitted. Five menu
JPEGs have EXIF/vendor metadata removed without recompression; their decoded
pixels match the originals. The optical comparison has no EXIF. Image hashes
and processing are recorded in adjacent provenance JSON. Original camera files,
firmware inputs, payload binaries and detailed trial logs remain external.

The staged-content firmware/decompiler guard passed against each official MAIN
with NumPy available. Its optional exact Ghidra-line comparison had no decompiler
export; text heuristics ran. Identifier/credential and private-commit-reference
scans found no confirmed outgoing leak. This review covers this export delta,
not a new audit of inherited upstream history.

## Initial export — 2026-10-23

Baseline: public upstream `e79e3f1ff4622bce0b8a4cee9d322f184d7f6696`.
All results below are offline checks of the exported source. No camera operation,
card write, deployment or hardware release acceptance is implied.

## Executed tests

With an ARM toolchain on PATH and externally supplied official images selected
by `FPL_MAIN`, `FPSUP_FPL_MAIN` and `FPSUP_FP_MAIN`:

| Suite | Result |
|---|---|
| All `test_fpl_*.py`, packaging, firmware profiles, heap probes, v3 shell profile, boot-chain/loader-hook/splash | 413 run: **410 passed, 3 expected failures**, no skips |
| Host EP83, MEM1 and upload harnesses | **13 passed** |
| Default fp worker MEM1/upload ARM harnesses | **24 passed**, external fp image supplied |
| MOV epoch classification including actual-firmware bounded replay | **10 passed** |
| Legacy catalogue reference helpers | **11 passed** |
| Shared gyro direct-GCSV/format/stream/lifecycle/release/safety | 130 run: **126 passed, 3 failures, 1 skip** |
| Imported OpenGate boot-entry build matrix | **Blocked:** all 14 builds require the upstream fixed-path `out/MAIN_c0000000.bin`, absent from the clean tree |

The three expected failures are existing worker lifecycle regressions: mode-4
exclusion, cancelled wait with cleared HWO, and descriptor replacement during a
pending submission. Scratch guard tests do not make those production gaps solved.

The shared gyro failures reproduce the prior development baseline. A separate
run of **unmodified current upstream** `test_safety` had 20 passes and one failure:
the same arena scan's five literals in `card_status.py`, `test_card_emulation.py`,
`test_qs_layer.py` and `test_ui_apply.py`. The export additionally retains the two
known immediate-`#ifndef` regex failures for `getfile.S`: its explicit non-fp
storage refusal is nested inside the guard. These tests were not weakened,
reclassified or silently repaired. The gyro skip requires its legacy fixed-path
firmware input. This is not an all-green shared suite.

Integration fixed one stale test Git path in `test_fpl_putfile`. Its reference
now pins public upstream's pre-port source instead of `HEAD`, avoiding a
self-comparison after commit. All 11 tests in that module passed, followed by
the complete 413-test rerun above.

Public native tests retain exact image checks. Missing required native input was
also checked to fail explicitly with instructions to set `FPL_MAIN`, not pass or
skip. Optional image-dependent tests retain explicit skip messages. Firmware,
DATA/container inputs and raw observations are never part of this patch.

The default fp worker harness initially skipped all 24 tests because its image
path was fixed. It now accepts `FPSUP_FP_MAIN`, preserving the legacy default and
all assertions. With the explicit external official image, all 24 executed and
passed; no firmware copy or skip override was used.

## Default fp artifact comparison

Built identical ordinary and Fast configurations from unmodified upstream and
the export in separate fresh output directories. AutoRun is byte-identical in
both configurations. Each BIN has exactly six changed ARM words: the three
USB arm helpers now save/restore r12 as well, keeping the stack 8-byte aligned
at firmware calls. No length, offset or other word changed. This is the shared
ABI-alignment correction already present in the port, not a model-address drift.

| Artifact | Export SHA-256 |
|---|---|
| Ordinary AutoRun | `e9e4e5f25041940a9f2f748416dc5697ec466a149780af0e66be66336410363f` |
| Ordinary BIN | `1b5866debaaca3b1dc9ce2ef5cabf900610d745a8afe918a9a96607a389cad6e` |
| Fast AutoRun | `6c6b566e9d8866be193aaefe6dd58ffb06f41ad9a658dce6152241eca050ce4a` |
| Fast BIN | `5042ec2ffefa80aed72b4cc2fab553a120ee2a9920530d5f47fd630e70db6cbb` |
| Base task, byte-identical to upstream | `5c0bae4b3bd3abb17e23c446bcd6a92f899dfd9b1be9f071c325328b5f7a7a38` |
| GCSV task, byte-identical to upstream | `c6e9f98bffaf057768bd099c587d903f031f378bc656692fdc17fb0bb07472bb` |

Ordinary flags: `--loader --no-four-box-bar --no-fast-echo --no-ep-patches`.
Fast flags: `--loader --store-boot --loader-hook --four-box-bar`.
Both use `build_autorun.py --out NEW/AutoRun.txt` with the default fp profile.
Base uses `gcsv_task.S` with `FPGYRO_EDITION_BASE=1`; GCSV uses its defaults.
These are reproducibility artifacts, not distributed cards or runtime pair IDs.

## Reproduction

Set the external-image variables as shown in [the port guide](FPL_PORT.md).
From `fpSup/fp_usb_shell`:

```sh
python3 -B - <<'PY'
import pathlib, unittest, sys
names = sorted(p.stem for p in pathlib.Path('.').glob('test_fpl_*.py'))
names += ['test_card_packaging', 'test_firmware_profiles', 'test_heap_probe',
          'test_heap_probe_native', 'test_v3_shell_profile', 'test_boot_chain',
          'test_loader_hook', 'test_splash']
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromNames(names))
sys.exit(not result.wasSuccessful())
PY
```

Other commands, from their respective directories:

```sh
# fpSup/fp_usb_shell/host/tests
python3 -B -m unittest test_ep83_host test_mem_host test_upload_host
# fpSup/fp_usb_shell (FPSUP_FP_MAIN set)
python3 -B -m unittest test_worker_mem test_worker_upload
# fpSup/tools
python3 -B -m unittest test_fpl_mov_epoch
# fpSup/tools/card-composer
python3 -B -m unittest test_catalogue_refs
# fpSup/gyro (known failures and skip above)
python3 -B -m unittest test_gcsv_direct test_gcsv_format test_imu_stream test_lifecycle test_release_card test_safety
# Repository root (requires upstream's fixed-path external input)
python3 -B projects/open-gate/build/test_boot_entry_chain.py --out NEW_OUTPUT
```

Upstream's staged-content pre-commit guard was run with NumPy installed and each
official model's MAIN supplied externally; both checks passed. No decompiler
export was supplied for its optional exact-line comparison. The guard's text
heuristics and full changed-blob identifier/credential scans were also reviewed.
Inherited upstream history and artifacts are unchanged; this validation concerns
the added patch and does not certify every historical upstream asset.
