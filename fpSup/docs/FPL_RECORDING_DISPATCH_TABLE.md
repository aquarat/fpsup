# fp L dispatch descriptors: bounded passive-read proposal

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Decision

**An exact table count/end is not proved. Do not read an assumed whole table.**
The small producer-justified alternative is:

| Indexed event | Read address | Bytes | End, exclusive |
|---|---|---:|---|
| `23` | `C2F2F738` | 16 | `C2F2F748` |
| `24` | `C2F2F748` | 16 | `C2F2F758` |

One contiguous read of **32 bytes at `C2F2F738`** covers both and nothing else.
These are candidate start/stop rows, not already-observed thunk associations.
The host decoder accepts only these indices and lengths. This is a tooling/read
proposal bound, **not the firmware's table bound**. No camera operation, hook,
task creation or camera file operation was performed for this audit.

The result thunk `C03ABBD0` is validated as stock code, but its indexed event ID
remains unproved. Do not infer its row from vtable slot +98, sequence order,
or a different subsystem's event number. A negative result in the proposed two
rows is not evidence that the three thunks are absent from the table.

## What the dispatcher actually bounds

Official fp L 3.02 MAIN: 49,310,208 bytes, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
CPU base `C0000000`; image end **C2F06A00**, exclusive.

`C038AEC0..C038AF70` materializes **C2F2F508** and performs:

```text
id = event[+4]                         // C038AEDC
row = C2F2F508 + (id << 4)             // C038AEE0, ARM 32-bit arithmetic
selector = signed32(row[+8])
result = 0x13
if selector != 0:
    adjusted_this = state + row[+4]
    if selector < 0: target = row[+C]
    else: target = *( *(adjusted_this + row[+C]) + selector*4 )
    result = target(adjusted_this, event, owner)
return state_vtable[+B8](state, result)
```

There is **no maximum-ID guard before indexing**, and no count/end literal in
this complete function. Row word zero is never read. The positive selector is
a **word index**, not a byte offset. Any negative signed selector takes the
direct arm; it need not equal FFFFFFFF. Zero skips the target, but still invokes
the state return filter at +B8.

The sole aligned direct BL found to this dispatcher is `C0388E74`, inside
consumer `C0388BF8..C0388EC8`. The examined consumer has special event/state
branches, state-object null/identity checks and post-dispatch publication; it
does not establish a maximum event ID. `C03A9770` forwards to enqueue
`C03A9798`; that enqueue checks pool capacity and distinguishes IDs 2B/30 for
reservation behavior, but does not reject IDs above a maximum. Pool capacity
is not descriptor count. This is a statement about these inspected paths, not
proof that no other producer imposes a local bound.

### Initializer and ownership limits

**Packaged-DATA follow-up:** [FPL_DATA_DISPATCH_PROVENANCE.md](FPL_DATA_DISPATCH_PROVENANCE.md)
now establishes exact packaged initial values for rows 23/24/2B/30 from the
separate official DATA payload, matching the archived bounded observations.
The MAIN-only search limitation below is historical; loader execution,
immutability and whole-table bounds remain unproved.

The table address is outside MAIN. The aligned MOVW-immediate search over the
first `730000` image bytes finds the table-base materialization at `C038AECC`
(MOVT at `C038AED4`), but no trustworthy initializer. Earlier failure work also
did not recover the direct target/row from image data. These searches do not
exclude encoded, relocated or decompressed initialization, or other address
construction forms. Neither allocation size, exclusive storage ownership,
immutability, nor exact last valid row is established.

`C03A97D4..DC` separately loads a pool pointer from **C2F2F838**. Its numerical
distance from table base is `330` bytes = 51 rows. **That adjacency is not an
end symbol or a proven 51-row declaration.** Likewise a producer using event
32 does not establish a maximum; it only demonstrates that index's use.
Accordingly the proposed read does not span base→pool or scan arbitrary RAM.

## Producer evidence for exactly the proposed indices

These are recording-owner queue producers, rather than guesses from thunk order:

| Producer | Concrete event construction | Queue edge |
|---|---|---|
| `C03A20D0` | zeroes 168-byte event; subtype 1 at +C; input+C → event+F4; **23 → event+4 at C03A2100/04**; input byte+2C → event+164 | `C0388BA8` obtains recording owner; `C03A2118 → C03A9770 → C03A9798` |
| `C03A2130` | same subtype/token/control fields; **24 → event+4 at C03A2160/64** | owner getter; `C03A2178 → C03A9770 → C03A9798` |

The producers' function pointers are installed in the image at `C0BC44BC` and
`C0BC44CC` respectively. The token +F4 and control byte +164 coincide with the
inputs actually consumed by the studied start/stop methods. This motivates
testing the rows; it does not prove their route without descriptor contents.

The tool's two bounded ARM tests execute each producer from entry through the
queue-submission boundary with synthetic input token 42 and control byte 1.
Only memset and owner-getter effects are stubbed; the test observes ID, subtype,
token and control byte at submission. It does not invoke the queue or claim a
physical button delivered this producer.

## Readability versus storage extent

