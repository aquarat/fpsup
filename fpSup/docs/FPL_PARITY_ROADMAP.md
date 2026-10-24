# fp L feature-parity roadmap

**Research cut: 23 October 2026. Target: SIGMA fp L 3.02; reference: SIGMA fp 5.02.**

## Decision

Deliver a dependable ordinary-boot development shell first. In parallel, reproduce the now-public v3/Gyro2 build inputs and implement a no-cave product-service adapter. Continue the existing shared finite gyro diagnostic as the measurement platform, but **do not make completion of the entire legacy Base mailbox/sidecar logger a prerequisite for Gyro2**. Gyro2 is now a realistic source-based port, with a better end-user recording workflow. Base/GCSV remain compatibility targets after that architecture choice.

The biggest correction to the October 20 plan is source availability: **upstream has published its research and projects trees**. Gyro2, FCAP, Unlocked Writer, OpenGate/Res-Custom builders, the strict ELF extractor and UI helpers are no longer categorically missing upstream. Availability is not build reproduction, and Res-Custom's released-source revision remains unresolved.

The existing live retained task, all its storage and its host pending interlock must remain untouched. The next work is offline discovery/admission and product integration; another invocation, cancellation, reclamation or reboot of that retained instance is not implied by this roadmap.

## 1. Exact comparison and evidence standard

Latest upstream `main` and remote `HEAD`, independently checked with `ls-remote`:

- **`e79e3f1ff4622bce0b8a4cee9d322f184d7f6696`**.
- Author and commit date: **2026-10-23 19:39:07 +08:00**, or **11:39:07 UTC**.
- Subject: *IMX410 Lab simulator: show frames at the sensor's output aspect*.
- Repository: <https://github.com/ijigen/fpSup>.
- Previous reviewed upstream: `dbaf2c95e21a3efcedcd82d8a556fc7566784ece`.

An isolated partial clone supplied commit objects, tree listings and selected source blobs. Its initial full checkout timed out; the assessment therefore uses explicit `git show`/tree reads, not a claimed complete checkout or build. No fetch, ref/index operation or edit was made in the primary repository. No camera, settings, card or pending-marker operation occurred. No build or test suite was executed for this report.

The comparison included the October 23 working tree and then-untracked files, especially the retained-task/relocation/launcher/boot tests, shared gyro includes, and recording/sensor audits. Integration has since preserved that work under `fpSup/`. Product-local paths below are relative to `fpSup/`; repository-wide `projects/` and `research/` paths remain relative to the repository root.

Evidence labels:

- **Live:** a documented fp L trial, limited to the exact operation and bytes described.
- **Offline:** source, actual-instruction emulation or host tests reported in local notes; not hardware acceptance.
- **Absent:** no fp L implementation/acceptance found for the product.
- **Upstream claim:** release/readme evidence for fp, not a new test by this review and never fp L evidence.

### What changed since dbaf2c9

There are **18 first-parent commits** after that revision; the merge also brings older research history into reach. The important commits are:

| Commit | Consequence |
|---|---|
| `2b9fe5758854bfba35ce2303c1d274e504dd896c` | Moves the old product/site tree into `fpSup/`. Path-aware integration is necessary. |
| `c2e94ec1583cfedb6d441c7a50b9fcb347c6fedf` | Merges the research/projects development repository. Previously external sources become public. |
| `b7a707f60b063bac087f03cd83465e7af6f132b5` | Adds private-material exclusions and a firmware pre-commit check. |
| `bd2b6d5dc6fa607630889005a4aa95fdb1179a08` | Synchronizes research/projects on October 23; current development sources need not equal released ones. |
| `acfe0de45ad993d4dc9ef673ddff99b1fdff303a` | Narrows Mac ioreg collection to the camera subtree. |
| `726b15599c09c8ed980b1ead061ba7bb21271f85`, `e79e3f1ff4622bce0b8a4cee9d322f184d7f6696` | Add/fix the IMX410 readout simulator; this is a research tool, not an fp L sensor feature. |

After accounting for the directory move, `fp_usb_shell`, `lossless` and `uishare` tree objects are identical to dbaf2c9. `gyro` changes only three release/web text files. Thus the substantial new opportunity is the research-source import, not a new shared USB or Base algorithm that automatically solves port blockers. The current release catalogue still selects the products below; development-tree activity does not create a new released version.

## 2. Define parity by behavior, not sensor equivalence

Parity means the same supported user workflows, formats, failure behavior, restoration and composition semantics on **explicitly supported fp L modes**, with a published capability matrix. It does not mean running fp BINs or reproducing fp addresses, sensor readout timings or throughput numbers.

The fp L firmware identifies an IMX455 configuration; upstream's sensor work targets IMX410. Different sensor geometry/readout, mode tables and processing budgets make literal fp sensor-mode parity an invalid promise. Matching a full-area 3:2 recording workflow is a reasonable target; matching every fp OG raster/rate/rolling-shutter figure is **unknown**, and some combinations may be physically unavailable. Do not call an untested mode impossible merely because the current port lacks it. Conversely, a simulator or timing-register write cannot create missing sensor readout hardware.

For every recording mode eventually offered, establish encoded raster, active field of view/crop, Bayer order, bit depth, real frame cadence, shutter behavior, rolling shutter, sustained storage rate and playback. Host tools must use fp L measurements, not inherited 6000-column/72-MHz calculations, gyro scales or nominal USB speeds. The observed fp L USB connection was High Speed; fp's claimed 398/382 MB/s is not an fp L measurement or guaranteed requirement on that connection.

No parity milestone requires Slit-scan, HDRx, Split Record, AF Optimisation, LUT, RES-Lab, the sensor-lab prototype, 6K-to-SSD research or unfinished focus/power projects. RES-Lab and several of those are visible development placeholders, not selectable current releases. Slit-scan remains a separate exploratory branch of research.

## 3. Current upstream product matrix and fp L disposition

Versions are from the current release table and actual Merge builder, not older project-summary prose. All release behavior in this table is an **upstream claim** unless the fp L column explicitly says otherwise.

