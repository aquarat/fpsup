#!/usr/bin/env python3
"""fp L 3.02 compatible, fixed-size BIN-only card update.

Caller must review payload/loader compatibility: identical AutoRun bytes do not
establish ABI compatibility. Only root AutoRun.txt and fpSup.BIN are supported.
Import/help are offline. No reboot, RAM handoff, rollback or uncertain-write
retry is performed. A failure after upload begins requires manual inspection.
"""
import argparse
import os
from pathlib import Path

import fpl_getfile as gf
import fpl_putfile as pf

NAMES = ('AutoRun.txt', 'fpSup.BIN')


def read_card(directory):
    directory = Path(directory)
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != set(NAMES):
        raise ValueError('card directory must contain only AutoRun.txt and fpSup.BIN')
    result = {}
    for name in NAMES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'{path}: expected a regular file, not a symlink')
        result[name] = path.read_bytes()
        if not result[name]:
            raise ValueError(f'{path}: empty file')
        gf.validate_request('\\' + name, len(result[name]))
    return result


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def backup_card(directory, current):
    """Publish exclusive files and sync data and directory before any card write."""
    directory.mkdir(mode=0o700)
    for name in NAMES:
        with (directory / name).open('xb') as output:
            output.write(current[name])
            output.flush()
            os.fsync(output.fileno())
    sync_directory(directory)
    sync_directory(directory.parent)


def deploy(candidate_dir, previous_dir, backup_dir, io=None):
    """Return 'updated' or 'unchanged'; backup_dir must be a new directory."""
    candidate = read_card(candidate_dir)
    previous = read_card(previous_dir)
    if candidate['AutoRun.txt'] != previous['AutoRun.txt']:
        raise ValueError('AutoRun must be byte-identical for a BIN-only update')
    if len(candidate['fpSup.BIN']) != len(previous['fpSup.BIN']):
        raise ValueError('BIN length must be unchanged; truncation is unsupported')
    backup = Path(backup_dir)
    if backup.exists() or backup.is_symlink() or not backup.parent.is_dir():
        raise ValueError('backup must be a new directory in an existing parent')
    with gf.staging_lock():
        io = io or gf.Backend()
        # Each exact reader checks firmware, staging bounds and echo ownership.
        current = {}
        for name in NAMES:
            current[name] = gf._download_locked('\\' + name, len(previous[name]), io)
            if current[name] not in (previous[name], candidate[name]):
                raise RuntimeError(f'current {name} does not match previous or candidate')
        if current['fpSup.BIN'] == candidate['fpSup.BIN']:
            if gf._download_locked('\\AutoRun.txt', len(candidate['AutoRun.txt']), io) != current['AutoRun.txt']:
                raise RuntimeError('AutoRun changed during preflight')
            return 'unchanged'
        backup_card(backup, current)
        pf._upload_locked('\\fpSup.BIN', candidate['fpSup.BIN'],
                          len(candidate['fpSup.BIN']), io)
        if gf._download_locked('\\fpSup.BIN', len(candidate['fpSup.BIN']), io) != candidate['fpSup.BIN']:
            raise RuntimeError('second exact BIN download mismatch; inspect card before retry')
        if gf._download_locked('\\AutoRun.txt', len(candidate['AutoRun.txt']), io) != current['AutoRun.txt']:
            raise RuntimeError('AutoRun changed during deployment; inspect card before retry')
    return 'updated'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--previous', type=Path, required=True,
                        help='previous known card directory')
    parser.add_argument('--backup', type=Path, required=True,
                        help='new host backup directory (parent must exist)')
    args = parser.parse_args(argv)
    result = deploy(args.candidate, args.previous, args.backup)
    print(f'{result}: BIN-only operation complete; no reboot performed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
