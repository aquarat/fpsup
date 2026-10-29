/* Finite checker for installed fp L string hooks. P is owned output (1 KiB).
 * P+4: verified reader; +8: layers (1 or 2); results +16, three per layer,
 * then stock resolve/owns/remain. No allocation, waits, UI events or settings.
 * Called only by command 3 of fpl_ui_guard while IRQ/FIQ remain excluded. */
.syntax unified
.arm
.text
#ifndef P
#error P must name allocated output
#endif
.global entry
entry:
    push {r4-r8, lr}
    ldr r4, =P
    mov r0, #1
    str r0, [r4]
    ldr r5, [r4, #4]
    ldr r8, [r4, #8]
    cmp r8, #1
    cmpne r8, #2
    bne done
    add r7, r4, #16
    mov r6, #0
check:
    mov r0, r5
    add r1, r6, #0x40000000
    ldr ip, =0xC05E1D39
    blx ip
    str r0, [r7], #4
    mov r1, r0
    mov r0, r5
    ldr ip, =0xC05E23A9
    blx ip
    str r0, [r7], #4
    mov r0, r5
    ldr ip, =0xC05E23C1
    blx ip
    str r0, [r7], #4
    add r6, r6, #1
    cmp r6, r8
    blo check
    mov r0, r5
    mov r1, #0
    ldr ip, =0xC05E1D39
    blx ip
    str r0, [r7], #4
    mov r1, r0
    mov r0, r5
    ldr ip, =0xC05E23A9
    blx ip
    str r0, [r7], #4
    mov r0, r5
    ldr ip, =0xC05E23C1
    blx ip
    str r0, [r7], #4
    dmb sy
    mov r0, #2
    str r0, [r4]
done:
    pop {r4-r8, pc}
    .ltorg
