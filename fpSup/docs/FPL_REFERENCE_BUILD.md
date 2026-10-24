# fp L roadmap M0: offline fp reference build

The fork's `tools/fpl_reference_build.py` reproduces the **fp 5.02** Gyro2
v0.2.0 reference and builds an ordinary, headless v3 loader. These are fp
artifacts, not an fp L port or a camera acceptance result.

## Run

From the repository root, supply official extracted MAIN images separately:

```sh
python3 -B fpSup/tools/fpl_reference_build.py \
  --source-rev 4654a6a6 \
  --fp-image "$FP_MAIN" --fpl-image "$FPL_MAIN" \
  --zig "$ZIG_HOME/zig" --out "$REFERENCE_OUTPUT"
python3 -B -m unittest discover -s fpSup/tools -p test_fpl_reference_build.py -v
```

`REFERENCE_OUTPUT` must be a **new directory outside the checkout**. No existing
file is replaced. Keep durable results in your own data directory; temporary
outputs may be cleaned by the host. Python and Unicorn are required. An ordinary
Clang installation can instead be selected with `--clang-dir DIR` (the binary
must be named `clang`); this alternate compiler was not used for the result below.

The tool reads committed blobs at the requested revision, not working-tree
edits. It copies only source/helper subsets, three DNG fixtures, the Lossless
composition fixture and Gyro2 release pins/BIN into `source/`. It does not require
copying the full research archive. It refuses a Gyro2 source hash mismatch with
the release's `build.json`. Other dependencies are pinned by the chosen git
revision and individually SHA-256 recorded in `manifest.json`.

Two symlinks, `source/out/MAIN_c0000000.bin` and
`source/fpSup/out/MAIN_c0000000.bin`, accommodate the imported builder and test
helpers' different historical roots. They are created only inside the fresh
external output, never in the checkout; firmware bytes are not copied. The fp L
image is fingerprinted only. Upstream sources, their default paths, and retained
camera state are untouched.

## Compiler and validation contract

The preserved Zig 0.17.0 executable supplies Clang 22.1.8. Its SHA-256 is
`5165c9a2d17938a8173839b3adf81d025b558d38d9e9711237a6fa5b8d8bb3f7`.
The old assembler-only wrapper does not support the C target spelling. The new
output-local wrapper translates `armv7[a]-none-eabi` to Zig's
`arm-freestanding-eabi`, or **`thumb-freestanding-eabi` when `-mthumb` is present**,
and translates `cortex-a9` to `cortex_a9`. This fixes instruction-state selection
at compile time, not by changing an ELF flag afterward.

It adds `-fno-unwind-tables -fno-asynchronous-unwind-tables`: these freestanding
text payloads have no unwinder. No object sections, undefined symbols or
relocations are stripped or patched to satisfy the strict C extractor. The
actual `elf/sloader.o` is retained, accepted by the imported `elf_text.load_text`,
and checked for ELF32 little-endian ARM ET_REL and a Thumb `sl_boot` offset.
`elf/text.json` records function offsets, text size and EABI flags. The separate
upstream ARM assembler retains its existing explicitly supported local CALL/LDR
relocation handling; that is not used as a substitute C extractor.

The manifest includes source/dependency hashes, image hashes, compiler executable
and key C header hashes, Python/Unicorn versions, commands, return codes, test and
skip counts, release equality, parsed Gyro2 header and artifact hashes. Per-step
logs retain failures as well as successes. A zero exit status can still include
explicitly reported upstream skips; inspect `steps` and `missing_fixtures`.

## Result (23 October 2026)

The main session independently reran the entire driver into a separate fresh
output directory: exact Gyro2 release equality, 20 extractor tests, 39 Gyro2
tests, 22 v3 tests, the selected mutation and minimal loader/ELF checks all
passed with zero skips. The five driver contract tests also passed separately.

Release-matched source revision: `4654a6a645a303dbc4162c2856e42bb90afcdac7`
(this branch's earlier tip; rerun there on 2026-10-24 with the same results:
release-equal Gyro2, 20 extractor, 39 Gyro2 and 22 v3 tests, mutation caught).
Gyro2 builder/source hashes match the v0.2.0 release pins without any source edit.
The generated 4,040-byte `gyro/40GYR2.BIN` is byte-for-byte equal to the frozen
release and its manifest SHA-256:

```text
2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3
```

Parsed ABI: FSB1, 32-byte header, ARM entry offset 32, ID GYR2, version/build 6,
minimum service 1, allocation 60,880 bytes; code 4,008 bytes.

Executed results:

| Check | Result |
|---|---|
| Strict extractor | 20 passed, no skips |
| Gyro2 real-instruction tests | 39 passed, no skips |
| Gyro2 mutation, omit commit-magic store | unmodified passed; mutant caught (2 failures, 20 errors) |
| v3 real-instruction tests | 22 passed, no skips |
| Driver contract checks | 5 passed |
| Actual C ELF | strict extraction passed, EABI5 soft float (`0x05000200`), `sl_boot=1`, text 6,472 bytes |
| Ordinary v3, no splash/manager/Instant/Fast | built; loader 7,712 bytes, AutoRun 3,463 bytes |

The mutation run covers one selected upstream mutant, not the entire mutation
suite. It changes a copied Gyro2 source only. The fixtures include FHD, moved
OG3K MakerNote and OG2K small-tail headers; the OG2K fixture is selected from its
imported location under `projects/open-gate/test-build/`, which the unchanged
upstream test locates by filename. Lossless composition uses the pinned existing
`10LOSS.BIN` fixture; this is not a Lossless rebuild.

Minimal v3 artifact SHA-256:

```text
LOADER.BIN  fd21f0eb1e25cdef7b98bac6cbc518648f1b3c06e5801acbaef492a186d2a56b
AutoRun.txt cec232c10cf0f01338d743fd5b144a782852e8e6716f65b9758ce627c5a92b5c
```

These are a new minimal reference configuration, not a claimed match to the
release's splash-enabled loader. Exact equality of the Gyro2 artifact establishes
unchanged fp product bytes under this input/toolchain adaptation; no production
builder or firmware-address source was edited. Firmware input fingerprints:

```text
fp 5.02   49245696 bytes aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622
fp L 3.02 49310208 bytes fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9
```

The generated manifest/logs and source subset are the complete local handover;
they contain local command paths and should be reviewed before sharing. Object
hashes can include source paths/debug metadata; executable artifact equality is
checked independently.

## Provenance and next gate

Read `fpSup/NOTICE`, `LICENSE`, `SUP_BUILD_RULES.en.md`, the imported Gyro2 README,
and the strict extractor README before use. Preserve their notices. The notice
covers the author's work and explicitly excludes SIGMA firmware and separately
licensed binary components. No sibling/root license was found establishing a
blanket grant for every imported third-party item; this reference exercise does
not resolve that scope or authorize firmware redistribution. Fixtures are used
from the pinned local repository, without obtaining additional camera captures.

M0 unlocks source-based service profiling, not fp L execution. The next gate is
an owned/no-cave fp L v3 service adapter and verified firmware bindings for the
Gyro2 observer, level and Vd paths. Calibration, sensor interpretation, actual
recording, DMA visibility, timing and power-off acceptance remain separate
hardware gates. No camera/card operation, publication or plugin build occurs here.
