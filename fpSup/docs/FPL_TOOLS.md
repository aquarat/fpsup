# fp L 3.02 USB development tools

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

These tools are for the corrected fp L worker, not the fp 5.02 cave tools.
Live evidence and build hashes: [investigation log](FPL_PORT.md).

## Connection

Use one daemon with PID filter `0xc442`, retaining the echo guards.
Inspect the process/socket before starting another. Set `FPSHD_SOCKET` to its
actual socket path; the Python default `/tmp/fpshd.sock` may not be in use.
Daemon STATUS strings alone do not establish worker capabilities. Require
structured MCAPS and actual shell version output (`w91c1`, `3.02.0.V90`).

The diagnostic AutoRun waits 90 seconds and may run twice. Transfers that
borrow echo refuse until its stock handler is restored; enumeration alone
is not readiness. Pool addresses must come from each boot's publication and
MCAPS, never from an earlier capture. Do not use `memmgr bufmem`: it shares
the publication descriptor.

## File transfers

Use an ARM-capable compiler targeting `arm-freestanding-eabi`, Cortex-A9.
Historical reproducibility checks used Zig 0.17.0 as the clang-compatible
driver. Place the selected toolchain on PATH.

Run from `fp_usb_shell/`, with an ARM-capable `clang` on PATH:

```sh
python3 -B fpl_getfile.py '\AutoRun.txt' ./readback-AutoRun.txt --size 8116
python3 -B fpl_putfile.py ./sample.bin '\FPLPROBE\UNIQUE.BIN' --size 65554
```

For a reviewed, equal-size BIN replacement with unchanged AutoRun:

```sh
python3 -B fpl_deploy.py NEW_CARD --previous KNOWN_OLD_CARD --backup NEW_BACKUP_DIR
```

Both local directories must contain exactly `AutoRun.txt` and `fpSup.BIN`.
The tool holds one staging lock, verifies the actual card against the known
previous or candidate bytes, durably backs up before writing, verifies the
upload and a second full download, and confirms AutoRun stayed unchanged.
Already-installed candidates are a checked no-op. No reboot, rollback,
truncation or uncertain-write retry. This checks bytes, not payload ABI
compatibility. The no-op path was live-tested on October 20; the new wrapper's
write sequencing is unit-tested and uses the previously live-proven uploader.

## Offline shared packaging

The maintained builder exposes a restricted ordinary headless fp L shell path:

```sh
python3 -B build_autorun.py --camera fp-l-3.02 --fpl-shell \
  --loader --no-four-box-bar --no-fast-echo --no-ep-patches \
  --main /path/to/FPL_V302/MAIN.bin --out NEW/AutoRun.txt
```

`card_build.py` now owns shared VBIN layout/entry chaining and fp L bootstrap
generation; the diagnostic wrapper delegates to it. Ordinary output removes
diagnostic file saves and the 90-second waits. Its BIN is identical to the PONG
trial, but **its shorter AutoRun is offline-tested only** and is not installed.
The trial's three persistent-in-RAM script patches retain their existing
lifetime; full power-off restoration/lifecycle acceptance remains outstanding.
Fast, UI and arbitrary product combinations still refuse explicitly.
Output inspected: `out/fpl-ordinary-headless-20261020-packaging/`.
AutoRun SHA-256: `0edb0e802b5c1665705af5463f2941e257b4f2057ea045ea9b9bd841ea5a734c`.
BIN SHA-256: `f6f719c7d327939de10f763102863f0072092b4ef89f8d4b0ad76f53a04efb8f`.

## Passive raw metadata snapshot

```sh
python3 -B fpl_metadata_snapshot.py --out NEW_METADATA_SNAPSHOT_DIR
```

Reads fixed settings/lens caches only when their construction guards equal 1,
then checks the guards again. No getters or constructors are called. First live
read returned raw width/height 3840/2160, format 0 and focal 1050; the 32-byte
name reached its bound without NUL. Units, freshness and coherence remain
unverified. Full readback guards, echo restoration and PONG passed.

## Passive naming snapshot

Passive naming/context observation:

```sh
python3 -B fpl_take_snapshot.py --out NEW_NAMING_SNAPSHOT_DIR
```

Reads both fixed media managers and the exact audited settings object twice,
without calling selectors/constructors, scanning media or emitting a filename.
First live observation found expected SD identity and an uninitialized SSD
manager. Candidate numbers are tentative and unreserved; matching snapshots
do not prove media readiness or a recorded take's identity.

## Conditional shared-drain diagnostic

```sh
python3 -B fpl_gyro_latched.py --out NEW_CONDITIONAL_CAPTURE_DIR
```

Add `--runtime-refs` to use the relocatable body with explicitly initialized
local references. The same body executes at different addresses in emulator
tests; first live runtime-reference run completed twenty observations/1114
records with verified guards/restoration and PONG. It uses the existing owned
staging reservation, not a new allocation or resident task.

This fixes each batch's head before calling the shared drain and records both
head observations, consumed cursor and conditional prefix. It stops on invalid
state, possible overwrite or capacity loss, with no resume. First live run
completed twenty observations and copied 1142 records; guards and PONG passed.
Every result remains diagnostic-only with `proven_valid_records: 0`: hidden
ring laps and publication visibility remain unproved. See
[coherence analysis](FPL_GYRO_DRAIN_COHERENCE.md).

## Retained native-task diagnostic

`fpl_gyro_task.py` is the one-attempt host workflow for a separately allocated
finite native task. Its first live trial completed twenty capture observations
and 997 conditional records, with full readback, native completion and final
PONG. It verifies exact firmware identity, reviewed resident worker bytes,
structured liveness, allocation bounds and entry ABI before proceeding.

The completed trial deliberately retains all native objects and storage, plus
`~/.cache/fpsup/fpl-staging.pending`. The marker blocks staging operations, including another trial,
while ownership remains unresolved. Worker-handoff
`reconcile` rejects its distinct schema; it must not be cleared as if it were
a completed handoff. There is no retry, resume, cancellation, join or free CLI.
Boot identity cannot be established from publication equality alone.

The manifest and exact helper/readback artifacts are under private research
storage at `fpl-live-2026-10-23/gyro-retained-task-first/`. Consult
[the retained-task record](FPL_GYRO_RETAINED_TASK.md) before further deployment.
Data remains uncalibrated and conditionally coherent, with proven-valid count
zero; this tool is not a continuous or recording-aware logger.

## Strict shared-drain diagnostic

For a finite RAM-only exercise of the actual shared upstream gyro drain:

```sh
python3 -B fpl_gyro_capture.py --out NEW_CAPTURE_DIR
```

The runner reserves bounded code/state/output in the discovered pool, performs
at most twenty drain observations with nominal 20-ms delays, and restores echo.
It retains counts, heads, raw output and host echo timing bounds. A changing
head stops collection; error output is diagnostic-only. First live use copied
164 records before detecting head movement, with all readback guards and PONG
passing. Complete and lossless capture remain unverified; no recording hooks,
sensor initialization, resident task or card writes are involved.

## Passive idle IMU snapshot

```sh
python3 -B fpl_imu_snapshot.py --out NEW_LOCAL_DIR
python3 -B fpl_imu_snapshot.py --records 16 --out ANOTHER_NEW_DIR
```

This executes one finite observer through the checked echo bootstrap, reading
the existing gyro ring and accelerometer cache into owned staging. It does not
start the IMU, install producers or record. JSON includes both head/publication
observations; binary artifacts retain exact results. A changing head reports
`stale`; do not treat the storage-order records as an atomic time series.
First live read succeeded with expected pointers and a correctly detected
two-record head advance. Physical axes, scaling and sample rate remain unproved.
`--records 1..599` copies that many recent completed records in chronological
order across wrap; default 600 preserves the original full-ring storage-order
format. JSON names the order and header interpretation. A 16-record live read
returned `valid_observed_stable` with unchanged head and all padding zero;
this still does not prove atomicity, freshness or no missed ring laps.
New artifacts include UTC/monotonic host bounds around just the probe echo,
excluding cache publication/restoration. Those are host request bounds, not
camera sample timestamps; use monotonic bounds for elapsed time.

