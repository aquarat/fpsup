#!/usr/bin/env python3
"""Offline fp 5.02 -> fp L 3.02 native UI binding candidates.

Instruction-shape matching is a locator, not live acceptance. Fingerprint both
official images; retain disassembly and exact bytes for review. No device IO.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import capstone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'fp_usb_shell'))
from firmware import get_camera

BASE = 0xC0000000
BINDINGS = {
    'gui_get': (0xC055F0F0, False),
    'subscribe_int': (0xC0560FB0, False),
    'post_int': (0xC0593F30, False),
    'post_string': (0xC0593FE0, False),
    'registry_lookup': (0xC05DB418, True),
    'registry_register': (0xC05DB308, True),
    'app_registry': (0xC05D9EB0, True),
    'string_resolve': (0xC05E5B58, True),
    'string_owns': (0xC05E61C8, True),
    'string_remain': (0xC05E61E0, True),
    'file_resolve': (0xC05E5BEC, True),
    'register_pages': (0xC05E84D8, True),
}


def instructions(image, address, thumb, count=36):
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB if thumb else capstone.CS_MODE_ARM)
    return list(md.disasm(image[address-BASE:address-BASE+count*4], address))[:count]


def shape(ins):
    operand = ins.op_str
    if ins.mnemonic in ('movw', 'movt'):
        operand = re.sub(r'#(?:0x[0-9a-f]+|\d+)', '#ADDR', operand)
    operand = re.sub(r'#0xc[0-9a-f]{7}', '#ADDR', operand)
    return ins.mnemonic, operand


def locate(fp, fpl, address, thumb):
    reference = instructions(fp, address, thumb)
    needle = bytes(reference[0].bytes)
    start, end = max(0, address-BASE-0x40000), min(len(fpl), address-BASE+0x40000)
    matches = []
    while (at := fpl.find(needle, start, end)) >= 0:
        start = at+1
        if at % (2 if thumb else 4):
            continue
        candidate = instructions(fpl, BASE+at, thumb)
        score = sum(shape(a) == shape(b) for a, b in zip(reference, candidate))
        if score >= len(reference)*.8:
            matches.append(dict(address=f'0x{BASE+at:08x}', score=score,
                                instructions=len(reference), bytes=fpl[at:at+32].hex(),
                                disassembly=[f'{i.address:08x} {i.mnemonic} {i.op_str}' for i in candidate]))
    return sorted(matches, key=lambda m: m['score'], reverse=True)[:6]


def audit(fp, fpl):
    resources = {}
    for name, magic in [('nbr', b'NBR\0'), ('nbu', b'NBU\0'), ('nbm', b'NBM\0')]:
        a, b = fp.index(magic), fpl.index(magic)
        resources[name] = dict(fp=f'0x{BASE+a:08x}', fpl=f'0x{BASE+b:08x}')
    a, b = fp.index(b'NBU\0'), fpl.index(b'NBU\0')
    resources['pool_equal'] = fp[a+20:a+20+176152] == fpl[b+20:b+20+176152]
    return dict(fp_sha256=hashlib.sha256(fp).hexdigest(), fpl_sha256=hashlib.sha256(fpl).hexdigest(),
                evidence='offline candidates; review full callers and runtime structures before use',
                resources=resources, bindings={name:dict(fp=f'0x{addr:08x}', thumb=thumb,
                    candidates=locate(fp,fpl,addr,thumb)) for name,(addr,thumb) in BINDINGS.items()})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp', type=Path, required=True)
    p.add_argument('--fpl', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    result = audit(get_camera('fp-5.02').verify_main(args.fp),get_camera('fp-l-3.02').verify_main(args.fpl))
    with args.out.open('x') as f:
        json.dump(result,f,indent=2)
    print(json.dumps({k:[(m['address'],m['score']) for m in v['candidates']] for k,v in result['bindings'].items()},indent=2))
