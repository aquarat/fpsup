/* Finite echo-context USER allocation. No free and no allocation payload writes.
 * Result survives beside this stub only until host copies it into owned RAM and
 * durable manifest. A repeated dispatch cannot allocate twice. */
.syntax unified
.arm
.text
#include "../firmware/loader.h"
.global entry, result, image_end
entry:
    push {r4-r8, lr}
    mov r8, sp
    bic sp, sp, #7
    sub sp, sp, #16
    adr r4, .Lresult
    ldr r0, [r4]
    cmp r0, #0
    bne done
    mov r0, #1
    str r0, [r4]                    @ attempt recorded BEFORE native call
    mov r0, sp
    mov r1, #0                      @ known USER class
    mov r2, #0x10000
    mov r3, #0x10000                @ explicit alignment required by prototype
    ldr ip, =FW_H_GET
    blx ip
    mov r0, sp                      @ H_GET returns descriptor, not success
    ldr ip, =FW_H_ADDR
    blx ip
    str r0, [r4, #4]
    ldm sp, {r0-r3}
    add r5, r4, #8
    stm r5, {r0-r3}                 @ all four native descriptor words
    dmb sy
    mov r0, #2
    str r0, [r4]
done:
    mov sp, r8
    pop {r4-r8, pc}
    .ltorg
    .balign 8
result:
.Lresult:
    .space 32
image_end:
