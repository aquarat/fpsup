# fp L 3.02 cave-free string-hook experiment

2026-10-26. **The finite install → string checks → restore path passed on the
camera with both one and two shared string layers.** No fp cave was used.
The follow-up deployed six-word shared-loader journaling and exercised the
resident hooks through a native menu redraw. A native slit-scan row has also
passed repeated selection and wraparound on the camera. At that earlier stage,
recording integration and boot/power-off acceptance were unfinished; the
30-October follow-up below supersedes its implementation status.

**30 October follow-up:** [ordinary native-menu boot](FPL_STANDALONE_BOOT.md)
adds the drawing vtable as a seventh journal word; [resident recording](FPL_RESIDENT_RECORDING.md)
adds the early-Vd slot as the eighth. Two debug-card software boots and recording
at 4/6/8/12 fps passed on UHD/8-bit/24. The later
[observation stage](FPL_RESIDENT_OBSERVATION.md) hit a live active-take size-change
hang. Physical recovery/restoration and physical-power acceptance remain pending.
Earlier installation/restoration status below is historical.

## Implementation

- `fp_usb_shell/asm/fpl_ui_cpu.S`, `fpl_ui_cpu.py`: finite CP15 diagnostic.
- `fp_usb_shell/asm/fpl_ui_guard.S`, `fpl_ui_guard.py`: IRQ/FIQ-masked task-PC
  admission and six-word transaction; read-only inspection command.
- `fp_usb_shell/asm/fpl_ui_string_check.S`, `fpl_ui_hook_trial.py`: finite live
  roundtrip using the **existing** `uishare/ui_strings.S`, with owned memory.
- `test_fpl_ui_cpu.py`, `test_fpl_ui_guard.py`, `test_fpl_ui.py`: instruction
  tests, including actual native kernel frame construction/restoration.

Each entry gets `ldr.w pc,[pc,#0]` (`F000F8DF` as a little-endian word), followed
by an aligned ARM entry in an allocator-owned USER block. This instruction
changes Thumb to ARM state; neither a nearby branch veneer nor a code cave is
needed. The shared layer implements the complete original leaf on a miss,
rather than jumping back through partially displaced instructions.

| Thumb site | Original first word | Original second word |
|---|---|---|
| resolve `C05E1D38` | `3FFFF1B1` | `6902BF1C` |
| owns `C05E23A8` | `428A6942` | `6900D805` |
| remain `C05E23C0` | `69406902` | `1A501812` |

All six words are checked before any site is written. Installation refuses
foreign bytes; removal requires exactly this owner's three entry pointers.
Code, string tables and the native allocation descriptor are uploaded and
read back before cache publication or execution. The host checks complete
immutable extents, not just headers. Staging is aligned upward to 1 KiB within
the worker's reserved extent; the pool itself need not be 1-KiB aligned.

The initial finite CLI path used command **3**, which installs, invokes the
checker, restores stock, publishes D/I caches again, and only then restores
the caller's interrupt mask. Commands 1/2 (leave installed / remove) were
subsequently exercised on hardware by the resident trials described below.
No GUI event, allocation, lock acquisition, wait or file operation runs in the
masked transaction. The checker calls only the three reviewed string leaves.

## Admission evidence and its scope

The read-only diagnostic returned:

```
MIDR    410FC075   ARM Cortex-A7 r0p5
MPIDR   80000000   affinity 0, same as earlier shell/Vd observations
L2CTLR  00800000   NumCPUs[25:24] == 0: one CPU in this cluster
```

L2CTLR is read only after recognizing Cortex-A7. The transaction additionally
requires the exact observed MIDR/MPIDR, one cluster CPU, SVC context, zero
kernel context count, and enabled dispatch. This is specific to the reviewed
fp L firmware/kernel, which uses one global current-task pointer. **A local
CP15 read is not a general proof about other clusters or coprocessors on a
SoC**; the tool does not claim such a proof or support arbitrary firmware.

With IRQ/FIQ masked, the guard checks IDs **1 through 500 inclusive** at
`C3000838 + 132*id`. It validates task identity/state, stack extent and saved
frame bounds; skips the current task and absent/dormant slots; and rejects a
saved PC in any of the three eight-byte windows, including the entry itself.
Unexpected state/layout refuses the entire operation. There is no retry loop.

