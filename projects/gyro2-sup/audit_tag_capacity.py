#!/usr/bin/env python3
"""Pin bounded fp/fp L native tag-storage and serialization evidence (no device)."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import audit_observer as O

# Explicit paired routine/window addresses; masked comparison is only supporting
# correspondence evidence. Exact official image fingerprints remain mandatory.
WINDOWS = (
    ('source_descriptor', 0xC00BD340, 0xC00B9AE8, 0x34),
    ('value_copy', 0xC00BD460, 0xC00B9C08, 0x84),
    ('ifd_selection', 0xC00B9F58, 0xC00B6700, 0x258),
    ('insertion', 0xC00BEC58, 0xC00BB400, 0x160),
    ('vector_append', 0xC00BDD38, 0xC00BA4E0, 0x58),
    ('vector_growth', 0xC00BDE10, 0xC00BA5B8, 0xA4),
    ('sort_allocation', 0xC00BDEB8, 0xC00BA660, 0x68),
    ('ifd_size', 0xC00BE360, 0xC00BAB08, 0x118),
    ('ifd_serializer', 0xC00BE478, 0xC00BAC20, 0x434),
    ('allocation_wrapper', 0xC03D8BD0, 0xC03D8DE8, 0xB0),
    ('template_allocation', 0xC038A288, 0xC038A4A0, 0x68),
    ('template_allocation_caller', 0xC0378D5C, 0xC0378F74, 0x64),
    ('serialized_length_publication', 0xC0378E94, 0xC03790AC, 0x38),
    ('frame_header_dma_window', 0xC038C74C, 0xC038C964, 0x34),
)


def shape(code):
    words = struct.unpack('<%dI' % (len(code)//4), code)
    def mask(w):
        if w & 0x0E000000 == 0x0A000000:  # branch displacement
            return w & 0xFF000000
        if w & 0x0FF00000 in (0x03000000, 0x03400000):  # MOVW/MOVT literals
            return w & 0xFFF0F000
        return w
    return [mask(w) for w in words]


def audit(fp_image, fpl_image):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    # Reuse authoritative fingerprints and observer/callsite/vtable checks.
    base = O.audit(fp_image, fpl_image)
    data = [Path(p).read_bytes() for p in (fp_image, fpl_image)]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    rows = []
    for name, fp, fpl, size in WINDOWS:
        pieces = [d[a-O.BASE:a-O.BASE+size] for d, a in zip(data, (fp, fpl))]
        if shape(pieces[0]) != shape(pieces[1]):
            raise ValueError('native correspondence mismatch: '+name)
        row = {'name': name, 'bytes': size}
        for model, address, code in zip(('fp', 'fpl'), (fp, fpl), pieces):
            row[model] = dict(address=hex(address), sha256=hashlib.sha256(code).hexdigest(),
                             instructions=[f'{i.address:08x}: {i.mnemonic} {i.op_str}'
                                           for i in md.disasm(code, address)])
        rows.append(row)
    # No masked immediate is used as capacity evidence. Pin actual size arithmetic
    # and publication words independently, including 50-entry vector growth.
    for address, mnemonic, operand in (
        (0xC00BA5C4, 'add', 'r1, r1, #0x32'),
        (0xC00BA5C8, 'lsl', 'r0, r1, #2'),
        (0xC00BA530, 'str', 'r2, [r4, #0xc]'),
        (0xC00BB544, 'mov', 'r6, #1'),
        (0xC038A4E0, 'mov', 'r2, #0x40'),
        (0xC038A4F4, 'str', 'r2, [r4, #0x10]'),
        (0xC0378FB0, 'cmp', 'r8, #0'),
        (0xC0378FB8, 'mov', 'r2, #3'),
        (0xC03790E0, 'str', 'r3, [r2, #0xc]'),
    ):
        i = next(md.disasm(data[1][address-O.BASE:address-O.BASE+4], address))
        if (i.mnemonic, i.op_str) != (mnemonic, operand):
            raise ValueError('capacity operand mismatch at '+hex(address))
    return {'images': base['images'], 'windows': rows,
            'scope': 'native tag storage and generic MakerNote IFD; no camera capacity admission'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fp-image', type=Path, required=True)
    p.add_argument('--fpl-image', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(audit(a.fp_image, a.fpl_image), indent=2))
