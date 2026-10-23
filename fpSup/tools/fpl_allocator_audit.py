#!/usr/bin/env python3
"""Offline fp L 3.02 allocator/MMU evidence; never opens USB or a card.

Requires Unicorn (and Capstone only with --disassembly). Firmware stays private.
The allocator runs with a synthetic heap and stubbed telemetry, not live RAM.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_CPSR,
    UC_CPU_ARM_CORTEX_A15,
)

BASE = 0xC0000000
SHA256 = "fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9"
STOP = 0xC3FF0000
STACK = 0xC3FE0000
DESC = 0xC3FD0000
CHANNEL = 0xC3073A58
HEAP = 0x44400000
HEAP_SIZE = 0x10000
REGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
RANGES = {
    "mmu": (0xC000E7B0, 0x16C),
    "caches": (0xC000E91C, 0x1B4),
    "interrupt_guards": (0xC000EC14, 0x28),
    "heap_core": (0xC0010310, 0xA48),
    "channels_and_descriptors": (0xC001CCE0, 0xB20),
    "mode_layout": (0xC001E640, 0x20D8),
    "address_alias": (0xC0022FA8, 0x74),
    "file_wrappers": (0xC0366008, 0x378),
    "file_open_write": (0xC0368390, 0x548),
}


class Machine:
    def __init__(self, image):
        self.mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.mu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_A15)
        self.mu.mem_map(BASE, 0x4000000)
        self.mu.mem_write(BASE, image)
        self.mu.mem_map(0x44300000, 0x4000)
        self.mu.mem_map(HEAP, HEAP_SIZE)
        self.stubs = {}
        self.mu.hook_add(UC_HOOK_CODE, self.hook)

    def words(self, address, count=1):
        return struct.unpack("<" + "I" * count, self.mu.mem_read(address, 4 * count))

    def put(self, address, *words):
        self.mu.mem_write(address, struct.pack("<" + "I" * len(words), *words))

    def hook(self, mu, address, size, _):
        if address in (0xC0011100, 0xC0011130):
            raise AssertionError(f"firmware assertion at {address:08x}; LR={mu.reg_read(UC_ARM_REG_LR):08x}")
        if address in self.stubs:
            result = self.stubs[address]
            mu.reg_write(UC_ARM_REG_R0, result)
            mu.reg_write(UC_ARM_REG_PC, mu.reg_read(UC_ARM_REG_LR))

    def call(self, address, *args, stop=STOP):
        self.mu.reg_write(UC_ARM_REG_CPSR, 0x13)
        self.mu.reg_write(UC_ARM_REG_SP, STACK)
        self.mu.reg_write(UC_ARM_REG_LR, STOP)
        for reg, value in zip(REGS, args):
            self.mu.reg_write(reg, value)
        self.mu.emu_start(address, stop, count=1000000)
        assert self.mu.reg_read(UC_ARM_REG_PC) == stop, "instruction budget exhausted"
        return self.mu.reg_read(UC_ARM_REG_R0)


def audit(image):
    m = Machine(image)
    # C++ local-static guard acquisition/release only. The layout instructions,
    # lookup, size/base resolution and preservation callback execute unchanged.
    m.stubs.update({0xC0013090: 1, 0xC00131E4: 0})
    m.call(0xC001ED78)
    modes = []
    for mode in range(13):
        layout = m.call(0xC001EE58, 0xC3073D28, mode)
        entry = m.call(0xC001EDF8, layout, 0)
        values = m.words(entry, 5)
        start = m.call(0xC001EA30, layout, 0)
        size = m.call(0xC001E950, layout, 0, 0)
        keep = m.call(0xC001EAE8, layout, 0, 0)
        assert values == (0, 0x2000000, 0xC00206F8, 15, 0)
        assert (start, size, keep) == (HEAP, 0x2000100, 1)
        modes.append({"mode": mode, "base": hex(start), "region_bytes": size,
                      "class_0_entry": [hex(v) for v in values], "preserve": keep})

    # A small synthetic class-0 region with the stock two-sentinel setup.
    # No firmware allocator internals are stubbed. Telemetry is outside allocation.
    m.stubs.update({0xC001E328: 0, 0xC001E3C8: 0})
    m.put(0xC30739D8, CHANNEL)
    m.put(0xC3073A10, CHANNEL)  # populated final channel, MEM_HEAP prerequisite
    m.put(CHANNEL, 0, 0)
    m.call(0xC0010310, CHANNEL + 8)
    m.call(0xC00103A8, CHANNEL + 8, HEAP)
    for address in (HEAP, HEAP + HEAP_SIZE - 0x40):
        m.put(DESC + 0x100, address, 0x40)
        m.call(0xC00103E8, CHANNEL + 8, DESC + 0x100)
    initial = m.words(CHANNEL, 9)
    allocations = []
    for size, alignment in [(1, 0), (65, 0), (4096, 0), (4096, 256), (0x20000, 0)]:
        m.put(DESC, 0xAAAAAAAA, 0xBBBBBBBB, 0xCCCCCCCC, 0xDDDDDDDD)
        returned = m.call(0xC001D740, DESC, 0, size, alignment)
        descriptor = m.words(DESC, 4)
        address = m.call(0xC001D7F0, DESC)
        assert returned == DESC
        assert descriptor == (address, 0, address, size)
        if size > HEAP_SIZE:
            assert address == 0
        else:
            assert address and address % max(alignment, 64) == 0
            m.mu.mem_write(address, b"\x5a" * size)
        m.call(0xC001D7A0, DESC, 2)
        assert m.words(DESC, 4) == descriptor, "destructor unexpectedly clears descriptor"
        # +0x1c is the high-water byte count and deliberately survives free.
        final = m.words(CHANNEL, 9)
        assert final[:7] == initial[:7] and final[8:] == initial[8:], (initial, final)
        allocations.append({"size": size, "alignment_arg": alignment,
                            "address": hex(address), "descriptor": list(descriptor)})

    # Execute ONLY the table-writing portion of the real MMU initializer.
    # CP15 installation/cache operations are outside this interval, not emulated.
    m.put(0xC2F06B64, 0xFFFFFFFF)
    m.put(0xC2F06B60, 0xFFFFFFFF)
    m.call(0xC000E814, 0x44300000, stop=0xC000E8E0)
    mappings = []
    for va in (0x44400000, 0x463FFFFF, 0x46400000, 0xC4400000):
        entry = m.words(0x44300000 + (va >> 20) * 4)[0]
        assert entry & 0x40000  # supersection
        assert entry & 0x10 == 0  # XN clear
        assert entry & 3 == 2  # PXN clear, section descriptor
        assert (entry >> 10) & 3 == 3  # AP[1:0] full access
        mappings.append({"va": hex(va), "descriptor": hex(entry),
                         "xn": bool(entry & 0x10), "pxn": bool(entry & 1)})
    return {"main_sha256": hashlib.sha256(image).hexdigest(),
            "hardware_tested": False, "mode_layouts": modes,
            "synthetic_allocator_cases": allocations, "fallback_mmu": mappings,
            "stubs": [hex(v) for v in sorted(m.stubs)],
            "limitations": ["synthetic heap, no live allocator/channel state",
                            "no live CP15/MMU/cache execution or peripheral model",
                            "fallback MMU table only; runtime override not captured",
                            "no custom code execution on camera, no file I/O"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", required=True, type=Path)
    parser.add_argument("--disassembly", type=Path,
                        help="optional private addressed disassembly output")
    args = parser.parse_args()
    image = args.main.read_bytes()
    if hashlib.sha256(image).hexdigest() != SHA256:
        parser.error("not the audited official fp L 3.02 MAIN")
    if args.disassembly:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
        dis = Cs(CS_ARCH_ARM, CS_MODE_ARM)
        dis.skipdata = True
        with args.disassembly.open("x") as out:
            for name, (address, length) in RANGES.items():
                out.write(f"\n{name}: {address:08x}+{length:x}\n")
                for ins in dis.disasm(image[address-BASE:address-BASE+length], address):
                    out.write(f"{ins.address:08x} {ins.mnemonic:10} {ins.op_str}\n")
    print(json.dumps(audit(image), indent=2))


if __name__ == "__main__":
    main()
