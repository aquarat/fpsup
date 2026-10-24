#!/usr/bin/env python3
"""Exact fp L MAIN+DATA evidence for one formatter virtual edge and size ledger.

No complete mode-selected object graph or RAW boundary is claimed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import audit_observer as O

DATA_BASE = 0xC2F06A00
DATA_SIZE = 238080
DATA_HASH = '758daa9204c91763eb1298eea515b5bae97c2798e8ca9416329383e41a0790a8'
POOL_WORD, POOL = 0xC2F3F90C, 0xC3824BF4
BASE_VTABLE, SELECTED_VTABLE = 0xC2E48BA8, 0xC2E4A65C
SIZE_FN, TABLE_INIT = 0xC0696CE8, 0xC06986F8
LIVE_CONTEXT_SIZE = 0x5E4
LIVE_CONTEXT_HASH = '18a6c33800357a14e71cfd5d16e0ab3c052a000b5d509f868a59b01b21d2cd25'
LIVE_TAKE_HASH = 'e48e8c0473f98b1dab39c3cc30a33bd2266d2e16b1010d7b3ba31635da8b4ff7'
DNG_PREFIX_HASH = '23e847a480b9c10336dfb397b467410762c66d94f28fac12c4a30a44c972501d'


def load_dng_prefix(path):
    data = Path(path).read_bytes()
    if len(data) != 0x20000 or hashlib.sha256(data).hexdigest() != DNG_PREFIX_HASH:
        raise ValueError('fp L DNG prefix fingerprint mismatch')
    return data


def load_live_take(path):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != LIVE_TAKE_HASH:
        raise ValueError('live fp L take fingerprint mismatch')
    return json.loads(data)


def validate_live_context(data):
    """Pin the owner's 2026-10-23 read-only capture; no embedded RAM fixture."""
    if len(data) != LIVE_CONTEXT_SIZE or hashlib.sha256(data).hexdigest() != LIVE_CONTEXT_HASH:
        raise ValueError('live fp L context fingerprint mismatch')
    return data


