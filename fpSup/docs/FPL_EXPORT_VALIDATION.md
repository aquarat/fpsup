# fp L development export validation — 2026-10-23

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
