# Recording lifecycle coverage — bounded evidence, integration still gated

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

2026-10-23. Resumes the incomplete October 20 checkpoint. **There is a common
local successful-return path for the studied start step, but no all-mode
successful-active flag or proven media-complete stop gate.** In particular:

* `XC_StillCreateRaw+ A0` is a dispatch selector (observed values 13, 1, 9),
  **not a Boolean recording flag**. Its publication precedes a failure exit.
* `C0379430` is the studied start step's common local success tail, reached
  with audio-file gate either zero or nonzero. Return zero means this step
  accepted its work, not proof of first exposure, durable media, or every mode.
* The existing STOP site is in **MovRecFuncStateCinemaDng**. Its later
  `stop_fin` branch also accepts a finalizer-zero bypass; neither site establishes
  complete successful media shutdown.

Scope: only this document and `tools/fpl_recording_state_audit.py`; offline
read-only firmware analysis, synthetic ARM execution. No camera access, card
build/write, production hook changes, commits or publishing. Fully read current
`gyro/rec_trigger.S`, [recording bindings](FPL_GYRO_RECORDING_BINDINGS.md),
[path bindings](FPL_GYRO_PATH_BINDINGS.md) and their audit tools. Source comments
about a take “really begins or really ends” are not an all-mode fp L contract.

## Reproduce and evidence limits

```sh
ROOT="$HOME/.local/share/fpsup/firmware"
python3 -B tools/fpl_recording_state_audit.py \
  --fp "$ROOT/FP__V502/MAIN.bin" --fpl "$ROOT/FPL_V302/MAIN.bin" --self-test
```

Requires Capstone and Unicorn; missing inputs/dependencies fail rather than skip.
Defaults use `Path.home()` and the same input directory. JSON goes to stdout;
it contains addresses, correspondence, assumptions, call traces and test cases,
not private source-file paths or firmware dumps.

| Official decompressed MAIN at C0000000 | Bytes | SHA-256 |
|---|---:|---|
| fp 5.02 | 49,245,696 | `aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622` |
| fp L 3.02 | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |

Passed **19 bounded fp/fp L ARM correspondences, 39 fp L actual-ARM scenarios,
14 negative cases**. Both complete images were fingerprinted. The new
correspondences include owner construction/access, caller branches, the full
selector consumer, installed result callback, stop worker and frame advancement.
The sibling normalizer retains ordinary constants, registers, field offsets and
internal branches; external targets and MOVW/MOVT literals are reported separately.
Owner/table identities additionally receive exact literal/slot/string checks.
This is not recursive equivalence of all callees or global function uniqueness.

The whole-image aligned branch/pointer scan reports potential xrefs, not a
code/data partition or proof of absence of computed/Thumb callers. Local caller
instructions and installed table edges below were inspected. The bounded +A0
operand scan is **not whole-program alias analysis**. Overall: `incompleteCFG`.

### What actual ARM execution tests

All selected instructions execute from the official fp L image in Unicorn.
Code is read/execute-only; writes are restricted to synthetic RAM. Every executed
address must be in an explicit bound or explicit stub, and each run must return
within 5,000 instructions. No firmware RTOS, sensor or filesystem service runs.
Stubs preserve registers except r0/PC and return zero unless explicitly
overridden; path-output and bounded memset writes are modeled explicitly.

* **8 start suffixes:** audio 0/1 × SD/SSD string × injected downstream
  result 0/1. Entry is `C0379204`, **after earlier setup is assumed successful**;
  registers and saved stack frame are synthetic. Explicit service stubs supply
  settings, initialized Cinema manager and valid pathname object. Audio calls
  return zero without opening anything. The real frame-advance body and number
  validator execute. Tests check hook bypass, return 2 versus 0, +A0 publication
  even on failure, frame increment only on success and unchanged take counter.
  SD/SSD here exercise volume argument propagation under a selector stub; they
  are not real media or selector-initialization tests.
* **16 complete stop bodies:** audio 0/1 × initial retry 0/1 × injected worker
  result 0/1 × raw format result 0/2. Check retry hook bypass, retry latch,
  `stop_fin` branch and returned state value. Format numbers remain raw values,
  not a proved MOV/DNG mapping. Each case has fresh RAM, so retry=1 models
  re-entry rather than an asynchronous two-call execution.
* **8 caller tails:** start statuses 0/1/2/3 × callback absent/present.
  Execute `C0378734` onward, the real callback dispatcher and real installed
  callback body. Check unchanged status, callback arguments and constructed
  event fields. Memset is a bounded synthetic stub; queue delivery is stubbed.
* **3 early failures:** stock instruction slices starting at the first resource
  check, setup check and cancellation gate return 1/3/1 respectively, without
  reaching the +A0 store. Cancellation calls the two observed cleanup services;
  their bodies are stubbed, so cleanup completion is not certified.
* **4 stop-worker negatives:** execute `C0398FA0` with injected state 0/1/2/3
  and real finalizer `C03A53A8` on a synthetic owner with byte +C zero.
  States 0/1/2 return zero; state 3 takes the finalizer-zero notification path
  and returns **one**, bypassing later finalization.