The native voluntary save (`C0000CFC..C0000D60`), IRQ-return reconstruction
(`C0000F88..C0001024`), and restore (`C0000DA0..C0000DE0`) were executed in
Unicorn against the fingerprinted MAIN. Both ARM and Thumb IRQ resumes recover
the supplied PC/CPSR. The saved frame is `D0` bytes: CPSR at `savedSP+C4`, PC
at `savedSP+CC`; the TCB holds savedSP at `+78`, size at `+18`, top at `+74`.
Live inspection scanned all 500 slots and checked **89 non-current active
frames**, with no refusal. The same counts were obtained in both hook trials.

A conservative whole-image ARM/Thumb immediate-branch scan found one apparent
interior entry, `ARM C05D0A60 → C05E23AC`. At the pinned native Thumb boundary
these bytes are `mov r1,sl; cmp r2,#0`, not an ARM branch. No interior pointer
literals were found. This scan does not exhaustively prove the absence of
computed indirect entries. The patched regions are complete leaf entries,
with no calls in their displaced instructions.

Cache routines `C000E91C` and `C000EABC` are live-byte checked against the image.
The former preserves the incoming IRQ/FIQ mask; publication runs D then I
before releasing exclusion. Kernel boundary bytes are checked too.

## Hardware results

The detailed trial manifests are retained externally; the bounded findings
and code hashes are summarized here.

| Trial | Retained allocation | Result |
|---|---|---|
| `ui-cpu-01` | worker staging only | finite CP15 diagnostic returned |
| `ui-context-01` | worker staging only | all 500 slots inspected; 89 active frames |
| `ui-hook-one-01` | none | host alignment check refused before any write |
| `ui-hook-one-02` | `45540000`, 64 KiB | one layer; private and stock checks passed |
| `ui-hook-two-01` | `45560000`, 64 KiB | two nested layers; both private ranges and stock checks passed |

The real patched firmware entry points returned:

- `Slit scan\0`: the owned string pointer, borrowed=`1`, remaining=`10`.
- Outer layer's `4 / 6 / 8 / 12 fps\0`: its owned pointer, borrowed=`1`,
  remaining=`19`; an inner-layer lookup correctly passed through the outer one.
- Stock offset zero: `C18D01B4`, borrowed=`1`, remaining=`176152`.

After each trial, all six original firmware words matched, all immutable
uploaded bytes matched, echo was stock, worker publication/capabilities matched,
the temporary MEM1 window was revoked, and `version` returned normally. The
pending marker was removed only after successful verification. The allocations
remain retained for this boot; they are not freed or reused. No boot/card files,
menu values or persistent settings were changed by these trials.

The final independent `ui-hook-final-stock.json` snapshot also confirmed the
221-screen stock reader/layout, idle recorder, stock early-Vd callback table,
stock echo, no pending marker, and the original exposure mode 3 / shutter 0/0 /
ISO 0 (Auto).

SHA-256 of bytes uploaded:

```
allocator.bin (1024 bytes, both trials)
7840070d07b444cd17a3054ab2f22ca1c657b021df720cac0d31b6594956b5b4
guard.bin (2048 bytes, both trials)
9dc751cd342723c6be8ef3e810fa17e538c2491ef2c8778bfbd68e6edff2ffbe
owned.bin (65536 bytes, one layer)
9512a078ea10cd1bcc1d4f5ec498ed0f8c0fd63a806c225b6f5dad259fd96f23
owned.bin (65536 bytes, two layers)
b11c44d4fb06ba20995da0e5749e981d4ec7ff7acab33514d194c7ec97e872ad
```

Each manifest retains the descriptor, private ownership token, source hashes,
exact entry addresses, operation intents, task snapshot and result bytes.
Boot-specific addresses above are evidence, not reusable allocation addresses.

## Reproduce

Use the scoped ARM toolchain on PATH and the official fp L MAIN:

```sh
cd fpSup/fp_usb_shell
export FPL_MAIN=/path/to/firmware/FPL_V302/MAIN.bin
export FPSHD_SOCKET="$HOME/.cache/fpsup/fpshd.sock"
python3 -B -m unittest -v test_fpl_ui_cpu test_fpl_ui_guard test_fpl_ui
python3 -B fpl_ui_guard.py --inspect --main "$FPL_MAIN" --out /path/to/new-inspection
python3 -B fpl_ui_hook_trial.py --main "$FPL_MAIN" --layers 2 --out /path/to/new-trial
```