WINDOWS = (
    ('late_root_population', 0xC06A2F18, 0x3A0),
    ('late_private_ifd_population', 0xC06A3750, 0x118),
    ('late_makernote_0200_population', 0xC06A32B8, 0x98),
    ('excluded_alternate_subifd_population', 0xC06A3350, 0x400),
    ('failure_callback_registration', 0xC0377410, 0x60),
    ('failure_event_construction', 0xC0385978, 0x120),
    ('failure_event_enqueue', 0xC03A9798, 0x110),
    ('failure_callback_registration_callers', 0xC03818F0, 0x30),
    ('failure_after_buffer_processing', 0xC037E694, 0x30),
    ('native_find_tag', 0xC00BAA10, 0x60),
    ('native_remove_tag', 0xC00BAA98, 0x70),
    ('native_vector_erase', 0xC00BA538, 0x80),
    ('remove_caller_one', 0xC00C5370, 0x20),
    ('remove_caller_two', 0xC00C55F8, 0x1C),
    ('builder_destructor_not_cancel', 0xC00B54A8, 0x58),
    ('writer_result_publication_no_error_test', 0xC03790AC, 0x38),
    ('cdng_state_getter', 0xC038B3D0, 0x50),
    ('cdng_state_constructor', 0xC038B470, 0x50),
    ('cdng_state_registration', 0xC0388B28, 0xC),
    ('cdng_state_method_candidate', 0xC038B620, 0x58),
    ('test_tag_native_attach', 0xC00CF208, 0xB0),
    ('test_tag_native_dispatch_no_veto', 0xC0053618, 0x68),
    ('test_tag_build_notify_continuation', 0xC0052FE8, 0x40),
    ('test_tag_take_pool_handoff', 0xC038A350, 0x38),
    ('test_tag_late_metadata_population', 0xC06A2858, 0x78),
    ('test_tag_writer_before_size', 0xC06A29E0, 0x18),
    ('test_tag_writer_serializer_call', 0xC06A2C7C, 0x2C),
    ('dng_builder_constructor', 0xC00B5468, 0x40),
    ('dng_builder_size_serializer', 0xC00B6510, 0x1F0),
    ('sigma_makernote_constructor', 0xC00BD0B0, 0x70),
    ('sigma_makernote_size_serializer', 0xC00BD428, 0xD0),
    ('writer_header_round_publish', 0xC06A29F8, 0x40),
    ('writer_round_zero_padding', 0xC0697018, 0x40),
    ('writer_strip_offset', 0xC06A2AD0, 0x34),
    ('writer_used_sum', 0xC0720758, 0x44),
    ('mode_factory_prefix', 0xC06A2618, 0xC4),
    ('mode_factory_composite', 0xC06A2768, 0x74),
    ('mode_branch_left', 0xC06A2490, 0x130),
    ('mode_branch_right', 0xC06A25C0, 0x58),
    ('base_composite_constructor', 0xC0696BB8, 0x34),
    ('base_leaf_constructor', 0xC0696E10, 0x48),
    ('ledger_factory', 0xC06976F0, 0x80),
    ('ledger_allocator', 0xC06987B8, 0x78),
    ('ledger_initializer', TABLE_INIT, 0x44),
    ('size_virtual', SIZE_FN, 0x38),
    ('leaf_reserved_size', 0xC0696EB8, 0x20),
    ('five_row_reserved_sum', 0xC06979F8, 0x40),
    ('four_row_body_sum', 0xC0697978, 0x40),
    ('dng_reserve_initializer', 0xC0720C28, 0xA4),
    ('aligned_body_size_setter', 0xC06970E0, 0x30),
    ('reserved_row_setter', 0xC0697178, 0x28),
    ('used_row_setter', 0xC06971A0, 0x68),
    ('allocation_and_prepare_caller', 0xC0378F74, 0x64),
    ('serialized_length_caller', 0xC03790AC, 0x38),
    ('raw_destination_dma_caller', 0xC038C964, 0x34),
    ('context_snapshot_constructor', 0xC0203A70, 0x48),
    ('context_snapshot_getter', 0xC0203D60, 0x10),
    ('runtime_context_pointer', 0xC0021B60, 0x10),
    ('runtime_context_singleton', 0xC0021B20, 0x40),
    ('runtime_context_initializer', 0xC0021A60, 0x7C),
    ('context_defaults', 0xC0022920, 0x288),
    ('composite_prepare', 0xC0696DB0, 0x60),
    ('base_leaf_prepare', 0xC06973C8, 0x18),
    ('selected_leaf_prepare', 0xC0720418, 0x40),
    ('jpeg_leaf_serialized_length', 0xC06A1D58, 0x488),
    ('tiff_leaf_serialized_length', 0xC06A28D0, 0x3D8),
    ('pointer_add_subtract', 0xC0010C98, 0x40),
    ('template_release', 0xC038A508, 0x28),
    ('template_pointer_getter', 0xC038A530, 0x10),
    ('early_release_condition', 0xC037918C, 0x54),
    ('operation_cleanup', 0xC03971F8, 0x54),
    ('raw_pointer_from_base_and_offset', 0xC0381E34, 0x24),
    ('alternate_raw_pointer', 0xC037EAA0, 0x20),
    ('recording_registry_singleton', 0xC0374438, 0x48),
    ('recording_registry_lookup', 0xC03755D8, 0x40),
    ('cdng_event_record_lookup', 0xC038BFB0, 0x30),
    ('cdng_frame_length_and_call', 0xC038C1D4, 0x18),
    ('cdng_frame_prologue', 0xC038C810, 0x10),
    ('cdng_state_constructor', 0xC038B470, 0x4C),
    ('parameter_container_factory', 0xC0697830, 0xA0),
    ('parameter_container_constructor', 0xC0697D88, 0x100),
    ('parameter_pair_copy', 0xC02E9B80, 0x4C),
    ('leaf_kind_lookup', 0xC06972C0, 0x88),
    ('tiff_leaf_kind_constructor', 0xC0720198, 0x80),
    ('jpeg_leaf_kind_constructor', 0xC07207B8, 0xA4),
    ('sentinel_singleton', 0xC0697510, 0x48),
    ('sentinel_constructor', 0xC0697558, 0xA8),
    ('tiff_alternate_constructor', 0xC06A3FC8, 0x58),
    ('tiff_alternate_base', 0xC0720120, 0x78),
    ('tiff_reservation_initializer', 0xC06A2838, 0x20),
    ('recording_pointer_retreat', 0xC037E5C8, 0x68),
    ('recording_context_rewrite', 0xC039E01C, 0x38),
    ('context_mutable_getter', 0xC0203D70, 0x10),
    ('conditional_context_rewrite', 0xC039C5B0, 0x40),
)


