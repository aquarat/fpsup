/* Temporary fp L UicDrawHandler observer. Only its BSS vtable pointer changes;
 * native methods and listener remain intact. No registration or controller.
 * OWNED is a verified retained 64-KiB allocation, code at +1000, table +2000.
 * +400 command (1 install, 2 remove), +404 result, +408 expected listener.
 * +420..+4ff diagnostics. All allocations survive removal and in-flight calls.
 */
.syntax unified
.arm
.text
#ifndef OWNED
#error OWNED must be allocator-owned
#endif
.equ STATE, OWNED+0x400
.equ TABLE, OWNED+0x2000
.equ OBJECT, 0xC38D37CC
.equ STOCK, 0xC2E55A70
.global entry, observe, image_end
entry:
    push {r4-r8, lr}
    mov r8, sp
    bic sp, sp, #7
    ldr r4, =STATE
    mrs r7, cpsr
    and r0, r7, #31
    cmp r0, #0x13
    bne refused
    cpsid if
    mrc p15, 0, r0, c0, c0, 5
    cmp r0, #0x80000000
    bne refused
    mrc p15, 1, r0, c9, c0, 2
    tst r0, #0x03000000
    bne refused
    ldr r5, =OBJECT
    ldr r0, [r5, #12]
    cmp r0, #1
    bne refused
    ldr r0, [r5, #8]
    ldr r1, [r4, #8]
    cmp r0, r1
    bne refused
    ldr r6, [r4]
    cmp r6, #1
    cmpne r6, #2
    bne refused
    ldr r0, =STOCK
    ldr r1, =TABLE
    mov r2, #0
verify_table:
    ldr r3, [r0, r2]
    cmp r2, #12
    ldreq r3, =OWNED+0x1000+observe-entry
    ldr ip, [r1, r2]
    cmp r3, ip
    bne refused
    add r2, r2, #4
    cmp r2, #40
    blo verify_table
    cmp r6, #1
    movne r2, r0
    movne r0, r1
    movne r1, r2
    ldr r2, [r5]
    cmp r2, r0
    bne refused
    str r1, [r5]                    @ one aligned BSS publication, no code patch
    dmb sy
    ldr ip, =0xC000E91C
    blx ip
    mov r0, #2
    b finish
refused:
    mov r0, #0x10
finish:
    str r0, [r4, #4]
    msr cpsr_c, r7
    mov sp, r8
    pop {r4-r8, pc}

observe:
    push {r4-r8, lr}
    mov r8, sp
    bic sp, sp, #7
    ldr r4, =STATE
    mrs r6, cpsr
    cpsid if
    str r6, [r4, #0x4c]
    ldr r3, [r4, #0x20]
    add r3, r3, #1
    str r3, [r4, #0x20]
    ldr r3, [r4, #0x28]
    add r3, r3, #1
    str r3, [r4, #0x28]
    ldr ip, [r4, #0x2c]
    cmp r3, ip
    strhi r3, [r4, #0x2c]
    ldr r3, =OBJECT
    cmp r0, r3
    ldrne r3, [r4, #0x3c]
    addne r3, r3, #1
    strne r3, [r4, #0x3c]
    ldr r3, =0xC3000098
    ldr r3, [r3]
    str r3, [r4, #0x34]
    ldr ip, [r4, #0x30]
    cmp ip, #0
    streq r3, [r4, #0x30]
    cmpne r3, ip
    ldrne ip, [r4, #0x38]
    addne ip, ip, #1
    strne ip, [r4, #0x38]
    ldr ip, [r3, #8]
    str ip, [r4, #0x58]
    ldr r5, [r3, #0x74]
    str r5, [r4, #0x54]
    ldr r3, [r3, #0x18]
    sub r5, r5, r3
    str r5, [r4, #0x50]
    cmp ip, #1
    blo skip_bit
    cmp ip, #500
    bhi skip_bit
    mov r3, ip, lsr #5
    and ip, ip, #31
    mov r5, #1
    lsl r5, r5, ip
    add r3, r4, r3, lsl #2
    ldr ip, [r3, #0x80]
    orr ip, ip, r5
    str ip, [r3, #0x80]
skip_bit:
    add r3, r8, #24                @ incoming SP, before wrapper's frame
    ldr ip, [r4, #0x40]
    cmp ip, #0
    streq r3, [r4, #0x40]
    cmp r3, ip
    strlo r3, [r4, #0x40]
    ldr ip, [r4, #0x44]
    cmp r3, ip
    strhi r3, [r4, #0x44]
    msr cpsr_c, r6
    ldr ip, =0xC06CF498
    blx ip                        @ original method, original r0/r1/r2
    mov r7, r0
#if defined(CALLBACK)
    /* Optional integration build: only the observed outer drawing task may
     * enter owned controller code. The C coordinator also rejects reentry. */
    ldr r3, [r4, #0x28]
    cmp r3, #1
    bne callback_done
    ldr r3, =0xC3000098
    ldr r3, [r3]
    ldr ip, [r4, #0x14]
    cmp r3, ip
    bne callback_done
    ldr ip, [r4, #0xc]
    tst ip, #3
    bne callback_done
    ldr r3, =OWNED+0x3000
    cmp ip, r3
    blo callback_done
    add r3, r3, #0x5000
    cmp ip, r3
    bhs callback_done
    ldr r0, [r4, #0x10]
    cmp r0, r3
    bne callback_done
    blx ip
callback_done:
#endif
    mrs r6, cpsr
    cpsid if
    ldr r3, [r4, #0x24]
    add r3, r3, #1
    str r3, [r4, #0x24]
    ldr r3, [r4, #0x28]
    sub r3, r3, #1
    str r3, [r4, #0x28]
    str r7, [r4, #0x48]
    dmb sy
    msr cpsr_c, r6
    mov r0, r7
    mov sp, r8
    pop {r4-r8, pc}
    .ltorg
image_end:
