/* Shared finite conditional capture body; firmware inputs supplied by adapter.
 * fp L default adapter has live evidence; coherence remains unproven.
 * Caller task, finite 20 observations and twenty 20-ms delays on success.
 * Errors/window failure/capacity loss stop before that batch's delay. Not a
 * deadline: scheduling gaps, hidden laps and cache visibility are unbounded.
 * Optional cooperative stop is work-bounded, never a scheduler deadline.
 * No recording, task creation, firmware stores, file I/O, installation or resume.
 * See docs/FPL_GYRO_DRAIN_COHERENCE.md for the conditional proof/limitations.
 *
 * Caller owns writable CODE[4096], STATE[2048], OUTPUT[CAPACITY*8] and stack.
 * Exact runtime P/R are checked before/after each shared drain; an owned view
 * freezes R and an owned latch freezes H. Prior cursor resets to -1 on entry.
 * Conditional test: a=(post-H) mod 600 < slack=600-d, d=(H-prior) mod 600.
 * Strict < reserves an unpublished next record. NEVER proves no hidden laps.
 * Cursor after drain is H, not post. Rejected batch bytes remain tentative.
 *
 * STATE header u32 offsets:
 * 0 magic GLAT (written last), 4 final (100 completed, else last row status),
 * 8 rows, 12 appended, 16 observed, 20 padbad, 24 drops, 28 conditional prefix,
 * 32 delays, 36 proven-valid (always zero), 40 schema=1, 44 capacity; rest zero.
 * Rows: offset 64, stride 80, twenty rows, then zero guard to 2048.
 * Row u32 offsets: 0 status; 4 prior; 8 latch; 12 post; 16 consumed;
 * 20/24/28 pre P/R/H; 32/36/40 post P/R/H; 44 output start;
 * 48 appended delta; 52 observed delta; 56 dropped delta; 60 pad delta;
 * 64 advance; 68 slack; 72 prefix after; 76 reserved zero.
 * Status: 1 armed, 2 no observed delta, 3 conditional_window_pass,
 * 4 possible overwrite, 5 capacity loss (window passed), 10 unavailable P,
 * 11 invalid P, 12 invalid R, 13 invalid head, 14 invalid cursor/provenance.
 * Zero unread snapshots/metrics mean unattempted, not a valid observation.
 */
#ifndef RUNTIME_REFS
#if !defined(CODE) || !defined(STATE) || !defined(OUTPUT) || !defined(CAPACITY)
#error "explicit owned CODE/STATE/OUTPUT/CAPACITY required"
#endif
#if CAPACITY < 1 || CAPACITY > 12000
#error "capacity must be 1..12000"
#endif
#if CODE < 0 || CODE > 0xFFFFF000 || STATE < 0 || STATE > 0xFFFFF800 || OUTPUT < 0 || OUTPUT > 0xFFFFFFFF - CAPACITY*8
#error "owned extent outside 32-bit address space"
#endif
#if (CODE & 3) || (STATE & 3) || (OUTPUT & 7)
#error "unaligned owned extents"
#endif
#if (CODE < STATE+2048 && STATE < CODE+4096) || (CODE < OUTPUT+CAPACITY*8 && OUTPUT < CODE+4096) || (STATE < OUTPUT+CAPACITY*8 && OUTPUT < STATE+2048)
#error "overlapping owned extents"
#endif
#endif
#if !defined(LAT_DESC_ROOT) || !defined(LAT_DESC_SLOT) || !defined(LAT_RING_BASE) || !defined(LAT_DELAY)
#error "explicit latched descriptor slot/root, ring and delay profile required"
#endif
#ifndef LAT_CANCEL
#define LAT_CANCEL 0
#endif
#if LAT_CANCEL != 0 && LAT_CANCEL != 1
#error "LAT_CANCEL must be 0 or 1"
#endif
.syntax unified
.arm
.text
.global capture
capture:
.Lcapture:
    push {r4-r10, lr}
#ifdef RUNTIME_REFS
    /* Echo's r0 is argv, NEVER a parameter pointer. The caller fills the
     * local table before D/I publication. No stores until validation passes.
     * Table: state, state bytes, output, output bytes, capacity. */
    bl validate_refs
    cmp r0, #0
    popne {r4-r10, pc}
    ldr r4, runtime_state
#else
    ldr r4, =STATE
#endif
    mov r0, #0
    mov r1, #0
