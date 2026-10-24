# Owned far-hook review (M2/M3 seam) — 23 October 2026

Offline review of the never-reviewed owned far-hook left by a prior delegation:

- `fp_usb_shell/v3/fpl_level_transfer.S`
- `fp_usb_shell/v3/fpl_owned_hook.py`
- `fp_usb_shell/v3/test_fpl_owned_hook.py`

Reviewer scope was offline only: no camera, no daemon/socket, no commit/push, and
edits limited to the three files above plus this note.

## Verdict

**Accepted, with one fix applied and one part not executable in this environment.**
The hook mechanism is sound and the generator/audit path runs against the real fp L
3.02 image. The installer *lifecycle* (claim/journal/cache-order/restore) is
implemented with matching test assertions but could not be executed here because the
v3 loader-C build is incompatible with the installed toolchain (details below). That
gap is in the build toolchain, not in the hook.

## What the code does

A far transfer from a firmware call site that ARM `BL` cannot reach into owned USER
RAM, by overwriting two words at the site with an absolute-jump trampoline.

- Site `0xC0509730` holds `mov r2,#0` (`0xE3A02000`) then `b 0xC0509748`
  (`0xEA000003`, target = RESUME). Confirmed byte-exact in the real image.
- Armed, the site becomes `ldr pc,[pc,#-4]` (`0xE51FF004`) at `SITE` and the veneer
  address literal at `SITE+4`.
- The veneer (in USER RAM) is `mov r2,#0 ; ldr pc,[pc,#-4] ; .word RESUME`, i.e. it
  replays the first displaced instruction and then jumps to the original branch's
  absolute target. Both displaced instructions are therefore replayed.
- The installer (`entry`) runs once per owned block, verifies both stock words
  itself, claims all 8 bytes through the owned service (full journal coverage of both
  patched words), publishes D/I caches for the veneer *before* arming, writes `SITE+4`
  (literal) before `SITE` (the `ldr pc`), then republishes caches. `SL_KEEP` is
  returned in every path, including refusal, so nothing frees on return.

## What is proved (offline, against the real image)

Firmware image: `FPL_V302/MAIN.bin`, SHA256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` (matches the
fingerprint the builder requires).

1. **Generator / audit** — `fpl_owned_hook.build(image, offline_quiescent_model=True)`
   succeeds: fingerprint + both stock words verified; the direct-branch scanner finds
   exactly the two expected Thumb false-positives (upper halves of ARM instructions at
   `0xC0508FF2`, `0xC05093F2`), matching the hard-coded exclusion list; the offline
   model gate refuses a plain `build(image)` and a wrong `site`. Produced bytes:
   veneer `[0xE3A02000, 0xE51FF004, 0xC0509748]`, stock `[0xE3A02000, 0xEA000003]`.
2. **Placement is genuinely far** — `bl_reachable(SITE, 0x44400000) == False`; a USER
   veneer is out of BL range, which is the whole reason for the trampoline.
3. **Displaced-instruction replay + flag/ABI preservation** — standalone unicorn run
   (Cortex-A15) of the real site: patched path (trampoline→veneer→RESUME) lands at
   RESUME with register/CPSR state **identical** to the stock path
   (`mov r2,#0 ; b RESUME`) for flags `0x0, 0xF0000000, 0xA8000000, 0x60000000`. Only
   `r2` is touched (to 0), exactly as the stock instruction does; LR, SP, r0–r12 and
   flags preserved.
4. **Mutation catches a broken replay** — changing the veneer's first instruction from
   `mov r2,#0` to `mov r2,#7` makes the patched result diverge from stock (`r2`
   differs); the equivalence check fails as it must.
5. **`adr` targets** — after the fix, the three `adr` instructions resolve to
   `result`/`veneer`/`stock` (offsets 260/240/252), semantics unchanged.

## Fix applied

`fpl_level_transfer.S`: the labels were declared `.global entry, veneer, stock,
result`. A global symbol is preemptible, so clang could not resolve the PC-relative
`adr`s at assemble time and emitted `R_ARM_ALU_PC_G0` (type 58) relocations, which the
card loader's `armasm` does not implement — the file did not assemble at all. Only
`entry` needs to be global; the replay/table labels are now local and are still read
by offset through `armasm.symbols()`. This was the reason the prior delegation never
got a passing run.

## What is NOT proved here

- **Installer lifecycle under the boot harness** — `test_fpl_owned_hook.py`'s arming
  order, journal-before-claim, cache-publish-before-arm, collision-refusal-without-
  partial-patch, and power-off stock restoration are implemented with matching
  assertions but were **not executed**: every test errors in `setUpClass` →
  `envelope()` → `build_v3.loader_bin`, because the v3 loader C build fails under the
  installed toolchain (see below). The assertions were read and look correct, but
  reading is not running.
- **Absence of other entries into the site** — the hook itself records
  `indirect_entries_proved_absent=False`; the scanner only covers direct ARM/Thumb
  immediate branches.
- **Live admission / duplicate refusal / quiescence** — explicitly out of model
  (`live_install_authorized=False`); the install window is "quiescent only" and the
  intermediate state (literal written, `ldr pc` not yet) is unsafe if executed.

## Environment blocker (toolchain, not the hook)

`$HOME/.local/share/fpsup-toolchain/bin/clang` is a thin wrapper that rewrites only
`armasm`'s exact token `armv7-none-eabi` and otherwise calls `zig cc`. `build_v3.py`
compiles the loader with `--target=armv7a-none-eabi -mcpu=cortex-a9`, which the
wrapper does not translate and `zig cc` rejects (`unknown architecture: 'armv7a'`).
This blocks **all** v3 tests that build the loader (`test_fpl_v3`, `test_v3`,
`test_boot_options`, `test_fpl_owned_hook`), not just the hook.

A zig-native triple does compile the loader C (`--target=arm-freestanding-eabi
-mcpu=cortex_a9`), but further divergences appear (unwind-table symbol
`__aeabi_unwind_cpp_pr0`, then a `.text` relocation the project's mini ELF reader
rejects), so the zig codegen is not a drop-in substitute. Fixing this belongs in the
toolchain wrapper or `build_v3.py`, both outside this review's scope.

## Exact commands and results

```
export PATH="$HOME/.local/share/fpsup-toolchain/bin:$PATH"
cd fpSup/fp_usb_shell

# In-repo suite (all v3 suites behave the same):
python3 -m unittest v3.test_fpl_owned_hook
#   -> Ran 0 tests; ERROR in setUpClass: build_v3.BuildError "unknown architecture: 'armv7a'"
#      (loader-C build, before any hook test body runs; not a skip)

# Generator/audit against the real image (passes):
python3 -c "from v3 import fpl_owned_hook as h; \
  img=open('<HOME>/.local/share/fpsup-research/fp-vs-fpl-2026-10-13/FPL_V302/MAIN.bin','rb').read(); \
  p,s,e=h.build(img, offline_quiescent_model=True); print(len(p), s['entry'], e['patch_bytes'])"
#   -> 296 32 8 ; scanner == expected exclusions ; gate refuses non-offline build

# Standalone trampoline+replay equivalence and mutation (passes):
#   stock vs patched register/CPSR identical for 4 flag states; mutation caught.
```

## Smallest next step

Unblock the loader-C build so the installer-lifecycle tests actually run: either teach
the toolchain wrapper to translate `--target=armv7a-none-eabi`/`-mcpu=cortex-a9` to the
zig spellings and suppress unwind tables, or point `build_v3.py` at a clang that
accepts the `armv7a` triple. Then run `python3 -m unittest v3.test_fpl_owned_hook -v`
and confirm all methods pass (journal, arming order, cache order, collision refusal,
power-off restore) with no skips — that is the one remaining piece of this hook not yet
executed offline.

---
Note for whoever commits: the working tree also carries unrelated changes to
`docs/FPL_GYRO2_FORMATTER.md` and `docs/FPL_ROADMAP_IMPLEMENTATION.md` (an N=560 live
take) made by a concurrent session during this review; they are **not** part of this
work.

## Follow-up run with the M0 compiler wrapper (main, 23 October)

The loader-C build is not blocked when the M0 wrapper
(`reference-builds/2026-10-23-m0/bin/clang`, documented in
[headless v3 services](FPL_HEADLESS_V3_SERVICES.md)) is first on PATH. With it,
`python3 -B -m unittest -v v3.test_fpl_owned_hook` (FP_MAIN/FPSUP_FP_MAIN/
FPL_MAIN/FPL_DATA/FIRMWARE_ROOT set) ran 6 tests, no skips: **5 passed, 1 failed**.
Passing: branch scanner, fingerprint/reach boundaries, replay mutation, overlap
refusal without partial patch, stock guard before claim. Failing:
`test_replay_two_native_owned_addresses_flags_and_shared_restore`. Its
**unpatched (stock)** reference run stops at PC `0x47000000` instead of RESUME
`0xC0509748`, so the failure is in the test's stock-path setup (it never reaches
the comparison of the patched path), not yet evidence against the veneer.

**Fixed.** Tracing showed the stock path does pass RESUME (`C0509730 -> 734 ->
748 -> ...`): unicorn skips its `until` check when the stock direct `b` chains
into the RESUME block, so emulation ran on through the epilogue to DONE. The
test now stops on RESUME with a code hook. Result: **6 passed, no skips**.
Mutation `mov r2,#0 -> #7` in the veneer fails 2 tests (replay bytes and the
mutation guard); reverted. **Accepted offline** as a quiescent-model far
transfer for this one site. Still not proved: live admission/quiescence and the
absence of other entries into the patched words; nothing has run on the camera.