**19 tests passed.** They cover all displaced halfwords (including task ID 500),
foreign second words, malformed frames/context/topology, caller stack alignment
and masks, actual far transfers, nested layers, and full stock restoration.
Private emulator mutations that remove the PC guard, corrupt a private pointer,
omit restoration, lose the topology output or bypass a string range are detected.
No working source is modified for mutation testing. Hardware/cache behavior is
reported separately from emulator CP15/cache models.

The staging lock and pending marker are shared with capture/download tools.
An uncertain trial leaves its marker and retained allocation evidence in place;
the slit-scan recovery command is **not** a recovery provider for this schema.
There is no automatic retry or reboot-based pointer reuse.

## Resident integration status

1. **Page-only adapter completed:** `slit_scan/fpl_pool.c` supplies fp L owned
   storage and installation. The general `uishare/ui_pool.c` still uses
   fp-specific cave and publication addresses.
   The shared layer itself is used unchanged here with QS fields zero; fp QS
   setting-bank addresses are not a portable fp L binding.
2. **Completed on the development card:** declare/journal all six stock words,
   not the three words sufficient for
   fp's B.W hooks. Use the shared loader's registered power-off restoration;
   do not add another power-off object. Verify the exact journal on hardware
   before leaving any hook installed.
3. Retain all reachable layers/tables through shutdown, then test the shared
   loader/card and repeated no-record warm boots/power-offs. A synchronous
   roundtrip does not establish that lifecycle or menu redraw behavior.
4. **Native row/controller selection completed.** Recording integration and
   its restoration remain unfinished.

The previously missing **cave-free transfer and bounded live transaction** now
have camera evidence. This is not yet a standalone-menu release.

### Menu integration follow-up, 2026-10-26

`fpl_ui_restore.py` checks both fp L power-off lists, the exact shared restore
routine and each of the six journaled words. The initial empty journal was
resolved by deploying the 4,988-byte BIN
`1639fe95ba115564f0140fd0359fd4432bd9134fc601bcc2392a5b74b7995e36`.
The existing 8,116-byte diagnostic AutoRun stayed byte-identical
(`7a82fa534a0f901eada154cded5a3699fb06b6b2237c6b15dcced8f8883473d0`),
including its 90-second wait. Exact existing-script emulation and two card
readbacks passed; the reboot at 2026-10-26 21:58:59Z reconnected and the new
boot's journal covered all six words in both shutdown lists.

The two-layer `--resident` trial installed the hooks, executed stock/private
string checks, redrew the native SHOOT menu, captured `SS__2383.JPG`, and
restored all six words. S1ON timed out after the screenshot; S1OFF was sent
separately, then immutable code, stock sites/UI/echo, idle recorder and revoked
window were verified before clearing the pending marker. The photographed menu
now stays visible; the trial no longer sends half-press events.

`slit_scan/fpl_pool.c` uses the shared page applier and unchanged string layer
with owned memory and the runtime-argument guard. Actual ARM tests match the
Python page byte-for-byte and reject bad journals, allocator failures, busy
saved PCs, existing hooks and fp-only opcodes. No fp cave or QS service is used.

The `fpl_ui_draw_trial.py` observer interposes an owned copy of the native
`UicDrawHandler` vtable at BSS object `C38D37CC`; its original update method
`C06CF498` and listener remain intact. Hardware observation recorded 66 matched
calls/returns on task 39, maximum depth one, then restored the stock pointer.
The optional menu build runs `slit_tick` after the native update, gated by task,
depth, owned callback/context and the coordinator's reentrancy flag. This
registered the five private variables and rendered/selectably focused the
Slit scan row. The first Right test did not change the value. Correcting the
donor's stale four-action counts alone was insufficient: the copied
`controlAppVariable` expects a literal, not `dst ± 1`. Two ordered actions now
reset the request to zero and send +/-1. Trial `native-menu-06` verified all
five values, repeated Right/OK/Left, wrapping in both directions and MENU
exit/reentry, with ten notifications for ten presses. See the screenshots and
native action-handler regression in the slit-scan document.

The native drawing listener changes between live view and menus. Detach
preserves it and refreshes only its comparison operand; it never overwrites
the listener. After disabling the controller on its owner and detaching the
wrapper, page/strings/registry storage remain retained until reboot.

Detailed resident manifests are retained externally.
Details, hashes and remaining resident lifecycle work:
[Slit-scan menu integration](FPL_SLIT_SCAN.md#additive-row-and-native-controller--offline-2026-10-26).