The stock fallback region record at **C0723AB4** is:

```text
virtual=C0000000, MiB_count=400, access=3, memory=1, physical_encoding=00400000
```

Executing the actual descriptor-writer slice **C000E814..C000E8E0** offline,
with both override words `C2F06B60/64` set to FFFFFFFF, produces descriptor
**42045C06** for the candidate address. This is a cached 16-MiB supersection:
`C2000000..C2FFFFFFF` → physical `42000000..42FFFFFF`, AP=011 (read/write),
XN/PXN clear. The proposed bytes map to physical `42F2F738..42F2F757` under
that fallback. This is mapping evidence, **not permission to switch aliases**.
Both rows and the previously observed row 2B are in the same 4-KiB page
`C2F2F000..C2F2FFFF` as well.

The existing saved passive observation of row 2B at `C2F2F7B8` demonstrates a
successful 16-byte read on one boot; it does not authenticate current mappings
or initialization. This task does not reread that hardware. The MMU initializer
can use runtime overrides; current TTBR/control state and page-table contents
are not captured here. A readable mapping cannot prove a table's allocation
extent, and ordinary-memory behavior under the fallback is not an all-boot
live guarantee. These limits are why the proposed extent comes from concrete
producer indices, not the size of a mapped region.

## Host decoder/auditor

```sh
python3 -B tools/fpl_recording_dispatch_table.py --self-test
python3 -B tools/fpl_recording_dispatch_table.py \
  --capture "$HOME/path/to/dispatch-23-24.bin" --address 0xC2F2F738
```

The capture is raw little-endian bytes saved **on the host** by main's separately
authorized passive read. Default official MAIN path is under
`$HOME/.local/share/fpsup/firmware/FPL_V302/`; override with
`--main`. With no capture, the tool prints the proposal and MAIN identity.

The decoder:

* Verifies the whole official MAIN fingerprint and exact dispatcher, producer
  and thunk code-slice hashes. Each captured target is compared against the
  **exact ARM entry address**, not a nearby pointer or a masked Thumb pointer.
* Accepts one 16-byte row at either listed address, or 32 bytes starting at
  `C2F2F738`. Rejects short, extra, misaligned and other-index data. File input
  is read with a 33-byte cap so an oversized file fails without an unbounded
  input read. It cannot request or connect to a camera.
* Derives event ID from supplied capture address plus row position. Reports
  word zero separately as ignored by this dispatcher. The operator must retain
  the address, boot/version provenance and acquisition ordering with the file;
  arbitrary bytes cannot authenticate where they were captured.
* Reports disabled, signed-negative direct, or positive virtual interpretation.
  It never dereferences a captured pointer. A virtual route remains unresolved
  without the adjusted live object's vptr.
* Recognizes `C03ABAB8 → state table +74`, `C03ABAF0 → +78`, and
  `C03ABBD0 → +98`. Nonzero this-adjustment is explicitly qualified; a matching
  thunk with adjusted object is not an unadjusted-state route proof. Unknown
  targets are reported, not silently assigned one of these names.
* Always remembers the subsequent state-table +B8 filter; observing a direct
  target does not establish handler acceptance, committed transition, or IO.

Self-test passes **6 decoder semantic checks, 10 rejected malformed/mutated
inputs, 2 bounded ARM producers, and the fallback MMU writer check**. All test
rows are synthetic, including the mismatched word-zero and negative-selector
fixtures. No synthetic row is presented as a capture. The existing format and
failure audits remain unchanged.

## What main can decide next

Authorize at most **32 bytes at C2F2F738** in the existing shell, or the two
16-byte reads separately; preserve exact host bytes and provenance. A direct
match in each row will close that indexed descriptor→thunk join for that boot.
If neither matches, retain the decoded evidence rather than expanding the
read. To locate `C03ABBD0`, first resolve a concrete recording-queue producer
ID (or obtain an event ID from already-authorized passive evidence); this audit
does **not** authorize or suggest a whole-table search without a proven end.

## Subsequent observed rows and producer-backed extension

Main captured exactly 32 bytes at `C2F2F738` on 2026-10-23. The saved host
`dispatch-23-24.bin` and provenance under
`$HOME/.local/share/fpsup/observations/` report:

```text
23  0  FFFFFFFF  C03ABAB8
24  0  FFFFFFFF  C03ABAF0
```

The official-version provenance and `PONG` sequence 95 accompany the capture.
This resolves the two indexed direct routes with zero this-adjustment for one
passive observation; no event dispatch was observed. Word zero remains ignored
by the dispatcher. The earlier candidate wording above describes the original
pre-read proposal.

The subsequent offline **FPL_MOV_RESULT_DELIVERY.md** proves recorder event
**30** from the installed MOV callback. The decoder now also permits **one
16-byte row at C2F2F808** (end exclusive C2F2F818), without widening to the gap
or an inferred whole-table extent. Row 30 remains unobserved. Updated decoder
self-tests cover 7 semantic checks, 12 rejected inputs, the original 2 ARM
producers and the fallback MMU check; the separate MOV audit executes the new
event-30 producer/callback chain.
