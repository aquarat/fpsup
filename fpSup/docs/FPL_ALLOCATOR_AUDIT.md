# fp L 3.02: allocator and executable-RAM audit

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

Independent offline audit, 2026-10-16. **The stock allocator and fallback MMU
configuration justify developing a short owned-RAM execution experiment. They
do not yet establish that the live camera can execute that allocation.** The
temporary bootstrap's ownership, serialization and restoration need their own
proof; this audit does not certify a borrowed shell handler.

No camera/card operations, commits or pushes were performed. The shared loader,
builders and port records were not edited by this audit.

## Source and method

Input: official fp L 3.02 MAIN, base `C0000000`, length `02F06A00`, SHA-256
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.
Private path:
`~/.local/share/fpsup/firmware/FPL_V302/MAIN.bin`.
Read the build contract, `FPL_PORT.md`, `FPL_BRINGUP_2026-10-16.md` and actual
`fp_usb_shell/asm/loader.S`; independently followed the official instructions.

Evidence levels used below:

- **Static:** directly observed firmware instructions/data and their semantics.
- **Offline execution:** real firmware instructions in Unicorn, with explicitly
  synthetic memory and named stubs. Not a hardware/MMU/cache validation.
- **Existing hardware evidence:** the earlier archived stock-command captures;
  no new hardware evidence was collected here.

Reproducible evidence tool: [`tools/fpl_allocator_audit.py`](../tools/fpl_allocator_audit.py).
Requires Python Unicorn; optional addressed disassembly requires Capstone.
It rejects every MAIN hash except the image above and has no camera interface.

```sh
python3 -B tools/fpl_allocator_audit.py \
  --main /private/path/FPL_V302/MAIN.bin > /private/path/allocator-audit.json
# Optional --disassembly /private/path/new-disassembly.txt (must not exist).
```

## 1. Descriptor ABI: proved static facts

All addresses below are **ARM**, not Thumb. Use normal callee-saved registers,
save LR around calls, and keep your call-boundary SP 8-byte aligned. No VFP
arguments, fifth user argument, or hidden file object is required.

| Entry | Arguments | Return / side effects |
|---|---|---|
| `C001D740` (`H_GET`) | `r0=descriptor`, `r1=class`, `r2=requested bytes`, `r3=alignment` | Returns **descriptor address**, even on allocation failure; initializes all four descriptor words |
| `C001D7F0` (`H_ADDR`) | `r0=descriptor` | Returns `[descriptor]`, the allocation address or **0** |
| `C001D7A0` (`H_FREE`) | `r0=descriptor`, `r1=destructor flags` | No useful status return; with `r1=2`, releases the allocation without deleting descriptor storage |

The descriptor is **16 bytes**, word-aligned, with this exact output layout:

```text
+00 allocation address (0 on ordinary allocation refusal)
+04 requested class
+08 duplicate allocation address
+0C requested size (not rounded actual capacity)
```

`H_GET` writes these at `C001D77C..C001D78C`; it does not consume the
descriptor's old contents. Reinitializing a still-live descriptor would lose
the old allocation. Keep it on a valid caller stack or in separately owned
memory until free completes. Never put the only descriptor or return stack in
the very allocation being freed.

`C001D75C` loads `[sp+18]` after a six-register push and four-byte local slot:
that is the **saved incoming LR**, not a fifth argument. It passes this callsite
to the inner allocator's accounting field. `C001D038` accepts
`(channel, bytes, alignment, optional_actual_size_out, callsite_on_stack)`;
the descriptor wrapper supplies a null actual-size pointer.

### Alignment, sizes and failures

`C001D064..C001D088` converts alignment 0 to 1. The core at
`C00104C8..C00104E4` replaces alignments that divide 64 with 64; the allocation
search rounds the payload address up to the resulting alignment using unsigned
division at `C0010624..C0010630`. Thus **the shared loader's `r3=0` gives
64-byte-aligned payloads**, sufficient for ARM code, cache-line separation and
word data. Explicit 256-byte alignment also works in the offline check.
Do not generalize this to arbitrary alignments: the implementation does not
simply take `max(requested_alignment,64)` for every possible integer.

Metadata uses 64-byte blocks. `C0010360` returns header address + `40` + header
padding; the search rounds the allocation's end up to 64 bytes. The caller
owns the **requested bytes at the returned pointer**, not metadata immediately
before it or apparent rounding slack afterward. No initialization/zero-fill of
the returned payload is performed by this path. Initialize every result word
and every instruction that will be used.

The normal out-of-space result is 0 from `C00104A8`/`C001D038`, recorded in
both descriptor address fields. `H_GET` itself still returns the nonzero
descriptor pointer. Test `H_ADDR`, not the constructor return. The descriptor's
size remains the request even on failure.

Other inputs are not a general error-return interface:

- Class 15 and an uninitialized channel table reach firmware assertion paths;
  the wrapper does not bounds-check arbitrary class indexes.
- Inner allocator sizes `FFFFFFFF` and `FFFFFFFE` are **special requests**
  (`C00104EC`, `C0010524`), not failure codes. Do not pass them.
- Size/alignment arithmetic is 32-bit and not an overflow-safe public API.
  Use a small, positive, fixed, checked request for this probe (e.g. a few KiB).
- No live free-capacity measurement has been made. The channel's nominal size
  is not a promise that any particular request will succeed during startup.

### Free: an important correction to a loader comment

`H_FREE` skips a null descriptor; for a valid descriptor with `[desc]==0` it
also skips the allocation release. Bit 0 of `r1` controls a separate
`C001349C(desc,16)` delete operation. Therefore **`H_FREE(desc,2)` after a
completed, failed `H_GET` is a no-op for the allocation**, contrary to the
loader comment that freeing a descriptor that never held anything is not a
no-op. The stock caller at `C0382558..C0382570` itself frees a descriptor after
observing a zero address. This does not make an *uninitialized* descriptor safe.

Free **does not clear any descriptor word** (`C001D7A0..C001D7E8`). `H_ADDR`
after free still returns a stale pointer. Do not use it as proof of ownership,
reuse it, or free it twice. Set your own state flag/descriptor to zero after
the successful release call returns if further cleanup paths can run.

## 2. Channel ownership and lifetime

`MEM_HEAP` at `C001CF78` maps `class` to `table[class]` at `C30739D8`.
**Table +38 is the pointer for class 14**, tested as a nonzero initialization
prerequisite; it is not a separate boolean flag. The separate initialization
byte is `C30739D4` (`C001CDF8`).

Initialization creates 15 **0x24-byte (36-byte) channel objects** (`C001CE30`, constructor
`C001D708`). Their observed addresses are spaced by 0x30 bytes in the earlier
capture; that observed spacing must not be confused with the constructor's
object size or treated as free space between channels.
The four-word descriptor must not be confused with these shared channel objects.

Relevant channel fields:

```text
+00 class
+04 memory-layout manager
+08..+1F allocation-list/accounting object
+20 fallback channel pointer, or 0
```

The loader uses class **0 (USER)**. The firmware's class-name strings include
USER/OSD/IMAGE/.../RAW in this order (`C0725809` onward), and its name accessor
`C001DE78` indexes the runtime name-pointer table at `C2F06E7C`. Class 10 is RAW;
it is not a substitute for USER.

### Stronger evidence than a populated pointer table

`C001ED78` sets memory area 0's base to `44400000` and area 1's base to
`80000000`. The layout constructor/selector at `C001EE58..C00206F4` builds
all thirteen mode layouts. In **every mode 0..12**, the first class entry is:

```text
class=0, policy bytes=02000000, preservation callback=C00206F8,
fallback class=15 (none), area=0
```

The real lookup/base/size functions (`C001EDF8`, `C001EA30`, `C001E950`)
resolve that entry to base **44400000**, channel-region size **02000100**
(32 MiB plus 256 bytes of allocator provision). This is a policy/region size,
not currently available bytes. The probe must obtain a block from `H_GET`,
never write directly to that nominal base.

Mode switching uses `C001CE88`: update the manager, then refresh every channel
through `C001D470`. `C001EAE8` invokes the entry's preservation callback with
`(class, previous_mode)`. `C00206F8` always returns 1. For an already initialized
channel, `C001D520..C001D560` checks the region base matches and returns without
resetting its list. This is positive static evidence that **USER allocations
survive ordinary changes among these mode layouts**. Other classes can be
reset or have fallback channels; do not infer their lifetime from USER.

The get/free paths use nested interrupt guards `C001CCE0`/`C001CD18`, backed
by `C000EC14`/`C000EC24` (save/disable/restore IRQ+FIQ mask bits). This protects
the allocator's individual operations. It is not a lock covering the whole
probe and does not prove cross-core exclusion or shell-handler serialization.

No task ownership or automatic task-exit reclamation is installed by this
descriptor constructor. Allocation-list metadata records the callsite. The
probe owns the allocation until explicit free, subject to firmware heap reset
at restart. No pointer may survive into a later boot. The earlier live HEAPS
capture establishes initialized channel pointers only; it did not capture
class-0 list state, mode, base, size, or available capacity.

## 3. Executability and aliases: what the MMU code proves

MAIN's reset path calls `C000E7B0` at `C0000650`. That routine:

1. Maintains caches/TLB, temporarily disables SCTLR M/C/I.
2. Installs a first-level table based at **44300000** (`C000EBF8` literal),
   with DACR **55555555** (all domains client).
3. Fills 4096 first-level descriptors, then applies the region table.
4. Enables M/C/I and performs DSB/ISB before returning.

It can use a runtime override: count at **C2F06B64**, region-table pointer at
**C2F06B60**. If either is `FFFFFFFF`, it uses count **4** at `C0723A38` and
the following fallback table at **C0723A78** (20-byte records):

| Virtual start | MiB count | Access field | Memory field | Physical encoding |
|---|---:|---:|---:|---:|
| `00000000` | `100` | 2 | 1 | `00000000` |
| `2E000000` | 2 | 0 | 0 | `002E0000` |
| `40000000` | `800` | 3 | 0 | `00400000` |
| `C0000000` | `400` | 3 | 1 | `00400000` |

The actual table-writing instructions at `C000E814..C000E8DC`, executed
offline without the surrounding CP15 operations, produce:

| Virtual address | First-level descriptor | Meaning relevant to probe |
|---|---|---|
| `44400000` | `44044C02` | USER area, AP=011, XN=0, PXN=0 |
| `463FFFFF` | `46044C02` | Same permissions toward end of USER area |
| `46400000` | `46044C02` | Same permissions for allocator's extra provision |
| `C4400000` | `44045C06` | Cached alias of physical `44000000` supersection |

These are ARM short-descriptor **16 MiB supersections** (bit 18 set), repeated
across sixteen first-level slots. The class-0 allocation address is ordinarily
in the **40000000 alias**, Normal non-cacheable under the ordinary TEX/C/B
interpretation; the C0000000 alias uses cacheable Normal attributes. The
allocator's ordinary `H_GET` path does not convert the returned address to a
cached alias. `C0022FA8` converts C0000000-and-above addresses by subtracting
80000000, and the alternate allocation path `C001D1E8` has explicit alias/cache
handling; these corroborate the alias distinction.

**Neither XN nor PXN is set by these fallback records.** There is no per-block
execute permission call in `H_GET` and no reason to patch MMU entries merely
to attempt execution. Use the address returned by the allocator; do not invent
an alias or physical address.

### Hardware unknowns, explicitly

- The live first-level table, override pointer/count, TTBR0, TTBCR, DACR and
  SCTLR have not been captured. The stock MMU routine changes M/C/I, but does
  not establish every inherited control bit (including WXN/UWXN and memory
  attribute-remap controls). This audit does not prove that the fallback table
  is the one active at AutoRun time or that no later code alters translation.
- The synthetic Unicorn mappings grant permissions for simulation; successful
  allocator emulation says **nothing** about real instruction fetch permission.
- Privileged execution context, cache behavior, multicore instruction-cache
  coherence and exceptions on the live camera remain untested for this probe.

The static evidence is considerably stronger than “a heap pointer exists”:
stock code intentionally maps USER's area with executable descriptors. It is
sufficient to motivate an authorized minimal trial, but successful return from
the allocated code must be the trial's evidence, not an assumption in its result.

## 4. Cache ABI and safe return/free ordering

`C000E91C()` takes **no arguments**, returns no status, and preserves the
callee-saved registers it uses. It saves interrupt-mask state, disables IRQ/FIQ,
selects cache levels 0 and 1, reads CCSIDR and issues **DCCISW** (`c7,c14,2`)
for every set/way, restores selector 0, executes DSB/ISB and restores masks.
It is **clean-and-invalidate**, not just clean. Caller-saved r0-r3/ip and flags
must be treated as clobbered. It uses CP15 and requires privileged execution.

`C000EABC()` takes no arguments, uses r0=0 with **ICIALLU** (`c7,c5,0`), then
DSB/ISB and return. It clobbers r0. Neither routine is a byte-range operation.

The shared-loader publication order remains appropriate:

```text
finish writing code/data -> C000E91C() -> C000EABC() -> BLX allocation
```

Required lifetime ordering for a minimal probe:

1. Obtain a successful descriptor, initialize code/result fields and publish.
2. Call allocated ARM entry at an aligned address, keeping LR/caller stack and
   the later cleanup code outside that allocation.
3. Allocated entry records a marker that only it can produce, preserves its
   callee-saved registers, and returns; it installs no task or callback.
4. After PC is back in still-owned bootstrap code, copy/log any result that
   otherwise resides in the allocation. Close/destroy any file object residing
   there before free.
