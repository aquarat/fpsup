/* Finite read-only topology diagnostic. P is a caller-owned 1-KiB block.
 * Only read Cortex-A7 L2CTLR after verifying MIDR implementer/architecture/part.
 * No hooks, system register writes, IRQ mask changes or native calls. */
.syntax unified
.arm
.text
#ifndef P
#error P must name allocated output
#endif
.global entry
entry:
    push {r4, lr}
    ldr r4, =P
    ldr r0, [r4]
    cmp r0, #0
    bne done
    mov r0, #1
    str r0, [r4]
    mrs r0, cpsr
    str r0, [r4, #4]
    mrc p15, 0, r0, c0, c0, 0
    str r0, [r4, #8]
    mrc p15, 0, r1, c0, c0, 5
    str r1, [r4, #12]
    ldr r1, =0xFF0FFFF0
    and r0, r0, r1
    ldr r1, =0x410FC070
    cmp r0, r1
    bne unknown
    mrc p15, 1, r0, c9, c0, 2
    str r0, [r4, #16]
    mov r0, #2
    b commit
unknown:
    mov r0, #3
commit:
    dmb sy
    str r0, [r4]
done:
    pop {r4, pc}
    .ltorg
