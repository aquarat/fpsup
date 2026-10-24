# Gyro2: shared fp L tag-observer seam (offline, 23 October 2026)

## Implemented boundary

`projects/gyro2-sup/src/gyr2.S` remains the single observer/tag/parser algorithm.
Its default fp build is still **exactly the released v0.2.0 BIN** (4,040 bytes,
SHA-256 `2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3`).
Source hashes intentionally change; M0's release-pin verifier continues to use
the immutable release-matched source revision.

The compile-time `GYR2_FPL_OBSERVER` selection uses
`src/profiles/fpl302_observer.inc.S`. It emits the existing `tag_observer`,
`take_start`, TIFF/MakerNote parser and unsigned division, private state and a
zero-filled tag-copy source. Mode 0 actually sizes/adds the tag; mode 2 actually
finds its aligned location and capacity; mode 3 delivers the current template
pointer/length to an explicitly supplied ARM frame callback. There is no second
observer implementation.

The probe has **no installer/FSB1 header**, no `entry`, `drain`, snapshot, level/Vd
hooks, sensor metadata call or fp frame/sample producer. It starts with private
data: call the returned `tag_observer` offset, never offset zero. The owner must
own/zero its allocation and callback and arrange registration/lifetime before
any eventual use. The current helper only builds offline bytes.

`build.observer_probe(fp_image, fpl_image, *, sample_hz, tag_capacity,
frame_callback)` requires all three experiment inputs. Missing inputs fail;
sample Hz is bounded 1..10000, tag capacity 352..4096, callback is a word-aligned
USER-RAM ARM address. These limits are build guards, **not measured fp L cadence,
native free-header capacity, allocation ownership, or calibration**. The test
values 100/1234 Hz and 768 bytes are deliberately synthetic. No period, scale,
6000×4000 sensor geometry or fp hook address appears in the probe's emitted text.

## Exact official inputs and evidence

Only MAIN is needed: all audited instructions and DataPool vtables below are
file-backed there. No DATA image or runtime calibration was read.

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 MAIN | 49245696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 MAIN | 49310208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

`projects/gyro2-sup/audit_observer.py` refuses any different image fingerprint,
emits bounded disassemblies and per-window hashes for both images, verifies
explicit BL edges, and reads the native DataPool vtable slots. The probe builder
includes this evidence plus its source hashes, parameters, symbols and text hash.
The evidence is exact to these images; matching code does not establish real-time
object lifetime, concurrency or storage capacity.

| Binding / ABI | fp 5.02 | fp L 3.02 |
|---|---|---|
| `F_SUBJECT`, initialized singleton | C00577F0 → C31AC4EC | **C0054E28 → C31AB0D0** |
| `F_ATTACH(subject, observer)` | C00D2958 | **C00CF208** |
| native event notify `(subject, mode, type, pool)` | C00559F0 | **C0053028** |
| native observer iteration | C0055FE0 | **C0053618** |
| `F_ADD_TAG(builder, ifd, tag, type, count, src)` | C00BA378 | **C00B6B20** |
| `F_RATE(out[2])`, numerator/denominator | C00C9BD0 | **C00C6378** |
| DataPool vtable | C0735A04 | **C07333D4** |
| vtable `+2C`, CinemaDNG builder getter | C0056748 | **C0053D80** |
| vtable `+40`, event getter | C0055DB0 | **C00533E8** |
| vtable `+44`, event setter | C0055DF8 | **C0053430** |
| template owner accessor | C038A0F8 → C358DB98 | **C038A310 → C358E9D8** |
| template pointer / length | C358DBA8 / C358DBA4 | **C358E9E8 / C358E9E4** |

Concrete call/layout evidence:

- `C038A35C` calls Subject; `C038A36C` calls `C0052F30` with type 3.
  The latter constructs the native DataPool vtable, then at `C0052FFC..C0053000`
  passes mode 0 to `C0053028`. The factory prefix materializes C07333D4.
- `C0379170` obtains Subject; `C0379180/84/88` pass type 3, mode 2 and notify.
  Earlier `C03790D4..E0` obtains the template owner and stores length at `+C`.
- `C038C8F0..C038C918` obtains Subject and chooses mode 2/3, type 3 before
  notification. The frame branch is conditional; not every call is mode 3.
- `C038A314/18` materialize owner C358E9D8. `C038A530` reads owner+10.
  These are a pointer field and a length field, not an arbitrary BSS relocation.
- Subject iteration ends at `subject+24`: **nine slots**, handler at observer
  vtable+0C. Returning zero detaches; shared observer returns one. Native attach
  rejects/asserts on a full list; this seam does not supply a safe installer.
- Native event get/set access pool+45E0, with words mode/type and flag byte +8.
  Native builder getter returns pool+45D0 after its native valid-member check.
  The tests execute these methods, not synthetic vtable stubs.
- Tag wrapper saves 48 bytes, loads original stack count/src at +30/+34,
  computes bytes using the native type-size function C00BC568, creates a source
  descriptor at C00B9AE8, then calls insertion C00B6A38. MakerNote IFD 5, tag 4653, UNDEFINED type 7
  and source zeros are checked at the real wrapper/backend boundary.
- The native rate routine reads context+14. Tested enumerations 0..11 yield
  `(30000,1001), (24000,1001), (24000,1000), (25000,1000), (30000,1001),
  (30000,1001), (48000,1000), (50000,1000), (60000,1001), (100000,1000),
  (120000,1001), (30000,1001)`. **Unknown enum fallback is not proof of the
  actual recording rate.** This is a sizing input, not IMU calibration.

