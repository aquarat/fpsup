#!/usr/bin/env python3
"""Read-only fp L USB diagnostics; import/help are offline.

Reads are sequential, not an atomic camera-side snapshot. Collection itself
increments worker counters. No TRB pointer is followed, no handler is borrowed,
and no window, USB mode, settings or payload memory is written.
"""
import argparse
import datetime
import json
import re
import time

import fpl_getfile as gf

# Fixed firmware globals, corroborated by the October 20 working-state capture.
# TRB table values are recorded only, never used as addresses by this tool.
GLOBALS = {
    'trb_bus_table': (0xC31E1638, 7),
    'trb_cpu_table': (0xC31E1664, 7),
    'usb_state': (0xC31E1B48, 1),
    'out_busy': (0xC31E1D74, 1),
    'ptp_buffer': (0xC3025744, 1),
    'endpoints': (0x2100C720, 1),
    'echo_handler': (gf.ECHO_SLOT, 1),
    # Lifecycle correspondence: docs/FPL_USB_LIFECYCLE.md. Byte fields are
    # captured inside aligned words and decoded below; no pointer following.
    'active_mode': (0xC3077794, 1),
    'configured_word': (0xC31E1D6C, 1),
    'backend_word': (0xC3032A90, 1),
    'out_consumed': (0xC31E1E08, 1),
    'controller_control': (0x2100C704, 1),
    'logical_out_config': (0xC31E1C98, 4),
    'logical_in_config': (0xC31E1CA8, 4),
}
COUNTERS = {'rounds': 3, 'served': 8, 'faults': 9, 'holds': 10}


def words(io, address, count):
    result = io.words(address, count)
    if (type(result) is not list or len(result) != count or
            any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in result)):
        raise RuntimeError(f'incomplete word read at {address:#x}')
    return result


def snapshot(io=None):
    # Pending handoff does not forbid observations; do not clear its marker.
    with gf.staging_lock(permit_pending=True):
        io = io or gf.Backend()
        started = time.monotonic()
        version = io.sh('version', retries=0)
        if (version.lstrip().startswith('ERR') or
                not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
                not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
            raise ValueError('expected fp L 3.02')
        publication = words(io, gf.PUBLICATION, 3)
        caps = io.caps()
        gf.layout(caps, publication, 0)
        pool = publication[0]
        state_before = words(io, pool + 0x1000, 16)
        fixed = {name: {'address': address, 'words': words(io, address, count)}
                 for name, (address, count) in GLOBALS.items()}
        swap = {'magic': words(io, pool + 0x1080, 1)[0],
                'address': words(io, pool + 0x10C0, 1)[0]}
        state_after = words(io, pool + 0x1000, 16)
        caps_after = io.caps()
        if words(io, gf.PUBLICATION, 3) != publication or caps_after != caps:
            raise RuntimeError('publication or capabilities changed during collection')
        return {
            'schema': 1,
            'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'elapsed_s': time.monotonic() - started,
            'version': version, 'publication': publication, 'caps': caps,
            'fixed_reads': fixed, 'swap': swap,
            'lifecycle_fields': {
                'active_mode': fixed['active_mode']['words'][0],
                'configured_byte': fixed['configured_word']['words'][0] & 0xFF,
                'backend_selector': (fixed['backend_word']['words'][0] >> 16) & 0xFF,
                'controller_running': bool(fixed['controller_control']['words'][0] & (1 << 31)),
            },
            'state_before': state_before, 'state_after': state_after,
            'counter_delta_mod32': {name: (state_after[i] - state_before[i]) & 0xFFFFFFFF
                                    for name, i in COUNTERS.items()},
            'pending_exists': gf.LOCK_PATH.with_suffix('.pending').exists(),
            'limitations': 'Sequential reads; not atomic. Commands perturb counters. '
                           'Absolute counters may be uninitialized; deltas assume no reset. '
                           'Stable publication is not an independent boot-generation ID.',
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(snapshot(), indent=2))


if __name__ == '__main__':
    main()
