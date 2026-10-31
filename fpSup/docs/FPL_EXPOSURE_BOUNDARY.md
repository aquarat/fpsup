# fp L exposure restoration boundary — 31 October 2026

**Offline controller and executable refusal contracts, not enabled automatic
exposure.** This continues [the earlier save-order finding](FPL_QUEUE_IDENTITY.md#exposure-lifetime-a-concrete-earlier-save).
No camera calls or physical tests were performed for this slice. The latest
separate live restoration is in [producer provenance](FPL_PRODUCER_PROVENANCE.md).

## Implementation and mandatory refusal

- `exposure.c/.h`: retained68-byte state and bounded borrow/restore/pre-save
  dispatch. Neither `build_adapter.py` nor the card launcher embeds this code.
- `exposure_boundary.py`: native seam checks and non-overridable admission refusal.
- `build_card.py --exposure`: refuses **before reading images, creating output
  or packaging**. Default compilation returns `EXP_UNQUALIFIED` from borrowing
  before native calls. `FPL_EXPOSURE_MODEL=1` is isolated test admission only;
  there is no product build flag overriding qualification.
- `test_exposure.py`: compiled ARM core and actual native save/snapshot/pointer/
  walker instructions. Temporary owned-vtable wrappers exist only in Unicorn.

The controller saves mode, shutter numerator/denominator and ISO before its first
write, marks originals dirty before setters, uses the host helper's quantized
choices, and verifies the entire requested tuple. Restoration is shutter → ISO
→ mode → **complete final tuple readback**. Mode-induced shutter changes fail
restoration rather than producing false success.

States are Idle/Borrowing/Borrowed/Restoring/Closed/Fault. Closing is sticky for
the boot; it prevents new borrows and cancels remaining work. An in-flight setter
unwinds to its owner, which checks closing between steps and restores before
releasing busy. Reentrant/foreign requests refuse without spinning. Native call
arguments/result are distinct from refusal status; dirty originals survive
failure for a later bounded retry. No allocation/free, loader or extra shutdown
registration exists here. Only unmasked SVC in the configured task is accepted.
Native calls may block: bounded module work does not prove bounded wall time,
and its private gate does not serialize foreign settings notifications.

Modeled borrowing requires idle CINE/UHD CinemaDNG8-bit nominal24, selection1..4,
base shutter250/500/1000 and ISO100/200/400/800/1600/3200. Recording format and
timing are untouched. Modeled task admission is not native-task qualification.

## Native facts and counterexamples

Official fp L3.02 MAIN SHA-256:
`fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9`.

`C0089D00 -> C00882F0` returns provider `C31ACF94`. Constructor `C0089CB8`
publishes the0x90-byte vtable `C07381A8` at provider+8:

| Slot | Method | Role |
|---|---|---|
| +10 | C0086228 | Serialize current settings |
| +28 | C0085BB0 | Snapshot through C0086DA8 |
| +2C | C0086508 | Import through C0086CC0 |

`C0055320` dispatches+10. Ordinary callback `C0075FE8` first invokes `C0055588`
(+2C then `C0055760`), then save. Shell `C03FAC08` calls save directly. The save
path reaches `C0085CD8`, copies0x4F48 bytes into the storage block and marks dirty.
Test `persist` events mean serialization staging, **not physical flash writes**;
the native return1 does not qualify later flushing.

`C0086DA8` snapshots the0x4F48-byte collection and0x9DC-byte current profile at
provider+B268. `C0086CC0` imports them if snapshot+592C is set. Prepare can thus
undo restoration before the ordinary callback. Native property entries3/6 use
`C00B12D0/C00B1398 -> C0086E78`: in the modeled CINE/normal bank, mode is
provider+4F54+98C, shutter the pair at+990. Native copy/pointer instructions
overwrite restored cells with borrowed snapshot values. Branch selection and
notifications are modeled; ISO layout is not inferred. Other ordering tests use
an explicitly synthetic tuple at provider+100, not a claimed firmware ABI.

`C0086E78` acquires mutex+10B98, chooses a pointer, releases at `C0086EC8`, then
returns it. Later shutter stores at `C009C9A4/C009C9AC` remain possible: holding
that mutex in a save hook cannot exclude a writer which already has its pointer.
Pair setter `C0064A70` silently returns when property byte+10 is busy, without
restoring or giving a useful failure status. Reentrant restoration is not quiescence.

Ordinary walker `C0023BE4/3BE8` and forced walker `C0023EBC/3EC0` advance without
checking callback r0. The settings callback is absent from the forced list;
its test fixture only exercises return semantics. Shell `C03FAC08` prints success
even when modeled save returns0. Returning BUSY/VERIFY is not safe native refusal.

| Candidate | Finding |
|---|---|
| Shared shutdown restore | Too late: earlier native save has run. |
| Restore before original settings callback | Prepare imports borrowed snapshot. |
| Owned provider vtable wrapping+10 | Quiescent ordering works: import, restore/readback, original save; ABI/result preserved. |
| Provider mutex | Pointer getter releases before later property stores. |
| Wait for busy/reentrant owner | Cannot drain suspended caller; native callers ignore bounded refusal. |
| Private gate only | Foreign write can occur after verification, before serialization. |

The+10 candidate would require retained table/veneer, stock admission, D/I
publication and provider+8 declaration in the **existing shared journal** before
publication. None is installed. Safe request-level deferral/common serialization
must cover property admission, snapshot import/export and final copy; let setters
unwind; restore on a qualified task; and complete the original request exactly
once. Ordinary posting `C0023EE0 -> C036E010` and synchronous forced-reason4 in
`C0023E58` differ. Failed restoration needs a valid completion policy. Direct
property writes are not proven nonpersistent: these pointers are snapshot-backed.
No speculative exposure MMIO path was introduced.

## Verification

Historical stage:26 exposure/binding/native-order and54 shared regressions passed
without skips. Tests cover context/mode admission, coupled restoration, retained
failures, closure/reentry, actual native snapshot/save/walkers and foreign writes.
Mutations catch discarded dirty state, omitted closing, uncleared work, missing
final readback and save-before-restore; native mutations bypass image hashes.
These are modeled concurrency counterexamples, not native scheduling proof.

```sh
# fpSup/slit_scan; compiler and external images configured
python3 -B -m unittest -v test_exposure test_bindings test_queue_binding
```

V1/v2 launchers historically reproduced unchanged, SHA-256 respectively:
`52aebc6ccdfdd55586e9f4a97c74dcd4e1e314543bbf2e2846baf971c68d6218`,
`2513c8c6132fa050990cbe9acbbcfb1995821f8ce8f9dadb31dd58b05663f8ae`.
Current exported-tree results are in [validation](FPL_EXPORT_VALIDATION.md).
Compiled offline objects and raw logs remain external. No exposure runtime was
placed in the card reservation or deployed; existing size guards remain intact.
