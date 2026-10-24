# fp L headless v3 services: executable adapter, not boot authority

Offline implementation, 2026-10-23. **58 tests passed, zero skips**, including
seven new fp L tests, 22 existing fp v3 tests, and the required shared boot-chain,
loader-hook and splash checks. This is the concrete service-port fallback from
the retained-provider task. It does **not** close post-boot retained discovery
or cross-loader/reboot duplicate admission.

## What the sources actually establish

`v3/sloader.c:sl_boot()` allocates a new resident code/state block and zeros its
books on every invocation. The service table is the first member of that owned
state. `load_one()` excludes an already-kept product ID only in those books.
The new executed counter-test calls the real loader twice without resetting the
emulator: two distinct resident states both load the same product. A timestamp
or a kept-ID entry cannot turn those independent objects into a boot singleton.

`sl_load()` allocates its journal and registers the resident callback in both
power-off lists. `sloader_entry.S:unhook` walks the journal, restores words and
publishes D/I. It does not revoke a service-table capability, invalidate all
retained product references, or establish a subsequent boot's identity. Shared
stage2 similarly registers its journal before placement. These are restoration
mechanisms, not an independent ownership oracle.

The native allocator audit and executed kernels establish a USER allocation's
descriptor/list behavior. `H_ADDR` reads the saved descriptor; `H_FREE` does not
clear it. Native class-mode preservation is not boot preservation. Even current
allocation membership could identify a reused address, not distinguish an old
capability from a new object at that address. No membership/token check in this
patch is promoted to reboot proof. No additional native reset-generation source
was established.

Consequently there is no provider here that returns authority=1 based on an
assumed boot model. The prior opt-in retained-provider interface remains
unbound. A caller actually executing within a resident loader object's lifetime
can use the table handed to it; an external reader cannot reconstruct that
lifetime from a stale global pointer after reset.

## Implemented service profile

`v3/build_v3.py:loader_bin(camera='fp-l-3.02', splash=False)` now builds a
diagnostic headless core. It uses the same resident C implementation, ARM entry
stub, strict ELF extractor and existing VBIN format. Default fp behavior and
bytes are preserved. Unsupported camera names, fp L splash and manager builds
are rejected. The public AutoRun/CLI and product catalogue admission are not
expanded.

`v3/services_fpl_302.h` supplies explicit fp L addresses for:

- USER heap/get/free and D/I cache publication;
- file constructor/open/create/read/write/close/destructor;
- directory constructor/open/next/destructor;
- timer and both power-off registration calls.

File/allocator addresses follow the existing fp L audits and shared profile.
The directory wrappers were inspected in the fingerprinted official fp L image:
constructor `C0366B30` calls backend construction at `C0366AA0` and stores its
object pointer; open `C0366BA8` dispatches through backend vtable +`0x0c`; next
`C0366C10` through +`0x14`; destructor `C0366B58` dispatches +8 with flags 3 and
does not delete caller-owned holder storage when invoked with flags 2. These
actual wrapper instructions execute in the new fixture. Backend enumeration
and its returned directory-entry data remain mocked; no card enumeration was
performed or newly hardware-validated.

The profile advertises **service version 2**. It does not claim version 3's
`SL_SVC_AT` discovery binding. `cave_alloc()` returns zero; fp cave reset,
`done_at_start` global reads, transient service publication and global load-done
stores are compiled out. The service table remains owned by the resident
loader. Calls through an already-held, in-lifetime table work after staging is
released. A sup requiring service 3 is rejected before entry. This is not a
promise that arbitrary fp service-1/2 products are safe on fp L: the tests use
finite service-only diagnostic products, not fp product hooks or firmware calls.

The `boot_id` header comment now accurately calls it a load timestamp, not proof
of reboot or ownership. No struct layout, generic registry, extra loader pass,
entry ABI, firmware publication word, worker reservation or BIN/AutoRun pairing
was added.

## Actual emitted boot model

`v3/test_fpl_v3.py:envelope()` uses `card_build.artifact()` for the existing fp L
loader/stage2 and `build_vbin()` for a section containing the v3 core. The entry
points to the core's existing ARM stub after its 16-byte header. The packer
calculates the enclosing file offsets; the stub retains the shared self-address
entry convention and computes its resident copy as before. No alternative
loader or added pass is involved.