| Product / workflow | Current upstream offering and intended behavior | fp L evidence and decision |
|---|---|---|
| USB shell + recovery | `fpsup-usbshell-v3.4.0test`: shell replies, memory transport/windows, folder-loaded `00SHELL.BIN`, conflict refusal and load log. Recovery is tooling/lifecycle behavior, not another product. | **Live partial:** shell, RAM transfers and card upload/download; reviewed equal-size handoffs and pending reconciliation. Ordinary short AutoRun **offline only**; unattended reboot/reconnect, arbitrary replacement, recording coexistence and power-off acceptance incomplete. **P0.** |
| Gyro Base | `fpsup-gyro-base-v1.14.0`: raw `.GYR` gyro/accel stream on the take's volume; browser conversion. | **Live diagnostic only:** shared raw drain and retained finite capture. No continuous `.GYR` recording product, take association or calibration. Preserve shared producer and decoder seams; sidecar product follows lifecycle decision. |
| Gyro/GCSV | `fpsup-gyro-v1.14.1test`: recording `.gcsv` plus lens `.json`; release itself still needs audio-sync validation. | **Absent product.** Same `gcsv_task.S` edition path as Base; do not fork another fp L logger. Calibrated timing, axes, lens model and actual take identity are mandatory. |
| Gyro2 | `fpsup-gyro2-v0.2.0`, `40GYR2.BIN`: per-frame CinemaDNG FSG2 data, Vd timing and level/lens metadata; compatible with Lossless. | **Absent port; source now present and release-matched.** Preferred eventual recording gyro workflow. Needs v3 services, no-cave hook placement, fp L tag observer/Vd/level bindings and plugin sensor adaptation. **P1/P2.** |
| Lossless | `fpsup-lossless-v0.3.0test`: hardware lossless CinemaDNG with uncompressed fallback, menu control and camera playback. | **Absent port.** Actual shared C/assembly/tests available. First establish codec/RAW ownership and native-reader ABI on stock fp L modes; then port streaming. Do not start with custom sensor formats. **P3.** |
| FCAP | `fcap-20261015` catalogue snapshot: lowers the file batch cap from 128 to 40 to avoid descriptor exhaustion with small frames. | **Absent port; source now present.** Implement alongside small-frame/Lossless acceptance once fp L writer pool/batch semantics are verified. Lossless ticks FCAP through a soft link, not a hard dependency. |
| Unlocked Writer | `fpsup-unlocked-writer-v0.1.0test`, `20ULWR.BIN`: dedicated zero-copy batch writer without holding the filesystem lock during I/O; SD automatic detection, SSD with Write Mode. | **Absent port; source now present.** Later optimization, not prerequisite for the first shell or gyro product. Requires genuine writer ownership/error-unwind proof. Release evidence used predecessor RECW bytes, not proof of every renamed shipping combination. |
| STOPFX | `stopfx-20261012`, 316-byte `05STOPFX.BIN`: clears pending frames after abnormal stop. | **Absent; binary snapshot and validation exist, authoritative source not located.** Obtain source/terms from author before reuse. Verify that the fp L fault exists; do not transplant its patch. |
| Res-Custom | `fpsup-res-custom-v0.1.4test`: `.RCD` formats OG2K/OG3K/OG3.5K/OG4K/S16 in Settings and Quick Set. | **Absent product; sensor transport/timing research offline.** Builders now public, but current sources differ from release pins. Port data/UI consumer with one evidenced fp L mode, not fp RCDs. **P4.** |
| Separate OG2K / OG3K | `fpsup-og2k-v0.1.5a`, `fpsup-og3k-v0.2.8a`: older separate open-gate cards; mutually exclusive. Current v3 Merge uses Res-Custom instead. | **Absent.** Do not build two new legacy implementations before Res-Custom. Functional full-area workflow through Res-Custom can satisfy modern parity; document any deliberately unprovided legacy card format. |
| RAW-View | `fpsup-raw-view-v0.3.0test`: preview clipping/gain/latitude behavior for CinemaDNG 12-bit; recorded RAW unchanged; settings on card. | **Absent; `projects/rawview` source now available.** Port after display/UI groundwork; fp L gain/saturation/colour behavior needs measurement. **P3/P4.** |
| ScreenFlip | `fpsup-screenflip-v0.1.0test`: per-custom-display-mode 180° flip/mirror. | **Absent; source in `screenflip/`.** Good first optional display product after shared UI services, since it need not alter recording data. **P2/P3.** |
| Desqueeze | `fpsup-desqueeze-v0.1.4test`: 1.33/1.6/2.0 preview, scaled guides/indicator; records unchanged. | **Absent; released third-party BIN, source not located in current tree.** Seek author's source and licensing/provenance; do not rebuild behavior by disassembling available binaries first. |
| Tap to Zoom | `fpsup-tap-to-zoom-v0.1.0test`: tap-centered 2× and dial-selectable 4×/8×; exposure controls preserved; chains with Desqueeze. | **Absent; released third-party BIN, source not located.** Same acquisition path. Explicitly test fp L touch-AF coexistence. |
| v3 loader, manager and native UI | Folder products, `LOAD.LOG`, claims/chains, optional management page, Settings/Quick Set, on-card preferences. | **Absent fp L v3 product support.** Restricted ordinary headless packaging is not v3. Recover/reproduce common build first, then no-cave services; manager/UI can follow headless v3. **P1/P2.** |
| Instant / Fast start | Current v3 has independent Instant warm RAM-hook and Fast cold settings-bootstrap choices; manager gives eight boot combinations. Legacy Fast Start 3 combines settings bootstrap and loader hook. | **Absent/refused.** Ordinary boot first; warm-resident loader ownership and persistent settings recovery are separate gates. Neither elapsed-time parity nor legacy/v3 option equivalence is established. **P4.** |
| Merged cards | Modern `tools/merge-v3` builds complete boot variants and selects frozen products; legacy single-BIN composer remains for older cards. | **Offline partial only:** legacy reference comparisons and diagnostic ordered entries. No fp L selectable product catalogue. Enable only accepted model-specific products; test conflict/chain/order and options. **P2 incrementally, P5 full matrix.** |

Release limitations matter: upstream's shell notes explicitly leave exact-folder-alone and power-off checks open and advise against commands during recording/playback. Gyro2 reports limited fp recording combinations, not every rate/depth/media or platform. Product headlines are not broader hardware certification.

## 4. Source, reproduction and licensing: revised blockers

### Now available: use instead of reinventing