## Transfer bounds

Supply the actual exact size. Download output must not already exist. The
file size plus slack must fit staging (current maximum 975872 bytes). Tools
verify the firmware, dynamic pool/publication, staging bytes, stock echo,
cache publication, operation status and complete result; they restore echo
with checked readback. They use no fp cave or `LOAD_DONE_US` claim.

All staging/echo tools must share `~/.cache/fpsup/fpl-staging.lock`. This is
host cooperation, not exclusion against another computer or arbitrary socket
clients. Do not run independent staging operations concurrently or while
recording. A failed/uncertain transfer is not permission to retry blindly.

**Upload mode 7 does not truncate.** An existing longer file's prefix is
overwritten before exact readback rejects its tail. Prefer new unique paths;
this tool is not an automatic atomic boot-file deployer. No automatic delete,
reboot, rollback or repeated write is performed.

## Verified and outstanding

- Shell execution, dynamic pool discovery, memory reads and RAM uploads.
- Full corrected resident-body readback; read-only window grant/revoke.
- Root card files and diagnostic downloads, compared with reader backups.
- New 65,554-byte card upload with two matching full downloads.
- Ordinary `reboot` caused an observed reboot, but unattended USB recovery is
  unresolved. One transition subsequently left USB unresponsive and required
  battery removal; do not present it as a reliable reboot tool yet.
- RAM handoff is live-verified: three same-image runs, then a reviewed
  same-size PONG-ack upgrade. It accepts only two known worker hashes and
  their shared ABI, not arbitrary new worker versions. Existing fp
  `swapworker.py` is not a supported fp L updater.

```sh
python3 -B fpl_swapworker.py check     # offline image/ABI check
python3 -B fpl_swapworker.py handoff   # live same-image handoff
python3 -B fpl_swapworker.py upgrade-pong # reviewed old -> PONG worker
python3 -B fpl_swapworker.py reconcile # inspect pending completion; never rearm
python3 -B fpl_status.py              # read-only sequential USB/state JSON
```

Handoff writes a persistent `~/.cache/fpsup/fpl-staging.pending` record before
arming. Upload/download tools refuse while it exists. Uncertainty leaves the
record intact. Explicit `reconcile` checks publication, completion cookie,
inactive swap magic, stock echo, MCAPS and the complete resident hash before
removing it. It temporarily grants/restores read-only MEM1 window metadata;
it never writes payload code or rearms. An incomplete/changed-boot result stays
blocked. Host locks protect cooperating local tools, not unrelated clients.

Current card BIN: 4916 bytes, SHA-256
`f6f719c7d327939de10f763102863f0072092b4ef89f8d4b0ad76f53a04efb8f`.
Resident PONG code was installed by RAM handoff and read back. The matching BIN
was uploaded and fully read back for the next boot, but has not been boot-tested.
AutoRun is unchanged. Daemon PING now reports `proof=PONG` or
`proof=legacy-ambiguous` according to the response received.

`fpl_status.py` validates firmware identity and discovers the current pool from
publication plus MCAPS before reading worker state. It records the fixed USB
globals and TRB tables without following their pointers, and refuses a changed
publication/capability set. No handler borrowing, window changes, settings writes
or mode switches. It can inspect while a handoff marker is pending but never
clears it. Reads are sequential, not atomic; collection increments counters, and
modulo-32-bit deltas assume no intervening reset. Absolute counters may be
uninitialized. Live October 20 snapshot matched the working USB baseline with
10 served commands, zero new faults/holds, and no pending marker.
The later lifecycle capture adds active mode/configured/backend/DCTL and
endpoint configuration: observed mode 5, configured 1, backend 1, run set.
These are diagnostic fields, not a synchronized transfer-ownership token;
see [lifecycle audit](FPL_USB_LIFECYCLE.md).

Offline checks:

```sh
python3 -B -m unittest -v test_fpl_getfile test_fpl_putfile test_fpl_swapworker test_fpl_reconcile
```

No commit, release or push is implied by these development tools.
