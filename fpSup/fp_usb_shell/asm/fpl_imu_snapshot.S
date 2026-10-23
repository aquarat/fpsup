.syntax unified
.arm
.text
.global entry
/* Finite passive fp L 3.02 observer, borrowed echo task context. No calls,
 * hooks, device writes, interrupt masking, retries or cache operations.
 * PARAM/RESULT are compiled from gf.layout, never supplied by the dispatcher.
 *
 * Bounds: FPL_GYRO_BINDINGS.md, identical embedded image local 04D6/04E2:
 * P=0x6004, R=0x644C, alias OR 0x2E000000. 092C..09DC writes 1200 words
 * after R's header, ending at local 0x7710 (exclusive). The host MMU maps
 * 2E000000..2E200000; we accept ONLY this evidenced state/ring subrange AND
 * the exact published object identities. A new firmware layout must refuse.
 * These are static mappings, not proof that live hardware is powered/ready.
 *
 * PARAM: magic,status,P,R,meta64,meta68,head_before,head_after,P_end,R_end,
 *        accel_x/y/z (sign extended), copied_bytes, reserved[2].
 * Magic IMU1 is written LAST. Status: 1 stable observation, 2 stale,
 * 3 unavailable (P=0), 4 invalid P, 5 invalid ring, 6 invalid head.
 * RESULT (RECORD_COUNT=600): exactly 0x12c4 raw ring bytes including head.
 * RECORD_COUNT<600: latched head_before followed by the last N completed
 * records in chronological ring order (wrap included). No freshness/lap or
 * atomicity claim: the coprocessor may advance/overwrite during copying.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef RESULT
#error RESULT required
#endif
#ifndef RECORD_COUNT
#define RECORD_COUNT 600
#endif
#if RECORD_COUNT < 1 || RECORD_COUNT > 600
#error RECORD_COUNT must be in 1..600
#endif
.equ PUB, 0xC31E23CC
.equ ACCEL, 0xC37772F4
.equ LO, 0x2E006004
.equ HI, 0x2E007710
.equ EXPECT_RING, 0x2E00644C
.equ SPAN, 0x12C0
.equ BYTES, 0x12C4
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm

entry:
    push {r4-r10, lr}
    addr r4, PARAM
    addr r10, PUB
    addr r0, ACCEL
    ldrsh r1, [r0]
    str r1, [r4, #0x28]
    ldrsh r1, [r0, #2]
    str r1, [r4, #0x2c]
    ldrsh r1, [r0, #4]
    str r1, [r4, #0x30]
    ldr r5, [r10]
    str r5, [r4, #8]
    mov r3, #3
    cmp r5, #0
    beq finish
    mov r3, #4
    tst r5, #3
    bne finish
    addr r0, LO
    cmp r5, r0
    blo finish
    addr r1, (HI-0x6c)
    cmp r5, r1
    bhi finish
    cmp r5, r0                  @ exact evidenced P, not just plausible RAM
    bne finish
    ldr r6, [r5, #0x60]
    str r6, [r4, #0x0c]
    ldr r0, [r5, #0x64]
    str r0, [r4, #0x10]
    ldr r0, [r5, #0x68]
    str r0, [r4, #0x14]
    mov r3, #5
    tst r6, #3
    bne finish
    addr r0, LO
    cmp r6, r0
    blo finish
    addr r0, (HI-BYTES)
    cmp r6, r0
    bhi finish
    addr r0, EXPECT_RING
    cmp r6, r0
    bne finish
    ldr r8, [r6]
    str r8, [r4, #0x18]
    mov r3, #6
    sub r0, r8, r6
    cmp r0, #8
    blo finish
    movw r1, #SPAN
    cmp r0, r1
    bhi finish
    tst r0, #7
    bne finish
    addr r7, RESULT
#if RECORD_COUNT == 600
    mov r0, r6
    movw r9, #BYTES
copy:
    ldr r1, [r0], #4
    str r1, [r7], #4
    subs r9, r9, #4
    bne copy
    movw r0, #BYTES
#else
    str r8, [r7], #4             @ header is the latched original head
    movw r1, #(RECORD_COUNT*8)
    sub r0, r8, r1
    add r0, r0, #4               @ first word of oldest requested record
    add r2, r6, #4               @ first ring data word
    movw r1, #SPAN
    cmp r0, r2
    addlo r0, r0, r1            @ at most one wrap: N <= 599
    add ip, r2, r1              @ exclusive ring data end
    movw r9, #RECORD_COUNT
copy:
    ldr r1, [r0], #4
    str r1, [r7], #4
    ldr r1, [r0], #4
    str r1, [r7], #4
    cmp r0, ip
    moveq r0, r2
    subs r9, r9, #1
    bne copy
    movw r0, #(4+RECORD_COUNT*8)
#endif
    str r0, [r4, #0x34]
    ldr r2, [r6]
    str r2, [r4, #0x1c]
    mov r3, #6
    sub r0, r2, r6
    cmp r0, #8
    blo finish
    movw r1, #SPAN
    cmp r0, r1
    bhi finish
    tst r0, #7
    bne finish
    mov r3, #2
    cmp r2, r8
    bne finish
    addr r0, RESULT
    ldr r0, [r0]
    cmp r0, r8                  @ head may have changed before copy started
    moveq r3, #1
finish:
    ldr r0, [r10]
    str r0, [r4, #0x20]
    cmp r0, r5
    movne r3, #2
    bne done                    @ never dereference a changed publication
    addr r1, LO
    cmp r5, r1
    bne done                    @ initial zero/invalid P: no dereference
    ldr r0, [r5, #0x60]
    str r0, [r4, #0x24]
    ldr r1, [r4, #0x0c]
    cmp r0, r1
    movne r3, #2
done:
    str r3, [r4, #4]
    dmb sy                      @ CPU result publication, NOT coprocessor lock
    addr r0, 0x31554D49          @ 'IMU1'
    str r0, [r4]
    mov r0, #0
    pop {r4-r10, pc}