1. **Gyro2:** `projects/gyro2-sup/build.py`, `src/gyr2.S`, `test_gyr2.py`, `mutate.py`, `fsg2.py`, verification tools and design notes. Both source SHA-256 entries in the v0.2.0 release `build.json` **match latest upstream exactly**. This removes the old missing-camera-source blocker. The assembler, official fp reference image and v3 runtime still need a reproducible build/test environment.
2. **Strict extractor:** `research/ui/tools/arm_text/elf_text.py` and `test_elf_text.py` exist. Its contract rejects text relocations, writable allocated sections and named undefined symbols; read-only metadata such as `.ARM.exidx` is validated rather than loaded. The October 20 compiler experiment's undefined unwind personalities therefore still need resolution with the real helper. Pin a working Thumb toolchain and run its tests; do not silently strip/apply relocations or replace it with a linker.
3. **UI:** `research/ui/tools/native_ui_audit.py`, `nbr.py` and `projects/open-gate/build/sl_pages.py` exist. This removes the corresponding blanket missing-helper claims. Reference assets, official images and exact release revisions still need declaration.
4. **Recording stack:** `projects/rec-core/fcap` and `projects/rec-core/writer` contain builders, source, tests and validation. Lossless remains in `fpSup/lossless`. These can be profiled/adapted once fp L ABI and ownership are known.
5. **Sensor/UI products:** OpenGate/Res-Custom and RAW-View development trees are available. Do not mistake a development builder for a release-identical source set.

### Still missing or unresolved

- **Res-Custom v0.1.4test reproduction:** its provenance says `product_bytes_rebuilt:false`. Against latest upstream, two of eight recorded source paths are absent (`vr_ui.py`, `test_lv_text_style.py`); the other six hashes differ, including `uishare/ui_apply.c`. Locate the pinned files in imported history/validation snapshots and test the accepted build; if not recoverable, ask upstream for that exact set. Current source availability does not close this release-reproduction gap.
- **STOPFX, Desqueeze and Tap to Zoom:** current tree searches found artifacts but no corresponding implementation sources. STOPFX's manifest has an empty source-hash map. Author engagement is the direct next action, not speculative firmware reimplementation.
- **Gyroflow plugin:** external <https://github.com/ijigen/gyroflow-plugins>; release requires v0.1.10 or later. Independently observed remote HEAD is `4b3dbacdbaeba7b78b5a607d05d327ffd50aa98d`; no matching `v0.1.10*` tag was returned. This HEAD is a research pin, **not a verified release-compatible build**. Select and record the actual tested source revision, format contract and build dependencies; add fp L sensor/timing interpretation and test recordings.
- **Official firmware/toolchain:** images remain external, fingerprinted inputs. New research publication is not a firmware redistribution grant. Existing path assumptions and compiler invocation problems remain engineering work.
- **Licensing scope:** `fpSup/LICENSE`/`NOTICE` give GPL-3.0-or-later for the author's covered work, with supplemental naming/trademark text and explicit exclusions for firmware and separately licensed binary-only components. Preserve notices and mark the fork distinctly. The newly imported sibling trees have no root LICENSE found by this inventory; establish applicability/provenance of reused project files rather than infer all third-party material is covered by `fpSup/LICENSE`. Request explicit source/redistribution terms for third-party BIN-only tools. Keep the plugin's own GPL obligations and dependency notices with that product. This is a concrete source/provenance task, not a claim that every release directory is reproducible or uniformly licensed.

## 5. Current fp L work: what must be carried forward

### Live evidence already worth preserving

`docs/FPL_PORT.md`, `FPL_TOOLS.md` and the investigation log document working shell execution, bidirectional RAM transfer, card upload/download, same-image handoffs and one reviewed different-build PONG handoff. The saved replacement BIN was read back but not boot-tested. An ordinary software reboot failed to reconnect in the recorded trial; unattended recovery is unfinished.

The retained native-task trial completed **20 capture observations and 997 conditional-prefix records**, with full readback, native-completion evidence, echo restoration, revoked temporary windows and final PONG. There were three host task observations, not twenty task-lifecycle observations. **`proven_valid_records` remains zero.** No continuous recording, calibration, timing synchronization, safe reclamation or repeatable activation is established. Storage/native objects and the pending interlock remain retained.

Earlier finite trials (strict drain, latched 1,142 records, runtime-reference 1,114 records) are useful component evidence; none can be concatenated into proof of a lossless continuous stream.