5. Call `H_FREE(desc,2)` exactly once. From then on, do not read the block,
   execute it, return into it, or use it as stack. Report “free call returned”
   rather than interpreting a nonexistent free-success code.

The bootstrap's own restoration must also leave a valid return path: never
restore bytes underneath instructions still to be executed. Restoration's D/I
publication and independent readback are separate from freeing the owned heap.
There is no allocator-provided unwind, exception recovery or code-reference
tracking that makes self-free safe.

## 5. Optional result-file ABI (static only)

The file wrapper is **12 bytes**, not about 3 KiB; the loader's 4 KiB reservation
is conservative. Constructor writes fields at +0, +4, +8; destructor's sized
delete passes `0C` at `C0366120`. Backend objects are allocated separately.

| Entry | ABI / result |
|---|---|
| `C03660A8` constructor | `(wrapper, volume)` -> wrapper; volume 1 is SD as used by stock callers |
| `C03661C8` open | `(wrapper, path, flags)` -> backend boolean; null path returns 0 |
| `C0366300` write | `(wrapper, buffer, byte_count)` -> **boolean**, not bytes written |
| `C0366238` close | `(wrapper)`; destroys backend with flags 3, sets wrapper +0 to zero; no useful status |
| `C03660E8` destructor | `(wrapper,2)`; invokes close, destroys its synchronization member, leaves caller-owned wrapper storage |

The concrete SD backend vtable at `C0BBCCEC` selects open `C0368390`, write
`C03687C8`. The writer checks readiness/open state, invokes the lower file
service at `C06394C8` (Thumb), tests its status and returns exactly 0 or 1
(`C0368884..C03688C8`). **Do not compare `F_WRITE`'s return against byte_count.**
The wrapper forwards this boolean unchanged and locks/unlocks around the call.

Stock `C03DC06C..C03DC0A8` demonstrates a stack-resident 12-byte wrapper,
volume 1, open flags **7**, and write tested against zero. Open mode conversion
at `C0368498..C03684B0` maps flags 7 to lower mode 2. This is an evidenced
write/create-style caller, not proof of all overwrite/append/error semantics.
Check open before write; retain the stock media-manager setup used by the
loader. A nonzero constructor return is only the wrapper address: check its
backend field before invoking an operation that asserts on a missing backend.

This audit did not execute filesystem/media services or verify durability,
partial-write behavior below the boolean interface, directory creation or
filename collision policy. Keep the versioned result small; verify its exact
length/content after a later authorized hardware trial. Stock `mem save` after
return remains a separately evidenced output mechanism if the bootstrap design
can keep the result in owned storage until that command has consumed it.

## 6. Offline checks run and conclusion

`tools/fpl_allocator_audit.py` passed against the exact MAIN above using
Unicorn 2.1.4 (Cortex-A15 instruction model). It executes:

- The real layout initializer, selector and accessors for all **13 modes**;
  confirms class-0 base, region size, no fallback and preservation callback.
- Real descriptor get/address/free plus allocation-list code with a synthetic
  64 KiB channel. Requests **1, 65, 4096 bytes** with alignment 0 all return
  `44400080`; 4096 bytes with alignment 256 returns `44400100`; 128 KiB
  refuses with address zero. Each case checks all descriptor words, writes the
  entire requested payload, frees, and checks list/current-accounting recovery
  (the deliberate high-water counter is retained). A failed initialized
  descriptor also frees without touching the synthetic channel.
- The real fallback MMU table-writing instructions, with CP15 install/cache
  operations outside the executed interval, obtaining the descriptors above.

Only four functions are stubbed: local-static guard acquire/release
`C0013090`/`C00131E4`, allocation/free telemetry `C001E328`/`C001E3C8`.
Assertions abort the harness. The allocator's IRQ guards, lookup, alignment,
list insertion/removal and descriptor wrappers execute real instructions.

Sensitivity check: in an in-memory copy only, changed `C001D7F4` from its
address load to `mov r1,#0`; the allocation oracle rejected it with an assertion.
No official image or shared code was modified for this mutation.

**Assessment:** use a small class-0 allocation, explicit zero initialization,
the established D/I sequence and an outside-allocation cleanup path. This is a
well-supported experimental design. It becomes a verified fp L owned-RAM
execution path only after separately proving the initial trampoline and an
authorized live result showing the allocated entry actually ran and returned,
cleanup completed, and borrowed stock bytes were restored. Resident workers,
power-off lifetime, recording coexistence and the full shared loader/stage2
port remain beyond what this audit establishes.
