# fp L roadmap implementation

Implementation started 2026-10-23 after integration of public upstream
`e79e3f1ff4622bce0b8a4cee9d322f184d7f6696`. The product tree is now under
`fpSup/`; upstream research and project sources are at repository root.
This follows [the parity roadmap](FPL_PARITY_ROADMAP.md).

## Active slices

| Milestone | Implementation scope | Acceptance still required |
| --- | --- | --- |
| M0: reproducible references | Explicit firmware/toolchain inputs, strict extractor checks, release-matched Gyro2 and minimal v3 reproduction | Actual builds and behavior tests; exact artifact match or explained differences |
| M1: USB lifecycle | Synchronization-aware admission and submission ownership; preserve the reviewed live worker path | Real-instruction race/mutation tests before hardware lifecycle trials |
| M2: retained admission | Discoverable owned instance and refusal of duplicate initialization from fresh staging | Evidenced publication ownership, stale-instance refusal and staging-independent native state |

These slices are being implemented independently in non-overlapping source
areas. Delivery alone is not acceptance: the main session reviews the changes
and reruns relevant checks before recording results here or in the investigation
log.

### M0 completed: reference reproduction

The main session independently reproduced Gyro2 v0.2.0 byte-for-byte:
`2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3`.
Twenty extractor, 39 Gyro2 and 22 v3 tests passed with no skips; the selected
commit-magic mutation was caught. Minimal ordinary v3 and strict Thumb/EABI ELF
validation passed, plus five driver contract checks. See
[reference reproduction](FPL_REFERENCE_BUILD.md). These remain fp references,
not fp L product acceptance. Gyro2 observer/profile adaptation is now underway.

### M1 first delivery: blocked active transport

The opt-in closed-admission experiment refuses every operation, including a
ready mode-5 connection. It is not a usable shell or an active lifecycle fix.
Main independently ran its refusal tests with the existing lifecycle/dispatch
tests: 38 tests, 35 passes and the same three expected failures. The reviewed
default worker remains unchanged. See
[the implementation boundary](FPL_USB_LIFECYCLE_IMPLEMENTATION.md).

M1 remains blocked on a common evidenced admission/close boundary, cleanup
rights tied to a submission, and drainage of older mutating call frames before
reopen. The follow-up examines native serialization and the newly imported
research sources. Passing an all-refused profile is not completion of M1.

The bounded follow-up is now stopped with active transport unresolved. Main
independently executed all four native-owner tests across both images using
`FIRMWARE_ROOT` (an initial run without that input skipped all four and is not
counted as verification). Native queued transfers do not exclude lifecycle
writers; injected descriptor replacement splits stores across descriptors, and
nested teardown precedes the outer submission's final status write. The missing
mechanism must defer independent destructive close until older frames drain
without making nested teardown wait on itself. No evidenced implementation was
found; no active candidate or live allowlist change was produced.

### M2 first delivery: product-side admission contract

Main independently passed 39 admission/launcher/boot/relocation/binding tests.
The opt-in reservation refuses duplicate fresh-staging attempts and validates
discovery without speculative owner dereferences. Its provider is explicitly
mocked: there is not yet an evidenced fp L reservation/current-boot authority.
Pointer/token equality does not supply that authority, and matching records
never authorize activation. See [retained admission](FPL_RETAINED_ADMISSION.md).
M2 remains incomplete until the real composition-owned provider is integrated.

The service-port fallback now executes the real shared boot chain with an fp L
headless v3 profile. Main independently passed 36 service/boot/loader-hook/splash
tests. Native allocator and directory wrapper instructions execute, including
journal restoration and poisoned-staging checks. Default fp core bytes remain
unchanged in the implementation agent's comparison. See
[headless v3 services](FPL_HEADLESS_V3_SERVICES.md).

Fresh loader instances demonstrably have separate books, so this does not bind
the retained provider or establish cross-loader boot identity. The next useful
independent implementation is owned far-hook placement/replay with journal
coverage; missing discovery authority is not replaced with pointer equality.

That delegation ended with a tool policy error rather than a completed handover.
Partial files `v3/fpl_level_transfer.S`, `v3/fpl_owned_hook.py` and
`v3/test_fpl_owned_hook.py` exist in the working tree, but have not been accepted
or independently verified by main. Their presence is not evidence that this
milestone passed. They remain undeployed and outside any supported product.

### M3 first delivery: shared native observer seam

