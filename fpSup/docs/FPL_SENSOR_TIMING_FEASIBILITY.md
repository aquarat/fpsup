# fp L 3.02 sensor timing: bounded offline feasibility trace

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. **Slow active readout remains unproved.** There is now a concrete
timing-table-to-shutter-write path, but no identified writable line-period or
frame-blanking control. This is static analysis plus bounded synthetic emulation,
not a camera experiment. No camera access or payload construction was performed.

## Input and reproduction

Official decompressed `FPL_V302/MAIN.bin`, CPU base `C0000000`, 49,310,208 bytes,
SHA-256 `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
The file contains `src/hal/ImageSensor/src/config/IMX455/ImageSensor_factoryIMX455.cpp`
at `C0B98BC0`; this identifies the firmware driver, not independently measured
silicon identity. `C0B98C50` is `setShutter_Async`.

```sh
python3 -B tools/fpl_sensor_timing_audit.py \
  --main "$HOME/.local/share/fpsup/firmware/FPL_V302/MAIN.bin"
```

Requires Unicorn. The tool validates the complete fingerprint before execution.
It runs the native initializer and native timing calculation/index lookup on
synthetic RAM, with a 10,000-instruction bound per call. The emulated mapped RAM
beyond MAIN is synthetic, not a recovered runtime image.

## 1. Descriptor +132 is not evidence of a clock measurement

`C0326E60` materializes descriptor `D = C2F2E71C`. At `C0326E70` it interworks
to **Thumb** `C0125110`: exactly `mov.w r0,#0x100; bx lr` (then padding).
`C0326E74` multiplies that constant by four; `C0326E7C` stores the halfword
**1024** at `D+132`. `C0326EA4..C0326EB8` copies 20 bytes from `D+130` to
`D+2C`, so the same halfword appears at **D+2E**.

There is no clock read, hardware access or frequency conversion in that producer.
Its physical meaning is unresolved. Treating it as a timing knob was premature.
The audit executes the full initializer and verifies both halfwords. A fresh
emulator with only the constant changed from 256 to 258 produces 1032 in both
locations, verifying this dataflow independently of the fingerprint check.

The same initializer copies 100 bytes from `C0B98A2C` to `D+50`.
Consequently `D+74` receives the word at **C0B98A50 = 0x11940 = 72000**.
This is an fp L byte-level finding, not an imported fp/IMX410 assumption.
It does **not alone prove 72 MHz**, nor that the value stays unchanged at runtime.

## 2. An exact timing arithmetic quantity; units still unresolved

The sensor object stores its descriptor pointer at +0. `C0324CB8` searches the
descriptor's table at +0, count at +4, stride 32, matching each row's first word.
No match returns index zero. `C03250E0` returns that row, using object+4 for
sentinel mode `0x77`. `C03253A8` caches the timing index in **object+0C**.

`C0325278..C03253A0` independently indexes the same table, reads its halfwords
`a = row+4`, `b = row+6`, `c = row+8`, and divisor `d = descriptor+74`:

```
p = a * (c - 1) + b             # ARM 32-bit arithmetic
result = max(1, floor(p * 1000 / d))
```

The implementation uses a quotient/remainder path when `p >= 0x418937` to avoid
overflow in the multiply-by-1000 step. The formula above presumes the initial
arithmetic and final result fit and d is nonzero; there is no claim for corrupt
rows or arbitrary divisors. Native tests cover both scaling branches, the minimum
result clamp, sentinel selection and unknown-ID fallback (nine cases). These
are synthetic values, not recovered fp L mode rows.

The quantity is compatible with a period conversion, but **microseconds, clock
cycles, line counts, HMAX and VMAX are not established names/units here**.
`C032CA50` consumes it together with timing row +8/+E/+10 and a separate table's
byte +D. Neither this accessor nor that calculation writes hardware. A direct
ARM BL scan found accessor callers at `C032CA74`, `C032CB14`, `C032CBC4`;
this is not an exhaustive indirect-call or Thumb-call analysis.

## 3. Concrete shutter-related write path

