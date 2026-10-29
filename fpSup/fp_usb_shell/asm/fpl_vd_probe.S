.syntax unified
.arm
.text
.global entry
/* Finite fp L 3.02 Vd observation; TIMING_TEST enables bounded timing writes.
 * PARAM and BUFFER are reserved by the host in locked worker staging.
 * PARAM: command, state, count, capacity, install MPIDR, callback MPIDR,
 *        expected timing04, expected timing20, last CPSR, reserved...
 * states: 1 armed, 2 completed, 3 detached, 4 refusal.
 * Records (32 bytes): seconds-before, timer5 ticks, seconds-after,
 * timing04, timing20, scan counter, CPSR, MPIDR.
 * Timer 5 counts at the runtime frequency in C2F09408; seconds are the
 * native TickTimer epoch. A rollover-spanning record is rejected by host.
 * A callback clears only its own slot after CAPACITY observations.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef BUFFER
#error BUFFER required
#endif
#ifndef END_COUNT
#define END_COUNT 88
#endif
#if END_COUNT < 9 || END_COUNT > 1000
#error END_COUNT must be 9..1000
#endif
.equ SLOT, 0xC31D6DD8
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm
entry:
    push {r4-r8, lr}
    addr r4, PARAM
    addr r5, SLOT
    adr r6, callback
    mrs r7, cpsr
    cpsid if
    mrc p15, 0, r8, c0, c0, 5
    str r8, [r4, #16]
    ldr r0, [r4]
    cmp r0, #1
    beq detach
    cmp r0, #0
    bne refuse
    ldr r0, [r5]
    cmp r0, #0
    bne refuse
    ldr r0, [r5, #4]
    cmp r0, #1
    bne refuse
    ldr r0, [r4, #12]
    cmp r0, #1
    blo refuse
    cmp r0, #1024
    bhi refuse
    addr r1, 0x30100004
    ldr r0, [r1]
    ldr r2, [r4, #24]
    cmp r0, r2
    bne refuse
    ldr r0, [r1, #0x1c]
    ldr r2, [r4, #28]
    cmp r0, r2
    bne refuse
    mov r0, #0
    str r0, [r4, #8]
    mov r0, #1
    str r0, [r4, #4]
    dmb sy
    str r6, [r5]
    dsb sy
    b done
detach:
    ldr r0, [r5]
    cmp r0, r6
    beq clear
    cmp r0, #0
    bne refuse
    b detached
clear:
    mov r0, #0
    str r0, [r5]
    dsb sy
detached:
#ifdef TIMING_TEST
    bl restore_timing
#endif
    mov r0, #3
    str r0, [r4, #4]
    b done
refuse:
    mov r0, #4
    str r0, [r4, #4]
done:
    msr cpsr_c, r7
    mov r0, #0
    pop {r4-r8, pc}

callback:
    push {r4-r8, lr}
    mrs r7, cpsr
    mrc p15, 0, r8, c0, c0, 5
    addr r4, PARAM
    str r8, [r4, #20]
    str r7, [r4, #32]
    ldr r5, [r4, #8]
    ldr r6, [r4, #12]
#ifdef WATCH_MODE
    ldr r0, [r4, #40]
    cmp r0, #1
    bne 2f
    addr r0, 0x30100000
    ldr r1, [r0, #4]
    ldr r2, [r4, #36]
    cmp r1, r2
    bne complete
    ldr r1, [r0, #0x20]
    ldr r2, [r4, #28]
    cmp r1, r2
    bne complete
2:
#endif
    cmp r5, r6
    bhs complete
    addr r0, BUFFER
    add r0, r0, r5, lsl #5
    addr r1, 0xC3076D98
    ldr r2, [r1]
    str r2, [r0]
    addr r2, 0x2D810054
    ldr r2, [r2]
    str r2, [r0, #4]
    ldr r2, [r1]
    str r2, [r0, #8]
    addr r1, 0x30100000
    ldr r2, [r1, #4]
    str r2, [r0, #12]
    ldr r2, [r1, #0x20]
    str r2, [r0, #16]
#ifdef FRAME_INDEX
    addr r2, FRAME_INDEX
    ldr r2, [r2]
#else
    ldr r2, [r1, #0x590]
#endif
    str r2, [r0, #20]
    str r7, [r0, #24]
    str r8, [r0, #28]
    dmb sy
    add r5, r5, #1
    str r5, [r4, #8]
#ifdef TIMING_TEST
    cmp r5, #8
    beq apply_timing
    movw r0, #END_COUNT
    cmp r5, r0
    bne 1f
    bl restore_timing
1:
#endif
    cmp r5, r6
    blo return
complete:
#ifdef TIMING_TEST
    bl restore_timing
#endif
    addr r0, SLOT
    ldr r1, [r0]
    adr r2, callback
    cmp r1, r2
    moveq r1, #0
    streq r1, [r0]
    dsb sy
    mov r1, #2
    str r1, [r4, #4]
return:
    pop {r4-r8, pc}

#ifdef TIMING_TEST
/* Bounded experiment: 8 baseline, 80 changed, then baseline observations.
 * Change only the two interval fields in timing04. No clock, voltage, sensor
 * packet, exposure or persistent-setting writes. Restore only our exact value
 * in the original timing20 mode; never replay old timing into a new mode.
 * PARAM+24 original04, +28 original20, +36 trial04, +40 applied, +44 result.
 */
apply_timing:
    addr r0, 0x30100000
    ldr r1, [r0, #0x20]
    ldr r2, [r4, #28]
    cmp r1, r2
    bne complete
    ldr r1, [r0, #4]
    ldr r2, [r4, #24]
    cmp r1, r2
    bne complete
    ldr r1, [r4, #36]
    str r1, [r0, #4]
    dsb sy
    mov r1, #1
    str r1, [r4, #40]
    b return

restore_timing:
    ldr r1, [r4, #40]
    cmp r1, #1
    bxne lr
    addr r0, 0x30100000
    ldr r1, [r0, #0x20]
    ldr r2, [r4, #28]
    cmp r1, r2
    bne changed_mode
    ldr r1, [r0, #4]
    ldr r2, [r4, #24]
    cmp r1, r2
    beq restored
    ldr r3, [r4, #36]
    cmp r1, r3
    bne changed_mode
    str r2, [r0, #4]
    dsb sy
restored:
    mov r1, #1
    b restore_result
changed_mode:
    mov r1, #2
restore_result:
    str r1, [r4, #44]
    mov r1, #0
    str r1, [r4, #40]
    bx lr
#endif
