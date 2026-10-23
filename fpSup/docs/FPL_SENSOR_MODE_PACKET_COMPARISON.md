# fp L 3.02: bounded per-mode packets versus timing MMIO

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. **Timing rows are not merely descriptive metadata:** a separate
native routine consumes them and programs SoC MMIO. However, **independent
active-row cadence control and seconds-long slit scans remain unproved**.
The strongest new separation is that IDs 97 and 142 emit identical bulk sensor
packets under the tested initial state, while producing different timing-MMIO
values. This narrows the next semantic question considerably.

Only this note and `tools/fpl_sensor_packet_audit.py` belong to this follow-up.
Prior audits remain unchanged; no camera, settings, card, payload or commit work.

## Reproduction and exact scope

```sh
ROOT="$HOME/.local/share/fpsup/firmware"
python3 -B tools/fpl_sensor_packet_audit.py \
  --main "$ROOT/FPL_V302/MAIN.bin" --data "$ROOT/FPL_V302/DATA.bin"
```

The new tool imports the previous audit's fingerprint/emulation helpers without
modifying them. Inputs are official fp L 3.02 MAIN (49,310,208 bytes,
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`) and DATA
(238,080 bytes, `758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8`).
DATA container provenance was established in `FPL_SENSOR_MODE_TRANSPORT.md`.

Two independently executed paths:

1. **Bulk programmer C032A108 through C032C4C4**, stopping at **C032C4C8**
   before calls to Thumb C01218D0/C01218F8 and before the final return. This
   executes **283 packet calls**, including their actual transport instructions.
   It is a complete packet-emission prefix, **not full mode-transition execution**.
2. **C0324858 through its return at C032492C**, including Thumb C0122E60,
   C0125258 and C01229C8. A synthetic sensor object points to the actual DATA
   descriptor and selected cached index. Object+45 is zero, disabling the
   override branch. MMIO starts zero, so the running-engine synchronization
   polling branch is not taken. No firmware service stub is needed on this path.

All calls have a 200,000-instruction limit and must reach their expected stop.
Controller completion bit is modeled as immediately ready; no physical sensor,
wire timing, PLL, receiver or scheduler is modeled. Native DATA caches retain
their initialized values; BSS cache C343C5C8 starts synthetically zero. In
particular DATA C2F2E878 starts at **0x20**: the address-2 packet ORs this with
row+0C (0x10), yielding **0x30**, rather than blindly copying row bytes. Tests
explicitly account for that difference. These initial states are not live reads.

## Compared existing entries

These are existing firmware mode IDs, not claims that each is exposed in the
recording menu. Timing rows are at C0B90FF8 (stride 32), geometry at C0B91A98
(stride 100), and programmer rows at C0B98DE8 (stride 1120). Each is matched by
its own ID field rather than assuming row-number equivalence.

| ID | Timing +4/+6/+8 | Geometry +4/+8/+44 | Reason for comparison |
|---:|---|---|---|
| 0 | 1122 / 1122 / 6440 | 9568 / 6380 / 1 | first full-geometry entry |
| 129 | 1122 / 1122 / 6440 | 6288 / 4192 / 1 | same timing, different geometry |
| 97 | 624 / 624 / 6440 | 9568 / 6380 / 1 | same geometry as 0, changed timing |
| 130 | 624 / 624 / 6440 | 6288 / 4192 / 1 | counterpart to 129 |
| 142 | 624 / 912 / 11538 | 9568 / 6380 / 1 | same geometry/+4 as 97, changed +6/+8 |

Geometry numbers are raw fields, not validated recorded raster sizes. No bit-depth
label is assigned merely from mode ID or the packet byte at address 1.

## Bulk packets: measured source-to-address correspondence

All five runs emit **279 table-sourced packets**, then four non-row-sourced
packets. The first 279 read row offsets **+4 through +45C**, stepping by four.
The audit records each actual table read and packet call, then independently
checks the packed words written to controller 21C00114/118. It does not infer
destinations from source-field numbering.

Under the initial-state assumptions above:

* All 283 packets for **0 and 129 are identical**.
* All 283 packets for **97, 130 and 142 are identical**.
* **0 versus 97 differs at 70 packet data bytes**. Their address sequences match.

A deliberately small selection of exact correspondences (hex):

| Programmer row offset | Emitted address argument | ID 0 byte | ID 97 byte |
|---|---|---|---|
| +008 | 0001 | 40 | 80 |
| +07C | 00A9 | 01 | 02 |
| +0A8 | 0112 | 03 | 02 |
| +438 | 0A80 | 72 | 62 |
| +440 | 0A82 | 0E | E6 |
| +444 | 0A83 | 04 | 02 |

These are **packet address arguments**, not named sensor registers or proven
banks. The byte differences could include bit-depth, analog, serializer or
timing configuration; this comparison alone cannot distinguish them.

The tail is also bounded and explicit: row+45C supplies address 0A96; then
C032C464 writes address 0113 with zero, the DATA word at C2F2E87C is toggled
from 0002FFFA to 0002FFFB, and C032C4A4/C032C4B4/C032C4C4 emit its three bytes
to **0116/0117/0118**. No physical meaning is assigned to that toggled quantity.

**Semantic control:** changing only ID 97's row+438 word at C0B99AE0 to 0x55
in a fresh emulator changes exactly the address-0A80 packet from 0x62 to 0x55.
All other packets are unchanged. No source file or firmware image is mutated.

## Timing rows have their own hardware-consuming path

`C0324858` reads halfwords `a=+4`, `b=+6`, `c=+8` using object+0C's cached
timing index. At C03248F0 it passes `(a,c,0)` to **Thumb C0122E60**; at
C0324920 it passes `b` to **Thumb C01229C8**.

Actual native writes, for the tested values:

1. C0122EA8 initially writes `(a-1) | ((a-1)<<16)` to **30100004**.
2. C0122EAE writes `(c-1)<<16` to **30100020**.
3. C0125258, called with zero, updates **30100048**; from synthetic zero it
   becomes **60000000**. This is a read-modify-write, not a universal final value.
4. C01229DE clears the low half of 30100004; C01229F2 ORs in `b-1`, leaving
   final **`((a-1)<<16) | (b-1)`** for these bounded input values.

| IDs | Final 30100004 | Final 30100020 |
|---|---|---|
| 0, 129 | 04610461 | 19270000 |
| 97, 130 | 026F026F | 19270000 |
| 142 | 026F038F | 2D110000 |

This is not just an unused conversion helper: direct ARM calls to C0324858
exist at C0318A64, C03195D4, C031AE4C, C031CB58 and C031CBAC. The caller at
C031CB58 tests the return value. Their complete mode-transition conditions
are outside this audit; no claim that these paths have executed on a camera.

**Semantic control:** changing only ID 97 timing+4 from 624 to 625 in emulator
memory increases final 30100004 by 00010000, leaving the other two tested MMIO
words unchanged. Running the entire 283-packet bulk prefix with that same
metadata mutation leaves its packet sequence unchanged. Therefore these two
configuration paths are distinguishable by actual dataflow, not correlation.

The arithmetic `(a*(c-1)+b)` in C0325278 and the two halfword fields above are
consistent with a repeated interval and a final/different interval plus count.
This is a **candidate timing-generator interpretation**, not proof of HMAX,
VMAX, clock cycles, active-row period or the sensor's externally driven sync
contract. Raising `c` could add idle/frame spacing instead of slowing active
rows. The connection between these SoC outputs and physical sensor sampling
remains the decisive missing fact. Shared use of 30100048 by the previously
traced shutter code also does not make all its fields exposure controls.

## Public corroboration and stopping point

The accessible [Atik IMX455 technical guide](https://www.atik-cameras.com/news/sony-imx455-sensor-complete-technical-guide/)
describes rolling-shutter operation, multiple output depths and windowed readout
in Atik's implementation. It explicitly distinguishes Sony's public product
flyers from full electrical documentation available through a distribution
relationship. **Manufacturer secondary evidence for broad capabilities only**;
it supplies no mapping for the fp L packet addresses or SoC MMIO above.

Search also located [Sony's IMX455 AQK/BQK/ALK flyer](https://www.sony-semicon.com/files/62/pdf/p-13_IMX455AQK_BQK_ALK_Flyer.pdf).
Its full PDF was not inspected in this bounded pass and is not cited as register
evidence. No publicly corroborated IMX455 register definition was established.
Search results mixing other Sony sensors' XHS/XVS documentation were not used
as evidence. Nothing here imports fp/IMX410 or Canon timer parameters.

**Verdict:** configurable native timing fields and separate mode programming
are proven offline; meaningful slow active readout remains unknown. The smallest
missing semantic fact is whether **30100004's interval fields drive the sensor's
successive active-row timing**, with what clock and admissible range, or instead
configure receiver/framing timing that must track a sensor-owned cadence.
Resolve that through authoritative SoC/sensor sync documentation or a directly
corroborated native timing-block interface before exploring arbitrary settings.
This audit stops here rather than treating a generic packet diff as a slit-scan
implementation. Exposure coupling and frame-completion limits would follow that
semantic identification, not precede it as assumed constants.

Checks: five 283-packet prefixes, five timing-MMIO cases, two semantic mutation
controls, four MAIN/DATA fingerprint negatives. Running-engine wait behavior,
override fields and the final two programmer calls are not tested here.

**Recorder ownership note:** DATA's discovery may also permit static provenance
checks of previously live-read recorder rows. Those rows and recording-owned
files were not inspected or edited by this follow-up; their audit belongs to
the main port task.
