/* BX from known next_round, with exactly the serve 32-byte frame.
 * Constants come from a reviewed fixed-size host plan. EXPECTED_SOURCE holds
 * the old body; SOURCE can hold either allowlisted ABI-compatible body.
 * No allocations: never exceed the original 3572-byte code allocation.
 */
.syntax unified
.arm
.text
.global entry
entry:
    push {r4-r10, lr}
    ldr r0, =0xC37588BC
    ldm r0, {r1-r3}
    ldr r5, =POOL
    cmp r1, r5
    bne abort
    ldr r0, =ROOM
    cmp r2, r0
    bne abort
    ldr r6, =DEST
    cmp r3, r6
    bne abort
    add r0, r5, #0x1000
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
    ldr r7, =EXPECTED_SOURCE
    mov r8, r6
    ldr r9, =3572
verify:
    ldr r0, [r7], #4
    ldr r1, [r8], #4
    cmp r0, r1
    bne abort
    subs r9, r9, #4
    bne verify
    ldr r7, =SOURCE
    ldr r9, =3572
copy:
    ldr r0, [r7], #4
    str r0, [r6], #4
    subs r9, r9, #4
    bne copy
    ldr ip, =0xC000E91C
    blx ip
    dsb sy
    ldr ip, =0xC000EABC
    blx ip
    dsb sy
    isb sy
    ldr r0, =STATUS
    ldr r1, =COOKIE
    str r1, [r0]
    dsb sy
    pop {r4-r10, lr}
unwind:
    pop {r4-r10, lr}
    ldr ip, =(DEST + 120)
    bx ip
abort:
    pop {r4-r10, lr}
    ldr ip, =(DEST + 292)
    bx ip
    .ltorg