### Completed offline work: do not assign it again

- `gyro/latched_capture.inc.S`: one shared finite conditional capture body, thin fp L adapter, opt-in cancellation; cancellation has not been deployed.
- `gyro/retained_task.inc.S`: shared one-shot native wrapper with explicit bindings. fp Base wrapper/query compatibility is not established merely by extraction.
- `fp_usb_shell/fpl_retained_relocation.py`: runtime-owned template/reference preparation.
- `gyro/retained_launch.inc.S` and `fp_usb_shell/fpl_retained_launcher.py`: allocator-owned launcher; entry creates a task **unattached** and returns.
- `test_fpl_retained_boot.py`: real shared loader → stage2 → ordered entries → pass 2 → staging free under emulation, with staging poisoning and external activation afterward. The diagnostic has not been installed/booted and does not relax the public builder's fp L allowlist.

The latest notes report 26 focused boot/launcher/packaging tests passing and 164 combined fp L tests at the launcher milestone. Separately, shared regressions were 108 pass / 3 fail / 1 skip, independently reproduced against the earlier baseline. These are reported prior results, not tests run here. Resolve or explicitly quarantine those baseline failures and supply required image inputs before a stable release; do not report an all-green suite.

### Specific remaining seams

- Post-boot discovery and duplicate admission are missing: staged one-shot intent is not a boot-global identity. A fresh copy can allocate again. Add a small versioned owned product interface with boot-instance identity and stale-instance refusal, using an evidenced publication mechanism; no borrowed IMU zeros or arbitrary BSS words.
- `gsup_launch.S`, `writer_core.inc.S` (`BLOBBASE`, `blob_at`, `gsup_boot`), `ring_task.inc.S` and `build_base_card.py` retain fp pool/cave assumptions. The worker's nonzero pool is not a gyro allocation. No fp L cave has been established.
- A firmware-to-USER-RAM branch may exceed ARM BL range. Every far-transfer patch needs proved placement, complete displaced-instruction replay, flags/ABI preservation and full journal coverage. Prepare owned targets and publish caches before arming.
- Base `take_close` uses an infinite native join; a timeout constant elsewhere does not bound it. Completion/DONE does not imply safe destruction or quiescence. A retained one-shot diagnostic is not a shipping lifecycle policy for endless takes.
- Recording audits expose audio-branch-dependent START, failed starts, STOP retries/bypasses and MOV result conflation. `tools/fpl_mov_epoch.py` is a bounded synthetic classifier: imported events cannot prove causal association; result 1 is not durable finalization. Do not add a generic “recording complete” flag based on it.
- Existing take/path/metadata bindings are valuable inputs, but root sidecar names are not reservations, cached dimensions are not necessarily encoded raster, and raw focal values do not establish units/coherence. Start with CinemaDNG coverage; MOV parity is not a prerequisite for upstream's CinemaDNG-only gyro workflows.

## 6. Critical path: implementation milestones and acceptance

### M0 — Reproducible reference and preserve port boundaries (P0, offline)

**Implement:** pin the upstream source dependency set and toolchain in a clean build workspace; adapt input paths instead of scattering private absolute paths. Run the recovered extractor tests, reproduce minimal fp v3 and Gyro2 at the release-matched source, and retain the fork's profile/parser fixes. Integration ownership remains with the integrating maintainer.

**Acceptance:** dependency/source manifest; valid Thumb/self-contained text; exact Gyro2 artifact comparison or a documented toolchain difference plus executed behavior tests; explicit missing/failed tests; unchanged default fp behavior for address-only changes. Do not require importing the entire multi-gigabyte research archive to build one product.

### M1 — Stable ordinary shell and recovery boundary (P0; hardware gate)

**Implement:** finish lifecycle synchronization in the existing worker/update tooling, with admission/refusal around USB generation invalidation and allocation ownership. Retain the reviewed fixed-size updater until a separately owned larger-worker handoff has passed acceptance. Provide deterministic cold-recovery/reconnect instructions and state reconciliation, not blind retry after an uncertain handoff.

**Acceptance offline:** actual worker instructions with invalidation while wait/transfer/command dispatch is in flight; no stale descriptor use, out-of-owned-range writes or second server; refusal and lost-reply cases preserve recoverability. Exercise real emitted ordinary AutoRun and both restoration registrations.

