# Retained launcher through the shared boot chain

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Offline diagnostic integration, 2026-10-23. **26 focused tests passed**, including
two new boot tests with eight configurations (success/refusal, two retained-owner
placements, two incoming stack phases). No hardware boot evidence is added.

## Composition and admission

`fp_usb_shell/test_fpl_retained_boot.py` composes through the existing
`card_build.artifact()` and `card_build.build_vbin()` APIs. It uses the actual
`asm/loader.S`, `asm/stage2.S` and generated `asm/entries.S` trampoline. No shared
builder or load-chain source was changed; no additional build helper was needed.

The `build_autorun.py --fpl-shell` allowlist deliberately excludes arbitrary
product switches, including `--boot-bin`, so future fp options cannot silently
become fp L support. This test uses the existing lower-level packer rather than
relaxing that gate. It produces no AutoRun and makes no public-product or Fast
compatibility claim. The build contract and composition skill were read.

Sections, in order:

1. Shared fp L stage2, with its existing journal registration enabled.
2. Shared worker built with `FPSUP_PONG_ACK=1`.
3. The unchanged created-unattached retained launcher and embedded template.
4. A four-byte ARM `bx lr` continuation witness.
5. Four diagnostic bytes, `PASS`, destined for published-pool offset `0x9000`.
6. The packer's ordered-entry trampoline: worker → launcher → witness.

The worker uses its existing publication convention. The retained launcher and
witness publish nothing. The pool-offset section is solely a test witness for
pass 2, not a new production allocation/publication policy. The PONG resident
body is checked against reviewed SHA-256
`e2b94aeb67938dbb05f581ca6f8ec5aff1e84dfe7dd34de11a1b76e0c7f2b342`.

## Executed path and assertions

The emulator enters the real loader in the borrowed dir-handler region. Mock
file reads supply the composed VBIN to the loader's requested 64-KiB staging
allocation at `0x45000000`, with file bytes at `+0x1000`. Execution traces:

```
loader → stage2 → entries → worker spawn → retained launcher
       → continuation → pass-2 write → loader staging free → caller
```

The fixture independently observes `s2_pass` with r8 values **1 then 0**. It
checks stage2's file-base argument, the resolved self-address r0 and aligned
stack at the trampoline and each entry, stage2 D/I publication before entry,
both launcher/runtime D/I pairs, and stage2 D/I publication after pass 2 but
before loader free. Incoming stack phases 0 and 4 are restored on return.

Worker spawn executes its real allocation/copy/publication instructions, creates
one mocked worker task, and returns. Its copied resident body is compared byte
for byte. Both journal callbacks are registered through the existing mock.

The launcher executes real USER allocator and retained native-wrapper kernels.
On success, its ownership/result copy remains at `owner+0x400`; the native task
has been created, **not attached**, and capture has not run. On actual synthetic
heap exhaustion, launcher phase 3 returns normally with no native task or owned
payload writes. In both cases the continuation runs and pass 2 writes its
witness only afterward.

At the real loader's H_FREE call, the mock verifies the loader descriptor and
existing destruction mode, poisons the **entire 64-KiB staging block**, and returns.
Any subsequent CPU read, write or execution within that block is rejected.
After the loader returns, tests compare the retained ownership record, execute
native observation (7), then independently activate and capture, observe (15),
and validate resident readbacks. This external test action is not part of boot.

## Explicit model boundaries

- `test_fpl_shell_card.ShellTrial` supplies file APIs, loader/worker allocations,
  H_FREE, journal allocation/registration, worker task creation/start and cache
  effects. H_FREE is observed and modelled, **not executed as native reclamation**.
- `test_fpl_retained_launcher` supplies real USER allocation/list/IRQ instructions
  and native task constructor/query/worker kernels. Its telemetry/static guards,
  native task backend and scheduling boundaries remain mocked.
- Loader, journal and USB-worker allocations are disjoint synthetic blocks, not
  allocations on the retained fixture's native USER list. That fixture retains
  its earlier reserved 32-KiB block as heap occupancy, but it is not this test's
  loader staging. Unified native allocator separation remains the launcher-only
  test's evidence; this boot test does not upgrade that to live heap evidence.
- Retained owners are `0x44500000` and `0x45a00000`; loader staging is fixed here.
- The USB worker's spawn and resident copy are exercised; its serve loop, PONG
  transport, USB enumeration and DWC3 behavior are not exercised.
- Journal setup executes, but power-off restoration is not invoked. Cache
  publication order is checked; hardware coherence and boot-context behavior
  remain unproved. No safe reclamation of the retained task is claimed.

## Reproduction and artifacts

Main independently reran the focused command below after delivery: all **26
tests passed**. This reproduces the integration model, not a camera boot.

From `fp_usb_shell/`, with the ARM toolchain on PATH:

```sh
python3 -B -m unittest test_fpl_retained_boot test_fpl_retained_launcher test_fpl_shell_card test_card_packaging
```

Result: **26 passed**. The boot tests construct the diagnostic in memory through
`composition(build())`; tests do not write a card or open a transport. Shared
load-chain sources were untouched, so the requested focused checks were used.

Durable offline bytes are in fresh directory
`out/fpl-retained-boot-diagnostic-20261023/`, with hashes and section offsets in
`manifest.json`. No existing output was overwritten. The VBIN is 18,356 bytes,
below the existing `0xF000` read cap; its header entry is offset 18,268.

| Artifact | SHA-256 |
| --- | --- |
| `fpSup.BIN` | `2875ddeb35c3290a621341d843add9a419298f4d0e3c38d283f2ea5a5ef5f552` |
| `loader.bin` | `40ace33a3cc303c95df4ca8996b7290eadb1b6d3880a8b65f35f4cd7547b3321` |
| `stage2.bin` | `604658520dd0395d2be6189151f0729ba6522e4b0f9dea185c8e587d6f0b637a` |
| `retained-launcher.bin` | `081b3a58e806a5081798e309aa4f1790e094102d950a8d9e6380fa61b6c070d5` |
| `pong-worker.bin` (including spawn) | `41f34b34f81e9404a855710b79ddc820b1d58c0bfcd82a95bac313f5d5dd95c3` |

The composer verification was also executed with catalogue-directory writes
guarded. All seven payload reproductions, current AutoRun comparisons, four
OG2K/OG3K merge comparisons, two reference AutoRun comparisons, and JavaScript
parsing passed. The run then intentionally raised at the final `artifact.html`
write guard; it did not regenerate the catalogue. These checks use shipped OG
artifacts and independent recomposition, not a rebuild of external OG sources.
No external dependency was missing for those checks.

At the time of this run, the following research evidence files were absent:
`../projects/usb-shell-sup/notes/CARD_BUILD_PIPELINE.md` and
`../projects/open-gate/notes/OG_BOOT_RESTORE_STABILITY_REVIEW_2026-09-23.md`.
Their historical/live claims were not verified or substituted.

No camera operation, card write, current-marker change, commit, push or release
was performed. Port and live-log documentation remains owned by the main session.
