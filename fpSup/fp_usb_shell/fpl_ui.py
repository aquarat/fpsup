#!/usr/bin/env python3
"""Read-only fp L 3.02 UI layout verification. No hooks, calls or card writes.

The addresses are image-reviewed bindings, not fp offsets applied blindly.
Runtime pointers belong to this boot only. The snapshot is evidence, never an
authority to reuse a pointer after reboot. Import and --help do no device IO.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from firmware import get_camera

GUI_GET, GUI_OBJECT = 0xC055B208, 0xC37B6B10
APP_REGISTRY, REGISTRY_LOOKUP = 0xC05D6091, 0xC05D75F9
REGISTRY_REGISTER, SUBSCRIBE_INT = 0xC05D74E9, 0xC055D0C8
POST_INT, POST_STRING = 0xC0590078, 0xC0590128
NBU, POOL, POOL_LEN = 0xC18D01A0, 0xC18D01B4, 176152
STRING_SITES = {'resolve': 0xC05E1D38, 'owns': 0xC05E23A8, 'remain': 0xC05E23C0}
PAGES = {'MainB2': 0x76FF04, 'B2_5': 0x19C130}


def heap_pointer(value):
    # UI objects use the firmware's cached heap alias, not USER's DMA address.
    if type(value) is not int or value & 3 or not 0xC3000000 <= value < 0xD0000000:
        raise ValueError(f'invalid cached UI heap pointer: {value!r}')
    return value


def words(io, address, count=1):
    if not 0 < count <= 8192 or address & 3:
        raise ValueError('unaligned or oversized UI read')
    result = []
    for off in range(0, count, 32):
        want = min(32, count-off)
        part = io.words(address + off*4, want)
        if len(part) != want or any(type(v) is not int for v in part):
            raise RuntimeError(f'incomplete UI read at {address + off*4:#x}')
        result.extend(part)
    return result


def snapshot(io, main):
    version = io.sh('version', retries=0)
    if not (re.search(r'\bmodel\s*=\s*w91c1\b', version) and
            re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise ValueError('fp L 3.02 required')
    app = heap_pointer(words(io, GUI_OBJECT)[0])
    count = words(io, app + 0x80)[0]
    screens = heap_pointer(words(io, app + 0x8C)[0])
    if not 0 < count <= 512:
        raise ValueError('UI screen count outside bound')
    screen = heap_pointer(words(io, screens)[0])
    if words(io, screen + 4)[0] != app:
        raise ValueError('screen belongs to a different app')
    reader = heap_pointer(words(io, screen + 0x24)[0])
    header = words(io, reader, 10)
    if header[0] != 0x01090000 or (header[4], header[5], header[9]) != (POOL_LEN, POOL, NBU):
        raise ValueError('not the stock fp L NBU reader')
    entry_count, table = words(io, reader + 0xA8, 2)
    heap_pointer(table)
    if not 0 < entry_count <= 512 or entry_count != count:
        raise ValueError('UI entry count outside bound or differs from screens')
    entries = words(io, table, entry_count*11)
    found = {}
    for i in range(entry_count):
        name_at, offset = entries[i*11+1:i*11+3]
        if not POOL <= name_at < POOL+POOL_LEN:
            raise ValueError('entry name outside stock pool')
        start = name_at - 0xC0000000
        name = main[start:start+64].split(b'\0', 1)[0].decode('ascii')
        if name in PAGES:
            if name in found or offset != PAGES[name]:
                raise ValueError('duplicate or redirected target page')
            # Check actual name bytes as well as their image location.
            aligned = name_at & ~3
            raw = struct.pack('<%dI' % ((len(name)+1+3+(name_at&3))//4),
                              *words(io, aligned, (len(name)+1+3+(name_at&3))//4))
            if raw[name_at&3:][:len(name)+1] != name.encode()+b'\0':
                raise ValueError('live page name differs from image')
            found[name] = dict(entry=table+i*44, offset=offset, source=NBU+offset)
    if found.keys() != PAGES.keys():
        raise ValueError('required target pages missing')
    registry = heap_pointer(words(io, app+0x888)[0]) + 0x60
    # The name map is embedded at registry+0x14, not a pointer at +0x14.
    mapping = words(io, registry+0x14, 6)
    if not 0 < mapping[2] <= 4096:
        raise ValueError('variable count outside bound')
    heap_pointer(mapping[3]); heap_pointer(mapping[4])
    sites = {}
    for name, site in STRING_SITES.items():
        raw = struct.pack('<2I', *words(io, site, 2))
        if raw != main[site-0xC0000000:site-0xC0000000+8]:
            raise ValueError('string function is already modified')
        sites[name] = dict(address=site, stock8=raw.hex())
    if (words(io, GUI_OBJECT)[0] != app or words(io, reader+0xA8, 2) != [entry_count, table]
            or words(io, app+0x80)[0] != count or words(io, app+0x8C)[0] != screens):
        raise RuntimeError('UI layout changed during snapshot')
    return dict(schema='fpl-ui-layout-v1', version=version, gui_object=GUI_OBJECT,
                app=app, screens=screens, screen_count=count, reader=reader,
                reader_header=header, entry_count=entry_count, table=table,
                pages=found, registry=registry, variable_count=mapping[2],
                string_sites=sites, main_sha256=hashlib.sha256(main).hexdigest(),
                evidence='read-only live layout; no native registration or hook installation tested')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    image = get_camera('fp-l-3.02').verify_main(args.main)
    if args.out.exists() or not args.out.parent.is_dir():
        p.error('output must be a new file in an existing directory')
    import fpl_getfile as gf
    with gf.staging_lock():
        result = snapshot(gf.Backend(), image)
    with args.out.open('x') as f:
        json.dump(result, f, indent=2)
        f.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
