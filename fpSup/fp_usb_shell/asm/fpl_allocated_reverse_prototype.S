/* OFFLINE ONLY: exact responsive 3884-byte candidate -> retained 3572-byte old.
 * BX from candidate next_round, one 32-byte serve frame. Never allocate/free.
 * EXPECTED_NEW includes the initialized descriptor/token/predecessor record.
 * Only the two guard pins and record phase are excluded from byte comparison;
 * phase is independently required to equal ENTERED (2).
 */
.syntax unified
.arm
.text
.global entry
entry:
    push {r4-r10, lr}
    ldr r5, =STATUS
    ldr r0, [r5]
    ldr r1, =REQUEST
    cmp r0, r1
    bne abort
    ldr r0, =0xC37588BC
    ldm r0, {r1-r3}
    ldr r6, =POOL
    cmp r1, r6
    bne abort
    ldr r0, =0x100000
    cmp r2, r0
    bne abort
    ldr r7, =NEW
    cmp r3, r7
    bne abort
    add r0, r6, #0x1000
    cmp r4, r0
    bne abort
    ldr r0, [r4]
    ldr r1, =0x4C485356
    cmp r0, r1
    bne abort
    ldr r0, [r4, #0x80]
    cmp r0, #0
    bne abort
    ldr r0, [r4, #0xC0]
    ldr r1, =STUB
    cmp r0, r1
    bne abort
    ldr r0, =(NEW + RECORD + 24)
    ldr r0, [r0]
    cmp r0, #2
    bne abort
    mov r8, r7
    ldr r9, =EXPECTED_NEW
    mov r10, #0
verify_new:
    ldr r0, =PINS
    cmp r10, r0
    beq skip
    add r0, r0, #4
    cmp r10, r0
    beq skip
    ldr r0, =(RECORD + 24)
    cmp r10, r0
    beq skip
    ldr r0, [r8, r10]
    ldr r1, [r9, r10]
    cmp r0, r1
    bne abort
skip:
    add r10, r10, #4
    ldr r0, =3884
    cmp r10, r0
    bne verify_new
    ldr r8, =OLD
    ldr r9, =EXPECTED_OLD
    ldr r10, =3572
verify_old:
    ldr r0, [r8], #4
    ldr r1, [r9], #4
    cmp r0, r1
old_mismatch:
    bne abort
    subs r10, r10, #4
    bne verify_old
    ldr ip, =0xC000E91C
    blx ip
    ldr ip, =0xC000EABC
    blx ip
    dsb sy
    isb sy
    ldr r9, =0xC37588C4
    ldr r0, [r9]
    cmp r0, r7
    bne abort
    /* Compare again, not CAS: single-owner/boot exclusion remains required. */
    ldr r0, =(NEW + RECORD + 16)
    ldr r0, [r0]
    ldr r1, =TOKEN
    cmp r0, r1
    bne abort
    ldr r6, =OLD
publish:
    str r6, [r9]
    dsb sy
    str r6, [r5, #4]     @ hint only; old has no generation acknowledgement
    pop {r4-r10, lr}
unwind:
    pop {r4-r10, lr}
    ldr ip, =(OLD + 120)
    bx ip
abort:
    pop {r4-r10, lr}
    ldr ip, =(NEW + 316) @ exact candidate no_swap, NOT old offset 292
    bx ip
    .ltorg