The shared Gyro2 source now has an explicit fp L observer profile, without a
second observer algorithm. Main independently passed 11 tests using native
Subject attach/notify, DataPool event methods and rate code plus the actual
shared tag/parser instructions. Build/serialized/frame events 0/2/3 execute;
the default fp BIN remains exactly release-matched. See
[Gyro2 bindings](FPL_GYRO2_BINDINGS.md).

This probe has no installer or calibrated frame producer. Its explicit sample
rate, capacity and callback are experiment inputs, not inferred fp L settings.
Tag storage/serialization capacity and real no-cave services remain gates;
the next slice replaces the modeled tag-storage boundary with native evidence.

Main independently passed the delivered 21 native tag-capacity/observer tests.
Native tag storage and generic IFD serialization now execute against an explicit
synthetic object graph. Insertion can report nonzero despite missing storage,
and serialization has no destination-capacity argument: an undersized owner is
overwritten. Added offline pre-write bounds and post-write structural admission
checks refuse the demonstrated invalid layouts, including RAW/Lossless overlap.
See [native tag capacity](FPL_GYRO2_TAG_CAPACITY.md). The next slice resolves the
mode-selected formatter's real allocation/length/RAW-boundary interfaces; the
synthetic fixture is not a measured camera header or a safe global capacity.

After the owner's pause and resume, the formatter slice was completed offline.
Main independently reran 31 formatter/capacity/observer tests (all passed, no
skips) and the standalone MAIN/DATA formatter audit. Native constructors and the
reservation-size virtual edge `+0x10 -> C0696CE8` (sum of child reservation
ledgers) execute; an in-emulator instruction mutation breaks the contract. The
probe initializer's `0xB000` is a fixture result, not a recording-mode capacity.
Admission refuses missing RAW-boundary evidence. Still unresolved: the selected
CinemaDNG instance, its serialized-length implementation, allocation lifetime
and actual RAW destination. See [formatter bounds](FPL_GYRO2_FORMATTER.md).

The conditional-edge follow-up resolved the leaf formatter selection, preparation
and serialized-length implementations, traced allocation/release callers, and
proved the header DMA destination is `recording[+0x4C] - serialized_length`.
Admission now also checks frozen flat-IFD metadata, allocation generation and
frame extent. Main independently reran 42 edge/formatter/capacity/observer tests
(all passed, no skips) and the expanded MAIN/DATA audit (exit 0). The ownership
tests remain synthetic: with native defaults the non-TIFF branch is selected, so
no actual CinemaDNG instance is established offline. Missing inputs: the runtime
context at `C31F6ABC` in a CinemaDNG mode, its initialized geometry/builders, and
live frame-allocation extents and lifetime. These need a passive camera
observation with the camera set to CinemaDNG; they cannot come from MAIN/DATA.

Live, read-only (owner-authorized, 23 October; word reads through the resident
worker, no reboot, mode switch or card write): the full 0x5E4-byte context
snapshot at `C31F6ABC` is byte-identical to its source `C3074BA8`
(`[C3075194+5C] == C3074BA8`). Selector words `(+44,+30,+C)` are `(0,0,0)`,
not the native defaults `(0,3,1)`; `+0/+4` are 3840x2160 and `+1C` is `0x2530`.
Under the traced factory predicate, `p[30]==0` selects the 0x8C-leaf
(`C2E4A5B0`) branch. That offline mapping is being replayed against the exact
snapshot before it is treated as established. Bulk MEMR at these addresses is
refused (code 4, outside the worker window); `mem get` succeeded. Evidence is in
the private live directory `cdng-context/`. The retained task and its pending
marker were not touched.

### First live CinemaDNG take (23 October, owner-authorized)

