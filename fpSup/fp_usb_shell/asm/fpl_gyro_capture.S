/* OFFLINE fp L 3.02 bounded idle observer, borrowed echo task context only.
 * Not a loader entry, recording logger, resident task, hook or file writer.
 * Caller owns CODE (4096 writable bytes), STATE (256 bytes), OUTPUT (CAPACITY*8 bytes),
 * and an aligned stack. No default addresses: these are staging allocations,
 * not a cave grant. Caller must check non-overlap including code extent and
 * stack, publish D/I, and restore echo before releasing any allocation.
 * No host runner/install path is supplied. All addresses are compile constants.
 *
 * STATE u32: 0 completion 'GCAP', 4 status (1 finished, 2 no observed motion,
 * 3 unavailable P, 4 invalid P, 5 invalid R, 6 invalid head, 7 stale during
 * drain); 8 iterations completed, 12 appended records, 16 observed delta count
 * (shared g_gcount), 20 padbad (copied records only), 24 dropped for capacity,
 * 28 unchanged-head observations; 32..111 pre heads, 112..191 post heads.
 * Remaining bytes reserved/zero. On error prior output is diagnostic only;
 * in particular status 7 invalidates the last batch. Marker is written last.
 * Internal g_ghead/count/padbad are payload-local and reset on EVERY entry.
 *
 * Reads exact live P/R and checks head before each shared drain. An owned
 * descriptor freezes R for the shared routine (which otherwise re-walks P).
 * R's head is still asynchronous: recheck publications and compare pre head,
 * shared consumed head and post head after drain. A bad racing head cannot
 * cause an unbounded copy: stream_claim caps every write to owned capacity;
 * source begins at the prior validated head and shared drain wraps at R end.
 * Stop on any detected inconsistency, never use its cursor on another drain.
 * This is NOT a coherent snapshot or a lossless claim: equal heads may hide
 * whole laps, and pointer ABA / stopped producer cannot be proved here.
 * Status 2 means no observed motion, not proof of a stopped sensor.
 *
 * Twenty delays of 20 ms (FW_WDELAY from the shared fp L worker) give ~400 ms
 * nominal, NOT a deadline / maximum scheduling gap. First drain arms only.
 */
#if !defined(STATE) || !defined(OUTPUT) || !defined(CAPACITY)
#error "STATE, OUTPUT and CAPACITY must name owned staging"
#endif
#if CAPACITY < 1 || CAPACITY > 12000
#error "CAPACITY must be 1..12000 records"
#endif
#if (STATE & 3) || (OUTPUT & 7)
#error "unaligned owned staging"
#endif
#if STATE < OUTPUT + CAPACITY*8 && OUTPUT < STATE + 256
#error "state/output overlap"
#endif
.syntax unified
.arm
.text
.global capture
capture:
    push {r4-r10, lr}
    ldr r4, =STATE
    mov r0, #0
    mov r1, #0
1:  str r0, [r4, r1]
    add r1, r1, #4
    cmp r1, #256
    blo 1b
    str r0, g_gcount
    str r0, g_padbad
    mvn r0, #0
    str r0, g_ghead
    /* The descriptor view is owned and lives in this payload. */
    adr r0, descriptor
    str r0, descriptor_ptr
    ldr r0, =0x2E00644C
    str r0, descriptor_ring
    mov r5, #0
loop:
    bl validate
    cmp r0, #0
    bne finish
    mov r6, r2
    add r1, r4, #32
    str r6, [r1, r5, lsl #2]
    bl gyro_drain
    bl validate
    cmp r0, #0
    bne finish
    add r1, r4, #112
    str r2, [r1, r5, lsl #2]
    cmp r2, r6
    bne stale
    ldr r1, g_ghead
    cmp r1, r6
    bne stale
    cmp r5, #0
    beq progressed
    add r1, r4, #32
    sub r3, r5, #1
    ldr r1, [r1, r3, lsl #2]
    cmp r1, r6
    ldreq r1, [r4, #28]
    addeq r1, r1, #1
    streq r1, [r4, #28]
progressed:
    add r5, r5, #1
    str r5, [r4, #8]
    mov r0, #20
    ldr ip, =0xC01F5244
    blx ip
    cmp r5, #20
    blo loop
    mov r0, #1
    ldr r1, g_gcount
    cmp r1, #0
    moveq r0, #2
    b finish
stale:
    mov r0, #7
finish:
    str r0, [r4, #4]
    ldr r1, g_gcount
    str r1, [r4, #16]
    ldr r1, g_padbad
    str r1, [r4, #20]
    ldr r1, =0x50414347
    str r1, [r4]
    pop {r4-r10, pc}

/* Leaf: r0 status, r2 validated head. Never dereference an untrusted pointer. */
validate:
    ldr r1, =0xC31E23CC
    ldr r1, [r1]
    mov r0, #3
    cmp r1, #0
    bxeq lr
    mov r0, #4
    ldr r2, =0x2E006004
    cmp r1, r2
    bxne lr
    ldr r1, [r1, #0x60]
    mov r0, #5
    ldr r2, =0x2E00644C
    cmp r1, r2
    bxne lr
    ldr r2, [r1]
    mov r0, #6
    sub r3, r2, r1
    cmp r3, #8
    bxlo lr
    movw ip, #0x12C0
    cmp r3, ip
    bxhi lr
    tst r3, #7
    bxne lr
    mov r0, #0
    bx lr

/* Shared producer ABI: claim(r0 wanted) -> r0 address, r1 granted;
 * commit(r0 count). Preserve r4-r11, never change the source cursor. */
stream_claim:
    ldr r2, =STATE
    ldr r3, [r2, #12]
    ldr r1, =CAPACITY
    sub r1, r1, r3
    cmp r1, r0
    movhi r1, r0
    /* Account only the refused remainder, once; drain retries after a partial
     * claim and asks again with exactly that remainder. */
    cmp r1, #0
    ldreq ip, [r2, #24]
    addeq ip, ip, r0
    streq ip, [r2, #24]
    ldr r0, =OUTPUT
    add r0, r0, r3, lsl #3
    bx lr
stream_commit:
    ldr r2, =STATE
    ldr r3, [r2, #12]
    add r3, r3, r0
    str r3, [r2, #12]
    bx lr

/* Override is an assembler expression, not a firmware descriptor address.
 * movw/movt need an absolute constant, supplied relative to CODE by caller. */
#ifndef CODE
#error "CODE must name the owned payload address"
#endif
#define GYRO_DESC_PTR (CODE + descriptor_ptr - capture)
#include "../../gyro/gyro_drain.S"
.balign 4
g_ghead: .word -1
g_gcount: .word 0
g_padbad: .word 0
descriptor_ptr: .word 0
descriptor: .space 0x60
descriptor_ring: .word 0
.ltorg
#if (CODE & 3) || (CODE < STATE + 256 && STATE < CODE + 4096) || (CODE < OUTPUT + CAPACITY*8 && OUTPUT < CODE + 4096)
#error "unaligned code or overlapping owned extents"
#endif
