#!/usr/bin/env python3
"""Offline, exact-span packaged DATA versus archived descriptor provenance."""
import argparse
import json
from pathlib import Path
import struct

from fpl_recording_dispatch_table import decode, require, sha, verify_main
from fpl_sensor_mode_audit import unpack_data

BASE = 0xC2F06A00
SOURCES = {
    'main': (49310208, 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'),
    'data': (0x3A200, '758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8'),
    'container': (25714688, '598ae32684844b50afff3797444041b794fb352b810db30f227d73474367cea4'),
}
SPANS = {
    'start_stop': (0xC2F2F738, (0x23, 0, 0xFFFFFFFF, 0xC03ABAB8,
                              0x24, 0, 0xFFFFFFFF, 0xC03ABAF0)),
    'event2b': (0xC2F2F7B8, (0x2B, 0, 0xFFFFFFFF, 0xC03ABD20)),
    'result': (0xC2F2F808, (0x30, 0, 0xFFFFFFFF, 0xC03ABBD0)),
    'sleep': (0xC2F06B48, (1,)),
}
ARCHIVES = {
    'start_stop': ('dispatch-23-24-provenance.json', 'dispatch-23-24.bin', 95),
    'event2b': ('recording-event-descriptor.json', None, 89),
    'result': ('dispatch-30-provenance.json', 'dispatch-30.bin', 98),
    'sleep': ('thread-sleep-descriptor.json', None, 92),
}
VERSION = ('model       = w91c1 \nxc version  = V90 \nrel version = 3.02.0.V90  \n'
           'git hash    = 13aa621060efff11aaba9b21ad925005302605cf \n\n')


def fingerprint(name, blob):
    size, digest = SOURCES[name]
    require(len(blob) == size and sha(blob) == digest, name + ' fingerprint mismatch')


def packaged_slice(data, address, size, base=BASE):
    require(base == BASE, 'DATA load base mismatch')
    require((address, size) in {(a, len(w)*4) for a, w in SPANS.values()},
            'outside exact authorized spans')
    offset = address-base
    result = data[offset:offset+size]
    require(len(result) == size, 'short DATA slice')
    return result


def compare(name, packaged, record, binary=None):
    address, words = SPANS[name]
    expected = struct.pack('<' + 'I'*len(words), *words)
    require(packaged == expected, 'unexpected packaged words')
    require(record['address'] == address, 'archive address mismatch')
    require(record['version'] == VERSION, 'archive version mismatch')
    require(record['ping'] == f'OK pong seq={ARCHIVES[name][2]} proof=PONG', 'archive ping mismatch')
    require(tuple(int(w, 16) for w in record['word_hex']) == words, 'archive hex words mismatch')
    if 'words' in record:
        require(tuple(record['words']) == words, 'archive numeric words mismatch')
    if ARCHIVES[name][1]:
        require(record['bytes'] == len(expected), 'archive length mismatch')
        require(binary == expected, 'archive binary mismatch')
        captured = binary
    else:
        require('words' in record, 'missing archived numeric words')
        captured = struct.pack('<' + 'I'*len(record['words']), *record['words'])
    require(packaged == captured, 'packaged/runtime mismatch')
    return dict(address=hex(address), data_offset=hex(address-BASE), bytes=len(expected),
                words=[hex(w) for w in words], packaged_sha256=sha(packaged),
                archive_bytes_sha256=sha(captured), equal=True,
                archive_representation='binary' if binary is not None else 'JSON words reconstructed LE',
                decoded=decode(packaged, address) if name in ('start_stop', 'result') else None)


def self_test(blobs, data, records, binaries):
    negatives = []

    def reject(name, call):
        try:
            call()
        except ValueError as exc:
            negatives.append(dict(name=name, reason=str(exc)))
        else:
            raise ValueError('negative accepted: ' + name)

    for name, blob in blobs.items():
        reject(name + '_truncated', lambda: fingerprint(name, blob[:-1]))
        reject(name + '_mutated', lambda: fingerprint(name, bytes([blob[0] ^ 1])+blob[1:]))
    address = SPANS['start_stop'][0]
    reject('shifted_base', lambda: packaged_slice(data, address, 32, BASE+4))
    reject('shifted_offset', lambda: packaged_slice(data, address+4, 32))
    reject('neighbor_row', lambda: packaged_slice(data, address-16, 16))
    reject('widen_result', lambda: packaged_slice(data, SPANS['result'][0], 32))
    reject('bridge_gap', lambda: packaged_slice(data, address, 0xE0))
    packaged = packaged_slice(data, address, 32)
    reject('changed_packaged_row', lambda: compare('start_stop', bytes([packaged[0]^1])+packaged[1:],
                                                 records['start_stop'], binaries['start_stop']))
    changed = dict(records['start_stop'], address=address+16)
    reject('changed_archive_offset', lambda: compare('start_stop', packaged, changed, binaries['start_stop']))
    reject('changed_archive_bytes', lambda: compare('start_stop', packaged, records['start_stop'], bytes(32)))
    # The existing decoder stays deliberately narrower: do not widen its policy
    # to 2B merely because packaged bytes are available.
    reject('existing_decoder_still_rejects_2b', lambda: decode(
        packaged_slice(data, SPANS['event2b'][0], 16), SPANS['event2b'][0]))
    return negatives


def main():
    root = Path.home()/'.local/share/fpsup/firmware'
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path, default=root/'FPL_V302/MAIN.bin')
    p.add_argument('--data', type=Path, default=root/'FPL_V302/DATA.bin')
    p.add_argument('--container', type=Path, default=root/'FPL_V302.bin')
    p.add_argument('--archive', type=Path, default=Path.home()/'.local/share/fpsup/observations')
    p.add_argument('--self-test', action='store_true')
    args = p.parse_args()
    blobs = {name: getattr(args, name).read_bytes() for name in SOURCES}
    for name, blob in blobs.items():
        fingerprint(name, blob)
    verify_main(blobs['main'])
    # Fingerprinted container before calling the existing read-only extractor.
    extracted = unpack_data(blobs['container'])
    fingerprint('data', extracted)
    require(extracted == blobs['data'], 'independent extraction mismatch')
    records, binaries, rows = {}, {}, {}
    for name, (meta, binary, _) in ARCHIVES.items():
        metadata_bytes = (args.archive/meta).read_bytes()
        records[name] = json.loads(metadata_bytes)
        binaries[name] = (args.archive/binary).read_bytes() if binary else None
        address, words = SPANS[name]
        rows[name] = compare(name, packaged_slice(extracted, address, len(words)*4),
                             records[name], binaries[name])
        rows[name].update(archive_file=meta, metadata_sha256=sha(metadata_bytes),
                          archive_provenance=records[name])
    negatives = self_test(blobs, extracted, records, binaries) if args.self_test else []
    print(json.dumps(dict(hardware_accessed=False,
        sources={name: dict(bytes=len(blob), sha256=sha(blob)) for name, blob in blobs.items()},
        extraction=dict(load_base=hex(BASE), data_bytes=len(extracted),
                        packed_offset='0x1746500', packed_bytes=120832,
                        consumed_token_bytes=120527, independently_reextracted=True),
        regions=rows, negatives=negatives,
        summary=dict(matching_regions=len(rows), descriptor_rows=4, negative_tests=len(negatives)),
        limitations=['No whole-table bound established', 'No loader execution proved',
                     'No absence of runtime mutation or all-boot stability proved',
                     'Archive provenance is recorded evidence, not authenticated by matching bytes']), indent=2))


if __name__ == '__main__':
    main()