**Acceptance on authorized hardware:** exact short ordinary card boots; shell replies cannot be satisfied by request echoes; RAM/file round trips match; unplug/replug and mode transitions are recoverable; idle boot/power-off/reboot approximately ten times, plus previous-card warm restart and recording coexistence. Verify stock-word restoration and no duplicate instance. Record USB speed separately. Until these pass, label a developer preview, not a stable general-use card.

### M2 — Owned resident admission + minimal v3 services (P1; offline first)

**Implement next small patch:** discovery/identity and duplicate refusal for the already-built retained launcher, with the task still unattached. Extend existing tests rather than another capture/launcher. Test fresh staging, repeated entry, stale publications, allocation/task-start failure and lost initialization outcomes. This is a narrow product contract, not a new generic lifecycle framework.

In parallel after M0, profile `v3/build_v3.py`, `sloader.c`, `sloader.h` and `cave.py`: allocator/file APIs, claims/chains/journal publication and tiny branch veneers. Reuse the shared loader/stage2/entries; give resident objects their own allocation. Keep public unsupported-option rejection until a product passes.

**Acceptance:** headless v3 shell plus a finite test product loads with correct entries/logging; collision refuses without partial patch; malformed/missing products fail cleanly; duplicate load does not launch again; staging poisoned after return; power-off restoration covers all patched words. Native completion and cancellation never authorize free. A later authorized boot trial must discover the exact instance before activation; the existing retained instance is not that trial.

### M3 — Calibrated gyro recording, with architecture decision bounded (P1/P2)

**Do immediately offline:** profile the now-available `projects/gyro2-sup/src/gyr2.S`/builder and decoder around firmware calls, sensor metadata and v3 services. Keep its FSG2 format and observer pipeline. Current build 6 writes through the tag observer (build, serialized-template, frame notifications); it no longer patches the old header-DMA site. Port actual current source, not stale README tables.

Gyro2 has its own ring/timing logic and fp constants (period, scales, backfill/lap assumptions, sensor dimensions) and cave-service dependencies. Availability does not prove it fixes fp L coherence. Compare this logic with the existing shared drain/ledger tests; share proven interfaces where practical without an unrelated algorithm rewrite. Obtain the tested plugin revision/format fixtures while that adapter is built.

**Hardware measurement gate:** distinguish publication order and hidden laps, measure rate/scale/axis mapping, correlate sensor Vd with recorded frame order and exposure/readout, exercise acceleration/level and lens behavior. Establish loss accounting under scheduler/storage delays, not just plausible record counts.

**Product acceptance:** successive short and long CinemaDNG takes (target at least a 15-minute stress take), stop/start, failed start, automatic storage stop and repeat take; correct take/frame association, continuity or explicit losses, no corrupted header/RAW and bounded callback cost. Decode every frame with the independent host parser and selected plugin. Validate native DNG before adding Lossless. A working but uncalibrated diagnostic cannot pass this gate.

**Architecture decision:** proceed Gyro2-first if v3/tag/Vd mapping is implementable; it avoids building a separate sidecar writer merely to reach the preferred workflow. If v3/no-cave integration dominates, deliver a recording-aware Base slice through `gcsv_task.S`/`FPGYRO_EDITION_BASE`, `writer_core.inc.S` and the existing `.GYR` converter, after proving its writer lifecycle. Do not block all useful gyro work on manager UI or Fast. GCSV lens/auto-sync follows calibrated Base; it is not needed to prove the finite producer.

### M4 — UI and first mergeable products (P2/P3)

**Implement:** port common `uishare` menu/Quick Set/display bindings and card-backed settings, then ScreenFlip as the first independent display product. Add minimal fp L catalogue selection with ordinary boot only. Seek Desqueeze/Tap-to-Zoom source in parallel, then port their CHAIN/display/touch semantics rather than treating them as fp L-compatible BINs.

**Acceptance:** menu navigation and first-open behavior, switching display modes, saving/reloading preferences, standalone/combined claims, disable/re-enable, playback and recording transitions. Verify unchanged recorded pixels for monitoring-only products. Test fp L touch-AF when zoom is disabled. EVF/HDMI require actual relevant hardware and remain unclaimed without it.

### M5 — Lossless and recorder helpers on stock modes (P3)

**Implement:** profile `lossless/native`, `build_v3_lossless.py` and the native reader/codec pipeline; first a bounded encode/decode of an owned frame, then recording. Adapt FCAP against fp L's measured batch/pool limits. Keep Unlocked Writer a separate optional optimization. Obtain STOPFX source and reproduce its failure condition before deciding whether fp L needs the same fix.

**Acceptance:** independent decompression is pixel-exact; uncompressed fallback works under codec pressure; all supported depths/geometries have valid DNG tags and camera playback; no ring/batch exhaustion on small frames; normal/error stops drain correctly and the next take works. Test SD and SSD separately. Combine with Gyro2 only after standalone passes: private-tag/header space, template size, cache/DMA visibility and frame association must all survive. A release linked to FCAP is not evidence for its current fp L batch limit.

### M6 — Sensor modes, Fast and complete composition (P4/P5)

**Sensor implementation:** adapt Res-Custom's consumer/data/UI model to one proved fp L mode. Use the existing fp L transport/timing audits as anchors; infer neither row cadence from receiver timing nor fp geometry from similarly named modes. Only expand the matrix after real DNG geometry/readout/storage acceptance. RAW-View calibration can proceed in parallel on stock modes.

**Boot implementation:** after ordinary/v3 lifecycle, establish a warm-resident loader location and stale-pointer recovery; add Instant. Only then add the persistent settings bootstrap with exact block ownership, prior-value recovery, cold miss/hit and disable behavior. Current v3's Instant and Fast are distinct options, even though legacy documentation uses Fast Start 3 collectively.

**Composition acceptance:** test every offered manager/Instant/Fast variant and supported product pair/group, conflict/CHAIN order, missing/disabled BIN, short-file replacement, RCD selection, previous-version boot and stock restoration. Use `tools/merge-v3` for modern catalogue changes; do not pass a legacy recomposition check off as v3 product acceptance. Compatible payload-only changes keep AutoRun unchanged. Ship only capability-matrix entries actually tested.

### Dependency DAG

```text
M0 reference reproduction ──────┬── M2 headless v3/services ──┬── M3 Gyro2
                               │                           ├── M4 UI/ScreenFlip
M1 shell/lifecycle ─────────────┴── M2 resident admission     └── M5 Lossless
finite gyro + calibration ───────────────────────────────────── M3
M3 Base alternative ── GCSV compatibility (not prerequisite for Gyro2)
M4 UI + sensor evidence + exact Res-Custom inputs ───────────── M6 formats
M1 + M2 ordinary/v3 lifecycle ── Instant ── Fast ────────────── M6 boot
accepted products + M4 catalogue ── M5/M6 combination tests ─── full matrix
```

The DAG is about product acceptance: isolated codec, UI, parser and profile implementation can proceed before unrelated hardware gates. Live tests run when a milestone calls for them: one session on the camera at a time, never writing firmware, recording what was done and restoring stock state. A passing offline milestone is not itself hardware acceptance.

## 7. Parallel work and external actions

| Workstream | Can proceed now offline | Needs external input / hardware |
|---|---|---|
| Build reproducibility | Exact Gyro2 source/hash checks, extractor/toolchain, fp v3 tests, portable input paths | Official firmware supplied separately; upstream clarification for missing Res-Custom release pins/license scope |
| Shell/retained lifecycle | Ownership and failure tests; discovery/admission; ordinary-card regression fixes | Idle power cycles, reconnect and recording coexistence; no operations on current retained state |
| Gyro | Gyro2 profile and decoder fixtures; shared conditional-capture tests; plugin format review | Rate/axes/scales, Vd/recording correlation, continuous takes and lens calibration |
| UI | Profile adapters, ScreenFlip, catalogue target filtering | LCD/touch/Quick Set plus optional EVF/HDMI validation |
| Recorder | Codec/writer/FCAP profile and emulation fixtures | Actual frames, media stress, failures, playback and durable close |
| Source engagement | Prepare exact requests and hash/path evidence | Ask upstream/third-party authors for sources/terms and tested plugin pin; communication requires separate approval |
| Sensor/Fast | Bounded mode-table and settings-layout work | Authorized mode trials and settings persistence/recovery tests |

