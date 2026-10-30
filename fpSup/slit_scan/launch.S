/* Returning product entry. Shared loader/stage2 own file I/O and journaling.
 * Runtime, wrapper, menu and every callback target move to a USER allocation.
 * Failure retains allocated memory; no native borrower is freed or reused. */
.syntax unified
.arm
.text
.global entry, embedded
entry:
    push {r4-r8, lr}
    mov r8, sp
    bic sp, sp, #7
    sub sp, sp, #16
    ldr r0, =0xC38D37CC
    ldr r0, [r0]
    ldr r1, =0xC2E55A70
    cmp r0, r1
    bne done
    mov r0, sp
    mov r1, #0
    str r1, [sp]
    str r1, [sp, #4]
    str r1, [sp, #8]
    str r1, [sp, #12]
    mov r2, #0x10000
    mov r3, #0x10000
    ldr ip, =0xC001D740
    blx ip
    mov r0, sp
    ldr ip, =0xC001D7F0
    blx ip
    mov r4, r0
    ldr r1, =0x44400000
    cmp r4, r1
    blo done
    ldr r1, =0x463f0000
    cmp r4, r1
    bhi done
    uxth r1, r4
    cmp r1, #0
    bne done
    ldr r1, [sp]
    cmp r1, r4
    bne done
    ldr r1, [sp, #4]
    cmp r1, #0
    bne done
    ldr r1, [sp, #8]
    cmp r1, r4
    bne done
    ldr r1, [sp, #12]
    cmp r1, #0x10000
    bne done
    /* Clear owned state and unused space, then copy three compact extents. */
    mov r0, #0
    mov r1, r4
    add r2, r4, #0x10000
1:  str r0, [r1], #4
    cmp r1, r2
    blo 1b
    ldmia sp, {r0-r3}
    stmia r4, {r0-r3}
    adr r5, .Lembedded
    add r6, r4, #0x1000
    ldr r7, =WRAPPER_BYTES
    bl copy
    add r6, r4, #0x3000
    ldr r7, =RUNTIME_BYTES
    bl copy
    add r6, r4, #0x8400
    ldr r7, =BLOCK_BYTES
    bl copy
    ldr r5, =0xC2E55A70
    add r6, r4, #0x2000
    mov r7, #40
    bl copy
    add r0, r4, #0x1000
    ldr r1, =DRAW_OBSERVE
    add r0, r0, r1
    add r1, r4, #0x2000
    str r0, [r1, #12]
#ifdef SLIT_VD
    add r1, r4, #0x1800
    ldr r0, =0xE59F0000
    str r0, [r1]
    ldr r0, =0xE59FF000
    str r0, [r1, #4]
    add r0, r4, #0x8000
    str r0, [r1, #8]
    ldr r0, =0x3000+SLIT_VD
    add r0, r4, r0
    str r0, [r1, #12]
#endif
    ldr ip, =0xC000E91C
    blx ip
    ldr ip, =0xC000EABC
    blx ip
    mov r0, r4
    ldr r1, =0x3000+SLIT_TICK
    add r1, r4, r1
    ldr r2, =0x3000+SLIT_KEY
    add r2, r4, r2
    ldr r3, =BLOCK_BYTES
    ldr ip, =0x3000+SLIT_BOOT
    add ip, r4, ip
    blx ip
    str r0, [r4, #0x20]          @ retained boot result, not an entry return ABI
done:
    mov sp, r8
    pop {r4-r8, pc}
copy:
    ldr r0, [r5], #4
    str r0, [r6], #4
    subs r7, r7, #4
    bne copy
    bx lr
    .ltorg
embedded:
.Lembedded:
    .incbin OWNED_IMAGE
