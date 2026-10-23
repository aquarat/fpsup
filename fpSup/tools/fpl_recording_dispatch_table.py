#!/usr/bin/env python3
"""Offline decoder for producer-justified fp L descriptor rows, never a RAM reader."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from fpl_gyro_audit import BASE, fingerprint

TABLE = 0xC2F2F508
ALLOWED = {0x23, 0x24, 0x30}
THUNKS = {0xC03ABAB8: ('start_candidate', 0x74),
          0xC03ABAF0: ('stop_candidate', 0x78),
          0xC03ABBD0: ('result_candidate', 0x98)}
CODE = {
    0xC0389BB8: (0x78, 'cdad2d54cd03ffb8889aefc7eed4f4bf91442f5b24bb90ed9174f7567e5fa55f'),
    0xC038AEC0: (0xB0, '0933dec7349278a016fecbda85f60993acdf99aab7b3027c2bd77b92ef7a6abe'),
    0xC03ABAB8: (0x38, '73293a688e0fcb3a276ff478a2f75247208ead3d21d9ea1b847504a68c0d8086'),
    0xC03ABAF0: (0x38, '6aaca84fcb58dd3e59dd863307197c2a52ba64c0ed0d2efeb7128b645509d954'),
    0xC03ABBD0: (0x38, '89218e24e57145d1fe1fae4119179e94939f5f6d3395c563dc9d99cca18fa983'),
    0xC03A20D0: (0x60, '8c602b91dd5b553e958a5df1fd7fb4352f8046db40213b6d8ef44a03d49b0090'),
    0xC03A2130: (0x60, 'f4ac56cbcd1ce3aef1f1654717a847dcc3f4953c973f1de24b9f0c74490a5317'),
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify_main(data):
    fingerprint(data, 'fpl')
    for address, (size, digest) in CODE.items():
        require(sha(data[address-BASE:address-BASE+size]) == digest, 'stock code mismatch')
    require(struct.unpack_from('<5I', data, 0x723AB4) ==
            (0xC0000000, 0x400, 3, 1, 0x400000), 'fallback MMU record')
    return dict(bytes=len(data), sha256=sha(data), stock_code_verified=True)


def decode(data, address):
    """Policy bound is three known producer indices, not an inferred table size.

    Call verify_main before using this result as an official-MAIN audit.
    No dereference of captured pointers, and no reliance on word zero.
    """
    require(type(address) is int, 'address must be integer')
    require(len(data) in (16, 32), 'capture must contain exactly 16 or 32 bytes')
    require(address >= TABLE and (address-TABLE) % 16 == 0, 'unaligned/outside address')
    first = (address-TABLE)//16
    ids = range(first, first+len(data)//16)
    require(set(ids) <= ALLOWED, 'capture exceeds producer-justified rows 23/24/30')
    rows = []
    for index, event_id in enumerate(ids):
        label, adjust, selector, operand = struct.unpack_from('<4I', data, index*16)
        signed = selector if selector < 0x80000000 else selector-0x100000000
        row = dict(address=hex(TABLE+16*event_id), event_id_from_index=hex(event_id),
                   words=[hex(w) for w in (label, adjust, selector, operand)],
                   word0_ignored_by_dispatcher=hex(label),
                   this_adjustment_u32=hex(adjust), selector_signed=signed,
                   exact_known_thunk=None)
        if signed == 0:
            row.update(kind='disabled', local_default_result='0x13')
        elif signed < 0:
            row.update(kind='direct', target=hex(operand))
            if operand in THUNKS:
                name, slot = THUNKS[operand]
                row['exact_known_thunk'] = dict(name=name, state_vtable_slot=hex(slot),
                    unadjusted_state_object=adjust == 0)
            else:
                row['qualification'] = 'not one of the three exact audited ARM entrypoints'
        else:
            row.update(kind='virtual', object_vptr_offset=hex(operand),
                       table_word_index=selector,
                       qualification='requires adjusted live object/vtable; not resolved from MAIN')
        rows.append(row)
    return dict(capture_sha256=sha(data), capture_bytes=len(data), address=hex(address),
                table_count_proven=False, rows=rows,
                qualification='capture origin/version/order supplied by operator, not authenticated by bytes')


def producer_test(main, entry, expected):
    """Execute complete stock producer to its queue-submission boundary."""
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(BASE, (len(main)+4095)&~4095, UC_PROT_READ | UC_PROT_EXEC)
    u.mem_write(BASE, main)
    ram = 0x10000000
    u.mem_map(ram, 0x10000)
    u.mem_write(ram+0xC, struct.pack('<I', 42))
    u.mem_write(ram+0x2C, b'\1')
    u.reg_write(UC_ARM_REG_R1, ram)
    u.reg_write(UC_ARM_REG_SP, ram+0xF000)
    captured = []

    def hook(uc, pc, size, _):
        if pc == 0xC03A9770:
            event = bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 0x168))
            require(struct.unpack_from('<I', event, 4)[0] == expected, 'producer ID')
            require(struct.unpack_from('<I', event, 0xC)[0] == 1, 'producer subtype')
            require(struct.unpack_from('<I', event, 0xF4)[0] == 42, 'producer token')
            require(event[0x164] == 1, 'producer stop/control byte')
            captured.append(expected)
            uc.emu_stop()
        elif pc in (0xC0015058, 0xC0388BA8):
            # The event scratch RAM starts zero; memset's exact extent is verified.
            if pc == 0xC0015058:
                from unicorn.arm_const import UC_ARM_REG_R2
                require(uc.reg_read(UC_ARM_REG_R2) == 0x168 and
                        uc.reg_read(UC_ARM_REG_R1) == 0, 'producer memset ABI')
                uc.mem_write(uc.reg_read(UC_ARM_REG_R0), bytes(0x168))
            uc.reg_write(UC_ARM_REG_R0, ram+0x1000)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
        else:
            require(entry <= pc < entry+0x60, f'unmodelled producer edge {pc:x}')

    u.hook_add(UC_HOOK_CODE, hook)
    u.emu_start(entry, BASE+len(main), count=200)
    require(captured == [expected], 'producer did not reach submit')


def self_test(main):
    pack = lambda *words: struct.pack('<4I', *words)
    address = TABLE+0x230
    # Explicitly synthetic rows: never represented as captured camera evidence.
    start = pack(0xDEADBEEF, 0, 0xFFFFFFFF, 0xC03ABAB8)
    stop = pack(0, 0, 0x80000000, 0xC03ABAF0)
    rows = decode(start+stop, address)['rows']
    require(rows[0]['event_id_from_index'] == '0x23', 'word0 must not determine ID')
    require(rows[1]['exact_known_thunk']['state_vtable_slot'] == '0x78', 'signed selector')
    require(decode(pack(0, 0, 0, 0xC03ABBD0), address)['rows'][0]['kind'] == 'disabled', 'zero selector')
    require(decode(pack(0, 0, 1, 0x10), address)['rows'][0]['kind'] == 'virtual', 'virtual selector')
    require(decode(pack(0, 4, 0xFFFFFFFF, 0xC03ABBD0), address)['rows'][0]
            ['exact_known_thunk']['unadjusted_state_object'] is False, 'this adjustment')
    require(decode(pack(0, 0, 0xFFFFFFFF, 0xC03ABAB9), address)['rows'][0]
            ['exact_known_thunk'] is None, 'Thumb/interior pointer must not match')
    result = decode(pack(99, 0, 0xFFFFFFFF, 0xC03ABBD0), TABLE+0x300)['rows'][0]
    require(result['event_id_from_index'] == '0x30' and
            result['exact_known_thunk']['state_vtable_slot'] == '0x98', 'result candidate row')
    negatives = 0
    for blob, addr in [(b'', address), (start[:-1], address), (start+b'\0', address),
                       (start*3, address), (start, address+1), (start, TABLE+0x220),
                       (start*2, address+16), (start, TABLE-16), (start, 2**32+address),
                       (start*2, TABLE+0x300), (start*2, TABLE+0x2F0)]:
        try:
            decode(blob, addr)
        except ValueError:
            negatives += 1
        else:
            raise ValueError('malformed/out-of-policy capture accepted')
    damaged = bytearray(main)
    damaged[0x38AEEC] ^= 1
    try:
        verify_main(damaged)
    except ValueError:
        negatives += 1
    else:
        raise ValueError('modified official MAIN accepted')
    for entry, event_id in ((0xC03A20D0, 0x23), (0xC03A2130, 0x24)):
        producer_test(main, entry, event_id)
    from fpl_allocator_audit import Machine
    mmu = Machine(main)
    mmu.put(0xC2F06B60, 0xFFFFFFFF)
    mmu.put(0xC2F06B64, 0xFFFFFFFF)
    mmu.call(0xC000E814, 0x44300000, stop=0xC000E8E0)
    descriptor = mmu.words(0x44300000+(address >> 20)*4)[0]
    require(descriptor == 0x42045C06, 'fallback candidate mapping')
    return dict(decoder_semantic_checks=7, rejected_inputs=negatives, arm_producers=2,
                fixtures='synthetic only', fallback_mmu_descriptor=hex(descriptor),
                fallback_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--main', type=Path, default=Path.home()/
        '.local/share/fpsup/firmware/FPL_V302/MAIN.bin')
    parser.add_argument('--capture', type=Path, help='raw little-endian host file, 16 or 32 bytes')
    parser.add_argument('--address', type=lambda s: int(s, 0), help='actual capture start address')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    require((args.capture is None) == (args.address is None), 'supply capture and address together')
    image = args.main.read_bytes()
    report = dict(official_main=verify_main(image), hardware_accessed=False,
                  read_proposal=dict(address='0xc2f2f738', max_bytes=32,
                                     indices=['0x23', '0x24'], table_count_proven=False),
                  result_read_proposal=dict(address='0xc2f2f808', max_bytes=16,
                                            index='0x30', producer_audit='fpl_mov_result_audit.py'))
    if args.capture:
        with args.capture.open('rb') as stream:
            capture = stream.read(33)  # oversized inputs rejected without unbounded reads
        report['capture'] = decode(capture, args.address)
    if args.self_test:
        report['self_test'] = self_test(image)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
