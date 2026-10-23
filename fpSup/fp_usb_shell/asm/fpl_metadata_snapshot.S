.syntax unified
.arm
.text
.global entry
/* Finite passive fp L 3.02 echo diagnostic; live execution verified October 20.
 * Evidence: docs/FPL_GYRO_METADATA_BINDINGS.md, passive subset.
 * No stock calls, constructors, pointer chasing, allocation or firmware stores.
 * Writes only PARAM/RESULT and caller stack; ignores dispatcher arguments.
 * Construction guards are NOT locks on later updates. ABA/torn loads remain.
 * PARAM: MET1 last, ABI 1, copied mask (settings=1/lens=2), size 0x60.
 * RESULT settings +00: before, after, copied bytes, reserved;
 *   +10 width, height, format, reserved.
 * RESULT lens +20: before, after, copied bytes, reserved;
 *   +30 exactly 32 name bytes, +50 focal u32, +54..5f reserved.
 * Skipped groups have after/copy/payload zero. Host discards changed-guard
 * payloads semantically, retaining the raw result as evidence. No retries.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef RESULT
#error RESULT required
#endif
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm
entry:
    push {r4-r10, lr}
    addr r4, PARAM
    addr r5, RESULT
    mov r0, #0
    str r0, [r4]
    mov r1, #0
clear:
    str r0, [r5, r1]
    add r1, r1, #4
    cmp r1, #0x60
    blo clear
    mov r6, #0
    addr r7, 0xC31F70B0
    ldr r0, [r7]
    str r0, [r5]
    cmp r0, #1
    bne lens
    dmb sy
    addr r8, 0xC31F6ABC
    ldr r0, [r8]
    str r0, [r5, #0x10]
    ldr r0, [r8, #4]
    str r0, [r5, #0x14]
    ldr r0, [r8, #12]
    str r0, [r5, #0x18]
    dmb sy
    ldr r0, [r7]
    str r0, [r5, #4]
    mov r0, #12
    str r0, [r5, #8]
    orr r6, r6, #1
lens:
    addr r7, 0xC3477208
    ldr r0, [r7]
    str r0, [r5, #0x20]
    cmp r0, #1
    bne done
    dmb sy
    addr r8, 0xC34657B8
    add r9, r5, #0x30
    mov r1, #0
name:
    ldrb r0, [r8, r1]
    strb r0, [r9, r1]
    add r1, r1, #1
    cmp r1, #32
    blo name
    addr r8, 0xC34657FC
    ldr r0, [r8]
    str r0, [r5, #0x50]
    dmb sy
    ldr r0, [r7]
    str r0, [r5, #0x24]
    mov r0, #36
    str r0, [r5, #0x28]
    orr r6, r6, #2
done:
    mov r0, #1
    str r0, [r4, #4]
    str r6, [r4, #8]
    mov r0, #0x60
    str r0, [r4, #12]
    dmb sy
    addr r0, 0x3154454D
    str r0, [r4]
    mov r0, #0
    pop {r4-r10, pc}
