/* Included ONLY in the existing shared restore body for --fpl-slit-recording.
 * No registration/call into product code. r4 journal and r6 SP are preserved.
 * Fixed narrow owner layout: descriptor, draw vtable, runtime+0x200, Vd veneer.
 * This is conditional MMIO cleanup, before the ordinary journal clears hooks.
 */
    push {r7, r8}
    mrs r5, cpsr
    cpsid if
    movw r0, #0x37cc
    movt r0, #0xc38d
    ldr r7, [r0]
    sub r7, r7, #0x2000
    movw r0, #0
    movt r0, #0x4440
    cmp r7, r0
    blo .Lslit_shutdown_done
    movt r0, #0x463f
    cmp r7, r0
    bhi .Lslit_shutdown_done
    uxth r0, r7
    cmp r0, #0
    bne .Lslit_shutdown_done
    ldr r0, [r7]
    cmp r0, r7
    bne .Lslit_shutdown_done
    ldr r0, [r7, #8]
    cmp r0, r7
    bne .Lslit_shutdown_done
    ldr r0, [r7, #12]
    cmp r0, #0x10000
    bne .Lslit_shutdown_done
    add r8, r7, #0x8000
    ldr r0, [r8]
    movw r1, #0x4954
    movt r1, #0x534c
    cmp r0, r1
    bne .Lslit_shutdown_done
    add r8, r8, #0x200
    ldr r0, [r8]
    cmp r0, #1
    bne .Lslit_shutdown_done
    add r7, r7, #0x1800
    ldr r0, [r8, #8]
    cmp r0, r7
    bne .Lslit_shutdown_done
    mov r0, #1
    str r0, [r8, #4]           @ stop future GUI/IRQ activation first
    /* Native Subject has nine fixed slots; remove only our retained observer.
     * No call, wait, heap release or staging reference in shutdown. A borrowed
     * in-flight observer sees shutdown and remains safe in retained memory. */
    ldr r1, [r8, #232]
    sub r0, r7, #0x1800
    add r0, r0, #0x2500
    cmp r1, r0
    bne .Lslit_shutdown_vd
    movw r2, #0xb0d0
    movt r2, #0xc31a
    mov r0, #9
.Lslit_shutdown_subject:
    ldr r3, [r2]
    cmp r3, r1
    moveq r3, #0
    streq r3, [r2]
    add r2, r2, #4
    subs r0, r0, #1
    bne .Lslit_shutdown_subject
.Lslit_shutdown_vd:
    movw r3, #0x6dd8
    movt r3, #0xc31d
    ldr r0, [r3]
    cmp r0, r7
    bne .Lslit_shutdown_done   @ never claim a foreign callback's timing
    ldr r0, [r8, #12]
    cmp r0, #1
    bne .Lslit_shutdown_clear
    ldr ip, [r8, #16]
    movw r0, #0x1ae7
    movt r0, #0x0c47
    cmp ip, r0                 @ 4 fps
    beq .Lslit_shutdown_mode
    movw r0, #0x11ef
    movt r0, #0x082f
    cmp ip, r0                 @ 6 fps
    beq .Lslit_shutdown_mode
    movw r0, #0x0d73
    movt r0, #0x0623
    cmp ip, r0                 @ 8 fps
    beq .Lslit_shutdown_mode
    movw r0, #0x08f7
    movt r0, #0x0417
    cmp ip, r0                 @ 12 fps
    bne .Lslit_shutdown_clear
.Lslit_shutdown_mode:
    movw r0, #0
    movt r0, #0x3010
    ldr r1, [r0, #0x20]
    movw r2, #0
    movt r2, #0x165b
    cmp r1, r2
    bne .Lslit_shutdown_clear
    ldr r1, [r0, #4]
    cmp r1, ip
    bne .Lslit_shutdown_clear
    movw r1, #0x047b
    movt r1, #0x020b
    str r1, [r0, #4]
.Lslit_shutdown_clear:
    mov r0, #0
    str r0, [r8, #12]
    str r0, [r8, #20]
    str r0, [r3]
    dsb sy
.Lslit_shutdown_done:
    msr cpsr_c, r5
    pop {r7, r8}
