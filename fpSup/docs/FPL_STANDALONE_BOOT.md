# fp L ordinary-boot native Slit scan menu — 30 October 2026

**Experimental development card, not a release.** Two ordinary debug-card
software boots installed the native menu without a post-boot RAM installer.
The later [recording](FPL_RESIDENT_RECORDING.md) and
[frame-observation](FPL_RESIDENT_OBSERVATION.md) stages extend this same owner.
The latest active-take mode-change trial hung the camera; physical recovery and
original-card restoration remain pending. Earlier successful restorations are
historical, not the current state.

## Build

Supply official, fingerprinted fp 5.02 and fp L 3.02 MAIN images externally,
with Python dependencies and an ARM-capable compiler on PATH:

```sh
python3 -B fpSup/slit_scan/build_card.py \
  --fp-main "$FP_MAIN" --fpl-main "$FPL_MAIN" --out NEW_DIRECTORY
# Add --debug for the existing diagnostic USB shell.
# Add --recording for the resident timing/observation backend.
```

Both `NEW_DIRECTORY/card/AutoRun.txt` and `fpSup.BIN` form the ordinary card.
No Fast, persistent bootstrap, loader hook, manager or sidecar menu is used.
On SHOOT 2, focus Slit scan: Right/OK advance and Left decrements through
Off / 4 / 6 / 8 / 12 fps, with wraparound. Selection starts at Off each boot.
Without `--recording`, these are selection only. No firmware storage or
persistent setting is written by this menu implementation.

The no-shell variant has no USB worker/interface/NOPTP patches. It is emulated,
**not hardware-boot-tested**. The debug variant retains unresolved shell USB
lifecycle/bootstrap-patch lifetime limitations. A cold stock start is required
for first no-shell acceptance after a diagnostic configuration.

Changing from the historical diagnostic AutoRun requires **both files once**;
its 90-second delay is removed. Within the same ordinary/debug configuration,
payload updates leave AutoRun byte-identical. Artifact hashes identify evidence,
not runtime pairing. Replacing the BIN on card does not unload a resident menu.
The existing `fpl_deploy.py` remains an equal-size, unchanged-AutoRun updater;
it is not a general pair-replacement tool.

## Shared chain and retained ownership

`build_card.py` invokes the existing `build_autorun.py --loader` path with
`--fpl-ui-boot`, stock declarations and `--boot-bin`. The shared `loader.S`,
`stage2.S`, `entries.S`, both placement passes and entry ABI remain in use.
Debug entries are worker → product launcher; the plain build has only the latter.

An opt-in stage2 admission table checks the six original string words and the
native drawing object's stock vtable before journal allocation, registration,
placement or entries. Nonstock values refuse without following them. Default
fp/fp L shell builds carry no admission table. The loader's return means stage2
returned, not that the product installed.

The journal declares seven four-byte words: six string words and
`C38D37CC = C2E55A70`, the live-verified native drawing BSS vtable. Both shutdown
lists use the same shared restore object; there is no product power-off callback.
The product verifies the complete restore body, both registrations and originals
before arming. Recording additionally declares the empty early-Vd slot.

`launch.S` is a returning product entry, not a second loader. It allocates one
aligned 64-KiB USER block, validates its descriptor, clears private state, copies
the wrapper/runtime/FPUI extents and publishes D then I cache before initialization.

| Owned offset | Contents |
|---|---|
| `0000`, `0020` | allocation descriptor, initializer result |
| `0400` | drawing command/result/callback observations |
| `1000` | relocatable shared `fpl_ui_draw.S` wrapper |
| `2000` | native 40-byte vtable copy; only update slot replaced |
| `3000..7fff` | adapter/controller/runtime/initializer |
| `8000..83ff` | runtime state |
| `8400..ffff` | additive FPUI block |

`boot.c` validates the UI reader, exact MainB2 entry, drawing object/listener,
task 39 and shared journal. It arms the existing IRQ/FIQ-excluded single-word
drawing publication last. The wrapper preserves the original update's return;
its outermost task-39 callback then invokes `slit_tick` to register variables,
publish page/strings and pump summaries. The loader task never waits for GUI work.

All allocations and native borrowers remain retained through shutdown, including
partial failures and in-flight calls. The nonstock drawing table is the duplicate
refusal boundary after publication. A pre-publication failure can leave an
unreachable retained allocation/journal; it does not authorize reclamation or
solve general cross-loader discovery, boot identity, concurrency or M2 admission.

## Historical live evidence and provenance

Two software boots initialized runtime phase 2/error 0, five private variables
(2,203 total), and the complete shared journal. No host RAM installer ran.
Right/Right/OK/OK/Right/Left displayed 4/6/8/12/Off/12; MENU exit/reentry retained
selection and the original audio row remained On. The second boot reset to Off.
Immutable owned extents were read back and compared. Recorder/exposure remained
unchanged. The original card and stock state were restored after this stage;
the later observation-stage failure supersedes that restored-state result.

| Historical debug artifact | Bytes | SHA-256 |
|---|---:|---|
| AutoRun.txt | 6,654 | `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c` |
| fpSup.BIN | 50,812 | `b117cb5d9601417b3a8d22bc3303b4ec050e43c5efaf7ced55cd97418e8399bd` |
| launch.bin | 45,616 | `105d3d2d6b64f249e8f63911a05e24ea0aa5dc89a5e45503972472ebed38e58f` |

Historical plain BIN: 46,696 bytes,
`b2794875071ff65a46ef1044ad66297045a35263f4ca0da04f65a7df6d80fa8f`;
plain AutoRun: 6,564 bytes,
`a27965148c4175a4b2d853e9b38571fb6a8975182fd9eacb735401dedffe43f7`.
The plain card was not deployed. These stage-one hashes are not current recording
build hashes. Generated artifacts and raw evidence are not distributed here.

## Offline evidence and outstanding acceptance

Stage one passed 33 product, 46 shared-chain/drawing and eight packaging tests.
The fixture executes the emitted AutoRun, real loader/stage2/entry/launcher and
native registry/key instructions after staging is poisoned. File APIs, allocators,
scheduling, CP15/cache effects and the original drawing method are modeled.
Admission-bypass and first-owned-I-cache-publication mutations are detected.
Current exported-source checks are in [export validation](FPL_EXPORT_VALIDATION.md).

Still open: no-shell hardware boot, physically disconnected USB, about ten
physical no-record power-switch cycles, retained-image previous-card boot and
callback quiescence. General M1/M2, v3 and Fast acceptance remain open.
Catalogue reproduction is blocked by the unavailable original `logo2.png`;
no catalogue/release acceptance is claimed.
