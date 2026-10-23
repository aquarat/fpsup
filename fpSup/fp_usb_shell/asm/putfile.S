.syntax unified
.arm
.text
#include "../firmware/loader.h"
/* ============================================================================
 * putfile — write a host-supplied blob to a file on the card.
 * ============================================================================
 *
 * A worked example of shellcmd.S, and the reason it exists.  The native shell
 * reads and writes memory, makes directories and lists them, but nothing in it
 * writes arbitrary content to a path of your choosing: `dbg write_out_script`
 * writes a fixed sequence to a fixed name, `sdcard test5` writes a test
 * pattern, `analyzer` writes its own log.
 *
 * The host does everything else with commands that already exist -- `mem set`
 * stages the bytes, `dir` confirms the result -- so this is only the write.
 *
 * Borrowed slot: echo, handler pointer 0xC0BAC2F8.  Run through a command
 * rather than the gyro callback because file I/O blocks and takes the media
 * mutex, and because a handler is a function that may simply return.
 *
 * Parameter block, 0xC072F700:
 *      +0x08  status                                  <- read this
 *      +0x0C  open() return
 *      +0x10  write() return
 *      +0x14  data pointer            host fills
 *      +0x18  data length             host fills
 *      +0x1C  file object scratch     host fills, ~1 KiB
 *      +0x20  open mode               host fills; 7 creates or overwrites a prefix
 *      +0x24  path, NUL-terminated    host fills, e.g. "\AutoRun.txt"
 *
 * Status:  1 running   2 written   3 open returned 0   4 write returned 0
 *
 * write() answers 1 for success, not a byte count -- it returned 1 for a 25
 * byte file that `dir` then showed as 25 bytes.  So the length is confirmed on
 * the host, from the directory, not from this return.
 *
 * Mode 7 does not truncate an existing file: a shorter replacement leaves the
 * old tail.  Mode 0x402, which the gyro logger uses,
 * fails when the file is already there -- fine for a logger that always picks a
 * new name, wrong for anything that updates a file in place.
 *
 * Every return is checked.  These calls report failure by returning zero, and a
 * write that never happened is indistinguishable from one that worked unless
 * somebody looks.
 * ========================================================================== */

/* The host says where this block is: it asks the cave allocator and passes
 * the address in.  The value below is only so the file still assembles on
 * its own -- nothing reaches it through a build. */
#ifndef P
#if FPSUP_CAMERA != 502
#error putfile requires explicit owned parameter storage on this camera
#endif
.equ P,        0xC072F700
#endif
.equ P_STATUS, 0x08
.equ P_OPENR,  0x0C
.equ P_WRITER, 0x10
.equ P_DATA,   0x14
.equ P_LEN,    0x18
.equ P_FOBJ,   0x1C
.equ P_MODE,   0x20
.equ P_PATH,   0x24

.equ FMT_S,    0xC0BABB38     /* "%s " */

.equ F_MGR,    FW_F_MGR
.equ F_VOL,    FW_F_VOL
.equ F_CTOR,   FW_F_CTOR
.equ F_OPEN,   FW_F_OPEN
#if FPSUP_CAMERA == 502
.equ F_WRITE,  0xC03660E8     /* (obj, buf, len)   -> 1 ok, 0 on failure   */
#else
/* Official declared-length fp L 3.02 MAIN (firmware.py hash): ARM wrapper
 * at C0366300 forwards (obj,buf,len) to vtable +0x14. Offline audited only. */
.equ F_WRITE,  0xC0366300
#endif
.equ F_CLOSE,  FW_F_CLOSE
.equ F_DTOR,   FW_F_DTOR

.macro LDA reg, value
    movw    \reg, #:lower16:\value
    movt    \reg, #:upper16:\value
.endm

.global entry
entry:
    /* An even number of registers, deliberately.  AAPCS wants the stack eight
     * byte aligned at a call, and pushing an odd count leaves it four -- which
     * costs nothing until the callee reaches an LDRD, and then it is a data
     * abort with the shell task holding the dispatcher. */
    push    {r4, r5, r6, r7, r8, lr}
    mov     r8, r0                  @ shell context, for the reply
    LDA     r4, P
    mov     r0, #1
    str     r0, [r4, #P_STATUS]

    LDA     ip, F_MGR
    blx     ip
    mov     r1, #0
    LDA     ip, F_VOL
    blx     ip
    mov     r1, r0
    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, F_CTOR
    blx     ip

    ldr     r0, [r4, #P_FOBJ]
    add     r1, r4, #P_PATH
    ldr     r2, [r4, #P_MODE]
    LDA     ip, F_OPEN
    blx     ip
    str     r0, [r4, #P_OPENR]
    cmp     r0, #0
    moveq   r0, #3
    streq   r0, [r4, #P_STATUS]
    beq     destroy                 @ nothing to close: the open never took

    ldr     r0, [r4, #P_FOBJ]
    ldr     r1, [r4, #P_DATA]
    ldr     r5, [r4, #P_LEN]
    mov     r2, r5
    LDA     ip, F_WRITE
    blx     ip
    str     r0, [r4, #P_WRITER]
    cmp     r0, #0
    moveq   r6, #4
    movne   r6, #2
    str     r6, [r4, #P_STATUS]

    ldr     r0, [r4, #P_FOBJ]
    LDA     ip, F_CLOSE
    blx     ip

destroy:
    ldr     r0, [r4, #P_FOBJ]
    mov     r1, #2
    LDA     ip, F_DTOR
    blx     ip

    ldr     r0, [r4, #P_STATUS]
    cmp     r0, #2
    adreq   r1, msg_ok
    adrne   r1, msg_bad
    ldr     ip, [r8]
#if FPSUP_CAMERA == 502
    LDA     r0, FMT_S
#else
    adr     r0, fmt_s
#endif
    blx     ip

    mov     r0, #0
    pop     {r4, r5, r6, r7, r8, pc}

msg_ok:
    .asciz  "putfile: written"
    .align  2
msg_bad:
#if FPSUP_CAMERA == 502
    .asciz  "putfile: FAILED, read status at 0xC072F708"
#else
    .asciz  "putfile: FAILED, read supplied status block"
#endif
    .align  2
#if FPSUP_CAMERA != 502
fmt_s:
    .asciz "%s "
    .align 2
#endif
