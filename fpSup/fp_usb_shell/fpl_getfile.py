#!/usr/bin/env python3
"""Exact-size fp L 3.02 card download. Import/help are offline.

Uses the worker's explicitly reserved file staging, not the fp cave. All host
users of fp L staging/echo must share ~/.cache/fpsup/fpl-staging.lock. This is
an advisory host lock, not exclusion against unrelated clients or camera input.
Live-verified on fp L 3.02 on 2026-10-20: AutoRun/BIN and three diagnostics
matched reader-backed copies; 42 further diagnostics downloaded. See
docs/FPL_USB_DIAG_2026-10-19.md. Downloads only; no card writes.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
from pathlib import Path
import re
import struct

from armasm import assemble
from firmware import get_camera
import putfile as transport

HERE = Path(__file__).resolve().parent
# Same borrowed stock slot/cache bootstrap as fpl_heap_probe.py.
PUBLICATION = 0xC37588BC
ECHO_SLOT, ECHO_STOCK = 0xC0BD2544, 0xC03D9BB8
DCACHE, ICACHE = 0xC000E91C, 0xC000EABC
STAGING_OFFSET, CODE_ROOM, PARAM_ROOM, FOBJ_ROOM = 0x10000, 0x400, 0x400, 0x400
SLACK = 0x1000
LOCK_PATH = Path.home() / '.cache/fpsup/fpl-staging.lock'


@contextmanager
def staging_lock(*, permit_pending=False):
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            if not permit_pending and LOCK_PATH.with_suffix('.pending').exists():
                raise RuntimeError('fp L handoff pending; inspect with fpl_swapworker.py reconcile before staging')
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def validate_request(remote, size):
    if type(size) is not int or not 0 <= size <= 0xFFFFFFFF - SLACK:
        raise ValueError('size must be a nonnegative 32-bit size with slack')
    if not remote.startswith('\\') or any(ord(c) < 32 for c in remote):
        raise ValueError('remote must be an absolute camera path without control characters')
    path = remote.encode('ascii') + b'\0'
    if len(path) > 0xE0 - 0x24:
        raise ValueError('path exceeds the shared getfile parameter ABI')
    return path


@dataclass(frozen=True)
class Layout:
    code: int
    param: int
    fobj: int
    buffer: int
    ask: int


def layout(caps, publication, size):
    if not caps or len(publication) != 3 or any(type(v) is not int for v in publication):
        raise ValueError('MEM1 and complete fp L publication required')
    pool, room, worker = publication
    if (caps.get('pool'), caps.get('pool_size')) != (pool, room):
        raise ValueError('MCAPS does not match fp L publication')
    if (not 0x44000000 <= pool < 0x80000000 or pool % 4 or
            not STAGING_OFFSET < room <= 0x4000000 or room % 1024 or
            pool + room > 0x80000000 or
            not 0x44000000 <= worker < 0x80000000 or worker % 4 or
            pool <= worker < pool + room or not 4 <= caps.get('xfer', 0) <= 0xFFFFFF):
        raise ValueError('invalid worker publication or MEM1 bounds')
    code = pool + STAGING_OFFSET
    param = code + CODE_ROOM
    fobj = param + PARAM_ROOM
    buf = fobj + FOBJ_ROOM
    if type(size) is not int or size < 0 or buf + size + SLACK > pool + room:
        raise ValueError('exact file size plus slack exceeds available staging')
    return Layout(code, param, fobj, buf, size + SLACK)


def parameters(plan, path):
    data = bytearray(PARAM_ROOM)
    struct.pack_into('<4I', data, 0x14, plan.buffer, plan.ask, plan.fobj, 1)
    data[0x24:0x24 + len(path)] = path
    return bytes(data)


class Backend:
    sh = staticmethod(transport.sh)
    words = staticmethod(transport.mem_get)
    set_word = staticmethod(transport.mem_set)

    def caps(self):
        return transport.mem_caps(refresh=True)

    def transfer(self, operation, address, count, data=None):
        # Check the daemon's complete byte count, not merely its OK prefix.
        memory = transport._shared(count)
        if data is not None:
            memory.buf[:count] = data
        reply = transport.mem_line(
            f'{operation} 0x{address:08X} {count} 1 /{memory.name.lstrip("/")}')
        parts = reply.split()
        expected = 'OKR' if operation == 'MEMR' else 'OKW'
        if len(parts) != 3 or parts[0] != expected or parts[1] != str(count):
            raise RuntimeError(f'{operation}: incomplete transfer: {reply!r}')
        return bytes(memory.buf[:count])

    def read(self, address, count):
        return self.transfer('MEMR', address, count) if count else b''

    def write(self, address, data):
        self.transfer('MEMW', address, len(data), data)


def set_handler(io, address):
    for _ in range(8):
        io.set_word(ECHO_SLOT, address)
        if io.words(ECHO_SLOT) == [address]:
            return
    raise RuntimeError(f'echo slot did not verify as 0x{address:08X}')


def echo(io):
    reply = io.sh('echo', retries=0, timeout_ms=10000)
    if reply.lstrip().startswith('ERR'):
        raise RuntimeError(f'echo outcome uncertain: {reply!r}')


def download(remote, size, io=None):
    with staging_lock():
        return _download_locked(remote, size, io)


def _download_locked(remote, size, io=None):
    """Internal: caller must hold staging_lock through all staging operations."""
    path = validate_request(remote, size)
    io = io or Backend()
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
            not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
            not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise ValueError(f'expected firmware version 3.02, got {version!r}')
    publication = io.words(PUBLICATION, 3)
    plan = layout(io.caps(), publication, size)
    if io.words(ECHO_SLOT) != [ECHO_STOCK]:
        raise RuntimeError('echo is not stock; cannot borrow it')
    code = assemble(HERE / 'asm/getfile.S',
                    get_camera('fp-l-3.02').loader_defines() + [f'P={plan.param:#x}'])
    if not code or len(code) > CODE_ROOM:
        raise ValueError('getfile code exceeds staging reservation')
    # Each write occupies a separate 1 KiB-sized reservation, including
    # the worker's rounded DMA write extent. Read every uploaded byte back.
    for address, data in ((plan.code, code.ljust(CODE_ROOM, b'\0')),
                          (plan.param, parameters(plan, path)),
                          (plan.fobj, bytes(FOBJ_ROOM))):
        io.write(address, data)
        if io.read(address, len(data)) != data:
            raise RuntimeError('staging readback mismatch')
    if io.words(PUBLICATION, 3) != publication or io.words(ECHO_SLOT) != [ECHO_STOCK]:
        raise RuntimeError('worker publication or echo owner changed during upload')
    try:
        # Never execute newly uploaded code to publish itself.
        for handler in (DCACHE, ICACHE, plan.code):
            set_handler(io, handler)
            echo(io)
    finally:
        set_handler(io, ECHO_STOCK)
    if io.words(PUBLICATION, 3) != publication:
        raise RuntimeError('worker publication changed during execution')
    status = io.read(plan.param, 0x24)
    if len(status) != 0x24:
        raise RuntimeError('short parameter readback')
    _, actual, state, opened, read, buf, ask, fobj, mode = struct.unpack('<9I', status)
    if (state != 2 or not opened or not read or
            (buf, ask, fobj, mode) != (plan.buffer, plan.ask, plan.fobj, 1)):
        raise RuntimeError('file read failed or parameter block changed')
    if actual != size:
        raise RuntimeError(f'file length {actual}, expected {size}; refusing a prefix')
    data = io.read(plan.buffer, size)
    if len(data) != size:
        raise RuntimeError('short MEMR download')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('remote', help=r'absolute card path, e.g. \AutoRun.txt')
    parser.add_argument('local', type=Path, help='local output file (must not exist)')
    parser.add_argument('--size', type=lambda s: int(s, 0), required=True,
                        help='known exact file size; larger/shorter reads are rejected')
    args = parser.parse_args(argv)
    validate_request(args.remote, args.size)
    if args.local.exists() or not args.local.parent.is_dir():
        parser.error('output must be a new file in an existing directory')
    data = download(args.remote, args.size)
    with args.local.open('xb') as output:
        output.write(data)
    print(f'{args.local}: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
