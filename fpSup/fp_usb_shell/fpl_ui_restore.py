#!/usr/bin/env python3
"""Read-only fp L shared-loader journal verification for all six UI hook words.

Unlike the older fp helper, the journal object may be in USER memory. Match the
current shared restore routine exactly and bound every journal read. No journal
extension, registration, patch, reboot or hook lifetime proof is performed.
"""
import argparse
import json
from pathlib import Path
import struct

import armasm
import fpl_ui as ui
from card_build import DIR_ENTRY
from firmware import get_camera

HERE = Path(__file__).resolve().parent
CAMERA = get_camera('fp-l-3.02')
MANAGER = 0xC3075684


def stock_sections(image):
    return [(site+offset, image[site+offset-0xC0000000:site+offset-0xC0000000+4])
            for site in ui.STRING_SITES.values() for offset in (0, 4)]


def restore_code(*, slit=False):
    source = HERE/'asm/stage2.S'
    defines = CAMERA.loader_defines()+['LH_RESTORE=1', f'LOADER_BASE={DIR_ENTRY:#x}']
    if slit: defines.append('FPL_SLIT_RECORDING=1')
    code, symbols = armasm.assemble(source, defines), armasm.symbols(source, defines)
    return code[symbols['lh_unhook']:symbols['lh_unhook_end']]


def inspect(read, image, *, draw=False, slit=False, producer=False):
    if read(MANAGER, 1) != [0xC0726CEC]:
        raise ValueError('power-off manager vtable differs')
    lists = {name: list(read(MANAGER+offset, 10))
             for name, offset in (('ordinary', 0x0C), ('forced', 0x34))}
    for values in lists.values():
        if len(values) != 10 or any(v and (v & 3 or not
                (0x40000000 <= v < 0x80000000 or 0xC3000000 <= v < 0xD0000000)) for v in values):
            raise ValueError('invalid power-off list')
        if 0 in values and any(values[values.index(0)+1:]):
            raise ValueError('power-off list has a hole')
    code = restore_code(slit=slit)
    candidates = []
    for obj in sorted(set(lists['ordinary']) & set(lists['forced']) - {0}):
        vtable, routine, journal = read(obj, 3)
        if (vtable, routine, journal) != (obj-8, obj+12, obj+12+len(code)):
            continue
        actual = struct.pack('<%dI' % (len(code)//4), *read(routine, len(code)//4))
        if actual != code:
            raise ValueError('shared restore code differs')
        entries, cursor, total = [], journal, 0
        for _ in range(65):
            address = read(cursor, 1)[0]
            if address == 0:
                break
            length = read(cursor+4, 1)[0]
            if (len(entries) == 64 or address & 3 or not 0 < length <= 4096 or length & 3 or
                    not (0xC0000000 <= address and address+length <= 0xC0000000+len(image) or
                         address in (0xC38D37CC, 0xC31D6DD8) and length == 4)):
                raise ValueError('invalid or oversized firmware journal entry')
            total += length+8
            if total > 16384:
                raise ValueError('journal exceeds read bound')
            data = []
            for offset in range(0, length, 128):
                data.extend(read(cursor+8+offset, min(128, length-offset)//4))
            entries.append(dict(address=address, bytes=length, words=data))
            cursor += 8+length
        else:
            raise ValueError('unterminated journal')
        candidates.append(dict(object=obj, routine=routine, journal=journal, entries=entries))
    if len(candidates) != 1:
        raise ValueError('expected one matching shared journal in both lists')
    block = candidates[0]
    sites = []
    expected = stock_sections(image)
    if draw:
        expected.append((0xC38D37CC, struct.pack('<I', 0xC2E55A70)))
    if slit:
        expected.append((0xC31D6DD8, bytes(4)))
    if producer:
        expected.extend((a,image[a-0xC0000000:a-0xC0000000+4]) for a in
                        (0xC031EBF8,0xC031EBFC,0xC031EC58,0xC031EC5C))
    for address, data in expected:
        values = [e['words'][(address-e['address'])//4] for e in block['entries']
                  if e['address'] <= address < e['address']+e['bytes']]
        want = struct.unpack('<I', data)[0]
        sites.append(dict(address=address, stock=want, recorded=values,
                          covered=values == [want]))
    return dict(kind='fpl-ui-shared-restore-v1', lists=lists, block=block, sites=sites,
                complete=all(s['covered'] for s in sites),
                power_switch_tested=False, hook_quiescence_proven=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    image = CAMERA.verify_main(args.main)
    if args.out.exists():
        p.error('output must be a new file')
    import fpl_getfile as gf
    with gf.staging_lock():
        io = gf.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version:
            raise ValueError('fp L 3.02 required')
        report = inspect(lambda a, n: ui.words(io, a, n), image)
        report['version'] = version
    with args.out.open('x') as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))