## Sensor/lens correspondence: deliberately outside the emitted seam

The earlier [metadata binding audit](FPL_GYRO_METADATA_BINDINGS.md) established
raw accessor/storage correspondence. The new audit includes the bounded native
mode/timing/geometry and correction-owner/population-call windows:

| Raw role | fp | fp L |
|---|---|---|
| current-mode wrapper | C032C720 | C032C7C0 |
| timing row | C0320FC8 | C03250E0 |
| geometry row | C0321028 | C0325140 |
| correction owner | C00467B0 → C307BC38 | C0043ED8 → C307A81C |
| first correction-focal word | owner+11B8 = C307CDF0 | owner+11B8 = C307B9D4 |

The correction update explicitly forms owner+11B8 and calls the population body
(fp C0053010, fp L C0050648). This establishes storage correspondence, **not**
active-lens slice selection, freshness, units or calibrated optics. The current
Gyro2 `MODE_OBJ`, table semantics including vertical binning, full-raster fields,
period/scales, TickTimer/IMU lap model, Vd and level patch sites are not admitted
as an fp L product profile by this patch. Raw mode metadata requires its own
owner/table ABI proof before reconnecting `mode_info`.

## Executed tests and how to reproduce

Main independently reran all 11 fp L observer tests after delivery; all passed
without skips, including exact default-fp release equality. The 39-test upstream
run below is the implementation agent's separate regression result.

Use the M0 compiler adapter described in [FPL_REFERENCE_BUILD.md](FPL_REFERENCE_BUILD.md)
on PATH. Set `FP_MAIN` and `FPL_MAIN` to the external official inputs:

```sh
cd projects/gyro2-sup
python3 -B -m unittest -v test_fpl_observer
python3 -B audit_observer.py --fp-image "$FP_MAIN" --fpl-image "$FPL_MAIN" > "$AUDIT_JSON"
```

The suite errors on missing images rather than silently skipping. It runs native
fp L initialized Subject lookup, attach, notify, nine-slot iteration, native
DataPool getters/setter, native rate-table code, tag wrapper/type-size code and
the **actual shared observer/parser instructions**. Every external instruction
must be on an explicit allowlist. Calls are instruction-bounded; callee-saved
registers and stack restoration are checked, as is 8-byte stack alignment at
tag-copy and frame-callback boundaries.

**Executed result: 11 passed, no skips.** With the explicit test-only inputs
1234 Hz / 768 bytes / callback `46020000`, the raw probe is 1,944 bytes,
`tag_observer` offset 280, SHA-256
`14a7e4d492ff6b91ba3d850e1cde2d4067e62579b8d9e1d4e9cd624544279c8b`.
These bytes contain an emulator-owned callback address and must not be installed.

Stubbed dependencies: initialized guard path, attach lock constructor/destructor,
context access, tag source-descriptor/insertion boundaries, and the owner-supplied
frame consumer. Consequently this does not certify lazy construction, native
tag allocation/serialization or FSG2 generation on fp L. The TIFF fixture is
structural and deliberately unaligned, not a claimed fp L captured DNG.

The subsequent [native tag-capacity slice](FPL_GYRO2_TAG_CAPACITY.md) executes the
descriptor, actual later value-copy, insertion and IFD serialization. It corrects
the earlier assumption that C00B9AE8 itself copies bytes, and demonstrates that a
nonzero add return can still lose a tag or its data on allocation failure.

Checks cover event 0 adding zero tag data, real rate sizing, event 2 locating the
tag/capacity, event 3 forwarding the mapped template, wrong types/modes, missing
builder, malformed template, native attach duplicate handling, refusal of missing
parameters and exact default fp bytes. An isolated machine-code mutation changes
the event getter load from vtable+40 to +2C; the previously successful tag-add
invariant fails (zero tags), showing the real native dispatch test is sensitive.

The unchanged upstream Gyro2 suite was also executed against the new default
source: **39 passed, no skips**, including real FSG2 frame blocks and the three
header fixtures. Thus the existing fp FSG2 implementation/bytes are preserved;
this is not evidence of calibrated fp L samples.

To run that suite in the migrated checkout without creating firmware symlinks:

```sh
python3 -B - <<'PY'
import os, pathlib, unittest
import build as G
import test_v3 as V
V.IMAGE = G.B.IMAGE = pathlib.Path(os.environ['FP_MAIN'])
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromName('test_gyr2'))
raise SystemExit(not result.wasSuccessful() or bool(result.skipped))
PY
```

## Next concrete product gate

1. Owned, no-cave v3 services and resident publication/lifetime, including observer
   duplicate admission, full-slot refusal, teardown/quiescence and stock restoration.
2. Native tag pool/header capacity and serialized header size, both alone and with
   Lossless. The probe's supplied cap is not an admission decision for a real take.
3. Connect a measured fp L producer/frame consumer: prove tick/ring timing and
   calibration, raw sensor owner/table semantics, lens validity, and take identity.
4. Level/Vd hooks require actual fp L displaced-instruction proof and a **far-hook
   placement/veneer** solution into owned USER RAM, complete journal coverage and
   cache publication. No assumption that fp cave allocation/BL range transfers.

No camera operation, new live hook, card, marker, commit or publication is part
of this seam. This is executable offline integration groundwork, not an
installable fp L Gyro2 product.
