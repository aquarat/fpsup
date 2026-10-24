/* Opt-in diagnostic contract, not a firmware binding or generic registry.
 * Trusted provider(entry, end) -> r0=exclusive 64-byte owned slot,
 * r1=current boot epoch, r2=1 only with independent current-boot authority.
 * No authority => r2=0, and no returned pointer is dereferenced.
 * Provider must preserve AAPCS and serialize lifetime/reset with all callers.
 */
admission_claim:
    push {r4, lr}
    mov r0, r8
    mov r1, r9
    ldr ip, =RL_ADMISSION_PROVIDER
    blx ip
    cmp r2, #1
    bne admission_unavailable
    cmp r1, #0
    beq admission_unavailable
    tst r0, #7
    bne admission_unavailable
    ldr r2, =0x44400000
    cmp r0, r2
    blo admission_unavailable
    adds r2, r0, #64
    bcs admission_unavailable
    ldr r3, =0x46400100
    cmp r2, r3
    bhi admission_unavailable
    cmp r0, r9
    cmplo r8, r2
    blo admission_unavailable
    ldr r2, [r0]
    ldr r3, =0x5241444D
    cmp r2, r3
    bne admission_unavailable
    ldr r2, [r0, #4]
    cmp r2, #1
    bne admission_unavailable
    ldr r2, [r0, #8]
    cmp r2, r1
    bne admission_unavailable
    add r3, r0, #16
    mov r2, #12
1:  ldr ip, [r3], #4
    cmp ip, #0
    bne admission_duplicate
    subs r2, r2, #1
    bne 1b
    add r3, r0, #12
    ldrex r2, [r3]
    cmp r2, #0
    bne admission_occupied
    mov r2, #1
    strex ip, r2, [r3]
    cmp ip, #0
    bne admission_duplicate           @ no retry after uncertain contention
    dmb sy
    mov r11, r0
    pop {r4, pc}
admission_occupied:
    clrex
admission_duplicate:
    mov r0, #7
    b admission_reject
admission_unavailable:
    mov r0, #8
admission_reject:
    str r0, [r4]
    pop {r4, pc}

admission_result:
    mov r0, r4
    add r1, r11, #16
    mov r2, #8
1:  ldr r3, [r0], #4
    str r3, [r1], #4
    subs r2, r2, #1
    bne 1b
    dmb sy
    bx lr
