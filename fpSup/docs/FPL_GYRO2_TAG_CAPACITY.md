# fp L Gyro2: native tag storage and bounded IFD serialization

**Offline increment, 23 October 2026. No camera acceptance or hardware capacity
claim.** The default Gyro2 source/algorithm is unchanged by this increment; its
4,040-byte fp artifact still has SHA-256
`2cbfe477bf8b11cc0e4fed37df177f6f5d561bf31243e2b00687eed15aa9a7d3`.

## Result that changes the next implementation gate

**`F_ADD_TAG` returning nonzero is not sufficient evidence that the tag or its
data was stored.** Executed fp L instructions show:

| Injected failure (new tag in empty IFD) | Native return | Result |
|---|---:|---|
| 20-byte value-object allocation | 0 | no tag |
| tag-data allocation (768 fixture bytes) | **1** | tag exists with count 768, but no owned value bytes |
| 24-byte tag-entry allocation | 0 | no tag |
| 200-byte initial pointer-vector allocation | **1** | no tag |

On data-allocation failure, the native serializer emits a tag count of 768 but
leaves the inline value/offset word untouched. In the poisoned fixture it is
`A5A5A5A5`; it is not a valid offset or a native error sentinel. The serialized
fixture shrinks to 108 bytes. The shared Gyro2 mode-2 parser selects **no writable
area** for all four failure outputs; the new host validator also rejects them.
This does not mean the frame callback is disabled: the observer-only seam still
calls its supplied consumer, which must honor admission/ownership.

The generic native IFD serializer takes **no capacity argument**. With a measured
876-byte fixture and a deliberately insufficient 512-byte owner bound, it writes
through the guard. A post-write validator cannot undo that corruption. Therefore
admission must use the native measured size **before** serialization and validate
the resulting structure **before** any FSG2 write. No new observer branch based
only on r0 was added: it would miss the demonstrated nonzero-return failures.

## Code and executed boundary

- `projects/gyro2-sup/test_fpl_tag_capacity.py`: extends the existing actual-
  instruction observer harness. Native source-descriptor creation, value copy,
  tag insertion/replacement, refcounts, pointer-vector growth/search/sort, IFD
  size and serialization now run from the official fp L MAIN image.
- `projects/gyro2-sup/audit_tag_capacity.py`: exact image checks, bounded paired
  fp/fp L windows/hashes/disassemblies, supporting masked correspondence checks,
  and explicit unmasked size/count/alignment/publication operands.
- `projects/gyro2-sup/tag_capacity.py`: `admit_serialization()` pre-write bounds
  and `validate_header()` post-serialization structural/ownership admission.
  The latter calls the existing **`fsg2.gtag_area`**, defining no new FSG2 format.

The test constructs native IFD/vector objects, then supplies a **synthetic
root→Exif→MakerNote object graph** with the observed native fields. The actual
native `F_ADD_TAG` resolves that graph and dispatches into the real IFD vtable.
For the serialized fixture, the TIFF/Exif/Sigma-signature envelope is host-made;
the MakerNote IFD, entry count, entry offsets and tag values are written by
native `C00BAC20`. It is not a complete native camera DNG take or a native RAW
buffer allocation. No fp capture is presented as an fp L recording/calibration.

In the end-to-end seam test, real native notify → shared observer → native tag
storage runs for mode 0. The original tag source is then overwritten with FF;
the serialized output remains zeros, proving the native copy owns those bytes.
Mode 2 runs the shared parser on the native IFD output; mode 3 forwards that
template to the same explicit test-owned callback.

Stubbed lower boundaries are recorded precisely: initialized singleton guards,
attach/heap locks, context getter, heap backend `C03D8E98`, lower free
`C03D9090`, base-destructor runtime cleanup `C03D9198`, memcpy `C001510C`,
allocator diagnostic logging, and native memory-manager allocation for the
template-owner test. **The native outer heap wrapper executes**, including its
zero-size path. Heap failure is injected at the backend; no claim is made about
the camera's physical free-heap state, concurrency, latency or allocator policy.
Assertions at `C0011100` stop the emulation and are reported, not treated as
successful returns. All top-level calls are instruction-bounded and check
callee-saved registers/stack restoration.

## Native evidence, not an inherited fp header limit

Both exact official MAIN inputs are mandatory; all relevant code/vtables are
file-backed in MAIN. DATA was not needed or read:

| Image | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49245696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49310208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

Key executed fp L routines/windows (the audit records their explicit fp pairs):

| fp L address | Meaning demonstrated |
|---|---|
| C00B9AE8 | source descriptor `{pointer, bytes, fallback}`; **not itself a copy** |
| C00B9C08 | allocate/copy owned value data; failed data allocation clears its stored size |
| C00B6700 | select requested IFD; MakerNote path resolves Exif and tag 927C |
| C00BB400 | create/replace tag; return can be 1 after failed vector insertion |
| C00BA4E0 | vector append; failed growth drops the newly referenced entry |
| C00BA5B8 | grows pointer capacity by **50 entries** (`+32` hex), four bytes each |
| C00BA660 | allocate temporary sort pointers; failure on nonempty IFD **asserts** |
| C00BAB08 | generic IFD serialized size: count/entries, child/value sizes and even padding |
| C00BAC20 | generic IFD serialization; caller supplies destination but no capacity |
| C03D8DE8 | outer native heap-allocation wrapper |
| C038A4A0 | template allocation from caller-supplied size, 64-byte alignment, manager kind 12 |

There is **no fixed 50-tag cap** established here. The test fills 50 entries;
the next append grows capacity to 100 if its 400-byte allocation succeeds.
When that allocation fails, the add call still returns 1 and count remains 50.
The serialized output has no Gyro2 tag and is refused. Duplicate tag insertion
replaces the existing entry instead of reserving a second independent span.

The native template allocator passes its incoming size to `C001D038`, publishes
the returned pointer at owner+10 and returns it, including null. A preexisting
pointer causes a native assertion. In the real caller:

- `C0378F74..C0378F84` obtains the requested size through `[[r7+8]+10]`.
- `C0378F90..C0378FA0` obtains the owner and allocates that size.
- `C0378FB0..C0378FBC` tests null and takes the error path with r2=3.
- `C0378FC0..C0378FD4` invokes another virtual method at `[[r7+8]+1C]` with
  the allocation. The current experiment does not instantiate this full owner.
- `C03790AC..C03790E0` gets the serialized length through another virtual path,
  stores it at recording object+14C and template owner+C.
- `C038C964..C038C994` forwards the template pointer and object+14C length to
  the header DMA path; RAW placement depends on object+4C and a separate helper.

These exact windows establish interfaces and failure edges. They **do not**
resolve the full mode-selected formatter/RAW owner or prove a globally safe
maximum. In particular **`0x15400` is not used as an fp L admission limit**.

## Host admission contract

Before writing, pass the native IFD size, envelope prefix bytes, independently
known owner allocation size and RAW start to `admit_serialization()`. It rejects
overflow/insufficient bounds. No experiment tag size substitutes for owner data.

After writing, `validate_header()` accepts only a bounded, little-endian,
single-strip root→Exif→Sigma MakerNote layout. The serialized length must fit
the supplied actual bytes/allocation and precede the independently supplied
RAW start; the root's LONG StripOffsets must agree with it. Additional IFD
graphs/next IFDs are refused. It checks count/table/value bounds, duplicate tags,
signature, tag type/count, overlapping structures and overlapping out-of-line
values (including **Lossless tag FD4C**). The aligned Gyro2 span must retain more
than the existing 60-byte frame header plus 288-byte event reserve. It then
cross-checks the span with the existing FSG2 parser.

This strict host tool is an offline admission check for the specified shape,
not a general TIFF validator or a resident firmware guard. The native generic
serializer has already overwritten an undersized destination by the time a
post-write check runs; product integration must enforce the pre-write contract.
The current serialized fixture is 876 bytes: 90-byte envelope, 18-byte one-entry
IFD and 768 native copied bytes, with writable GTAG span `[108,876)`. A separate
synthetic FD4C value is added and serialized natively to test non-overlap. This
does not reproduce a live Lossless take or its capacity consumption.

## Tests and mutations

Main independently reran `test_fpl_tag_capacity test_fpl_observer` after
delivery: all **21 tests passed**, with zero skips and external official images.

**Executed: 21 tests passed, no skips** (10 native storage/capacity tests plus
11 observer regressions, including default fp artifact equality). The paired
image/native-window audit passed. The synthetic 876-byte native-IFD fixture has
SHA-256 `01e75a8659d5980733caa999175bd32a55bd97cf04d8fc3d7c9ac57e0284ad8e`;
this identifies test data, not a camera-derived DNG.

Using the M0 compiler adapter on PATH and explicit external `FP_MAIN`/`FPL_MAIN`:

```sh
cd projects/gyro2-sup
python3 -B -m unittest -v test_fpl_tag_capacity test_fpl_observer
python3 -B audit_tag_capacity.py --fp-image "$FP_MAIN" --fpl-image "$FPL_MAIN" > "$AUDIT_JSON"
```

Coverage includes native allocation failures at each of the four stages, full
pointer-vector growth/failure, native duplicate replacement, owned copy lifetime,
native sort-allocation assertion, undersized-buffer guard overwrite, template
allocation/alignment/null/preexisting-pointer behavior, native event 0/2/3, and
malformed IFD counts/offsets, duplicate serialized tags, RAW/FD4C/directory alias
refusals. Default fp artifact equality remains in the observer suite.

One isolated machine-code mutation changes `C00BA530` (publish incremented
vector count) to NOP: native add still returns 1, but the positive native-tag
invariant fails and admission rejects the missing tag. Unicorn's translated
block cache is explicitly invalidated after this in-emulator mutation; the
official image file/source is never modified. Serialized-output mutations also
demonstrate that each unsafe header is refused. No full upstream mutation sweep
or camera trial is claimed.

## Remaining product gate, narrowed

1. Resolve and instantiate the mode-selected formatter/owner virtual calls above;
   obtain the **actual allocation size, serialized length and RAW start** for the
   selected fp L recording mode. A real fp L DNG/header capture is still absent.
2. Establish full native serialization and native RAW/header buffer admission,
   including actual Lossless composition. The synthetic IFD slice cannot supply
   those owner facts or prove concurrent header immutability.
3. Add an owned no-cave resident admission path that can refuse **before** a write
   and accounts for nonzero-but-incomplete tag insertion. Callback lifecycle,
   far-hook placement/restoration and calibrated producer gates remain separate.

No camera, live hook, card, marker, commit or publication was used for this work.