1:  str r0, [r4, r1]
    add r1, r1, #4
    cmp r1, #2048
    blo 1b
    str r0, g_gcount
    str r0, g_padbad
    str r0, g_latched_head
    mvn r0, #0
    str r0, g_ghead
#ifdef RUNTIME_REFS
    ldr r0, =descriptor - (.Ldescriptor_pc + 8)
.Ldescriptor_pc:
    add r0, pc, r0
#else
    adr r0, descriptor
#endif
    str r0, descriptor_ptr
    ldr r0, =LAT_RING_BASE
    str r0, descriptor_ring
    mov r0, #1
    str r0, [r4, #40]
#ifdef RUNTIME_REFS
    ldr r0, runtime_capacity
#else
    ldr r0, =CAPACITY
#endif
    str r0, [r4, #44]
    mov r5, #0
    add r6, r4, #64
loop:
#if LAT_CANCEL
    ldr r0, g_cancel_request
    cmp r0, #0
    movne r0, #101
    bne finish
#endif
    ldr r2, g_ghead
    str r2, [r6, #4]
    str r2, [r6, #16]
    ldr r0, [r4, #12]
    str r0, [r6, #44]
    cmn r2, #1
    beq cursor_ok
    bl valid_head
    cmp r0, #0
    movne r0, #14
    bne row_done
cursor_ok:
    add r7, r6, #20
    bl snapshot
    cmp r0, #0
    bne row_done
    str r2, [r6, #8]
    str r2, g_latched_head
    ldr r8, g_gcount
    ldr r9, g_padbad
    ldr r10, [r4, #24]
    bl gyro_drain
    ldr r0, g_ghead
    str r0, [r6, #16]
    add r7, r6, #32
    bl snapshot
    mov r7, r0
    ldr r0, [r6, #40]
    str r0, [r6, #12]
    ldr r0, [r4, #12]
    ldr r1, [r6, #44]
    sub r0, r0, r1
    str r0, [r6, #48]
    ldr r0, g_gcount
    sub r0, r0, r8
    str r0, [r6, #52]
    ldr r0, g_padbad
    sub r0, r0, r9
    str r0, [r6, #60]
    ldr r0, [r4, #24]
    sub r0, r0, r10
    str r0, [r6, #56]
    mov r0, r7
    cmp r0, #0
    bne row_done
    ldr r1, [r6, #8]
    ldr r2, [r6, #16]
    cmp r1, r2
    movne r0, #14
    bne row_done
    ldr r2, [r6, #12]
    subs r2, r2, r1
    movw r3, #4800
    addlo r2, r2, r3
    lsr r2, r2, #3
    str r2, [r6, #64]
    ldr r1, [r6, #52]
    movw r3, #600
    sub r3, r3, r1
    str r3, [r6, #68]
    ldr r0, [r6, #4]
    cmn r0, #1
    moveq r0, #1
    beq row_done
    cmp r1, #0
    moveq r0, #2
    beq row_done
    cmp r2, r3
    movhs r0, #4
    bhs row_done
    ldr r1, [r4, #28]
    ldr r2, [r6, #48]
    add r1, r1, r2
    str r1, [r4, #28]
    mov r0, #3
    ldr r1, [r6, #56]
    cmp r1, #0
    movne r0, #5
row_done:
    str r0, [r6]
    ldr r1, [r4, #28]
    str r1, [r6, #72]
    add r5, r5, #1
    str r5, [r4, #8]
    cmp r0, #4
    bhs finish
#if LAT_CANCEL
cancel_after_ledger:
    ldr r0, g_cancel_request
    cmp r0, #0
    movne r0, #101
    bne finish
#endif
    mov r0, #20
    ldr ip, =LAT_DELAY
    blx ip
    str r5, [r4, #32]
    add r6, r6, #80
    cmp r5, #20
    blo loop
    mov r0, #100
finish:
    str r0, [r4, #4]
    ldr r1, g_gcount
    str r1, [r4, #16]
    ldr r1, g_padbad
    str r1, [r4, #20]
    ldr r1, =0x54414C47
    str r1, [r4]
    pop {r4-r10, pc}

/* Snapshot writes raw observations as they become available. Never follows
 * an untrusted pointer. r7 -> three owned words, r2 = head on success. */
snapshot:
    ldr r1, =LAT_DESC_SLOT
    ldr r1, [r1]
    str r1, [r7]
    mov r0, #10
    cmp r1, #0
    bxeq lr
    mov r0, #11
    ldr r2, =LAT_DESC_ROOT
    cmp r1, r2
    bxne lr
    ldr r1, [r1, #0x60]
    str r1, [r7, #4]
    mov r0, #12
    ldr r2, =LAT_RING_BASE
    cmp r1, r2
    bxne lr
    ldr r2, [r1]
    str r2, [r7, #8]
valid_head:
    mov r0, #13
    ldr r1, =LAT_RING_BASE
    sub r3, r2, r1
    cmp r3, #8
    bxlo lr
    movw ip, #4800
    cmp r3, ip
    bxhi lr
    tst r3, #7
    bxne lr
    mov r0, #0
    bx lr

stream_claim:
#ifdef RUNTIME_REFS
    ldr r2, runtime_state
#else
    ldr r2, =STATE
#endif
    ldr r3, [r2, #12]
#ifdef RUNTIME_REFS
    ldr r1, runtime_capacity
#else
    ldr r1, =CAPACITY
#endif
    sub r1, r1, r3
    cmp r1, r0
    movhi r1, r0
    cmp r1, #0
    ldreq ip, [r2, #24]
    addeq ip, ip, r0
    streq ip, [r2, #24]
#ifdef RUNTIME_REFS
    ldr r0, runtime_output
#else
    ldr r0, =OUTPUT
#endif
    add r0, r0, r3, lsl #3
    bx lr
stream_commit:
#ifdef RUNTIME_REFS
    ldr r2, runtime_state
#else
    ldr r2, =STATE
#endif
    ldr r3, [r2, #12]
    add r3, r3, r0
    str r3, [r2, #12]
    bx lr

#ifdef RUNTIME_REFS
/* Select addresses of the owned pointer/head slots, not their contents. */
#define GYRO_DESC_LOCAL descriptor_ptr
#define GYRO_LATCH_LOCAL g_latched_head
#else
#define GYRO_DESC_PTR (CODE + descriptor_ptr - capture)
#define GYRO_LATCHED_HEAD_PTR (CODE + g_latched_head - capture)
#endif
#include "gyro_drain.S"
#ifdef RUNTIME_REFS
#undef GYRO_DESC_LOCAL
#undef GYRO_LATCH_LOCAL

/* Validate complete reservations (including guards), not just written bytes.
 * Bounds are USER-address-domain checks, not proof of ownership: host verifies
 * the existing worker pool reservation. Reject firmware/MMIO and overflow.
 * r4-r10 are saved by capture. No memory writes or external calls here. */
validate_refs:
    mov r0, #15
    adr r3, .Lcapture
    adds r7, r3, #4096
    bcs refs_return
    cmp r3, #0x40000000
    bxlo lr
    cmp r7, #0x80000000
    bxhi lr
    ldr r4, runtime_state
    ldr r5, runtime_output
    ldr r6, runtime_capacity
    cmp r6, #1
    bxlo lr
    movw ip, #12000
    cmp r6, ip
    bxhi lr
    tst r4, #3
    bxne lr
    tst r5, #7
    bxne lr
    cmp r4, #0x40000000
    bxlo lr
    cmp r5, #0x40000000
    bxlo lr
    ldr r1, runtime_state_bytes
    cmp r1, #2048
    bxne lr
    adds r8, r4, r1
    bcs refs_return
    cmp r8, #0x80000000
    bxhi lr
    ldr r2, runtime_output_bytes
    lsl r6, r6, #3
    add r6, r6, #1024
    cmp r2, r6
    bxlo lr
    adds r9, r5, r2
    bcs refs_return
    cmp r9, #0x80000000
    bxhi lr
    cmp r4, r7
    cmplo r3, r8
    bxlo lr
    cmp r5, r7
    cmplo r3, r9
    bxlo lr
    cmp r4, r9
    cmplo r5, r8
    bxlo lr
    mov r0, #0
refs_return:
    bx lr

.balign 4
runtime_refs:
runtime_state: .word 0
runtime_state_bytes: .word 0
runtime_output: .word 0
runtime_output_bytes: .word 0
runtime_capacity: .word 0
runtime_refs_end:
#endif
.balign 4
g_ghead: .word -1
g_gcount: .word 0
g_padbad: .word 0
g_latched_head: .word 0
descriptor_ptr: .word 0
descriptor: .space 0x60
descriptor_ring: .word 0
#if LAT_CANCEL
/* Single owner publishes a monotonic nonzero request. Never reset by capture.
 * Retention and one-shot invocation belong to the caller. No wall-time bound. */
g_cancel_request: .word 0
#endif
.ltorg
body_end:
