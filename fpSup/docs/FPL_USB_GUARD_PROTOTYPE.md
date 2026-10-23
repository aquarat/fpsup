# fp L USB guards: scratch-only prototype

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-20. This experiment fixes three bounded regression targets in a
scratch-derived copy of the real worker. **It is not a synchronized lifecycle
solution or an installable candidate.** No production assembly, profiles,
handoff allowlist, known bodies, camera or card were changed. No commit made.

## Reproduce and evidence

From `fp_usb_shell/`:

```sh
python3 -B -m unittest -v test_fpl_worker_guards test_fpl_worker_lifecycle
```

Requires Unicorn and an ARM-capable `clang` on PATH. This run used the existing
wrapper at
`/path/to/arm-toolchain/bin/clang`
(Zig cc, arm-freestanding-eabi, Cortex-A9). Scratch sources were created below
the session TMPDIR and removed automatically. There is no retained binary to
install; `variant()` reproducibly constructs the source in memory and `build()`
assembles it in a temporary directory. The only durable additions are this note
and `fp_usb_shell/test_fpl_worker_guards.py`.

Actual result: **20 tests ran; 17 passed, 3 expected failures**. All 11 new
prototype tests passed, without skips. The original lifecycle suite still has
its three expected failures against the unchanged production source. Its
non-expected-failure fixture controls also passed.

The new suite executes relocated ARM instructions in Unicorn, extending the
existing `Dispatch` / `Lifecycle` mocks. Firmware services, completion and DMA
effects are synthetic. It does not run official teardown instructions, model
DWC3, caches, task scheduling, IRQs or establish a failure cause on hardware.

Verified new behavior:

* Modes 0/4/8/12/13/18 with otherwise control-mode-shaped readiness do not arm,
  dispatch or reply. Missing configured/backend/run readiness holds; configured
  2 is also rejected (the prototype requires **exactly 1**).
* Direct entry to each arm helper in mode 4 makes no firmware call and changes
  neither descriptor nor OUT_BUSY, even with deferred-cleanup flag set.
* Wait returning -4 with HWO cleared returns exactly -4; -1, -5 and positive 7
  also propagate unchanged. They cannot be turned into success by HWO-clear.
* Pointer replacement during Wait is rejected with original HWO still set and
  replacement descriptor unchanged. Replacement **before wait entry** is also
  rejected, without calling Wait.
* Original-pointer successful completion, full gate → OUT → SHL/capture → IN
  reply, three-fragment MEM1 capabilities and 1,024-byte MEMR pass. Successful
  paths increment served, not faults; firmware calls are 8-byte stack aligned.
  Wait preserves r4–r11 and balances its stack.
* Three independent source mutations disable admission, Wait-status propagation
  and pointer comparison respectively. Each executes and causes its desired
  exclusion/rejection assertion to fail. Positive tests rule out an
  always-reject implementation.

## Minimal experimental mechanism

`guard_ready` checks active mode `C3077794 == 5`, configured byte
`C31E1D6C == 1`, backend byte `C3032A92 == 1`, and DCTL `2100C704` bit 31.
It runs at `no_swap`, at each of `arm_out`, `arm_in`, `arm_in_block`, and
before the inline MEMW descriptor preparation. Existing top-of-round endpoint
mask/suspend checks remain. These are sampled values, not admission locks.

Two new, initially zero words, `guard_pins[OUT, IN]`, reside inside the copied
body allocation. Each of the four descriptor preparation paths records the
pointer it writes **before** StartTransfer. Wait loads that saved pointer,
checks the current table pointer equals it before dereferencing it, and rejects
zero or non-16-byte-aligned saved pointers. Separate OUT and IN slots are needed
because MEMW submits OUT, sends READY over IN, then waits for OUT. A single slot
would lose the OUT identity. Slots are addressed PC-relatively in relocated
code, not through staging or an assumed spare pool word.

This avoids changing the caller's argument ABI: `wait_done(logical, ms)` still
uses r0/r1 and returns status in r0. The helper saves six registers instead of
four, adding 8 bytes of stack usage while retaining alignment. Arm helpers keep
their existing save/restore convention. No new external entry or state offset
is claimed. The new mutable body words are nevertheless a **new internal
storage/lifetime contract**, not merely a different implementation hash.

