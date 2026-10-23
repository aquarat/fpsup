# fp L packaged DATA: bounded descriptor provenance

> Evidence scope: dated measurements, test counts and source-availability
> observations below describe their original runs. The imported upstream
> research tree changes source availability; see the current
> [parity roadmap](FPL_PARITY_ROADMAP.md). Historical checks are not
> acceptance of a newly built card.

## Result

The official fp L 3.02 container's separate **DATA** payload supplies packaged
initial values for the four requested recorder rows and the sleep descriptor.
All match the archived October 23 observations at the **same exact addresses**.
Earlier MAIN-only searches did not include this payload; the addresses remain
outside file-backed MAIN, but their packaged byte provenance is now resolved.

This does **not** establish loader execution, absence of runtime mutation,
all-boot stability, table size, event delivery or task quiescence. Equal bytes
at two evidence points do not prove what happened between them.

## Sources and extraction

Input root:
`$HOME/.local/share/fpsup/firmware/`.

| Source | Bytes (decimal) | SHA-256 |
|---|---:|---|
| FPL_V302/MAIN.bin | 49,310,208 | `fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9` |
| FPL_V302/DATA.bin | 238,080 | `758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8` |
| FPL_V302.bin | 25,714,688 | `598ae32684844b50afff3797444041b794fb352b810db30f227d73474367cea4` |

`tools/fpl_data_dispatch_audit.py` fingerprints all three before interpretation.
It reuses the existing **read-only** `unpack_data` helper from
`tools/fpl_sensor_mode_audit.py`, not that module's sensor/native execution
tests. It independently re-extracts DATA from the container, fingerprints the
result and requires byte equality with the supplied DATA.bin.

The helper checks the `@DFI` marker at container+100, declared expanded length
**3A200**, initialized address **C2F06A00**, packed length **1D800** (120,832
decimal), and packed checksum. Packed bytes begin at **1746500**, computed
from `300 + word[134]`. Declared-length LZSS expansion consumes 120,527 source
token bytes; the returned expanded payload is exactly the declared length.
This is container-format/load-address evidence, not execution of a bootloader.
The initialized region's declared exclusive end is **C2F40C00**; that payload
extent is not a recorder-table extent.

## Exact comparisons

All numeric addresses, offsets and words in this table are hexadecimal. Archive
PONG sequence numbers in the last column are decimal.

| Item | Address | DATA offset | Bytes | Packaged and observed words | Archive PONG |
|---|---|---|---|---|---:|
| Event 23 | C2F2F738 | 28D38 | 10 | `23 0 FFFFFFFF C03ABAB8` | 95 |
| Event 24 | C2F2F748 | 28D48 | 10 | `24 0 FFFFFFFF C03ABAF0` | 95 |
| Event 2B | C2F2F7B8 | 28DB8 | 10 | `2B 0 FFFFFFFF C03ABD20` | 89 |
| Event 30 | C2F2F808 | 28E08 | 10 | `30 0 FFFFFFFF C03ABBD0` | 98 |
| Sleep descriptor | C2F06B48 | 148 | 4 | `1` | 92 |

The comparison allows only **four spans**: 32 bytes at C2F2F738, 16 bytes at
C2F2F7B8, 16 bytes at C2F2F808 and 4 bytes at C2F06B48. It does not inspect
intervening rows, neighboring descriptors or scan for an end marker.

Archives are read from
`$HOME/.local/share/fpsup/observations/`:

* `dispatch-23-24.bin` plus `dispatch-23-24-provenance.json`;
* `dispatch-30.bin` plus `dispatch-30-provenance.json`;
* `recording-event-descriptor.json` for 2B;
* `thread-sleep-descriptor.json` for the sleep word.

The last two contain numeric and hexadecimal words, not separate raw binaries.
The audit checks both representations and reconstructs little-endian bytes for
comparison; it does not mislabel these as preserved raw USB captures. The first
two comparisons require exact binary lengths/content and matching metadata.
All metadata must report the exact address, expected PONG, model `w91c1`,
release `3.02.0.V90`, XC `V90` and git hash
`13aa621060efff11aaba9b21ad925005302605cf`.

Output preserves the archive provenance and records metadata/payload hashes.
These checks establish consistency of the saved evidence, not independent
authentication of its original camera acquisition. “Runtime match” means the
archived point-in-time observation, **not a fresh current-camera read**.

## Decoder and semantic boundaries

For 23/24/30 the audit reuses `fpl_recording_dispatch_table.decode`, after its
official MAIN/code verification. Negative selectors and zero adjustment yield
the known direct thunks and state slots +74/+78/+98 respectively. Word zero is
not used to infer the event ID: the dispatcher indexes from C2F2F508.

The existing decoder's policy remains unchanged: it still refuses row 2B.
This new audit compares only the already observed, separately justified 2B
four-word record; it does not widen the decoder or infer neighboring rows.
The meaning and generic-event bypass of 2B remain as established in
[FPL_RECORDING_FAILURE_UNWIND.md](FPL_RECORDING_FAILURE_UNWIND.md).

Likewise, equality of the sleep descriptor's word `1` gives a packaged source
for that saved value, not a new proof about a task's wait state or lifetime.
No retained-task code or documentation is changed by this audit.

Packaged values and observed runtime values are distinct evidence classes:

1. Container metadata and re-extraction establish what bytes are packaged for
   these initialized addresses in this firmware release.
2. Archived observations establish what was reported at those addresses on
   those individual reads.
3. Their equality does not identify which loader/copy path executed, rule out
   writes followed by restoration, prove read-to-read atomicity or establish
   immutability across starts, power cycles or firmware versions.

Neither the payload end nor the nearby pool pointer C2F2F838 is a table-end
declaration. No whole-table bound follows from this correlation.

## Reproduce and negative coverage

```sh
python3 -B tools/fpl_data_dispatch_audit.py --self-test
```

Options `--main`, `--data`, `--container` and `--archive` override local paths.
Imports require the dependencies of the reused helpers (Capstone/Unicorn);
this audit performs no emulated ARM execution and no sensor or device access.

Verified: **4 matching regions (4 recorder rows plus the sleep word), DATA
re-extraction, and 15 expected refusals**:

* truncated and changed MAIN, DATA and container sources (six);
* shifted DATA base, shifted offset, neighbor row, widened result span and
  gap-spanning request (five);
* changed packaged row, archive address and archived binary (three);
* unchanged narrow decoder rejection of row 2B (one).

The existing sensor and recording audits are reused without modification.
No camera reads, card writes, hooks, main-log changes or commits are involved.