def audit(main_path, data_path):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    main, data = Path(main_path).read_bytes(), Path(data_path).read_bytes()
    if hashlib.sha256(main).hexdigest() != O.HASHES[1]:
        raise ValueError('fp L MAIN fingerprint mismatch')
    if len(data) != DATA_SIZE or hashlib.sha256(data).hexdigest() != DATA_HASH:
        raise ValueError('fp L DATA fingerprint mismatch')
    if len(main) != DATA_BASE-O.BASE:
        raise ValueError('MAIN/DATA load boundary mismatch')
    provider = struct.unpack_from('<I', data, POOL_WORD-DATA_BASE)[0]
    if provider != POOL:
        raise ValueError('DATA ledger pool pointer mismatch')
    for table in (BASE_VTABLE, SELECTED_VTABLE):
        if struct.unpack_from('<I', main, table-O.BASE+0x10)[0] != SIZE_FN:
            raise ValueError('formatter size slot mismatch')
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    checks = (
        (0xC0378F78, 'add', 'r2, r2, #0x10'),
        (0xC0378F84, 'blx', 'r2'),
        (0xC0378F98, 'mov', 'r1, fp'),
        (0xC0378FA0, 'bl', '#0xc038a4a0'),
        (0xC03790B8, 'add', 'r2, r2, #0x2c'),
        (0xC03790D0, 'str', 'r2, [r4, #0x14c]'),
        (0xC038C974, 'ldr', 'r0, [r5, #0x4c]'),
        (0xC038C978, 'ldr', 'r1, [r5, #0x14c]'),
        (0xC038C97C, 'bl', '#0xc0010cb8'),
        (0xC0697A04, 'add', 'r2, ip, #0x20'),
        (0xC0697A08, 'add', 'r4, r2, #0x28'),
        (0xC0010CC4, 'sub', 'r2, ip, r4'),
        (0xC038A51C, 'bl', '#0xc001d2b8'),
        (0xC038A524, 'str', 'r1, [r4, #0x10]'),
    )
    for addr, mnemonic, operand in checks:
        ins = next(md.disasm(main[addr-O.BASE:addr-O.BASE+4], addr))
        if (ins.mnemonic, ins.op_str) != (mnemonic, operand):
            raise ValueError('formatter edge/field mismatch at '+hex(addr))
    result = {'main_sha256': O.HASHES[1], 'data_sha256': DATA_HASH,
              'data_bytes': len(data), 'data_address': hex(DATA_BASE),
              'pool_pointer_word': hex(POOL_WORD), 'pool_pointer': hex(provider),
              'size_slot': {hex(t): hex(SIZE_FN) for t in (BASE_VTABLE, SELECTED_VTABLE)},
              'windows': []}
    for name, addr, n in WINDOWS:
        code = main[addr-O.BASE:addr-O.BASE+n]
        result['windows'].append(dict(name=name, address=hex(addr), bytes=n,
            sha256=hashlib.sha256(code).hexdigest(),
            instructions=[f'{i.address:08x}: {i.mnemonic} {i.op_str}' for i in md.disasm(code, addr)]))
    init = main[0x2E48F50:0x2E48F50+0x4C]
    result['ledger_initial_values'] = list(struct.unpack('<19I', init))
    result['leaf_slots'] = {
        hex(t): {hex(s): hex(struct.unpack_from('<I', main, t-O.BASE+s)[0])
                 for s in (0x10, 0x2C, 0x58, 0x60)}
        for t in (0xC2E4A4B0, 0xC2E4A5B0)}
    if result['leaf_slots'] != {
            '0xc2e4a4b0': {'0x10': '0xc06973c8', '0x2c': '0xc06a1d58',
                            '0x58': '0xc0697438', '0x60': '0xc0720ce0'},
            '0xc2e4a5b0': {'0x10': '0xc0720418', '0x2c': '0xc06a28d0',
                            '0x58': '0xc06a3940', '0x60': '0xc06a3960'}}:
        raise ValueError('selected leaf slots mismatch')
    # Direct ARM BL references only; indirect and Thumb calls are not excluded.
    result['direct_arm_callers'] = {}
    for target in (0xC038A4A0, 0xC038A508):
        callers = []
        for off in range(0, len(main), 4):
            w = struct.unpack_from('<I', main, off)[0]
            if w >> 24 != 0xEB:
                continue
            d = w & 0xFFFFFF
            if d & 0x800000:
                d -= 0x1000000
            if O.BASE+off+8+d*4 == target:
                callers.append(hex(O.BASE+off))
        result['direct_arm_callers'][hex(target)] = callers
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--main', type=Path, required=True)
    p.add_argument('--data', type=Path, required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.main, args.data), indent=2))
