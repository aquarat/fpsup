#!/usr/bin/env python3
"""Capture/download the fp L display, optionally after one menu-key pulse.

Uses the fp L transfer path and shared staging lock. Never records, half-presses
the shutter, retries a key, or overwrites a local capture. Inspect each image
before choosing the next navigation key.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import fpl_getfile as gf

KEYS = ('MENU', 'UP', 'DOWN', 'LEFT', 'RIGHT', 'OK')


def capture(out, key=None):
    out = Path(out)
    if out.exists() or out.with_suffix('.json').exists():
        raise ValueError('capture and provenance paths must be new')
    if key is not None and key not in KEYS:
        raise ValueError('one supported menu key required')
    report = dict(commands=[], key=key, status='started')
    out.parent.mkdir(parents=True, exist_ok=True)
    sidecar = out.with_suffix('.json')
    with sidecar.open('x') as f:
        json.dump(report, f, indent=2); f.write('\n')
    def save():
        sidecar.write_text(json.dumps(report, indent=2)+'\n')
    try:
        _capture(out, key, report, save)
        report['status'] = 'complete'
        return report
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save()


def _capture(out, key, report, save):
    with gf.staging_lock():
        io = gf.Backend()
        def command(text):
            entry = dict(command=text)
            report['commands'].append(entry)
            save()  # retain intent even if the transport raises
            try:
                reply = io.sh(text, retries=0)
            except BaseException as error:
                entry['error'] = f'{type(error).__name__}: {error}'
                save()
                raise
            entry['reply'] = reply
            save()
            if reply.lstrip().startswith('ERR'):
                raise RuntimeError(f'{text}: {reply.strip()}')
            return reply
        version = command('version')
        if 'w91c1' not in version or '3.02.0.V90' not in version:
            raise RuntimeError('fp L 3.02 required')
        if any(io.words(0xC358E9D8, 3)):
            raise RuntimeError('recorder must be idle')
        def listing():
            folders = re.findall(r'<DIR>\s+(\d{3}SIGMA)\s*$', command('dir \\DCIM'), re.M)
            if not folders: raise RuntimeError('no SIGMA screenshot directory')
            folder = max(folders)
            text = command('dir \\DCIM\\'+folder)
            return {'\\DCIM\\'+folder+'\\'+name: int(size)
                    for size, name in re.findall(r'\s(\d+)\s+(SS__\d+\.JPG)\s*$', text, re.M)}
        before = listing()
        if key:
            try:
                command('key '+key+'ON')
            finally:
                command('key '+key+'OFF')
            time.sleep(1)
        try:
            command('key CAPTUREON')
        finally:
            command('key CAPTUREOFF')
        time.sleep(3)
        after = listing()
        fresh = after.keys()-before.keys()
        if len(fresh) != 1: raise RuntimeError('capture did not produce exactly one new screenshot')
        remote = fresh.pop(); size = after[remote]
        data = gf._download_locked(remote, size, io)
        if not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise RuntimeError('download is not a complete JPEG')
    with out.open('xb') as f: f.write(data)
    report.update(remote=remote, bytes=size, sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--key', choices=KEYS)
    a = p.parse_args()
    r = capture(a.out, a.key)
    print(f'{a.out}: {r["bytes"]} bytes, SHA-256 {r["sha256"]}')
