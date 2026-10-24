.syntax unified
.arm
.text
.global entry
/* One-shot fp L 3.02 test-tag observer: adds ONE UNDEFINED GTAG (0x4653) of
 * exactly N bytes to the Sigma MakerNote on the next CinemaDNG take start,
 * records what the native builder reported, and detaches itself.
 * Owner-authorized experiment (23 October): card contents may be lost.
 * Evidence for every native address: docs/FPL_GYRO2_FORMATTER.md,
 * docs/FPL_GYRO2_BINDINGS.md. NOT a fail-closed gate: nothing here can veto
 * the take; the host checks the result afterwards.
 *
 * entry    echo handler (shell task): native attach of OBJ to the Subject.
 * observer OBJ's vt+0xC, called inline as (obs, DataPool) on every notify.
 *          On mode 0 / type 3 it adds the tag once and returns 0, which makes
 *          the native dispatcher clear its slot. Any other event returns 1.
 *
 * VARS (PARAM):
 *   +00 install state  1 running 2 attached 3 no empty slot 4 already present
 *                      5 unexpected Subject 6 attach did not verify
 *   +04 Subject        +08 slot index      +0C empty slots before attach
 *   +10 observer calls +14 last mode       +18 last type
 *   +20 fired          1 added 2 null builder 3 called again after firing
 *   +24 builder        +28 size before     +2C add return  +30 size after
 *   +34 N
 * OBJ (PARAM+0x100): vptr -> VT (PARAM+0x110); VT slots 0..2 -> ret0, +C -> observer.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef SRC
#error SRC required
#endif
#ifndef N
#error N required
#endif
.equ OBJ,         PARAM + 0x100
.equ F_SUBJECT,   0xC0054E28
.equ F_ATTACH,    0xC00CF208
.equ SUBJECT,     0xC31AB0D0
.equ SLOTS,       9
.equ DP_EVENT,    0x40
.equ DP_BUILDER,  0x2C
.equ F_SIZE,      0xC00B6510
.equ F_ADD_TAG,   0xC00B6B20
.equ GTAG,        0x4653
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm

entry:
    push {r4-r8, lr}
    addr r4, PARAM
    mov r0, #1
    str r0, [r4]
    addr ip, F_SUBJECT
    blx ip
    str r0, [r4, #4]
    addr r1, SUBJECT
    cmp r0, r1
    movne r0, #5
    bne install_done
    mov r5, r0
    addr r6, OBJ
    mov r7, #0                  @ index
    mov r8, #0                  @ empty slots
scan:
    ldr r0, [r5, r7, lsl #2]
    cmp r0, r6
    moveq r0, #4
    beq install_done
    cmp r0, #0
    addeq r8, r8, #1
    add r7, r7, #1
    cmp r7, #SLOTS
    blo scan
    str r8, [r4, #12]
    cmp r8, #0
    moveq r0, #3
    beq install_done
    mov r0, r5
    mov r1, r6
    addr ip, F_ATTACH
    blx ip
    mov r7, #0
verify:
    ldr r0, [r5, r7, lsl #2]
    cmp r0, r6
    beq attached
    add r7, r7, #1
    cmp r7, #SLOTS
    blo verify
    mov r0, #6
    b install_done
attached:
    str r7, [r4, #8]
    mov r0, #2
install_done:
    str r0, [r4]
    mov r0, #0
    pop {r4-r8, pc}

observer:
    push {r4-r6, lr}
    sub sp, sp, #8
    mov r5, r1                  @ DataPool
    addr r4, PARAM
    ldr r0, [r4, #0x10]
    add r0, r0, #1
    str r0, [r4, #0x10]
    ldr r0, [r5]
    ldr ip, [r0, #DP_EVENT]
    mov r0, r5
    blx ip
    cmp r0, #0
    beq keep
    ldr r1, [r0]                @ mode
    ldr r2, [r0, #4]            @ type
    str r1, [r4, #0x14]
    str r2, [r4, #0x18]
    cmp r2, #3
    bne keep
    cmp r1, #0
    bne keep
    ldr r0, [r4, #0x20]
    cmp r0, #0
    movne r0, #3
    strne r0, [r4, #0x20]
    bne detach
    ldr r0, [r5]
    ldr ip, [r0, #DP_BUILDER]
    mov r0, r5
    blx ip
    str r0, [r4, #0x24]
    movs r6, r0
    moveq r0, #2
    streq r0, [r4, #0x20]
    beq detach
    addr ip, F_SIZE
    blx ip
    str r0, [r4, #0x28]
    ldr r0, =N
    str r0, [r4, #0x34]
    str r0, [sp]
    addr r0, SRC
    str r0, [sp, #4]
    mov r0, r6
    mov r1, #5                  @ MakerNote IFD
    movw r2, #GTAG
    mov r3, #7                  @ UNDEFINED
    addr ip, F_ADD_TAG
    blx ip
    str r0, [r4, #0x2C]
    mov r0, r6
    addr ip, F_SIZE
    blx ip
    str r0, [r4, #0x30]
    mov r0, #1
    str r0, [r4, #0x20]
detach:
    mov r0, #0
    b out
keep:
    mov r0, #1
out:
    add sp, sp, #8
    pop {r4-r6, pc}

ret0:
    mov r0, #0
    bx lr

.ltorg