Constructor `C0329DC0` installs table `C0B98CFC` at object+D0. The function
`C0328A08` supplies the literal `setShutter_Async` to its logger at `C0328A34`.
It splits an input using `C03254B0` and a value returned by `C0122548`, then:

1. Calls virtual slot **+68 = C0328B78** on the first component. This conversion
   reads the cached timing index object+0C and row halfwords +4/+6 at
   `C0328B94..C0328BBC`, plus descriptor+74. It also consumes other table fields
   and `C0122278`; its complete physical contract is unresolved.
2. Passes the converted result and second component to **C01227A8** at
   `C0328A9C`. This Thumb routine can wait on state, then calls `C01227E0`
   (state-dependent RAM cache stores) and **C0122808**.
3. `C0122808`, depending on `C0124698`, either caches the argument at
   `C31D6DD0` or read-modify-writes **MMIO 30100048** at `C012283A`/`C012287A`.
   The shift pair places argument bits 0..10 into bits 16..26. This identifies
   packing and address, **not the hardware register's semantic name**.
4. `C0328AAC -> C0328B58 -> C0329FD8` forwards both components to
   `C0329FF8` and `C032A040`. The first bounds its input to 1..0x8FFE, then
   sends low 8 bits under address argument **0x16**, and bits 8..13 under
   **0x17**, via **C0326D88**. Do not silently reinterpret the unusual upper
   bound/mask combination as a documented sensor range.
5. `C032A040` explicitly replaces its incoming value with zero and sends zero
   under address arguments **0x12/0x13**. Thus those writes do not simply
   preserve the second component.
6. `C0326D88 -> C0326DC8` packs address high byte, address low byte, data byte
   into a stack packet, then calls **Thumb C0122DF0**. The transport, bank/device
   selection and final hardware destination beyond that call remain unaudited.

The return-side slot **+6C = C0328CE8** also reads timing +4/+6 and descriptor+74;
`C0328A08` uses its result to update object+3C. This supports an exposure-related
conversion/write/readback-accounting chain, corroborated by `setShutter_Async`.
It does not identify 0x16/0x17 as line length, or 0x12/0x13 as frame blanking.
These are packet address arguments, not verified standalone sensor register names.
Only initializer/arithmetic paths were emulated; transport/MMIO paths were
disassembled, not executed or modeled by this audit.

## Feasibility and smallest next evidence

The concrete unresolved edge is **timing-table metadata versus programmable
active scan timing**. Exposure conversion consuming a row does not demonstrate
that editing that row changes the sensor's row cadence. It could only change
the driver's calculation while hardware timing remains fixed.

Next offline work should resolve `C0122DF0`'s transport/device/bank contract and
the producer of the timing table pointer/count at `D+0/+4`, then trace the native
mode-setting path to the packets that configure cadence. Recover initialization
provenance from file-backed code/data; do not read bytes beyond MAIN as if they
were supplied table contents. Independently establish units of descriptor+74 and
the `C0122548/C0122278` inputs before labeling the arithmetic microseconds.
One verified mode-initialization packet linked to a documented or corroborated
line-period field would be more useful than another generic register search.

**Line period, frame blanking and exposure remain distinct unknowns.** Extending
blanking can lower FPS without lengthening the active scan. Slowing line cadence
can change both exposure and scan; receiver synchronization, arithmetic bounds
and frame-completion deadlines would also need evidence before a seconds-long
scan claim. fp/IMX410 mode IDs, 72 MHz calibration and Canon parameters are not
used as proof for fp L.

Magic Lantern's real precedent is
[fps-engio.c](https://github.com/reticulatedpines/magiclantern_simplified/blob/dev/src/fps-engio.c),
comments around lines 1366–1393 and menu text around 1589: **“High Jello:
slit-scan effect (use 2-5 fps and fast shutter)”**. Timer A increases jello and
affects exposure; Timer B changes frame cadence with implementation-dependent
exposure side effects. This supports the artistic premise, not an arbitrary
seconds-long scan or a portable SIGMA register recipe. Narrow hardware ROI is
also unproved. Computational strip composites from ordinary frames remain a
separate feasible approach.
