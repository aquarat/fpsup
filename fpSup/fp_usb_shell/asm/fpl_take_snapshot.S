.syntax unified
.arm
.text
.global entry
/* OFFLINE-tested finite passive echo observer. No stock calls, initialization,
 * filesystem/device APIs, interrupt masking, retries or firmware stores.
 * Only owned PARAM/RESULT and the caller stack are written. Not reentrant:
 * the host staging lock excludes cooperating hosts, not camera tasks/other clients.
 * Two sequential observations are not atomic; ABA/intra-tuple races remain.
 *
 * Official fp L MAIN SHA256 fb8c20968e01ff9d8edf5f3e3f681c7341958048a004e717092c75e11106d4b9.
 * Context evidence: C0021A20 materializes C3074BA8; +5E4 is its init guard.
 * C0021A90 calls it and C0021A98..AA0 publishes via owner+58/+5C;
 * owner C3075194 -> publication C30751F0. Accept ONLY that exact object.
 * Requested bytes end at +5DA, inside [C3074BA8,C307518C); aligned words.
 * MMU fallback at C0723A78 (last record C0723AB4) maps C0000000 for 0x400
 * MiB, AP field 3, Normal memory field 1, physical encoding 00400000.
 * See FPL_ALLOCATOR_AUDIT.md: runtime overrides exist. This is static range
 * evidence, not a live MMU/readiness guarantee and NOT a generic Cxxx allowlist.
 * Refuse temporary/unknown context pointers, even if they look like RAM.
 * Managers/fields/vtable: FPL_GYRO_PATH_BINDINGS.md; no selector is called.
 *
 * PARAM: TAK1 (last write), ABI=1, changed bits, result_bytes=0xC0; rest zero.
 * changed: bit0 SSD tuple, bit1 SD tuple, bit2 context status/fields,
 *          bit3 ANY publication disagreement across the four observations.
 * RESULT: two 0x60-byte frames, each:
 *  +00 publication_before, +04 publication_after, +08 context status
 *      (0 null, 1 exact validated object read, 2 unknown/invalid),
 *  +0C reset byte, +10 letter byte, +14 reel halfword, +18/+1C reserved;
 *  +20 SSD and +40 SD: volume, vtable, letter, reel, current, saved, gate44,gate45.
 * No filename or readiness claim. Host separately validates identity and bounds.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef RESULT
#error RESULT required
#endif
.equ CTX_PUB, 0xC30751F0
.equ CTX_LO, 0xC3074BA8
.equ CTX_HI, 0xC307518C
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm

entry:
    push {r4-r10, lr}
    addr r4, PARAM
    addr r5, RESULT
    mov r0, #0
    mov r1, #0
clear_result:
    str r0, [r5, r1]
    add r1, r1, #4
    cmp r1, #0xc0
    blo clear_result
    str r0, [r4]                   @ invalidate any prior completion
    mov r6, #2                     @ exactly two passes, no retries/delays
pass:
    addr r7, CTX_PUB
    ldr r8, [r7]
    str r8, [r5]
    mov r3, #0
    cmp r8, #0
    beq context_done
    mov r3, #2
    tst r8, #3
    bne context_done
    addr r0, CTX_LO
    cmp r8, r0
    blo context_done
    addr r1, (CTX_HI-0x5da)
    cmp r8, r1
    bhi context_done
    cmp r8, r0                     @ exact identity, not just a mapped address
    bne context_done
    ldrb r0, [r8, #0x5d5]
    str r0, [r5, #0xc]
    ldrb r0, [r8, #0x5d6]
    str r0, [r5, #0x10]
    movw r1, #0x5d8
    ldrh r0, [r8, r1]
    str r0, [r5, #0x14]
    mov r3, #1
context_done:
    str r3, [r5, #8]
    addr r8, 0xC34392D0
    add r9, r5, #0x20
    mov r10, #2
manager:
    ldr r0, [r8]
    str r0, [r9]
    ldr r0, [r8, #4]
    str r0, [r9, #4]
    ldrb r0, [r8, #8]
    str r0, [r9, #8]
    ldr r0, [r8, #0xc]
    str r0, [r9, #0xc]
    ldr r0, [r8, #0x10]
    str r0, [r9, #0x10]
    ldr r0, [r8, #0x2c]
    str r0, [r9, #0x14]
    ldrb r0, [r8, #0x44]
    str r0, [r9, #0x18]
    ldrb r0, [r8, #0x45]
    str r0, [r9, #0x1c]
    add r8, r8, #0x68             @ explicit selector-derived SD offset
    add r9, r9, #0x20
    subs r10, r10, #1
    bne manager
    ldr r0, [r7]
    str r0, [r5, #4]
    add r5, r5, #0x60
    subs r6, r6, #1
    bne pass

    addr r5, RESULT
    mov r6, #0
    ldr r0, [r5]
    ldr r1, [r5, #4]
    cmp r0, r1
    orrne r6, r6, #8
    ldr r1, [r5, #0x60]
    cmp r0, r1
    orrne r6, r6, #8
    ldr r1, [r5, #0x64]
    cmp r0, r1
    orrne r6, r6, #8
    mov r2, #8
compare:
    ldr r0, [r5, r2]
    add r3, r2, #0x60
    ldr r1, [r5, r3]
    cmp r0, r1
    beq next
    cmp r2, #0x20
    orrlo r6, r6, #4
    blo next
    cmp r2, #0x40
    orrlo r6, r6, #1
    orrhs r6, r6, #2
next:
    add r2, r2, #4
    cmp r2, #0x60
    blo compare
    mov r0, #1
    str r0, [r4, #4]
    str r6, [r4, #8]
    mov r0, #0xc0
    str r0, [r4, #0xc]
    dmb sy                         @ completion ordering, NOT a coherence lock
    addr r0, 0x314B4154
    str r0, [r4]
    mov r0, #0
    pop {r4-r10, pc}