Do not start another broad audit instead of these implementation slices. For unresolved firmware seams, use a bounded question attached to the specific patch (for example, how the tag observer is registered), then implement/refuse based on its answer.

## 8. Release scope

**Feasible first stable public release:** ordinary headless fp L shell, explicit 3.02 targeting, RAM/card transfer tools, verified lifecycle/recovery procedures and reproducible sources. Optional finite raw gyro tooling may be included as an explicitly experimental diagnostic with unknown calibration; it is not a stable recording logger. No Fast, v3 manager or sensor feature is needed for this release. Today the live boot/restoration/coexistence gates prevent calling it stable.

**First useful recording release:** one calibrated CinemaDNG gyro workflow, preferably Gyro2 if M2/M3 succeed, on a narrow tested mode/media matrix; Base is a viable earlier compatibility release if its writer lifecycle is solved sooner. Manager UI and Lossless are independent follow-ons.

**Eventual behavioral parity:** accepted current v3 products and merged workflows, calibrated Base/GCSV compatibility, Lossless/recorder helpers, monitoring tools and hardware-supported custom formats, with documented physical limitations. Full parity cannot currently be promised: third-party source/terms, exact Res-Custom reproduction, fp L sensor capabilities and continuous recording lifecycle remain open. Do not delay a solid shell/gyro release until speculative sensor or Fast goals are met.

## 9. Source index

All upstream tree links below are pinned to **`e79e3f1ff4622bce0b8a4cee9d322f184d7f6696`**. Local evidence references describe the October 23 working-tree snapshot; their historical statuses must be read with the latest follow-ups.

- [Pinned upstream commit](https://github.com/ijigen/fpSup/commit/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696)
- [Upstream agent instructions](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/AGENTS.md) and [build contract](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/SUP_BUILD_RULES.en.md)
- [Current release table](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/README.md), [actual catalogue builder](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/tools/merge-v3/build_catalogue_v3.py), [Merge options/tests](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/tools/merge-v3/README.md)
- [Gyro2 implementation/tests](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/projects/gyro2-sup), [v0.2.0 provenance and notes](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/releases/fpsup-gyro2-v0.2.0)
- [Strict ELF extractor/tests](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/research/ui/tools/arm_text), [UI helpers](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/research/ui/tools)
- [FCAP/writer sources](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/projects/rec-core), [Lossless source](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/lossless)
- [Res-Custom provenance](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/releases/fpsup-res-custom-v0.1.4test/provenance.json), [OpenGate development builders](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/projects/open-gate/build)
- [RAW-View source](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/projects/rawview), [ScreenFlip source](https://github.com/ijigen/fpSup/tree/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/screenflip)
- [Shell release evidence](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/releases/fpsup-usbshell-v3.4.0test/README.txt), [Desqueeze evidence](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/releases/fpsup-desqueeze-v0.1.4test/README.txt), [Tap to Zoom evidence](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/releases/fpsup-tap-to-zoom-v0.1.0test/README.txt)
- [STOPFX manifest](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/tools/merge-v3/inputs/stopfx-20261012/manifest.json), [license notice](https://github.com/ijigen/fpSup/blob/e79e3f1ff4622bce0b8a4cee9d322f184d7f6696/fpSup/NOTICE)
- [Plugin research pin](https://github.com/ijigen/gyroflow-plugins/tree/4b3dbacdbaeba7b78b5a607d05d327ffd50aa98d)

Local evidence consumed: `docs/FPL_PORT.md`, `FPL_UPSTREAM_DELTA_2026-10-20.md`, `FPL_V3_BUILD_DEPS.md`, `FPL_BASE_INTEGRATION_PLAN.md`, `FPL_GYRO_RETAINED_TASK.md`, `FPL_RETAINED_TASK_NEXT_STEP.md`, `FPL_SHARED_RETAINED_TASK.md`, `FPL_RETAINED_LAUNCHER.md`, `FPL_RETAINED_BOOT.md`, `FPL_MOV_EPOCH_CLASSIFICATION.md`, and the current thin adapters/shared capture sources. Related mapping/coverage notes are referenced from those documents. The older missing-source conclusions are superseded only where this report independently found public files; prior live results remain precisely scoped.
