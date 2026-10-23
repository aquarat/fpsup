#!/usr/bin/env python3
"""Offline fp L DATA provenance and bounded native packet transport tests."""
import argparse
import hashlib
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_PC

MAIN_SHA = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
DATA_SHA = "758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8"
CONTAINER_SHA = "598ae32684844b50afff3797444041b794fb352b810db30f227d73474367cea4"


def fingerprint(data, size, sha):
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("firmware fingerprint mismatch")


def unpack_data(container):
    """Declared-length LZSS prefix, retaining the source token count."""
    word = lambda off: struct.unpack_from("<I", container, off)[0]
    assert container[0x100:0x104] == b"@DFI"
    assert (word(0x138), word(0x140), word(0x14C)) == (238080, 0xC2F06A00, 120832)
    start = 0x300 + word(0x134)
    assert start == 0x1746500
    packed = container[start:start + word(0x14C)]
    assert sum(packed) & 0xFFFFFFFF == word(0x144)
    ring, cursor, out, pos = bytearray(4096), 4078, bytearray(), 0
    while len(out) < word(0x138):
        flags = packed[pos]
        pos += 1
        for bit in range(8):
            if flags & (1 << bit):
                values = [packed[pos]]
                pos += 1
                for value in values:
                    out.append(value)
                    ring[cursor] = value
                    cursor = (cursor + 1) & 4095
            else:
                a, b = packed[pos:pos + 2]
                pos += 2
                offset = a | ((b & 0xF0) << 4)
                for j in range((b & 15) + 3):
                    value = ring[(offset + j) & 4095]
                    out.append(value)
                    ring[cursor] = value
                    cursor = (cursor + 1) & 4095
            if len(out) >= word(0x138):
                break
    assert pos == 120527
    return bytes(out[:word(0x138)])


def machine(main, data, ready):
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for address, size in [(0xC0000000, 0x3000000), (0xC3400000, 0x100000),
                          (0x100000, 0x10000), (0x21C00000, 0x1000),
                          (0x30000000, 0x3000)]:
        u.mem_map(address, size)
    u.mem_write(0xC0000000, main)
    u.mem_write(0xC2F06A00, data)
    writes, polls = [], []

    def read(uc, access, address, size, value, user):
        if address == 0x21C00120:
            polls.append(address)
            uc.mem_write(address, struct.pack("<I", int(ready)))

    def write(uc, access, address, size, value, user):
        if 0x21C00100 <= address < 0x21C00200:
            writes.append((address, size, value))

    u.hook_add(UC_HOOK_MEM_READ, read)
    u.hook_add(UC_HOOK_MEM_WRITE, write)
    return u, writes, polls


def run(u, pc, r0=0, r1=0, stop=0x100000):
    u.reg_write(UC_ARM_REG_SP, 0x10F000)
    u.reg_write(UC_ARM_REG_LR, 0x100000)
    u.reg_write(UC_ARM_REG_R0, r0)
    u.reg_write(UC_ARM_REG_R1, r1)
    u.emu_start(pc, stop, count=200000)
    assert u.reg_read(UC_ARM_REG_PC) == stop, "instruction bound exhausted"
    return u.reg_read(UC_ARM_REG_R0)


def audit(main, data, container):
    fingerprint(main, 49310208, MAIN_SHA)
    fingerprint(data, 238080, DATA_SHA)
    fingerprint(container, 25714688, CONTAINER_SHA)
    assert unpack_data(container) == data
    assert struct.unpack_from("<II", data, 0xC2F2E71C - 0xC2F06A00) == (0xC0B90FF8, 85)
    assert struct.unpack_from("<II", main, 0xB98DE0) == (0xC0B98DE8, 85)
    # Native constructor + selector + first two native mode packets. Hardware
    # status is synthetic; this is packet construction, not sensor simulation.
    for mode, index, byte, mutate in [(0, 0, 0x40, False), (97, 2, 0x80, False),
                                      (97, 2, 0x55, True)]:
        u, writes, polls = machine(main, data, True)
        if mutate:
            # Change only mode 97's address-1 source word in emulator memory.
            u.mem_write(0xC0B996B0, struct.pack("<I", byte))
        run(u, 0xC0329F68, 0x101000)
        assert run(u, 0xC032C5F0, 0x101000, mode) == index
        assert run(u, 0xC032C5F0, 0x101000, 0xFFFFFFFF) == 0xFFFFFFFF
        run(u, 0xC032A108, 0x101000, mode, stop=0xC032A18C)
        payload = [(a, v) for a, size, v in writes if a in (0x21C00114, 0x21C00118)]
        assert payload == [(0x21C00114, 0x81), (0x21C00118, 4),
                           (0x21C00114, 0x10081), (0x21C00118, byte)]
        assert len(polls) == 2
    # Asymmetric bytes verify address order; held-low status verifies timeout.
    for ready in (True, False):
        u, writes, polls = machine(main, data, ready)
        u.mem_write(0x102000, bytes.fromhex("1234ab"))
        assert run(u, 0xC0122DF1, 0x102000) == 0
        assert (0x21C00114, 4, 0x341281) in writes
        assert (0x21C00118, 4, 0xAB) in writes
        assert len(polls) == (1 if ready else 10000)
    # Fingerprint negatives for each source, independently.
    for blob, sha in [(main, MAIN_SHA), (data, DATA_SHA), (container, CONTAINER_SHA)]:
        for bad in (blob[:-1], bytes([blob[0] ^ 1]) + blob[1:]):
            try:
                fingerprint(bad, len(blob), sha)
            except ValueError:
                pass
            else:
                raise AssertionError("changed source accepted")
    print("PASS: DATA re-extraction; 2 native mode prefixes + table-source mutation; unknown-mode rejection value; "
          "packet packing; ready/timeout paths; 6 fingerprint negatives")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--main", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--container", type=Path, required=True)
    args = p.parse_args()
    audit(args.main.read_bytes(), args.data.read_bytes(), args.container.read_bytes())