The pin is the descriptor the worker prepared; StartTransfer itself consults
current firmware tables. A concurrent replacement inside StartTransfer can
still submit something else. The prototype does not close that race.

### Wait-status compatibility tradeoff

The original dispatch harness clears IN HWO and returns -1, intentionally
modeling an event already consumed elsewhere. The prototype's positive fixture
explicitly changes that mocked successful IN return to **0**. This is not a
claim that the old scenario still succeeds: strict nonzero propagation rejects
it, and the new status test proves that rejection. This conservative policy can
turn a physically completed transfer into a protocol fault. A separately
reviewed status classification/ownership design would be needed to recover
shared-event tolerance without accepting cancellation. No such classification
is established here.

## Bytes, ABI and existing handoff

Source SHA-256 at experiment time (`camera/worker.S`):
`603cbb7d6abd384c4f00af499fdad29974b3b375153122fa934ae25b3ebe6317`.

| Item | Current PONG body | Scratch guard body |
|---|---:|---:|
| Complete assembled image | 4016 bytes | 4272 bytes |
| Resident body | 3572 bytes | **3828 bytes** |
| `serve` relative to body | 120 | 120 |
| `next_round` | 200 | 200 |
| `no_swap` | 292 | 292 |
| `arm_out` | 3064 | 3144 |
| `wait_done` | 2152 | 2188 |

Current resident SHA-256:
`e2b94aeb67938dbb05f581ca6f8ec5aff1e84dfe7dd34de11a1b76e0c7f2b342`.
Scratch initial resident SHA-256:
`105fc57be3c6d683e797cf2cfcd5264e59db2b6806ca50a17c2c2569e6ca296d`.
The internal `mem_body_len` agrees with 3828; both pin words lie within it.

**The existing 3572-byte allocation is 256 bytes too small.**
`fpl_swapworker.py` requires SIZE=3572, a known SHA and exact symbol manifest
(including `arm_out=3064`). `asm/fpl_swapworker.S` verifies and copies exactly
3572 bytes, unwinds the known serve frame, enters `DEST+120`, and aborts to
`DEST+292`. Keeping those three entry offsets does not establish compatibility:
copying only 3572 truncates this body; copying 3828 overruns the old allocation.
Do not extend just the hash allowlist or copy length.

Furthermore, the new pin words mutate after first use, so a future whole-body
identity comparison against initial assembled bytes would fail. Any future
handoff design must explicitly handle owned mutable data, verified allocation
capacity, initialization and retirement, stack/unwind/pending/fault contracts,
and D/I publication before execution. A newly allocated body or reviewed new
boot allocation is necessary; neither was implemented or tested here. No
AutoRun/BIN pair was generated, so packaging compatibility is not established.

## Deliberate limits and next design obligation

This is a narrow regression prototype, **not the fuller worker-only proposal in
`FPL_USB_LIFECYCLE.md` section 4**, and not permission for a RAM trial:

* Readiness is not rechecked after every yield; direct arm helpers add the four
  new gates but do not repeat the existing mask/suspend gates. `out_owned` is
  unchanged. A readiness change after the check can still precede a write/call.
* Pointer equality misses same-address reuse (ABA), buffer/control replacement
  at the same address and same-mode reset. There is no generation or quiescence.
* Stock Wait and StartTransfer retain their internal teardown effects. Returning
  a Wait error cannot undo those effects.
* Existing fault handling still sets deferred cleanup; MEMW loss/abort still
  uses current-table EndTransfer and may attempt status replies. The prototype
  does **not** establish safe transaction abandonment or protect a replacement
  endpoint from subsequent cleanup. Rejection tests stop at wait return.
* MEMW's pin/gate instructions assemble, but its READY/data/DONE path and failure
  paths were not dynamically exercised. MEM1 positive coverage is MCAPS/MEMR.
  Handoff, reboot/reconnect, mode switching, power-off and stock fallback/rearm
  concurrency were not tested. Global NOPTP2 suppression is unchanged.

A stronger candidate requires proven lifecycle admission/quiescence covering
reset/init/stop and nested teardown, generation-bound submissions and cleanup,
and a proven reopen boundary. The controller semaphore is not that proven
boundary (see lifecycle audit section 7). Until those obligations are met, these
checks only reject demonstrated stale-state cases; they provide no race-free
or mode-switch safety guarantee.