Started and stopped with the stock shell `key MOVON`/`MOVOFF` (record button).
Both key replies timed out over USB, but the keys landed and the shell stayed
responsive. The card gained `\CINEMA\A001_001\`: 141 DNGs of 8,447,488 bytes
each, a WAV and `SPP_metadata.xmp`. The files were not downloaded, because the
transfer tool refuses while the retained-task pending marker exists, and that
marker is kept. Reads were word reads only, following pointers only into known
RAM ranges. Evidence: private `cdng-take-1/` (`take.json`, card listing, hashes).

Idle, before the take: template owner `C358E9D8` all zero, registry
`C3520D88` all zero. Mid-take, three snapshots about 1.2 s apart, owner stable:

| Item | Live value | Offline prediction |
| --- | --- | --- |
| Owner `+8` composite F, vtable | `C38CA08C`, `C2E4A65C` | `C2E4A65C`: **matches** |
| Owner `+C` header length H | `0x13800` | unknown |
| Owner `+10` source template S | `51500780` | unknown |
| Left leaf vtable, kind | `C2E4A5B0`, 1 | `C2E4A5B0`, 1: **matches** |
| Left leaf `+88` low byte | **1** | 0 (edge `C06A40A0`): **mismatch** |
| Right leaf vtable, kind | **`C2E490F0`, 3** | `C2E4A4B0`, 0: **mismatch** |
| Left ledger reservations | `+20=0x18000`, `+40=0x5400`, used `+24=0x13800` | fixture `0xB000`, not a mode |
| Prepare pointers | left `+4 = S`; right `+4 = S + 0x1D400` | composite prepare: base, base + left reservation: **consistent** |
| Parameter object P `+0/+4` | 3840x2160 | constructor copies geometry: consistent |

Buffer registry: 8 to 13 live slots per snapshot, changing during each
snapshot (not atomic). Every live slot had `+14C = 0x13800 = H`,
`+128 = 0x15400`, `+12C = 0` and `+138 = 0`; `+10FC` equals the slot index.
Frame buffers are spaced `0x810400` apart. `+4C` is either `+68 + 0x15400`
(header destination `+68 + 0x1C00`, with `0x1C00` spare before the header) or
`+68 + 0x1C00` (subtraction would land `0x11C00` below `+68`). The second form
is probably a slot not yet prepared for its current frame, but that is not
proved. The `0x15400` value is now live-measured on fp L in `+128`; it is no
longer only an fp-derived assumption, but it is still not a proved reservation.

Not established: which slot is active at the DMA instant; the extent and
lifetime of each frame allocation; the selected right leaf's behavior; and
whether H stays constant across settings.

**Reconciliation (offline).** Both mismatches come from native edges, not from
an error in the live reads. `C039E040..C039E050` writes snapshot `+44=2` after
the idle capture. Replaying that over the captured context selects left
constructor `C06A3FC8`, which writes `+88=1`, and the right selector returns
`C0697510`: singleton `C3824B7C`, vtable `C2E490F0`, kind 3. Both match the
take. The idle-context selection recorded above was therefore incomplete.
Native accessors reproduce the `0x1D400` reservation and the right prepare
pointer `S+0x1D400` from the captured ledgers.

The two `+4C` forms are two phases of one buffer. `C0381E44..54` sets
`+4C = +68 + +128`. Later, `C037E5EC..5FC` subtracts H and stores the result
back into `+4C`, giving the header start `+68 + 0x1C00`. Subtracting H again
from that retreated value is invalid. The admission contract now checks measured
headroom and accepts only the pre-retreat layout: 4 captured layouts accepted,
30 retreated forms refused. `0x15400` stays specific to this measured mode.

Main independently reran 55 tests (all passed, no skips) with the exact
context and take fixtures, plus the expanded MAIN/DATA audit (exit 0), and
re-verified the take evidence hashes. Default fp Gyro2 remains release-exact.
Remaining: captures are not atomic; the active DMA slot, frame-allocation
extent and lifetime, and full frozen DNG metadata are unproved. Buffer stride
alone is not ownership evidence.

### First real fp L DNG header (23 October)

The owner allowed downloads from now on, so the retained-task pending marker
was archived and removed (see [tools](FPL_TOOLS.md)); no native storage was
freed. A full 8.4 MB frame does not fit the 1 MiB staging pool, so
`fpl_getfile.py` gained an exact `--prefix` mode (11 download tests pass) and
read the first 0x20000 bytes of frame 1. Evidence: private `cdng-take-1-files/`
and `cdng-take-1/dng1_ifd_listing.txt`, hashed in `cdng-take-1/SHA256SUMS`.

| Item | Value |
| --- | --- |
| Layout | Little-endian TIFF; IFD0 at 8 with 60 entries, Exif IFD 47 entries, no SubIFDs |
| Identity | `SIGMA fp L`, software `SIGMA fp L Ver.3.02.0.V90`, DNG |
| Raster | 3856x2170, 8 bits per sample, uncompressed CFA, one strip; ActiveArea is the full frame |
| StripOffsets | **79872 = 0x13800 = H**, the live header length |
| StripByteCounts | 8367528 (8 bytes more than 3856x2170); file has 88 bytes after the strip |
| Largest blocks | MakerNote 0xD46C at 0x4746; OpcodeList3 0x3114; DNGPrivateData 0x1A12 at 0x11BB2 |
| Metadata end | 0x135C4; bytes 0x135C4 to 0x13800 are all zero (572 spare bytes) |

This confirms on a real file what the memory reads indicated: the serialized
header is exactly H, raw data begins at H, and the header is padded to a fixed
size. For Gyro2 there are three distinct limits in this mode. The live header has
572 bytes of zero padding. The buffer's measured headroom (`+128 = 0x15400`)
leaves 0x1C00 bytes beyond H before the header would cross into the space
in front of it. The left ledger reserves 0x18000 for the template. Which of
these binds a larger header, and whether H grows or the padding is consumed when
a tag is added, is not yet known; it needs an offline serializer replay with a
GTAG, then a take with a test tag. This is one 8-bit 3840x2160 mode only.

**GTAG growth replay (offline).** H is the serialized size rounded up, not a
fixed reservation: native `C06A29F8..C06A2A34` turns builder size `0x135C4`
into used-row H `0x13800` by aligning to `0x400`. With one added UNDEFINED tag
of N > 4 bytes:

```text
H(N) = align_up(0x135C4 + 12 + align_up(N, 2), 0x400)
```

| Limit | Largest N |
| --- | ---: |
| Existing 572-byte zero padding (H unchanged) | 560 |
| Measured `+128 = 0x15400` buffer headroom | 7,728 |
| `0x18000` ledger reservation | 18,992 |

The measured headroom binds before the reservation. In the replay StripOffsets
follows H. Main reran 61 tests (shared `gyr2.S` parser on the real prefix,
admission boundaries, mutations, default fp release bytes; no skips with the
fixtures) and the MAIN/DATA audit (exit 0), and recomputed H(560)=`0x13800`,
H(561)=`0x13C00`, H(7728)=`0x15400`, H(7729)=`0x15800`. Bound: the replay keeps
every tag payload and the total extent, but relocates child IFDs relative to
the capture. A live take with a test tag at N=560/561 must confirm actual
growth, H/StripOffsets agreement, headroom and runtime ownership. Evidence:
private `reference-builds/2026-10-23-m3-real-dng/`.

**Live test-tag route (offline; arming blocked).** A hookless native attach
exists: Subject `C31AB0D0`, attach `C00CF208`. The observer is called
synchronously during take construction, before serialization. Under unicorn
against FPL MAIN it inserts exactly 560 and 561 bytes and gives H `0x13800` and
`0x13C00`, with StripOffsets = H. It does not fail closed, though. A zero return
only detaches the observer; it neither cancels the take nor removes the tag.
Fault injection showed that missing payload storage can leave the observer
attached while native writing continues. Mode 2 checks run too late to prevent
writes. **Missing piece:** a synchronous gate that checks the final builder and
the real destination bounds before padding and serialization, with proven
rollback or cancellation. Until that exists, arming the observer and MOVON for a
test-tag take stay blocked. The procedure is drafted in
[formatter](FPL_GYRO2_FORMATTER.md): reads, echo restore, two takes, prefix
download and timeout recovery. Main reran 65 tests (no skips) and the audit
(exit 0). The blocked far-hook files were not read or changed. Evidence: private
`reference-builds/2026-10-23-m3-test-tag-route/`.

**Header stability within a take (live).** The first 0x20000 bytes of frames 70
and 141 were also downloaded (`--prefix`; hashes in `cdng-take-1/SHA256SUMS`).
All three frames have identical IFD structure, StripOffsets `0x13800`,
metadata ending at the same place (last nonzero byte `0x135BC`) and zero padding
up to H. Only 9 header bytes differ from frame 1, in `0x723..0x71A0`, including
the per-frame ImageUniqueID (tag 42016). So within one take H is constant and the
layout is fixed, with only per-frame values changing. Other modes are unmeasured.

**Padding-only tag with rollback (offline; arming still blocked).** Native
`C00BAA98` removes a tag (native release plus vector erase). Under unicorn it
restores the reconstructed baseline header byte for byte, including after
allocation failures. Reading back the stored entry detects a missing payload
even when insertion reported success. An experimental ARM transaction
(`test_fpl_formatter_rollback.py`) accepts only N=560 on baseline size
`0x135C4`. It verifies the stored type, count and data and the resulting size
`0x13800`, removes the tag on any failure, and refuses N=561 before inserting.
Main reran 71 tests (no skips) and the audit (exit 0).

Still unproved, so even N=560 stays unarmed: the observer runs before late
metadata population, so its builder size is not the final size. The writer's
immediate caller publishes a zero return as H without checking for an error.
No synchronous take-cancellation path is established. A refusal by the test
primitive therefore does not show that a live take would stop. Needed next: a
final-builder insertion point before padding, tied to real destination
ownership and a caller that honours refusal. Evidence: private
`reference-builds/2026-10-23-m3-padding-rollback/`.

**Late population and cancellation (offline; arming stays blocked).** The
selected final population pass (`test_fpl_formatter_late.py`) adds 11 root
entries plus the MakerNote (tag `0x0200`, 16,384 bytes), with further
mode-dependent branches. Removing those entries from the reconstructed header
shrinks it from `0x135C4` to `0xF52C`, a delta of `0x4098`. That is the
all-absent case, not the delta between the observer and the final size: entries
that already exist can make the net growth zero or something else. So no fixed
observer-to-final delta is proved. The earlier observer and state-callback
interval is still not fully mapped, and finished prefixes cannot show it.

No second Subject notification occurs between final population and padding.
The builder-size virtual call could be intercepted, but replacing it is a code
hook. The `0x2B` failure path queues an event without waiting for cancellation,
and can itself fail when the pool is exhausted. It does not prove that the first
frame is kept off the card, or that anything is rolled back.

Outcomes of a bad live N=560 take: unexpected growth could give
H = StripOffsets = `0x13C00`, which may still be a valid DNG with a shifted
strip if placement and bounds agree. Missing storage can produce malformed
metadata. Growth beyond the real bounds can overwrite RAM before the host can
detect it, so recovery without harm cannot be guaranteed. **Decision: no live
test-tag take.** The bounded investigation stops here, like M1. Moving forward
needs either a code hook at the builder-size call (it would share the far-hook
blocker) or more mapping of the observer-to-final interval. Main reran 77 tests
(no skips) and the audit (exit 0). Evidence: private
`reference-builds/2026-10-23-m3-late-population/`.

**Worst case of an overflow (analysis, untested).** The header DMA destination
is `recording[+4C] - H`, so overflow runs *backwards*, into memory below the
frame, not past its end. The measured headroom allows about 7.7 KB of growth
before anything spills; an N=560 tag alone cannot reach that. The DMA has no
bounds check. Possible effects, from mild to severe: overwriting a gap or the
last rows of the previous frame (stride `0x810400` suggests adjacent frames);
corrupting a previous frame before it is saved; or, below the lowest frame or
under a different layout, corrupting allocator records or other tasks' data
(crash, error stop or freeze). Separately, a header built past its 0x18000
reservation would be overwritten by the CPU into the right leaf at `+0x1D400`.
The worst practical outcome is a crash mid-take that leaves the clip and
possibly the card's file system damaged (repair or reformat). Damaged settings
are unlikely. Firmware and hardware are very unlikely to be affected: firmware
is rewritten only through the update routine, and a battery pull restarts from
clean RAM. A restart also drops the retained task from the earlier trial,
harmlessly.

**Owner decision (23 October).** The owner said the card's contents have no
value and may be cleared, and authorized proceeding with the N=560 test take
on that basis. This accepts card and clip loss; it does not change the rule
that firmware is never overwritten.

**Preflight attempt, then stop (23 October).** Nothing executable existed yet:
the worksheet in [formatter](FPL_GYRO2_FORMATTER.md) still has no admitted
wrapper, placement or quiescence step for arming. Main began read-only
preflight readings to build one against the camera's real state. The first
camera call failed before any read or write: `mcaps` returned
`ERR mcaps open 1003:c442 failed`, so the MEM1 capability was uncertain and the
script stopped. The cause was not investigated: the USB device may have gone
away, re-enumerated or been claimed elsewhere. Next time, first check `version`
over the shell and the host shell daemon before anything else. The
owner then changed plan and stopped the work. **State at stop:** no observer
attached, no echo borrow, no RAM or card write, no key press, card not
cleared. The private directory `gtag-test-preflight/` was created but holds
only its README. No arming code exists for this test.

**N=560 test take done (23 October, owner-authorized, live).** The earlier
`mcaps` failure was the camera being switched off; after the owner powered it
on, the existing daemon answered and MEM1 was open (the very first status read
after power-on failed once, the retry was clean). The power cycle ended the
earlier retained task.

New one-shot observer `fp_usb_shell/asm/fpl_gtag560.S`, driven by
`fpl_gtag560.py`: on the first mode-0/type-3 notify it calls native
`F_ADD_TAG` once with a fixed 560-byte pattern, records the builder size before
and after, and returns 0, so the native dispatcher clears its Subject slot in
the recording task itself. It is not a veto gate. Emulator test
`projects/gyro2-sup/test_fpl_gtag560.py` runs the exact bytes against native
attach/notify/insert/size/serialize on the real-DNG reconstruction: 4 tests pass
(no skips); a mutation that stops the self-detach is caught.

Live result: preflight read-only checks passed (3840x2160, `+1C=0x2530`, owner
idle, 3 empty Subject slots, echo stock). Observer attached in slot 6; one record
press started, one stopped (~3.5 s; key replies returned normally this time).
The observer ran once (mode 0, type 3): builder size 6,874 -> 7,446 (+12+560),
add returned 1, slot cleared. Owner H stayed `0x13800` during the take. Frames 1
and 40 of `\CINEMA\A001_002\` carry exactly one GTAG `0x4653`, type 7, count
560, at `0x11BBE`, byte-equal to the payload; StripOffsets `0x13800`; metadata
now fills the padding exactly; strict admission passes. All frames share the
template, so frame 40's tag bytes equal frame 1's. Echo, Subject and owner were
back to stock/idle afterwards. Evidence: private `gtag560-take/` (README,
events, prefixes, SHA256SUMS).

What this settles: the mode-0 builder is small (late population adds the rest),
and on this mode the add is carried through late population into the final
header with no extra growth, as the replay predicted. What it does not settle:
behaviour for N > 560 (H growth to `0x13C00` and the headroom limit), other
modes, per-frame tag contents (Gyro2 rewrites the tag on each frame notify),
and a veto path. Next: N=561 to observe real H growth (done below), then the per-frame write (done below).

**N=561 take done (23 October, live).** Same tool with `--n 561`. Observer ran
once at take start (builder 6,874 -> 7,448), added the tag and detached. Owner
H became **`0x13C00`** during the take, one 0x400 step as the replay predicted.
Frames 1 and 40 of `\CINEMA\A001_003\`: one GTAG, type 7, count 561, byte-equal
payload; StripOffsets `0x13C00`; StripByteCounts unchanged; 0x3FE zero bytes of
padding before the strip; raw data starts at `0x13C00`; strict admission passes.
So the camera grows the header and moves the strip consistently: a tag beyond
the padding produces a valid, shifted-strip DNG rather than corruption, at
least for one 0x400 step. Not checked: full file length and trailer, pixels
beyond the first 0x4000 raw bytes, and live buffer `+128` headroom in this
take. Camera back to stock afterwards. Evidence: private `gtag561-take/`.

**Full-frame check (live reads only).** New `fp_usb_shell/fpl_getrange.py`
(`asm/fpl_getrange.S`) downloads a file larger than staging by chunks: each call
opens the file, reads and discards whole chunks up to the wanted one, reads it
and closes; a short last chunk gives the exact length. An 8.4 MB frame takes
about 2 s. N=561 frames 1 and 40 are 8,448,512 bytes (stock + 0x400) with the
same 88-byte zero trailer, and their prefixes equal the earlier downloads.
tifffile and LibRaw (rawpy) both decode them as 3856x2170 8-bit CFA from offset
`0x13C00`. The test scenes are dark, so the pixel check uses the dark frame's
fixed pattern: against the N=560 frame the column profile correlates best at
shift 0 (0.20, versus 0.02 at a 1024-column shift), row profile 0.87. No strip
displacement. Hashes: private `gtag561-take/FULL_FRAMES.SHA256`.

**Per-frame tag write: done (24 October, live).** The M3 slice that was
paused that morning (the attempt to write the experiment observer was
interrupted before any file existed) was resumed on the owner's explicit
authorization and completed first attempt. New persistent observer
`fp_usb_shell/asm/fpl_gtagpf.S` (1508 bytes live, 1568 after the review fixes; driven by `fpl_gtagpf.py`):
mode 0 adds the same 560-byte GTAG and stays attached; mode 2 locates the
tag's value in the serialized template with the shared gyr2 parser algorithm
(raw value offset, not the aligned one: byte writes need no alignment); mode 3
rewrites all 560 value bytes in the template on every frame notify. Payload per frame: `'FPLP'`, counter,
`~counter`, N, then `(i*7+3)&255` from byte 16; a frame whose notify never
wrote would carry counter 0. Emulator test `test_fpl_gtagpf.py`: 6/6 against
the real-DNG reconstruction, including a mode-3 dispatch mutation that leaves
every frame unwritten (the association assertion fails on it); full 71-test
regression 0 skips 0 failures.

Live result (85 notifies = 1 mode 0 + 1 mode 2 + 83 mode 3): the add grew the
builder 6,874 -> 7,446; the tag value sat at template offset `0x11BBE`
(the same offset as the 560/561 takes); 83 frames, 83 writes, 0 pointer
mismatches, 0 skips; H stayed `0x13800` throughout; template pointer stable
all take. Frames 1, 2, 3, 41, 82 and 83 of `\CINEMA\A001_004\` (whole files,
stock 8,447,488 bytes each) each carry counter == frame number, full payload
verified (magic, complement, N, all 544 pattern bytes). **This settles the
per-frame contents and frame-association questions: the mode 3/type 3 notify
fires before its own frame's template DMA, so Gyro2-style per-frame data
written at frame f's notify lands in frame f's DNG — not f+1's.** Every
frame notify the observer received produced a write (writes == notifies). The
run did not list `A001_004`, so that the card holds exactly 83 frames (no
frame without a notify) is inferred from the sampled frame 83, not checked. Camera back to stock afterwards
(echo stock, owner idle, six stock observers, host cleared the observer's own
slot). Evidence: private `fpl-live-2026-10-24/gtagpf-take/` (README, events,
six whole frames, hashes). Still open in M3: Vd timing (the sensor frame-sync
hook model, untouched here), other modes, per-frame rewrites with N > 560,
and the veto path.

**Review fixes (24 October, offline; not yet run live).** A review of the
slice found the write-up's "cannot overrun the tag's own extent" untrue: the
tag's count (VARS+0x4C) was stored but never compared, so a pre-existing GTAG
smaller than N (another sup's) would have had 560 bytes written over it and
the header after it. Fixed in `fpl_gtagpf.S`: mode 3 refuses when N exceeds the
count or the template; the parser bounds-checks template offsets before adding
them and does not parse templates over 1 MiB. The counter is now the take's
frame index (mode-3 notifies since mode 0, skipped ones included; VARS+0xF0),
so a skip can no longer shift later frames' counters. The host tool writes the
shared `fpl-staging.pending` marker before uploading and removes it only once
no Subject slot holds the observer, clearing the slot on every exit path while
the owner is idle; otherwise the marker stays and blocks staging tools that
would overwrite the observer's code, and `--teardown` recovers. It now lists the
take folder and requires a contiguous frame run equal to the frame index
before giving a verdict. Tests: `test_fpl_gtagpf.py` 9/9 (the three new cases
fail or fault on the live-run observer), host `test_fpl_gtagpf_host.py` 8/8,
gyro2-sup suite 129 tests with no skips. The live result above was produced by
the observer before these fixes.

**Hookless per-frame gyro capture (24 October, built offline; live result
below).** The per-frame result gives a regular callback inside the
recording task with no code hook: the mode-3 notify of every frame. One ring
read per frame keeps up with the 600-record (~240 ms at fp's rate) ring when
frames are tens of ms apart, so this sidesteps the far-hook blocker for a first
fp L gyro measurement. `fpl_gtagpf.S` built with `GYRO=1` (2,536 bytes; the
pattern build's bytes are unchanged) arms the **shared** `gyro/gyro_drain.S`
(latched head, owned descriptor view, as `fpl_gyro_capture.S`) at mode 2, and on
each frame notify drains exactly the records published since the previous
frame into a measurement block in the GTAG: frame index, TickTimer at notify
and previous notify, consumed/latched/re-read heads, records due, written,
dropped and pad errors, status, then the records in the drain's
`{x, y, 0, z}` layout. N=1584 keeps H at `0x13C00`, the growth the N=561 take
showed decodes correctly; capacity is 189 records per frame (~75 ms at
2.5 kHz). The block is deliberately not FSG2: fp L rate, scales and axes are
what it measures, and FSG2 would carry fp's constants. The TickTimer is fp L
`C0029320`, matched instruction for instruction to fp `C002B6E0` with its
callees (only global addresses differ; see [gyro bindings](FPL_GYRO_BINDINGS.md)).

Host: `fpl_gtagpf.py --gyro` (same marker/teardown discipline) refuses unless
the ring is published as bound and its head moves in 50 ms, then downloads
every frame's header prefix and reports drain-cursor continuity, losses, frame
intervals, the gyro rate against the TickTimer, and lap suspects (a gap near a
whole ring, or a count a ring away from the rate's prediction), plus two whole
frames for StripOffsets = H. Tests: `test_fpl_gtagpf_gyro.py` 6/6 (records
since the last notify only, oldest first across the ring end, capacity drops,
latching while the producer moves, invalid P/R/head statuses without loss,
arming failure, re-arm per take; a NOP over the frame drain and dropping the
latch are each caught), host report/parser tests 11/11; gyro2-sup suite 135 with no skips. Simulated: the ring
producer and the TickTimer. **What a live take would settle:** whether the
recording task reads the coprocessor ring coherently, fp L's gyro rate against
the TickTimer, per-frame loss under recording load, and per-frame gyro data in
the DNGs. **What it would not:** scales, axes, Vd timing or calibration.

**Live gyro take done (24 October).** `fpl_gtagpf.py --gyro --run --seconds 6`
under the new live-work rule. Attach in slot 6, one press each way, teardown
cleared the slot and removed the marker; Subject back to the six stock
observers. The tool then crashed on a host bug (it read the observer's
variables only to 0xF0; the GYRO ones run to 0xFC, fixed since); the counters
were recovered from staging and the frame analysis run on the same take with
the tool's own functions. 134 frames on the card = 134 notifies, 134 writes,
every block intact with status 0, drain cursor unbroken across all frames,
H `0x13C00` and StripOffsets `0x13C00` on whole frames 1 and 134 (8,448,512
bytes, stock + 0x400). **fp L's gyro rate against the TickTimer is 2499.46 Hz**
(frames 2..134; fp's measured value is 2499.466 Hz). Frames are 41.67 ms apart
(24 fps), carrying 90..117 records each with no loss and no pad errors. So the
recording task reads the coprocessor ring coherently at every frame notify,
and per-frame gyro data reaches every DNG with no hook.

**Frame 1 lost a hidden lap.** Arming at mode 2 preceded frame 1 by 331 ms,
more than the 240 ms ring: 827 records were due, the heads showed 227 (one lap
fewer), and the 189 copied are mislabelled. The first report missed it (its
lap check skipped frame 1; fixed, with a test). Evidence: private
`fpl-live-2026-10-24/gyro-take/` (README, events, recovered counters, 134
prefixes, two whole frames, records CSV, hashes).

**Frame-1 fix, second live take: complete (24 October).** Frame 1 now reaches
back exactly one block's capacity (189 records, ~76 ms) from its own latch, as
Gyro2's BACKFILL does; a reach-back under the ring cannot span a lap whatever
the arming gap (build guard: capacity < 584). An emulator test with an
827-record arming gap reproduces the live 227-due symptom on the old observer
and passes on the new one; the host report recognises a backfilled frame 1.
Live (`A001_006`, fixed `--run` end to end, exit 0): 132 frames = 132
notifies, all blocks status 0, cursor unbroken, **13,818 records, 0 dropped,
0 pad errors, no lap suspects**, rate 2499.49 Hz, H = StripOffsets =
`0x13C00`. The arming gap was 337 ms again: systematic, so the reach-back is
required. Teardown clean. Evidence: private `fpl-live-2026-10-24/gyro-take-2/`.

M3 now has a hookless, lossless per-frame gyro stream into every CinemaDNG
frame of a short take on this mode. Still open for the M3 gate: scales and
axis mapping (motion takes), Vd timing (frame exposure vs records), the
accelerometer/level stream, other modes, long and repeated takes (stress,
storage stop), and turning the measurement block into FSG2 once calibrated.

Owned far hook (M2): the review agent fixed the assembly; main fixed the replay
test's stop condition. `v3.test_fpl_owned_hook`: 6 passed, no skips, with the
M0 compiler wrapper; veneer mutation caught. Accepted offline for one site; not
run on the camera. See [owned hook review](FPL_OWNED_HOOK_REVIEW.md).

## Preserved live boundary

The previous native task and its storage remain retained. Its host pending
marker was cleared with the owner's approval on 23 October (archived with the
trial evidence; see [tools](FPL_TOOLS.md)); clearing it freed nothing, and it was
never a completed worker-handoff record. Passing offline tests does not establish boot identity,
authorize reuse of that allocation, or prove safe native destruction.

The reviewed 3572-byte PONG resident body remains the live reference. Larger or
lifecycle-modified workers need their own deployment/admission evidence; changing
tests or a supported-image hash is not that evidence.

## Subsequent implementation

Once reference reproduction succeeds, profile the actual release-matched Gyro2
observer and metadata path rather than completing a second sidecar implementation
as a prerequisite. Headless v3 services, no-cave hook placement and measured fp L
timing/calibration remain dependencies. UI, codec/writer products, custom modes
and Fast follow their roadmap acceptance gates. Slit-scan remains exploratory.
