# fp L 3.02: mode-table provenance and packet transport (offline)

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. **Two previously unresolved edges are now concrete:** the timing
descriptor is initialized from the official update's separate DATA section,
and the packet writer reaches controller MMIO with mode-dependent data from a
different programming table. **Supported slow line-period control is still
unknown.** No register meaning, clock unit, or physical bus destination is
inferred from a familiar-looking address.

This bounded follow-up leaves `FPL_SENSOR_TIMING_FEASIBILITY.md` and its audit
unchanged. No camera access, settings changes, payloads or commits were made.

## Inputs and verification

| Input | Length | SHA-256 |
|---|---:|---|
| MAIN.bin | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |
| DATA.bin | 238,080 | `758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8` |
| FPL_V302.bin update container | 25,714,688 | `598ae32684844b50afff3797444041b794fb352b810db30f227d73474367cea4` |

```sh
ROOT="$HOME/.local/share/fpsup/firmware"
python3 -B tools/fpl_sensor_mode_audit.py \
  --main "$ROOT/FPL_V302/MAIN.bin" \
  --data "$ROOT/FPL_V302/DATA.bin" \
  --container "$ROOT/FPL_V302.bin"
```

Requires Unicorn. Tests fingerprint all inputs and re-extract DATA into host
memory. Native instruction execution is bounded to 200,000 instructions per
call. Only simulated memory/MMIO is used. Completion-status reads are explicitly
modeled, not assumed to represent real hardware. Native constructor, selector,
packet packing and first-two-packet mode prefixes run without service stubs.

## 1. Descriptor initialization: separate DATA, not missing MAIN bytes

The earlier MAIN-only limitation is resolved without a live memory scan:

* Update header `@DFI` at file offset `0x100` gives DATA output size at `0x138`,
  output address at `0x140`, packed checksum at `0x144`, packed length at `0x14C`.
* DATA's declared destination is **C2F06A00**, length **0x3A200**, ending at
  **C2F40C00** exclusive. Its compressed source is container file offset
  **0x1746500**, length **0x1D800** (computed as `0x300 + MAIN_packed_length`).
* LZSS decoding consumes **120527** packed bytes. The declared-length prefix
  exactly matches the fingerprinted DATA file. The last token extends beyond
  the declared output; the audit retains the declared prefix, as the existing
  extractor does. This does not newly prove IPL's treatment of that trailing
  token or padding.
* `D = C2F2E71C` is DATA offset **0x27D1C**. Its initialized words are:

| Descriptor field | Initial value | Meaning established by consumers |
|---|---|---|
| D+0 | **C0B90FF8** | timing table pointer |
| D+4 | **85** | timing row count |
| D+8 | **C0B91A98** | geometry table pointer |
| D+C | **85** | geometry row count |

Thus the **descriptor is in DATA, while all 85 timing rows are in MAIN**,
`C0B90FF8..C0B91A98` exclusive, stride 32. No additional decompression or
constructed runtime table is needed to recover these initial rows.
`C0326E60` later fills other descriptor fields, but does not establish +0/+4;
their source is these initialized DATA bytes. Subsequent runtime changes are
outside this audit.

Example initial timing halfwords (labels deliberately remain offsets):

| Row | Mode ID | +4 | +6 | +8 |
|---:|---:|---:|---:|---:|
| 0 | 0 | 1122 | 1122 | 6440 |
| 1 | 129 | 1122 | 1122 | 6440 |
| 2 | 97 | 624 | 624 | 6440 |

Container header interpretation and LZSS implementation were cross-checked with
the existing offline `inspect_firmware.py` beside the official inputs. The new
audit independently decodes DATA and checks its full hash. This establishes
exact packaged initialization provenance, **not a new disassembly audit of the
bootloader or a readback of live descriptor contents**.

## 2. Packet transport: exact controller destination, limited bus identity

The native chain is:

```
C0326D88 -> C0326DC8 (address-high, address-low, data byte)
         -> Thumb C0122DF0 -> Thumb C0125118
```

`C0122DF0` forwards the packet pointer and returns zero unconditionally.
`C0125118` reads exactly three packet bytes. It performs enable/configuration
read-modify-writes at **30000800** (bit 4), **300021B8** (bit 0), and
**300021B0** (bit 0), then programs the controller block **21C00100**:

| Offset | Observed writes |
|---|---|
| +00 | 0x11, then 0x13 |
| +10 | 0, then 1 |
| +2C | 0 |
| +04 | 0x100 |
| +08 | 0x30 |
| +0C | 0x818 |
| +20 | 0 (then polled bit 0) |
| +14 | **0x81 \| (address_high << 8) \| (address_low << 16)** |
| +18 | **data byte** |

Writes to +14/+18 are at **C01251CA/C01251CC**. These establish controller
word packing, not the wire byte order. `0x81` is a constant prefix in the
controller word. The function supplies no separate caller-selected device or
bank argument. **Whether that prefix selects a device, command or protocol
operation remains unresolved**, as do physical chip-select wiring and any
sensor bank state left by previous packets. The IMX455-named driver's use of
this writer is provenance evidence, not a peripheral datasheet.

Polling tests establish a notable limit: with bit 0 held low, the native routine
performs **10000** status reads and still returns zero. With bit 0 immediately
high, it reads once and returns the same zero. Thus neither wrapper's return
value distinguishes completion from this timeout. It is an iteration bound,
not an established timeout duration in seconds.

Tests use asymmetric packet bytes `12 34 AB` and assert +14=`00341281`,
+18=`AB`; all enable/configuration writes run against synthetic MMIO.

## 3. One concrete mode-programming packet source

There is a distinct table, not the 32-byte timing metadata table:

* Sensor constructor `C0329DC0` stores the helper from `C0329FA0` at object+D8.
* Its constructor **C0329F68** calls **C032C790**, storing **C0B98DE0** at
  helper+0. The descriptor at C0B98DE0 holds pointer **C0B98DE8**, count **85**.
* **C032C5F0** searches this table by its first word, using stride
  **1120 = 0x460**. Not-found returns **FFFFFFFF**, unlike timing lookup's
  row-zero fallback. The inspected programming prefix does not check this
  sentinel before computing the row address; unknown IDs are not valid input.
* **C0327890** forwards its mode argument and sensor object's helper to
  **C032A108** at C03278A4. `C032A108` calls the selector at C032A128.
* Its first packet uses row+4 OR cached state, address argument zero. Its
  **second packet** reads **row+8** at C032A180, passes address argument
  **1** at C032A184, and calls C0326D88 at **C032A188**.

Two concrete sources for that second packet:

| Requested ID | Selected row | Row address | Source word at row+8 | Emitted data byte |
|---:|---:|---|---|---|
| 0 | 0 | C0B98DE8 | C0B98DF0 = 0x40 | 0x40 |
| 97 | 2 | C0B996A8 | C0B996B0 = 0x80 | 0x80 |

Native execution from C032A108 through the return of that packet call (stopping
at **C032A18C**) yields controller +14=`00010081` and +18=`40`/`80`.
The preceding address-zero packet yields data 4 with a deliberately zeroed
synthetic cache. That cache value is not claimed as a boot or live default.

As a semantic negative/control, changing only the mode-97 source word at
C0B996B0 to 0x55 **in a fresh emulator** changes only the expected second
packet's data to 0x55. The official files remain unchanged. Selector tests also
verify unknown-ID FFFFFFFF; the programmer is deliberately not executed with
that invalid index. All three input fingerprints reject truncation and a
one-byte mutation (six negatives).

This proves **mode-dependent hardware-controller programming**, not that
address 1 changes scan speed, that IDs 0/97 are selectable recording formats,
or that an arbitrary table edit produces a valid sensor mode. The later bulk
programming body, physical acceptance and frame pipeline are outside these
bounded prefix tests.

## Feasibility and next evidence

The timing metadata and programming tables both contain mode IDs 0 and 97,
but shared IDs and changed bytes do not assign physical units or prove causal
line-period control. Exposure, vertical blanking, active row cadence and output
serialization may be configured by different fields.

The next useful offline step is a **bounded per-mode table comparison tied to
the native address-emission sequence**, then corroborating a specific differing
field with IMX455 documentation or driver dataflow. The controller's constant
prefix/device-select and bank semantics also need independent hardware/driver
evidence before naming a sensor register. No live scan is needed to recover
the initial tables now that DATA provenance is known.

Until then, seconds-long true rolling-shutter scans, arbitrary narrow hardware
ROI and independent exposure/readout control remain unproved. No Canon timer
parameters or fp/IMX410 register mappings are transferred to fp L here.
