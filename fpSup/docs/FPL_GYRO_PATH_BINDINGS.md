# fp L 3.02: current Base take-path bindings

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Later passive live observation

`fpl_take_snapshot.py` executes a finite two-pass observer with exact settings
object validation, verified staging and echo restoration. Fifteen offline tests
pass, including real ARM execution, pointer refusal, mutations and transport
failure checks. It calls no constructors, selectors or media APIs.

First live result: settings object `C3074BA8`, reset=1, letter=A, reel=1.
SD volume/vtable matched, current/saved counters were zero, gates were 0/1;
SSD's fields were all zero and classified uninitialized. Both observations
matched. The SD candidate number 1 is explicitly unreserved, not an active
take or filename. Code/result guards, stock echo and PONG verified afterward.
Evidence/hashes: investigation log, "Passive naming snapshot". This later
observation does not establish naming collision safety or recording coexistence.

2026-10-20, **offline audit only**. The fp L Cinema path managers are
**SSD `C34392D0`, SD `C3439338`**. The context-pointer publication is
**`C30751F0`**, and its pointed-to settings byte **+5D5** is indeed
`AutoRstFlg`. These follow actual selector/constructor/consumer instructions,
not a global relocation delta.

The short Base name can correspond to the stock next-take identity for valid,
initialized, stable state. It is **not a complete stock filename, an atomic
reservation or a collision check**. In particular, copying the addresses alone
does not make the writer safe across reset numbering, multiple volumes, dates,
repeated attempts or failed recordings.

Scope: only this document and `tools/fpl_gyro_path_audit.py`. No camera access,
production changes, hook installation, card writes or commits. Earlier context:
[recording bindings](FPL_GYRO_RECORDING_BINDINGS.md),
[gyro bindings](FPL_GYRO_BINDINGS.md), [port](FPL_PORT.md).

## Reproduction

```sh
ROOT=/path/to/firmware
python3 -B tools/fpl_gyro_path_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" --self-test
```

Requires Capstone; `--self-test` also requires Unicorn. The sibling
`fpl_gyro_audit.py` supplies the existing instruction normalizer and fingerprints.
All firmware files are read-only. No live modules are imported.

| MAIN, loaded at C0000000 | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

Verified **23 bounded ARM correspondences, five explicit materialized-address
pairs, ten string pairs, four vtable slots, 24 execution scenarios and 14
negative cases**. The normalizer preserves registers, memory offsets, ordinary
constants and internal branches; external branch destinations and MOVW/MOVT
immediates are reported separately. Materialized manager/context/vtable/saved
state addresses and formatting strings receive additional exact checks.
Matching bodies do not recursively certify every external callee.

Execution scenarios run the **real stock instructions** for selector, number
peek, next-tuple calculation and validity check in each image. Initialization
guards are stubbed as already initialized; context access returns synthetic
settings; string comparison is stubbed. Every executed instruction must lie
within the selected routine or an explicit stub, and all writes must remain
inside synthetic RAM. This tests neither real initialization nor filesystem I/O.
Cases include both volumes, reset values 0/1/2, both high-water orderings,
equality, initial zero, 998/999 boundaries, reel 1000 and a signed-negative
counter diagnostic.

Negatives: eight full-image fingerprint changes/truncations; four tests bypass
fingerprints to mutate the flag-field offset, branch condition, manager literal
or format string; two execution-only negatives change increment 1 to 2 and
signed BGE to unsigned BHS. The latter is caught by the signed-negative case.
The report is JSON on stdout; missing dependencies/images fail, not skip.

## Source contract being audited

Current `gyro/writer_core.inc.S:take_path`:

1. Chooses SSD only for volume **5**, otherwise SD.
2. Loads manager +10. If settings pointer is null, or its +5D5 byte is zero,
   takes the **unsigned maximum** with manager +2C; otherwise ignores +2C.
3. Adds one, emits manager byte +8, three decimal reel digits from +C, `_`,
   and three decimal take digits. It does not validate these fields.

`gcsv_task.S` Base uses fallback rung 1 (volume root), then rung 2 (SD root),
and appends `.GYR`/`.json`. It does not use the stock pathname object itself.
The root path is therefore `\A001_037.GYR`, not a literal `\GYRO` directory
despite older comments. A fallback to SD still uses the originally selected
recording manager's identity, not a fresh SD-manager identity.

## Selector and initialization: concrete chain

| Role | fp 5.02 | fp L 3.02 | Checked bytes |
|---|---|---|---:|
| path-manager selector | C03092F8 | C030D390 | 298 |
| Cinema constructor | C030ADD8 | C030EE70 | B0 |
| media synchronization | C030AE88 | C030EF20 | 1E0 |
| next pathname object | C030B068 | C030F100 | F0 |
| context owner | C0021C00 | C0021B20 | 40 |
| context get | C0021C40 | C0021B60 | 10 |

Sizes and offsets in this document are hexadecimal unless stated otherwise.
All entry points are ARM, not Thumb pointers.

Selector arguments: r0 points to a selector word; r1 points to a volume string.
It compares against materialized **`SD\0` (3 bytes)** and **`SSD\0` (4 bytes)**,
assigning volume ids 1 and 5. Selector word **1** chooses the Cinema class.
Other selector values/unknown volume strings choose different objects and are
not permission to treat them as these Cinema managers.

fp L selector materializes **C34392D0** at `C030D398/C030D3A0`.
Within the Cinema branch:

* SSD: guard at base+A74; constructor `C030EE70(base,5)`; returns base.
* SD: guard at base+A7C; constructor `C030EE70(base+68,1)`; returns base+68.

This explicit `add #68` is the evidence for **C3439338**. There is no independent
literal for the SD manager, and searching only literal references would miss it.
The fp selector materializes C3438398 and uses the same instructions to derive
C3438400. The guards are `C0013090/C00131E4`, with destructor registration
through `C00132F4`: these accessors can **construct/mutate** state. Do not call
the selector during a passive snapshot or before its subsystem is ready.

The constructor stores volume at +0 and the Cinema dispatch table at +4:
fp **C0B55D8C**, fp L **C0B8D874**. It zeroes two 1C-byte tuples at +8 and +24,
sets +40 to 9999, clears bytes +44/+45 and initializes embedded members.
An allocated/static address alone does not mean media synchronization occurred.
Verified table slots: +14 = media sync; +18 = next pathname; +24 = advance take.

## Fields, their actual producers and meanings

| Manager offset | Meaning established by instructions | Evidence |
|---|---|---|
| +8, byte | camera letter | media sync copies signed byte settings+5D6; reconciliation checks A..Z; formatter `%c` |
| +C, word | reel number | sync copies unsigned halfword settings+5D8; filename parser reads characters 1..3; formatter `%03d` |
| +10, word | media/current take counter | sync scans matching letter/reel names and keeps largest parsed take; advancement increments it |
| +14, word | within-take frame counter | reset by advance-take; separate frame step increments it; DNG suffix uses the tuple's +C |
| +2C, word | saved/high-water take counter | +8 of the tuple at +24; loaded from separate saved-state object, reconciled with +10 |
| +44/+45, bytes | manager control gates | setters at fp C030BEF8/C030BF10, fp L C030FF90/C030FFA8; do not equate raw nonzero address with readiness |

The context owner materializes fp **C30751D4** / fp L **C3075194**. Its
getter loads +5C, proving the publication word fp **C3075230** / fp L
**C30751F0**. This is a pointer to settings, not the settings block itself.

### Media scan and identity changes

Sync reads settings+5D6/+5D8 into the identity tuple, opens `\CINEMA`, and
calls fp `C030B9A0` / fp L `C030FA38` to enumerate names. The scanner compares
the first character and parsed reel against the selected identity, parses
three take digits starting at character 5, and retains the **signed maximum**
in tuple+8 (= manager+10 for the initial tuple). No matching entry resets the
counter to zero. External enumeration/encoding behavior is not emulated here.

Before making a pathname, stock calls reconciliation fp `C030B6D8` /
fp L `C030F770`. If its +45 gate is clear it returns the supplied tuple;
otherwise it checks settings letter/reel, substitutes A/1 for invalid letter
or zero reel, and may rescan `\CINEMA` when identity changes. This is more than
the four direct loads in Base. Reentrancy, concurrent settings changes and
whether this synchronization has completed at an arbitrary observation time
remain runtime questions.

## AutoRstFlg and high-water arithmetic

This byte is not inferred from proximity to another setting. In
fp `C030B1A8` / fp L `C030F240`, actual context calls are followed by
`ldrb [settings,#5D5]`; the adjacent materialized log string is **AutoRstFlg**.
Independent consumers in load-take and peek-tuple use the same offset.

Let `c = manager[10]`, `h = manager[2C]`, `reset = settings[5D5] != 0`.

**Read-only number peek**, fp `C030BA80` / fp L `C030FB18`:

```text
copy the 1C-byte current tuple
if not reset: output.take = signed_max(c, h)
else:         output.take = c
```

**Next tuple**, fp `C030BB28` / fp L `C030FBC0`, copies that tuple and adds one
to its take and frame fields. These functions return a candidate without
reserving it. **Advance take**, fp `C030B1A8` / fp L `C030F240`, mutates:

```text
if reset:
    c = c + 1                     # h is not updated/persisted by this branch
else:
    c = h = signed_max(c, h) + 1
    save tuple at manager+24       # saves its take field
manager[14] = 0
manager[1C] += 1
update stock control state, then return number-validity result
```

The saved value is not merely another on-media maximum. Save/load functions
materialize fp **C3074954**, fp L **C3074914**, load its pointer at +14 and
use pointed-to word +8. Save invokes fp `C00222D0` / fp L `C00221F0` after
storing, with log **SaveTakeNo**; durable-write internals are outside this audit.
Both volume managers use this saved-state chain. Do not invent separate
per-volume persisted counters.

Load-take fp `C030B588` / fp L `C030F620` reads saved data, treats a saved value
**>=999 (signed)** as zero in the local candidate (logging `LoadTakeNo Reset`),
then assigns manager+2C. With reset set it replaces that with current +10;
otherwise it raises +2C to the signed maximum with +10. It calls the saved-state
update routine on the reset path; this audit does not claim the local zeroing
alone demonstrates a particular persisted on-disk value.

