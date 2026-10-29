"""Bounded static fp L 3.02 ETTR integration evidence; never executes firmware.

python -m fpSup.ettr.audit_firmware --main /path/to/MAIN.bin --self-test
Requires Capstone. Emits address/instruction evidence, not callable-API approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

BASE = 0xC0000000
SIZE = 49310208
SHA256 = 'fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9'
# name, command row, handler, setter, getter
BINDINGS = (
    ('SetExpMode', 0xC0BE13A8, 0xC03FAD18, 0xC00559D8, 0xC0055A10),
    ('SetShutterSpeed', 0xC0BE13CC, 0xC03FAE68, 0xC0055BA0, 0xC0055BE8),
    ('SetIso', 0xC0BE1444, 0xC03FB378, 0xC0056158, 0xC0056190),
    ('SetDriveMode', 0xC0BE14B0, 0xC03FB7B8, 0xC0056470, 0xC00564A8),
    ('SetIntervalRecHour', 0xC0BE14C8, 0xC03FB898, 0xC00565A0, 0xC00565D8),
    ('SetIntervalRecMin', 0xC0BE14D4, 0xC03FB908, 0xC0056638, 0xC0056670),
    ('SetIntervalRecSec', 0xC0BE14E0, 0xC03FB978, 0xC00566D0, 0xC0056708),
    ('SetIntervalRecNum', 0xC0BE14EC, 0xC03FB9E8, 0xC0056768, 0xC00567A0),
)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def fingerprint(data):
    require(len(data) == SIZE and hashlib.sha256(data).hexdigest() == SHA256,
            'not the audited official fp L 3.02 MAIN')


def audit(data):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)

    def listing(address, size):
        return [dict(address=hex(i.address), mnemonic=i.mnemonic, operands=i.op_str)
                for i in md.disasm(data[address-BASE:address-BASE+size], address)]

    def instruction(address, mnemonic, operands):
        rows = listing(address, 4)
        require(len(rows) == 1 and (rows[0]['mnemonic'], rows[0]['operands']) ==
                (mnemonic, operands), f'instruction mismatch at {address:08x}')

    def call(address, target):
        instruction(address, 'bl', '#'+hex(target))

    rows = []
    for name, table, handler, setter, getter in BINDINGS:
        string, help_string, actual_handler = struct.unpack_from('<3I', data, table-BASE)
        require(data[string-BASE:string-BASE+len(name)+1] == name.encode()+b'\0', name+' table string')
        require(actual_handler == handler, name+' table handler')
        shutter = name == 'SetShutterSpeed'
        call(handler+(0x4C if shutter else 0x2C), 0xC0055120)
        call(handler+(0x5C if shutter else 0x38), setter)
        call(handler+(0x84 if shutter else 0x58), getter)
        if shutter:
            instruction(handler+0x50, 'mov', 'r1, r4')
            instruction(handler+0x54, 'mov', 'r2, r5')
            instruction(handler+0x58, 'mov', 'r3, #1')
            instruction(handler+0x80, 'mov', 'r0, sp')
        else:
            instruction(handler+0x30, 'mov', 'r1, r7')
            instruction(handler+0x34, 'mov', 'r2, #1')
        rows.append(dict(name=name, table=hex(table), handler=hex(handler),
                         setter=hex(setter), getter=hex(getter),
                         instructions=listing(handler, 0xA8 if shutter else 0x70)))
    # RTTI-associated virtual slots, plus actual pixel sampling/count code.
    require(struct.unpack_from('<I', data, 0xC2E07CD8-BASE)[0] == 0xC059F270,
            'record histogram provider slot')
    call(0xC059F27C, 0xC0423E60)
    call(0xC059F280, 0xC0424040)
    instruction(0xC059F3F8, 'add', 'ip, r7, r3, lsl #2')
    instruction(0xC059F414, 'ldrb', 'fp, [ip, fp, lsl #2]')
    instruction(0xC059F430, 'str', 'lr, [r6, fp, lsl #2]')
    require(struct.unpack_from('<I', data, 0xC0BC38EC-BASE)[0] == 0xC0399B48,
            'interval timer observer slot')
    instruction(0xC0399BC8, 'mov', 'r2, #0x2e')
    instruction(0xC0399BD0, 'mov', 'r2, #0xa')
    call(0xC0399BD8, 0xC0388BA8)
    call(0xC0399BE0, 0xC03A9798)
    return dict(sha256=SHA256, evidence='static only; no emulation or camera calls',
                owner='0xc0055120', bindings=rows,
                display_histogram=listing(0xC059F378, 0xF0),
                interval_observer=listing(0xC0399B48, 0xD4))


def self_test(data):
    # Fingerprint failures and structural mutations tested separately, so a
    # hash rejection cannot masquerade as ABI/dataflow validation.
    failures = 0
    for offset in (0, len(data)-1):
        changed = bytearray(data)
        changed[offset] ^= 1
        try:
            fingerprint(changed)
        except ValueError:
            failures += 1
        else:
            raise AssertionError('fingerprint mutation survived')
    for address in (0xC0BE13B0, 0xC03FAEC4, 0xC03FB3AC, 0xC059F414, 0xC0399BD0):
        changed = bytearray(data)
        struct.pack_into('<I', changed, address-BASE, 0xE320F000)  # ARM NOP
        try:
            audit(changed)
        except ValueError:
            failures += 1
        else:
            raise AssertionError(f'structural mutation survived: {address:08x}')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', required=True, type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    data = args.main.read_bytes()
    fingerprint(data)
    result = audit(data)
    if args.self_test:
        result['negative_cases_rejected'] = self_test(data)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
