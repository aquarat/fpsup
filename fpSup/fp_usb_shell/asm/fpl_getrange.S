.syntax unified
.arm
.text
#include "../firmware/loader.h"
/* fp L 3.02 ranged card read: getfile.S's open/read/close, but it first reads
 * and discards SKIP whole chunks of LEN bytes into the same buffer, so the
 * chunk returned starts at SKIP*LEN. There is no verified seek; sequential
 * read is the verified primitive. The host supplies bounded worker staging.
 *
 * Parameter block P (getfile.S layout, plus):
 *      +0xE4  chunks to skip            host fills
 *      +0xE8  chunks skipped            <- filled
 *      +0xEC  bytes of the short skip   <- filled when a skip read came up short
 * Status:  1 running   2 read   3 open returned 0   4 read returned 0
 *          5 no buffer  6 end of file inside the skipped range
 */
#ifndef P
#error P required
#endif
.equ P_ACTUAL, 0x04
.equ P_STATUS, 0x08
.equ P_OPENR,  0x0C
.equ P_READR,  0x10
.equ P_BUF,    0x14
.equ P_LEN,    0x18
.equ P_FOBJ,   0x1C
.equ P_MODE,   0x20
.equ P_PATH,   0x24
.equ P_SKIP,   0xE4
.equ P_SKIPPED, 0xE8
.equ P_SHORT,  0xEC

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    push    {r4, r5, r6, r7, r8, lr}
    LDA     r4, P
    mov     r0, #1
    str     r0, [r4, #P_STATUS]
    mov     r0, #0
    str     r0, [r4, #P_ACTUAL]
    str     r0, [r4, #P_SKIPPED]
    str     r0, [r4, #P_SHORT]
    ldr     r0, [r4, #P_BUF]
    cmp     r0, #0
    moveq   r0, #5
    streq   r0, [r4, #P_STATUS]
    beq     done

    LDA     ip, FW_F_MGR
    blx     ip
    mov     r1, #0
    LDA     ip, FW_F_VOL
    blx     ip
    mov     r1, r0
    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, FW_F_CTOR
    blx     ip

    ldr     r0, [r4, #P_FOBJ]
    add     r1, r4, #P_PATH
    ldr     r2, [r4, #P_MODE]
    LDA     ip, FW_F_OPEN
    blx     ip
    str     r0, [r4, #P_OPENR]
    cmp     r0, #0
    moveq   r0, #3
    streq   r0, [r4, #P_STATUS]
    beq     destroy

    ldr     r5, [r4, #P_SKIP]
skip:
    ldr     r0, [r4, #P_SKIPPED]
    cmp     r0, r5
    bhs     target
    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_BUF]
    ldr     r2, [r4, #P_LEN]
    add     r3, r4, #P_ACTUAL
    LDA     ip, FW_F_READ
    blx     ip
    cmp     r0, #0
    moveq   r6, #4
    beq     finish
    ldr     r0, [r4, #P_ACTUAL]
    ldr     r1, [r4, #P_LEN]
    cmp     r0, r1
    strne   r0, [r4, #P_SHORT]
    movne   r6, #6
    bne     finish
    ldr     r0, [r4, #P_SKIPPED]
    add     r0, r0, #1
    str     r0, [r4, #P_SKIPPED]
    b       skip

target:
    mov     r0, #0
    str     r0, [r4, #P_ACTUAL]
    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_BUF]
    ldr     r2, [r4, #P_LEN]
    add     r3, r4, #P_ACTUAL
    LDA     ip, FW_F_READ
    blx     ip
    str     r0, [r4, #P_READR]
    cmp     r0, #0
    moveq   r6, #4
    movne   r6, #2

finish:
    str     r6, [r4, #P_STATUS]
    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, FW_F_CLOSE
    blx     ip

destroy:
    ldr     r0, [r4, #P_FOBJ]
    mov     r1, #2
    LDA     ip, FW_F_DTOR
    blx     ip

done:
    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}
