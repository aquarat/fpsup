#!/usr/bin/env python3
"""Bounded offline mode packets and timing-MMIO comparison, fp L 3.02 only."""
import argparse
import json
from pathlib import Path
import struct

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1

import fpl_sensor_mode_audit as transport

MODES = (0, 129, 97, 130, 142)


def rows(main, base, stride):
    return {struct.unpack_from("<I", main, base + i * stride)[0]: i for i in range(85)}


def capture(main, data, mode, mutation=None):
    index = rows(main, 0xB98DE8, 1120)[mode]
    row = 0xC0B98DE8 + index * 1120
    u, writes, polls = transport.machine(main, data, True)
    if mutation:
        address, value = mutation
        u.mem_write(address, value)
    transport.run(u, 0xC0329F68, 0x101000)
    source, packets = [None], []

    def read(uc, access, address, size, value, user):
        if row <= address < row + 1120:
            source[0] = address - row

    def packet(uc, address, size, user):
        packets.append((uc.reg_read(UC_ARM_REG_R0), uc.reg_read(UC_ARM_REG_R1) & 255, source[0]))
        source[0] = None

    u.hook_add(UC_HOOK_MEM_READ, read)
    u.hook_add(UC_HOOK_CODE, packet, begin=0xC0326D88, end=0xC0326D88)
    transport.run(u, 0xC032A108, 0x101000, mode, stop=0xC032C4C8)
    assert len(packets) == len(polls) == 283
    assert [s for _, _, s in packets[:279]] == list(range(4, 1120, 4))
    assert all(s is None for _, _, s in packets[279:])
    # Independently decode transport MMIO rather than only observing call arguments.
    payload = [v for a, size, v in writes if a in (0x21C00114, 0x21C00118)]
    for i, (address, value, source) in enumerate(packets):
        assert payload[2*i:2*i+2] == [0x81 | ((address >> 8) << 8) | ((address & 255) << 16), value]
        if source is not None:
            expected = u.mem_read(row + source, 1)[0]
            if address == 2:
                # Native getter C032A0A0 uses the initialized DATA cache.
                expected |= struct.unpack_from("<I", data, 0xC2F2E878 - 0xC2F06A00)[0]
            assert value == expected
    return packets


def cadence(main, data, mode, mutation=None):
    index = rows(main, 0xB90FF8, 32)[mode]
    u, _, _ = transport.machine(main, data, True)
    u.mem_map(0x30100000, 0x1000)
    # Fresh zeroed MMIO bypasses the running-engine synchronization loop.
    obj = 0x102000
    u.mem_write(obj, struct.pack("<IIII", 0xC2F2E71C, mode, 0, index))
    if mutation:
        address, value = mutation
        u.mem_write(address, value)
    assert transport.run(u, 0xC0324858, obj) == 1
    return tuple(struct.unpack("<I", u.mem_read(a, 4))[0]
                 for a in (0x30100004, 0x30100020, 0x30100048))


def audit(main, data):
    transport.fingerprint(main, 49310208, transport.MAIN_SHA)
    transport.fingerprint(data, 238080, transport.DATA_SHA)
    outputs, summary = {}, {}
    ti, gi = rows(main, 0xB90FF8, 32), rows(main, 0xB91A98, 100)
    for mode in MODES:
        packets = capture(main, data, mode)
        outputs[mode] = packets
        a, b, c = struct.unpack_from("<HHH", main, 0xB90FF8 + 32*ti[mode] + 4)
        geometry = struct.unpack_from("<25I", main, 0xB91A98 + 100*gi[mode])
        mmio = cadence(main, data, mode)
        assert mmio == (((a-1) << 16) | (b-1), (c-1) << 16, 0x60000000)
        summary[mode] = dict(timing=[a, b, c], geometry_4_8_44=[geometry[1], geometry[2], geometry[17]],
                             mmio_30100004_20_48=[hex(x) for x in mmio], packets=len(packets))
    assert outputs[0] == outputs[129]
    assert outputs[97] == outputs[130] == outputs[142]
    diff = [(hex(a), hex(s), x, y) for (a, x, s), (b, y, t) in zip(outputs[0], outputs[97]) if x != y]
    assert len(diff) == 70
    # Packet-source sensitivity: a late mode-table field changes one exact packet.
    pi = rows(main, 0xB98DE8, 1120)[97]
    mutation = (0xC0B98DE8 + pi*1120 + 0x438, struct.pack("<I", 0x55))
    changed = capture(main, data, 97, mutation)
    assert [(x, y) for x, y in zip(outputs[97], changed) if x != y] == [
        ((0xA80, 0x62, 0x438), (0xA80, 0x55, 0x438))]
    # Timing metadata is consumed by hardware configuration, but not by bulk packets.
    mutation = (0xC0B90FF8 + ti[97]*32 + 4, struct.pack("<H", 625))
    assert capture(main, data, 97, mutation) == outputs[97]
    old = cadence(main, data, 97)
    assert cadence(main, data, 97, mutation) == (old[0] + 0x10000, old[1], old[2])
    for blob, sha in [(main, transport.MAIN_SHA), (data, transport.DATA_SHA)]:
        for bad in (blob[:-1], bytes([blob[0] ^ 1]) + blob[1:]):
            try:
                transport.fingerprint(bad, len(blob), sha)
            except ValueError:
                pass
            else:
                raise AssertionError("changed source accepted")
    print(json.dumps(summary, indent=2))
    print("PASS: five 283-packet native bodies; five timing-MMIO cases; two semantic mutations; four fingerprint negatives")
    print("mode 0 vs 97: differing packet count", len(diff))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    args = parser.parse_args()
    audit(args.main.read_bytes(), args.data.read_bytes())