The test runs the actual shared loader → stage2 → v3 stub/C → finite products →
stage2 return → loader staging release. Loader staging is poisoned at its
modelled release and subsequent CPU accesses are trapped. Native USER
`MEM_HEAP`, `MEM_GET`, `MEM_FREE`, allocator-list and IRQ-guard instructions
execute against a synthetic USER heap. Stage2, resident code/state, journal,
scratch and product allocations use those actual direct allocator paths.
The loader's descriptor allocation/release remains the existing file-harness
mock, with a disjoint staging allocation.

Directory wrapper instructions execute against modelled backend objects.
File I/O, directory backend results, cache effects and power-off registration
are explicit mocks. Allocator telemetry/static-guard boundaries are also mocked.
The resident ARM power-off callback itself executes: the test claims a real
firmware word, rejects a conflicting second product, verifies the exact stock
journal bytes, then invokes restoration after staging has been poisoned.

Additional cases cover missing/short/version-3 products, both shared-stage2 and
resident-v3 registration failures, absent heap, real synthetic heap exhaustion,
post-return service calls, duplicate IDs within one loader, and a second fresh
loader with new books. All CPU accesses to the fp cave/global-publication range
are rejected. Native service entry stack alignment is checked. An isolated
source mutation drops the stock journal copy; the journal/restore oracle fails.

The Cortex-A15 mixed ARM/Thumb Unicorn run exposed multi-instruction IT-state
translation anomalies in the unrestricted compiler output (valid headers were
rejected after skipped conditional instructions). The fp L build explicitly
uses `-mrestrict-it`, emitting valid ARMv7 single-instruction IT blocks. Tests
execute those exact emitted bytes; no emulator PC/flags repair or post-extraction
instruction rewrite is used. This compiler choice does not change the default
fp build. Hardware execution remains unverified.

## Reproduction and results

Main independently ran the 36-test fp L service/shared-boot command after
delivery, with the M0 compiler wrapper and explicit official images: all passed
without skips. The additional 22 fp v3 tests below are the implementation
agent's separate regression run.

Use the compiler wrapper established by the M0 reference build, which selects
Thumb correctly and disables unsupported freestanding unwind generation. Put
its `bin/` and the ARM assembler toolchain on PATH. From `fpSup/fp_usb_shell/`:

```sh
FPSUP_FP_MAIN="$FP_MAIN" python3 -B -m unittest \
  v3.test_fpl_v3 test_boot_chain test_loader_hook test_splash
```

Result: **36 passed**. The existing `v3.test_v3` suite additionally passed all
**22 tests** using the fingerprinted fp image supplied to its legacy `IMAGE`
module variable in an in-process runner. Its image-dependent skip flag was
cleared only after image verification; no checkout symlink or firmware copy was
created. The final combined run passed **58, zero skips**.

Generated bytes in the test run (not installed on a card):

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Default fp headless core, before = after | 6696 | `11bb9d5ff7bee9391754c289f8cbd2bc0479df501a284f10da5c1971854519bd` |
| fp L headless core | 6656 | `8df4267eaf000ab2f893c8f59cfb32762f921a2d71abfdaf1f3a8abdea4d9bd5` |
| fp L shared-stage2 diagnostic envelope | 7556 | `c22fecde6255cdcdbef7b471b71e30405100e5a2b1a8fb3a843413acc16e459d` |
| Existing fp L loader | 316 | `40ace33a3cc303c95df4ca8996b7290eadb1b6d3880a8b65f35f4cd7547b3321` |

Hashes identify tested bytes only; there is no runtime version/hash pairing.
The envelope is below the existing read cap. No new AutoRun was emitted.

## Exact changes and next binding

Changed `fp_usb_shell/v3/sloader.c`, `sloader.h`, `build_v3.py`;
added `services_fpl_302.h`, `test_fpl_v3.py`, and this document.
USB worker/profile, retained launcher/runtime, Gyro2 source/build, public product
catalogue, main's tracker and port/live logs are outside this slice.

The remaining provider needs a **real retained owner of the loader context**:
either a native lifecycle-held object which can furnish the current context
without first dereferencing a stale published pointer, or an explicitly agreed
publication/reset contract owned by the composition and verified through native
boot/power-off/reset paths. That owner must reserve the diagnostic slot once,
serialize re-entry, revoke discovery on lifecycle end, and refuse ambiguous
recovery. Native callbacks in the current journal lists alone are insufficient.
Only then can the previous retained admission interface be bound and tested
across fresh staging using that real provider. Same-loader kept books and
post-return service access demonstrated here are useful prerequisites, not that
binding. No new arbitrary BSS word or private worker-pool offset is proposed.

No camera/socket/card/reboot/pending-marker operation, retained free/rearm,
commit or push was performed.
