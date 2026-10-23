/* OFFLINE ONLY. Synthetic caller-owned 64-KiB reservation, no allocator or
 * firmware hooks. Not a card payload: OWNED is supplied by the emulator.
 * Entry r0 remains its own address. Creation does not attach capture: the
 * external owner must call activate AFTER entry returns and staging is gone.
 * Result/state ownership lasts through join, external readback and retirement.
 * No routine frees this reservation, including retire (caller frees later).
 * Layout and native failure limitations: docs/FPL_GYRO_TASK_LIFETIME.md. */
#ifndef OWNED
#error "explicit synthetic owned reservation required"
#endif
#ifndef CAPTURE_FILE
#error "actual relocatable capture binary required"
#endif
#if OWNED < 0x40000000 || OWNED > 0x7FFF0000 || (OWNED & 0xFFFF)
#error "invalid synthetic owned extent"
#endif
.syntax unified
.arm
.text
.global entry
.equ XT_CREATE,  0xC036E320
.equ XT_ATTACH,  0xC036E3D0
.equ XT_JOIN,    0xC036E410
.equ XT_DESTROY, 0xC036E380
.equ PHASE, 0
.equ HOLDER, 4
.equ BODY, 8
.equ VT, 0x10
.equ CAPTURE, 0x20
.equ DONE, 0x24
.equ JOIN_RC, 0x28
.equ ACK, 0x2C
.equ RELEASE_READY, 0x30
.equ ERROR, 0x34

entry:
    push {r4-r8, lr}
    ldr r4, =OWNED
    ldr r0, [r4, #PHASE]
    cmp r0, #0
    bne entry_return                 @ never reset a live/uncertain instance
    mov r0, #1
    str r0, [r4, #PHASE]             @ initialization attempted
    ldr r5, =resident_image - (.Lsource_pc + 8)
.Lsource_pc:
    add r5, pc, r5
    add r6, r4, #0x1000
    mov r7, #0x2000
copy:
    ldr r0, [r5], #4
    str r0, [r6], #4
    subs r7, r7, #4
    bne copy
    add r0, r4, #VT
    str r0, [r4, #BODY]              @ body object stores ADDRESS of vtable
    ldr r0, =OWNED + body_entry - resident_image + 0x1000
    str r0, [r4, #(VT+0xC)]
    add r0, r4, #0x2000
    str r0, [r4, #CAPTURE]
    /* Capture table is initialized by the synthetic owner before copying.
     * Publish the entire retained image before task/body references escape. */
    ldr ip, =0xC000E91C
    blx ip
    ldr ip, =0xC000EABC
    blx ip
    add r0, r4, #HOLDER
    mov r1, #6
    mov r2, #0x2000
    ldr r3, =OWNED + task_name - resident_image + 0x1000
    ldr ip, =XT_CREATE
    blx ip
    ldr r0, [r4, #HOLDER]            @ return r0 is NOT allocation success
    cmp r0, #0
    moveq r1, #1
    streq r1, [r4, #ERROR]
    moveq r1, #0                    @ only if native allocator RETURNS null;
                                    @ inspected backend wrapper asserts first
    movne r1, #2                    @ created; not proof of successful sta_tsk
    str r1, [r4, #PHASE]
entry_return:
    pop {r4-r8, pc}
    .ltorg

/* Only this region survives loader staging. Keep offsets deliberately simple
 * and checked; this is an experiment, not a new resident layout protocol. */
    .org 0x1000
resident_image:
activate:
    push {r4, lr}
    ldr r4, =OWNED
    ldr r0, [r4, #PHASE]
    cmp r0, #2
    bne activate_return
    mov r0, #3
    str r0, [r4, #PHASE]             @ retain even if attach asserts/doesn't return
    add r0, r4, #HOLDER
    add r1, r4, #BODY
    ldr ip, =XT_ATTACH
    blx ip                           @ no reliable return-status interpretation
activate_return:
    pop {r4, pc}

body_entry:
    /* Stock trampoline's internal stack alignment is not assumed. Preserve
     * its original SP while presenting an eight-aligned SP to our capture. */
    push {r4, lr}
    mov r4, sp
    bic sp, sp, #7
    ldr r0, =OWNED
    ldr ip, [r0, #CAPTURE]
    blx ip
    ldr r0, =OWNED
    mov r1, #1
    str r1, [r0, #DONE]              @ body returned, NOT yet a successful join
    mov sp, r4
    pop {r4, pc}                     @ back to native pool; never tk_ext_tsk

join:
    push {r4, lr}
    ldr r4, =OWNED
    ldr r0, [r4, #PHASE]
    cmp r0, #3
    bne join_return
    add r0, r4, #HOLDER
    ldr ip, =XT_JOIN
    blx ip                           @ native wait is infinite, not bounded
    str r0, [r4, #JOIN_RC]
    cmp r0, #0
    bne join_return                  @ unknown/error: no teardown or release
    ldr r0, [r4, #DONE]
    cmp r0, #1
    bne join_return                  @ set flag alone doesn't prove body ran
    ldr r0, [r4, #HOLDER]
    ldr r0, [r0, #8]
    cmp r0, #0
    bne join_return                  @ pool must have detached callback
    mov r0, #4
    str r0, [r4, #PHASE]
join_return:
    pop {r4, pc}

/* Private external-owner ABI: r0=1 only AFTER reading/validating retained
 * results. This acknowledgement is trusted caller evidence, not a camera read.
 * Must not run in body/stock pool context. Reservation released only by owner
 * AFTER this function returns to an independent stack/code allocation. */
retire:
    push {r4, lr}
    cmp r0, #1
    bne retire_return
    ldr r4, =OWNED
    ldr r0, [r4, #PHASE]
    cmp r0, #4
    bne retire_return
    mov r0, #1
    str r0, [r4, #ACK]
    mov r0, #6
    str r0, [r4, #PHASE]             @ teardown attempted; never blindly retry
    add r0, r4, #HOLDER
    mov r1, #2
    ldr ip, =XT_DESTROY
    blx ip                           @ assertion/nonreturn leaves release flag 0
    mov r0, #0
    str r0, [r4, #HOLDER]            @ native destructor does NOT clear holder
    str r0, [r4, #BODY]
    str r0, [r4, #(VT+0xC)]
    str r0, [r4, #CAPTURE]
    mov r0, #5
    str r0, [r4, #PHASE]
    mov r0, #1
    str r0, [r4, #RELEASE_READY]
retire_return:
    pop {r4, pc}
task_name: .ascii "GyrDiag\0"
    .ltorg
    .org 0x2000
capture_image:
    .incbin CAPTURE_FILE
    .org 0x3000
image_end:
