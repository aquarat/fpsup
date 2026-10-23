/* Echo's r0 is argv. Translate it to loader-compatible r0 = own entry.
 * Target and result are private to one host intent. No automatic rearm. */
.syntax unified
.arm
.text
#ifndef TARGET
#error "explicit checked target required"
#endif
.global entry, result, image_end
entry:
    push {r4-r6, lr}
    mov r4, sp
    bic sp, sp, #7
    adr r5, .Lresult
    ldr r0, [r5]
    cmp r0, #0
    bne done
    mov r0, #1
    str r0, [r5]
    ldr r0, =TARGET
    str r0, [r5, #4]
    blx r0
    dmb sy
    mov r0, #2
    str r0, [r5]
done:
    mov sp, r4
    pop {r4-r6, pc}
    .ltorg
    .balign 8
result:
.Lresult:
    .space 16
image_end:
