#!/usr/bin/env python3
"""fp L 3.02 upload with exact whole-file readback.

Live-verified 2026-10-20: a new 65,554-byte file matched both immediate whole-file
readback and an independent subsequent download. See docs/FPL_USB_DIAG_2026-10-19.md.

Mode 7 does not truncate: an existing longer file is rejected at readback,
after its prefix has been overwritten. Use a new unique test path. No delete,
truncate, reboot or retry of uncertain file writes is performed.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct

from armasm import assemble
from firmware import get_camera
import fpl_getfile as gf


def parameters(plan, path, size):
    data = bytearray(gf.PARAM_ROOM)
    struct.pack_into('<4I', data, 0x14, plan.buffer, size, plan.fobj, 7)
    data[0x24:0x24 + len(path)] = path
    return bytes(data)


def upload(remote, data, size, io=None):
    """Write then verify; size must exactly match the supplied immutable bytes."""
    _validate_upload(remote, data, size)
    with gf.staging_lock():
        return _upload_locked(remote, data, size, io)


def _validate_upload(remote, data, size):
    path = gf.validate_request(remote, size)
    if not isinstance(data, bytes) or len(data) != size:
        raise ValueError('data must be bytes matching the supplied exact size')
    if remote.endswith('\\') or any(p in ('.', '..', '') for p in remote[1:].split('\\')):
        raise ValueError('remote must name a file without empty or dot components')
    return path


def _upload_locked(remote, data, size, io=None):
    """Internal: caller must hold gf.staging_lock for write and verification."""
    path = _validate_upload(remote, data, size)
    io = io or gf.Backend()
    version = io.sh('version', retries=0)
    if (version.lstrip().startswith('ERR') or
            not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
            not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
        raise ValueError(f'expected firmware version 3.02, got {version!r}')
    publication = io.words(gf.PUBLICATION, 3)
    plan = gf.layout(io.caps(), publication, size)
    if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('echo is not stock; cannot borrow it')
    code = assemble(gf.HERE / 'asm/putfile.S',
                    get_camera('fp-l-3.02').loader_defines() + [f'P={plan.param:#x}'])
    if not code or len(code) > gf.CODE_ROOM:
        raise ValueError('putfile code exceeds staging reservation')
    # Explicitly cover MEMW's 1 KiB rounded extent; layout reserves slack.
    payload = data.ljust((size + 1023) & ~1023, b'\0')
    for address, blob in ((plan.code, code.ljust(gf.CODE_ROOM, b'\0')),
                          (plan.param, parameters(plan, path, size)),
                          (plan.fobj, bytes(gf.FOBJ_ROOM)),
                          (plan.buffer, payload)):
        if blob:
            io.write(address, blob)
            if io.read(address, len(blob)) != blob:
                raise RuntimeError('staging readback mismatch')
    if io.words(gf.PUBLICATION, 3) != publication or io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
        raise RuntimeError('worker publication or echo owner changed during upload')
    try:
        for handler in (gf.DCACHE, gf.ICACHE, plan.code):
            gf.set_handler(io, handler)
            gf.echo(io)
    finally:
        gf.set_handler(io, gf.ECHO_STOCK)
    if io.words(gf.PUBLICATION, 3) != publication:
        raise RuntimeError('worker publication changed during execution')
    status = io.read(plan.param, 0x24)
    if len(status) != 0x24:
        raise RuntimeError('short parameter readback')
    _, _, state, opened, written, buf, count, fobj, mode = struct.unpack('<9I', status)
    if (state != 2 or not opened or not written or
            (buf, count, fobj, mode) != (plan.buffer, size, plan.fobj, 7)):
        raise RuntimeError('file write failed or parameter block changed')
    # The reader asks for size+slack: longer files cannot pass as prefixes.
    # Keep the same host lock; public download() would deadlock/reject it.
    result = gf._download_locked(remote, size, io)
    if result != data:
        raise RuntimeError('remote whole-file readback mismatch')
    return hashlib.sha256(result).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('local', type=Path)
    parser.add_argument('remote', help=r'explicit new unique path, e.g. \UP20261020A.BIN')
    parser.add_argument('--size', type=lambda s: int(s, 0), required=True,
                        help='exact local byte count, checked before camera access')
    args = parser.parse_args(argv)
    data = args.local.read_bytes()
    digest = upload(args.remote, data, args.size)
    print(f'{args.remote}: {len(data)} bytes verified, SHA-256 {digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
