#!/usr/bin/env python3
"""Offline, bounded execution of fp L descriptor/timing arithmetic; no device IO."""
import argparse
import hashlib
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP

SHA = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
BASE = 0xC0000000
DESC = 0xC2F2E71C


def validate(data):
    if len(data) != 49310208 or hashlib.sha256(data).hexdigest() != SHA:
        raise ValueError("not the official fp L 3.02 MAIN")


def machine(data):
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, 0x3000000)
    u.mem_write(BASE, data)
    u.mem_map(0x100000, 0x10000)
    return u


def run(u, pc, r0=0, r1=0):
    u.reg_write(UC_ARM_REG_SP, 0x10F000)
    u.reg_write(UC_ARM_REG_LR, 0x100000)
    u.reg_write(UC_ARM_REG_R0, r0)
    u.reg_write(UC_ARM_REG_R1, r1)
    u.emu_start(pc, 0x100000, count=10000)
    # A count-limited stop must not be mistaken for a return.
    from unicorn.arm_const import UC_ARM_REG_PC
    assert u.reg_read(UC_ARM_REG_PC) == 0x100000
    return u.reg_read(UC_ARM_REG_R0)


def audit(data):
    validate(data)
    u = machine(data)
    run(u, 0xC0326E60)
    assert struct.unpack("<H", u.mem_read(DESC + 0x132, 2))[0] == 1024
    assert struct.unpack("<H", u.mem_read(DESC + 0x2E, 2))[0] == 1024
    assert struct.unpack("<I", u.mem_read(DESC + 0x74, 4))[0] == 72000
    # Synthetic descriptor/table: exercises real lookup, sentinel and arithmetic.
    obj, desc, rows = 0x101000, 0x102000, 0x103000
    u.mem_write(obj, struct.pack("<II", desc, 42))
    u.mem_write(desc, struct.pack("<II", rows, 1))
    u.mem_write(desc + 0x74, struct.pack("<I", 72000))
    cases = [(100, 100, 720), (65535, 65535, 100), (1, 1, 1)]
    for a, b, c in cases:
        u.mem_write(rows, struct.pack("<IHHH", 42, a, b, c) + bytes(22))
        expected = max(1, ((a * (c - 1) + b) * 1000) // 72000)
        for mode in (42, 0x77, 999):
            assert run(u, 0xC0325278, obj, mode) == expected
    # Semantic sensitivity: mutate only the in-emulator constant producer.
    # mov.w r0,#0x100 -> mov.w r0,#0x102; both copied halfwords must change.
    u = machine(data)
    u.mem_write(0xC0125110, bytes.fromhex("4ff48170"))
    run(u, 0xC0326E60)
    assert struct.unpack("<H", u.mem_read(DESC + 0x132, 2))[0] == 1032
    assert struct.unpack("<H", u.mem_read(DESC + 0x2E, 2))[0] == 1032
    # Fingerprint rejection is separate from the semantic mutation above.
    for candidate in (data[:-1], bytes([data[0] ^ 1]) + data[1:]):
        try:
            validate(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("changed image accepted")
    print("PASS: native initializer, 9 timing cases, producer mutation, 2 fingerprint negatives")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    audit(parser.parse_args().main.read_bytes())
