#!/usr/bin/env python3
"""Reviewed fixed-size fp L RAM handoff. Import/help/check are offline.

No automatic retry/rearm. Reconcile clears a pending marker only after proven
completion: read-only payload inspection plus restored MEM1 window metadata.
Host locking does not exclude other hosts or camera-side writers.
Live-verified 2026-10-20: three same-image handoffs, a reviewed PONG upgrade,
and completed-marker reconciliation. Arbitrary images are not supported.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import secrets
import struct

from armasm import assemble, symbols
from firmware import get_camera
import fpl_getfile as gf

SHA = '48d3b2f4fec039c0c6141c61d4e496ea443e9685468f43366cbfd667271c8668'
PONG_SHA = 'e2b94aeb67938dbb05f581ca6f8ec5aff1e84dfe7dd34de11a1b76e0c7f2b342'
SIZE = 3572
EXPECT = dict(serve=120, next_round=200, no_swap=292, arm_out=3064)


def known_body():
    return reviewed_body(False)


def supported_hashes():
    return {SHA, PONG_SHA}


def reviewed_body(pong):
    source = gf.HERE / 'camera/worker.S'
    defines = get_camera('fp-l-3.02').loader_defines() + [f'FPSUP_PONG_ACK={int(pong)}']
    labels = symbols(source, defines)
    body = assemble(source, defines)[labels['wbody']:labels['wbody_end']]
    if (len(body) != SIZE or hashlib.sha256(body).hexdigest() != (PONG_SHA if pong else SHA) or
            any(labels[k] - labels['wbody'] != v for k, v in EXPECT.items()) or
            body[120:124] != struct.pack('<I', 0xE92D47F0)):
        raise ValueError('not the allowlisted worker body/symbol manifest')
    return body


def plan(publication, caps, cookie):
    gf.layout(caps, publication, 8192)
    pool, room, dest = publication
    if dest + SIZE > 0x80000000 or dest < pool + room and dest + SIZE > pool:
        raise ValueError('code overlaps pool or exceeds address bounds')
    return dict(POOL=pool, ROOM=room, DEST=dest, STUB=pool + 0x10000,
                STATUS=pool + 0x10400, SOURCE=pool + 0x10800,
                EXPECTED_SOURCE=pool + 0x11800, COOKIE=cookie)


def stub(p):
    code = assemble(gf.HERE / 'asm/fpl_swapworker.S',
                    [f'{k}={v}' for k, v in p.items()])
    if len(code) > 1024:
        raise ValueError('trampoline exceeds reservation')
    return code.ljust(1024, b'\0')


@contextmanager
def resident_window(io, dest):
    windows = io.caps()['windows']
    slot = next((i for i, w in enumerate(windows) if tuple(w) == (0, 0, 0)), None)
    if slot is None:
        raise RuntimeError('no unused MEM1 window')
    try:
        gf.transport.mem_window(slot, dest, SIZE, 1)
        if tuple(io.caps()['windows'][slot]) != (dest, SIZE, 1):
            raise RuntimeError('read-only window did not verify')
        yield
    finally:
        gf.transport.mem_window(slot, *windows[slot])
        if tuple(io.caps()['windows'][slot]) != tuple(windows[slot]):
            raise RuntimeError('window restoration did not verify')


def resident(io, dest):
    with resident_window(io, dest):
        return io.read(dest, SIZE)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_pending(record):
    path = gf.LOCK_PATH.with_suffix('.pending')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(record, f)
        f.flush()
        os.fsync(f.fileno())
    sync_directory(path.parent)
    return path


def handoff(io=None, pong=None):
    body = reviewed_body(bool(pong))
    with gf.staging_lock():
        io = io or gf.Backend()
        version = io.sh('version', retries=0)
        if 'w91c1' not in version or '3.02.0.V90' not in version or version.startswith('ERR'):
            raise ValueError('expected fp L 3.02')
        publication = io.words(gf.PUBLICATION, 3)
        caps = io.caps()
        if any(tuple(window) != (0, 0, 0) for window in caps['windows']):
            raise RuntimeError('active MEM1 windows; cannot reset another transfer owner')
        p = plan(publication, caps, secrets.randbits(32) or 1)
        if io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]:
            raise RuntimeError('echo not stock')
        initial_magic = io.words(p['POOL'] + 0x1080)
        if (len(initial_magic) != 1 or type(initial_magic[0]) is not int or
                initial_magic == [0x50415753]):
            raise RuntimeError('swap already armed')
        previous = resident(io, p['DEST'])
        if len(previous) != SIZE or hashlib.sha256(previous).hexdigest() not in supported_hashes():
            raise ValueError('unknown resident body')
        if pong is None:
            body = previous
        for address, data in ((p['STUB'], stub(p)), (p['STATUS'], bytes(1024)),
                              (p['SOURCE'], body.ljust(4096, b'\0')),
                              (p['EXPECTED_SOURCE'], previous.ljust(4096, b'\0'))):
            io.write(address, data)
            if io.read(address, len(data)) != data:
                raise RuntimeError('staging readback mismatch')
        try:
            for routine in (gf.DCACHE, gf.ICACHE):
                gf.set_handler(io, routine)
                gf.echo(io)
        finally:
            gf.set_handler(io, gf.ECHO_STOCK)
        if (io.words(gf.PUBLICATION, 3) != publication or
                io.words(p['POOL'] + 0x1080) != initial_magic):
            raise RuntimeError('publication/swap changed')
        marker = write_pending(dict(plan=p, publication=publication, sha256=hashlib.sha256(body).hexdigest()))
        answer = io.sh(f"mem set 0x{p['POOL'] + 0x10C0:08X} 0x{p['STUB']:08X}", retries=0)
        if answer.lstrip().startswith('ERR'):
            raise RuntimeError('swap address uncertain; pending retained')
        if io.words(p['POOL'] + 0x10C0) != [p['STUB']]:
            raise RuntimeError('swap address uncertain; pending retained')
        answer = io.sh(f"mem set 0x{p['POOL'] + 0x1080:08X} 0x50415753", retries=0)
        if answer.lstrip().startswith('ERR'):
            raise RuntimeError('swap magic uncertain; pending retained')
        caps = io.caps()
        if (not caps or (caps['pool'], caps['pool_size']) != tuple(publication[:2]) or
                io.words(p['STATUS']) != [p['COOKIE']] or
                io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK] or
                io.words(gf.PUBLICATION, 3) != publication or
                io.words(p['POOL'] + 0x1080) != [0] or
                resident(io, p['DEST']) != body):
            raise RuntimeError('completion unproven; pending retained')
        marker.unlink()
        sync_directory(marker.parent)
        return p


def parse_pending(raw):
    """Accept only a reviewed image record, before using any address.

    This schema deliberately has no caller-selected ranges or image manifest.
    Future schemas/images require an explicit reviewed allowlist extension.
    """
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate pending key')
            result[key] = value
        return result
    if len(raw) > 4096:
        raise ValueError('oversized pending record')
    record = json.loads(raw, object_pairs_hook=unique)
    allowed = globals().get('supported_hashes', lambda: {SHA})()
    if (type(record) is not dict or
            set(record) != {'plan', 'publication', 'sha256'} or
            type(record['sha256']) is not str or record['sha256'] not in allowed):
        raise ValueError('unknown pending schema or image')
    publication, p = record['publication'], record['plan']
    if (type(publication) is not list or len(publication) != 3 or
            any(type(v) is not int for v in publication) or
            type(p) is not dict or
            'COOKIE' not in p or
            any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in p.values()) or
            p['COOKIE'] == 0):
        raise ValueError('invalid pending plan')
    expected = plan(publication, dict(pool=publication[0], pool_size=publication[1],
                                      xfer=4096), p['COOKIE'])
    if p != expected:
        raise ValueError('pending addresses do not match known plan')
    return record


def reconcile_caps(caps, publication):
    """Require complete MCAPS, including the eight window descriptors."""
    gf.layout(caps, publication, 4096)
    if (type(caps.get('xfer')) is not int or
            type(caps.get('windows')) not in (list, tuple) or len(caps['windows']) != 8):
        raise ValueError('invalid MCAPS')
    for w in caps['windows']:
        if (type(w) not in (list, tuple) or len(w) != 3 or
                any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in w) or
                (tuple(w) != (0, 0, 0) and
                 (not w[1] or w[0] + w[1] > 0x100000000 or w[2] not in (1, 2, 3)))):
            raise ValueError('invalid MCAPS window')


def reconcile(io=None):
    """Read-only payload inspection plus temporary MEM1 window metadata.

    Never executes staged code, retries/rearms a swap, or writes payload/echo.
    Failure (including a stale boot or an aborted handoff) retains the marker.
    The publication and unpredictable completion cookie are the recorded boot
    evidence; there is no independent firmware boot-generation identifier.
    """
    with gf.staging_lock(permit_pending=True):
        marker = gf.LOCK_PATH.with_suffix('.pending')
        with marker.open('rb') as f:
            raw = f.read(4097)
        record = parse_pending(raw)
        p, publication = record['plan'], record['publication']
        io = io or gf.Backend()
        version = io.sh('version', retries=0)
        if (version.lstrip().startswith('ERR') or
                not re.search(r'\bmodel\s*=\s*w91c1\b', version) or
                not re.search(r'\brel version\s*=\s*3\.02\.0\.V90\b', version)):
            raise ValueError('expected fp L 3.02; pending retained')

        def observe():
            # Only fixed publication is read before validating current bounds.
            if io.words(gf.PUBLICATION, 3) != publication:
                raise RuntimeError('publication/boot changed; pending retained')
            caps = io.caps()
            reconcile_caps(caps, publication)
            if plan(publication, caps, p['COOKIE']) != p:
                raise ValueError('current plan changed; pending retained')
            if (io.words(p['STATUS']) != [p['COOKIE']] or
                    io.words(p['POOL'] + 0x1080) != [0] or
                    io.words(gf.ECHO_SLOT) != [gf.ECHO_STOCK]):
                raise RuntimeError('completion unproven; pending retained')
            return caps

        before = observe()
        data = resident(io, p['DEST'])
        if len(data) != SIZE or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise RuntimeError('resident image mismatch; pending retained')
        after = observe()
        if after != before:
            raise RuntimeError('MCAPS changed during inspection; pending retained')
        if marker.read_bytes() != raw:
            raise RuntimeError('pending record changed during inspection')
        marker.unlink()
        sync_directory(marker.parent)
        return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'handoff', 'upgrade-pong', 'reconcile'),
                        help='reconcile: read-only payload inspection; temporarily grants/restores MEM1 window metadata')
    args = parser.parse_args()
    if args.command == 'check':
        print(f'{len(known_body())} bytes SHA256 {SHA}')
        print(f'{len(reviewed_body(True))} bytes SHA256 {PONG_SHA}')
    elif args.command == 'reconcile':
        print(reconcile())
    else:
        print(handoff(pong=True if args.command == 'upgrade-pong' else None))


if __name__ == '__main__':
    main()