Eight negative cases change first/code/last bytes or truncate either image and
must fail full fingerprinting. Six more bypass fingerprinting and structural
comparison: change +A0 publication 1→0, reverse late-start result/audio-gate
branches, reverse stop retry branch, clear rather than set the retry latch, or
skip the caller's failure callback. Actual-execution oracles reject all six.
The suite does not test live scheduling, concurrent settings changes, media
removal, all dispatch modes or callback installation/lifetime.

## Owner identity, actual caller and +A0 accesses

Addresses below are fp L 3.02 ARM addresses; sizes/offsets are hexadecimal.

1. `C0377560` initializes via `C03774A0` and returns singleton **C3520F24**.
   Constructor writes table **C0BBF82C** at +0; associated RTTI names
   **XC_StillCreateRaw**. It initializes +A0 to **13** at `C0377514`.
2. Table slot **+18 → C0377C48**. Worker `C0377368` loads that slot at
   `C03773CC..D4`, obtains a request through `C03755D8`, and calls it indirectly
   at **C03773FC**, with r0=owner and r1=request. Queue/dequeue implementation
   and other derived owners remain outside this proof.
3. Dispatcher saves owner in r7 and request in r4. At `C0377EA8`,
   **request word +4 == 1** chooses the branch calling `C0378C68` at
   **C0377F14**, r0=owner, r1=request. It is the only aligned direct branch
   reference found to that start entry. Other request values select other
   bodies, including `C0379440`, `C0379850`, `C0379B70`, `C0379D80`.
   This dispatch value must not be silently renamed a user-facing format enum.
4. Start saves r0 in r6. Thus `[r6+A0]` at **C037936C** belongs to this raw
   creation owner, not CameraMgrSetting, the path manager or the Cinema state.
5. Another start body writes **9** at `C0379E08`. Full consumer
   **C037A020..C037A7A7** reads +A0 at `C037A0C4`, `C037A158`,
   `C037A234`, `C037A4D8`, `C037A5A8`: compares against 9 or passes it into
   dispatch helpers (`C0398A78`, `C0374480`). Its caller at `C037F9D4`
   obtains the same owner through `C0377560` immediately beforehand.

The bounded owner region contains three direct +A0 stores (13, 1, 9) and five
loads above, no observed clear-on-stop. This establishes selector usage, not a
complete catalog of indirect/aliased writers. A cached +A0=1 cannot prove a take
is active, has started successfully, or has stopped.

## Start acceptance, media/path edge and failure delivery

The whole start body `C0378C68..C037943F` corresponds to fp
`C0378A50..C0379227`. Observed returns:

| Condition / branch | Return | Relation to publication |
|---|---:|---|
| `C0378D34 → C03A4F18` returns zero | 1 | before +A0=1 |
| `C0378FA0 → C038A4A0` returns zero | 3 | before +A0=1 |
| owner byte +78 nonzero at `C037918C` | 1 | before +A0=1; calls `C038A508`, audio `C01F7D88` |
| `C0379398 → C0311030` returns zero | 2 | **after +A0=1**, no local reversal |
| later tail completes | 0 | `C0379430`, both audio gate branches |

Live-settings +E0 selects the audio-file branch; zero bypasses the existing
START `C03792D0`. Both paths join at `C0379354`. Following the +A0 store,
`C0311030` builds a parameter block, copies 1B0 bytes, and delegates to
`C031FF78`; that larger operation has sensor/callback/asynchronous dependencies
not certified here. A nonzero result is only the local acceptance condition.

On that result, `C03793D8` selects a Cinema manager (selector word 1, current
volume string). The indirect edge **C03793F8** uses **table +28**, verified
against **C0B8D874 → C030F380**. That method increments manager **+14 and
+1C**, calls the number validator, then returns. **It does not advance +10
(the take number)**; take advancement is slot +24, `C030F240`. The caller
ignores this method's result. It then sends notifications at `C037940C` and
`C037942C` and returns zero. Earlier audio pathname lookup uses slot +18 and
path extension slot +C as established in the path audit; it remains a candidate
identity, not a successful filename reservation for every path.

The dispatcher preserves the start return in r5. After common bookkeeping,
`C0378734` tests it: zero returns without this callback; nonzero calls
**C0377428** at `C0378754`, with `(owner, request[10FC], 0, error)`.
It subsequently returns that same error.

This callback edge is now resolved one level further:

* `C0377410` sets owner+0C. `C0381870` installs its own embedded callback
  object at +E8 into this owner at `C03818F8` (and three other owners).
* It loads table **C0BC1A5C** through literal word **C0BC15E4**. Slot +C is
  **C0385978**, used by `C0377428`'s indirect call at `C0377468`.
* With callback-kind r2=0, the real callback constructs event **0x2B**, subtype
  **5**, stores request identifier at event+E8 and error at event+E4, then calls
  `C0388BA8 → C03A9798` to submit it.

This is **failure notification, not synchronous unwind**. The event consumer,
delivery outcome, abort ordering and post-failure resource state remain unresolved.
The callback null case performs no notification. Neither observing a failed
return nor the event construction proves the audio/media workers are quiescent.

## Stop owner, retry and the nonzero-result counterexample

`C038B3D0` returns **C358EAC0**, constructed by **C038B470**. The constructor
installs table **C0BC24AC** at +10; RTTI names **MovRecFuncStateCinemaDng**.
It clears byte **+20** at `C038B4AC`; reset method `C038BF90` also clears it
at `C038BFA8`. This is a **different owner and field** from raw-owner +20 or +A0.

Seven aligned direct callers of `C038C5D8` were found and their call contexts
inspected: **C038BA58, C038BDE8, C038C044, C038C16C, C038C23C,
C038C320, C038C33C**. They pass the state object in r0; returned values are
propagated or saved as state results, not universally interpreted as Boolean
success. Full event reachability into all seven callers remains unresolved.

* If state+20 is zero, the body calls raw-owner stop request `C0377838`, audio
  work and `C0399368`. `C0377838` sets raw-owner byte +78, calls
  `C03110B0 → C0321448` and drains a request list via `C0377330`;
  this chain is not a certified writer join/durable close.
* Audio-file/no-file branches join at **C038C698**, existing STOP hook
  **C038C69C**. If state+20 was already nonzero, **the hook is bypassed**.
* Both paths reach **C038C6FC → C0398FA0(1, caller argument)**. Result is
  saved in r11. Raw `C0310AC8` result 2 skips another processing sequence;
  no format-name equivalence is asserted.
* Worker result zero branches at `C038C774` to set state+20=1 at
  `C038C7FC` and return state+0C. A later retry skips initial teardown/hook.
* Nonzero reaches the `stop_fin` log at `C038C778`, then audio reset,
  `C0386B78`, notification 0x13 and a state-result return. It **does not
  clear an existing +20 latch**; constructor/reset are separate.

Crucial counterexample inside **C0398FA0**: it gets a state from `C0376518`.
States 0/1/2 return zero (state 2 also calls `C03A53A8` with r1=0). Other
states call `C03A53A8` with r1=1. That routine returns zero immediately when
its own owner's byte +C is zero; otherwise it conditionally handles a file,
clears +C/+10 for r1 nonzero, and returns one. The full flag's lifecycle and
durability semantics remain unresolved. If the call returns **zero**, the code sends
notification `(0x15, 0x11, 1, 0)` at `C0399168`, logs and **returns one** at
`C039919C`, without reaching the later path/media work. This branch executes
in the bounded negative scenario. It is a terminal bypass, not by itself a
proved user-visible error. Therefore `stop_fin` means a terminal local
branch was chosen, **not certified successful media close**.

The other worker branch uses Cinema slots +18 (path), +2C (number eligibility),
+24 (conditional take advancement), pathname extension +C and a volume-object
indirect +20 operation at `C03992B4`. Known Cinema/path slots are grounded in
the path audit. The volume target, finalizer internals, worker state semantics,
durability and consumer transitions still require resolution.

## Coverage matrix and next actionable integration gate

| Axis | Established | Still unresolved |
|---|---|---|
| audio/noaudio | local start tail convergence; stop first-pass convergence | audio result/worker success, entry reachability |
| CinemaDNG | stop owner's concrete type; Cinema manager table chain | end-to-end successful active interval and completed media close |
| MOV | path formatter supports MOV | MOV lifecycle owner/dispatch and pairing with these sites |
| SD/SSD | same bounded start control flow with injected initialized managers | real media operations, fallback/removal, stable identity |
| failure | early and late return classes, installed failure event callback | event consumption and complete unwind |
| repeated stop | +20 retry latch and hook bypass | eventual task/IO quiescence and reset ordering |

**Zero of the eight MOV/CinemaDNG × audio/noaudio × SD/SSD combinations is
proved end-to-end by this audit.** Some user-facing combinations may not be
supported at all; the emulator matrix does not assert otherwise.

Next integration gate is a **bounded observation-only lifecycle experiment**,
after the main session independently establishes reachable placement, exact
restoration and callback lifetime. Record the request kind, local start return,
raw-owner identity/+78/+A0, Cinema-state identity/+20, stop-worker result and
whether the finalizer-zero bypass was taken. For the studied start, use
`C0379430`/returned zero as a *local accepted-start observation*, never the
earlier +A0 store as an active flag. Pair with stop retry/terminal-error evidence,
not only the current STOP hook or `stop_fin` log.

Before enabling recording-gated writer open/close:

1. Resolve **event 0x2B/subtype 5** consumer and its failed-start abort path.
2. Resolve `C031FF78` completion semantics, `C03A53A8` finalizer and the
   stop worker's volume-object edge; distinguish terminal error from durable
   completion. Establish the actual MOV state/dispatch separately.
3. Correlate repeated successful and failed takes with actual stock files,
   observed mode/media, stable naming and no orphan writer. Establish both
   first-pass and retry stop behavior and media/power cancellation.
4. Only then select shared logger lifecycle callbacks and file collision policy.

No exposure timing, universal recording flag, writer coexistence, safe USB use
while recording or safe synchronous callback placement follows from these tests.
