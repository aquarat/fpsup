#!/usr/bin/env python3
"""Whole fp L 3.02 card file larger than the staging pool, by chunks.

Import/help are offline. Each chunk is one borrowed-echo call of
asm/fpl_getrange.S: open, read and discard `index` whole chunks, read one,
close. A short final chunk gives the exact file length. Downloads only; no
card writes. Uses fpl_getfile's lock, version/publication checks and staging.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct

import fpl_getfile as gf

HERE = Path(__file__).resolve().parent
CHUNK = 0xC0000
STATUS = {1: 'running', 2: 'read', 3: 'open returned 0', 4: 'read returned 0',
          5: 'no buffer', 6: 'end of file inside skipped range'}


def chunk(io, plan, path, index, publication):
    code = gf.assemble(HERE / 'asm/fpl_getrange.S',
                       gf.get_camera('fp-l-3.02').loader_defines() + [f'P={plan.param:#x}'])
    if not code or len(code) > gf.CODE_ROOM:
        raise ValueError('getrange code exceeds staging reservation')
    param = bytearray(gf.parameters(plan, path))
    struct.pack_into('<I', param, 0xE4, index)
    for address, data in ((plan.code, code.ljust(gf.CODE_ROOM, b'\0')),
                          (plan.param, bytes(param)), (plan.fobj, bytes(gf.FOBJ_ROOM))):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('staging readback mismatch')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('worker publication or echo owner changed during upload')
    try:
        for handler in (gf.DCACHE, gf.ICACHE, plan.code):
            gf.set_handler(io, handler)
            gf.echo(io)
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    p = io.read(plan.param, 0xF0)
    _, actual, state, opened, readr, buf, ask, fobj, mode = struct.unpack_from('<9I', p)
    skipped, short = struct.unpack_from('<2I', p, 0xE8)
    if (buf, ask, fobj, mode) != (plan.buffer, plan.ask, plan.fobj, 1) or not opened:
        raise RuntimeError(f'chunk {index}: {STATUS.get(state, state)}; parameter block changed or open failed')
    if state == 6 or (state == 4 and skipped == index and index):
        return b''                      # file ends at or before this chunk
    if state != 2 or skipped != index or not 0 <= actual <= plan.ask:
        raise RuntimeError(f'chunk {index}: {STATUS.get(state, state)}, skipped {skipped}, actual {actual}')
    data = io.read(plan.buffer, actual) if actual else b''
    if len(data) != actual:
        raise RuntimeError('short MEMR download')
    return data


def download(remote, limit):
    path = gf.validate_request(remote, CHUNK)
    with gf.staging_lock():
        io = gf.Backend()
        version = io.sh('version', retries=0)
        if not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version):
            raise ValueError(f'expected firmware version 3.02, got {version!r}')
        publication = io.words(gf.PUBLICATION, 3)
        plan = gf.layout(io.caps(), publication, CHUNK, prefix=True)
        if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
            raise RuntimeError('echo is not stock; cannot borrow it')
        out = bytearray()
        for index in range(limit // CHUNK + 1):
            data = chunk(io, plan, path, index, publication)
            out += data
            print(f'chunk {index}: {len(data)} bytes', flush=True)
            if len(data) < CHUNK:
                return bytes(out)
        raise RuntimeError(f'file longer than --limit {limit}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('remote')
    parser.add_argument('local', type=Path)
    parser.add_argument('--limit', type=lambda s: int(s, 0), default=64 << 20)
    args = parser.parse_args(argv)
    if args.local.exists() or not args.local.parent.is_dir():
        parser.error('output must be a new file in an existing directory')
    data = download(args.remote, args.limit)
    with args.local.open('xb') as output:
        output.write(data)
    print(f'{args.local}: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