### Limits and the difference from Base

Stock `C030BC40` / `C030FCD8` checks **signed reel <1000 and take <1000**.
There is no lower-bound check in that small helper; identity validation elsewhere
is important. A current/saved 998 produces candidate 999 (accepted); 999
produces 1000 (rejected), not a silently wrapped 000. Both are exercised.

For valid nonnegative counters, Base's unsigned maximum equals stock's signed
maximum and its `+1` matches the next tuple. Outside that domain they differ.
Base also treats a null settings pointer as reset-off, while stock obtains the
context through its accessor; null is not proven legitimate state. Base's
`put_dec3` assumes 0..999 and does not enforce it: 1000 produces a nondecimal
hundreds character. Hence a profile should not turn these direct loads into
an unconditional filename generator.

## Supported stock formats versus Base sidecars

fp `C030ABE0` / fp L `C030EC78` contain the same checked format strings:

```text
\CINEMA\%c%03d_%03d\%c%03d_%03d_%04d%02d%02d.XXX
\CINEMA\%c%03d_%03d_%04d%02d%02d.XXX
```

The passed settings object's word +C selects folder form when zero, flat form
otherwise. The final three fields come from halfwords of the supplied date
object. This establishes the numeric date suffix shape; it is not a timezone
or rollover guarantee. Do not confuse this object with CameraMgrSetting+40
merely because other code uses a format field nearby.

fp `C030ACA0` / fp L `C030ED38` recognizes **MOV, WAV, DNG**, returns null
for other extension strings, and writes `.%s` or `_%06d.%s` at fixed offsets
in its own pathname buffer. In the intended combinations:

* MOV: flat `\CINEMA\A001_037_YYYYMMDD.MOV`.
* WAV: folder `\CINEMA\A001_037\A001_037_YYYYMMDD.WAV`.
* DNG: folder `\CINEMA\A001_037\A001_037_YYYYMMDD_NNNNNN.DNG`.

The folder/flat setting and extension must agree: this helper uses fixed offsets,
not arbitrary-format path assembly. No new filename-format difference was found
between these fp/fp L bodies and literals. This is bounded support, not a claim
that all firmware recording types use this class (other selectors do not).

Base deliberately emits only `A001_037` plus its sidecar extension at the root.
It omits date and frame suffixes and the Cinema directory, so the short identity
alone cannot distinguish all retries, settings resets or reused media. Firmware's
scan of `\CINEMA` does not check for an existing root `.GYR`/`.json`, and the
Base fallback to SD can put an SSD take's short name beside an unrelated SD
take's sidecar. Neither this audit nor the addresses prove overwrite avoidance.
A later writer design must detect/refuse a conflicting sidecar and preserve
the true association, rather than invent another clip number or modify the
camera's manager counters to make room.

## START timing, non-live limitations and profile boundary

The checked recorder span fp `C037900C..C03790BC` /
fp L `C0379224..C03792D4` shows the actual pre-hook path:

1. Selector word 1, volume string from file manager, call **C030D390**.
2. Virtual call at **C0379268** through manager table **+18**, the
   `next_path_object` method **C030F100** mapped above.
3. Extension conversion through the returned pathname object, then audio start
   **C01F7BB8**; START candidate **C03792D0** follows.

The returned object's table is fp **C0B55E58** / fp L **C0B8D940**; its +C
slot points to the checked extension routine. This is also verified directly.

This connects the manager to the current hook rather than to a historical audio
debug path. The pathname method reconciles identity, peeks and increments a
**temporary** number tuple and constructs a path object. It is not evidence that
every later asynchronous recording operation succeeded. The caller has later
failure exits, and the audit does not prove quiescence of other manager users
between those instructions and a future logger's loads.

As established in the recording audit, settings live-block +E0 == 0 bypasses
this START hook. MOV/no-audio/HDMI behavior cannot be generalized from the
audio-file branch. Names read idle, after STOP or on a later callback may be
off by one; a valid number is not proof that it is this take's number.

**Candidates for shared firmware profiles**, not production edits:

```text
PATH_MGR_SSD = C34392D0
PATH_MGR_SD  = C3439338
SETTINGS_PTR = C30751F0
camera_letter = +8; reel = +C; current_take = +10; saved_take = +2C
AutoRstFlg = settings+5D5
```

These require initialized Cinema managers, validated letter/reel/counter ranges,
a stable recording-volume identity and a proven observation point. The stock
accessor/initialization/sync/advance functions are evidence, **not passive APIs
to call casually**: they can initialize state, enumerate media, change counters,
persist settings or allocate path objects. Base's shared output buffers are also
not demonstrated reentrant. A read-only host snapshot can race manager updates;
normalization and synthetic execution supply no locking/lifetime guarantee.

Next work can place these bindings behind shared profiles while retaining one
logger implementation. Live recording/filename agreement, collision handling,
writer coexistence and shutdown remain separate acceptance steps. No changes
to the other session's drain seam or latched diagnostic were made here.
