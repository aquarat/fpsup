/* fp L 3.02 finite cave-free string-site transaction.
 * P: caller-owned 1 KiB parameters; B: caller-owned 16 KiB task snapshot.
 * command +0: 0 inspect, 1 stock->owned, 2 owned->stock, 3 finite roundtrip.
 * Command 3 calls a verified finite checker at owner+3000, then restores all
 * six stock words BEFORE releasing I/F. State +4: 2 success,
 * 0x10 topology, 0x11 context, 0x12 TCB/frame, 0x13 interrupted site,
 * 0x14 site ownership, 0x15 request. No retry, allocation, wait or reclamation.
 * Owner +76, entries +64/+68/+72. All three sites checked BEFORE any write.
 * Whole shared string leaves are replayed by the owned layer, so a task inside
 * a layer may finish after removal: its allocation MUST stay retained.
 * A caller must publish and verify owned code before requesting installation.
 */
.syntax unified
.arm
.text
#ifdef PRODUCER_TRACE
#define SITE_COUNT 2
#define JUMP_WORD 0xE51FF004
#define ENTRY_LIMIT 0x4000
#else
#define SITE_COUNT 3
#define JUMP_WORD 0xF000F8DF
#define ENTRY_LIMIT 0x2000
#endif
#if !defined(RUNTIME_ARGS) && (!defined(P) || !defined(B))
#error P and B must name reserved storage
#endif
.global entry
entry:
    push {r4-r11, lr}
    mov r11, sp
    bic sp, sp, #7
#if defined(RUNTIME_ARGS)
    mov r4, r0                     @ owned parameters and snapshot supplied by caller
    mov r7, r1
#else
    ldr r4, =P
#endif
    mrs r10, cpsr
    str r10, [r4, #8]
    mov r0, #1
    str r0, [r4, #4]
    mov r0, #0
    str r0, [r4, #24]
    str r0, [r4, #32]
    str r0, [r4, #36]
    str r0, [r4, #40]
    and r0, r10, #0x1f
    cmp r0, #0x13
    bne bad_context
    cpsid if
    mrc p15, 0, r0, c0, c0, 0
    str r0, [r4, #12]
    ldr r1, =0x410FC075
    cmp r0, r1
    bne bad_cpu
    mrc p15, 0, r0, c0, c0, 5
    str r0, [r4, #16]
    cmp r0, #0x80000000
    bne bad_cpu
    mrc p15, 1, r0, c9, c0, 2
    str r0, [r4, #20]
    tst r0, #0x03000000             @ Cortex-A7 cluster: exactly one CPU
    bne bad_cpu
    ldr r0, =0xC3033268
    ldr r0, [r0]
    cmp r0, #0
    bne bad_context
    ldr r0, =0xC3000094
    ldr r0, [r0]
    cmp r0, #0
    bne bad_context
    ldr r0, =0xC3000098
    ldr r9, [r0]
    str r9, [r4, #28]
    ldr r5, =0xC30008BC             @ TCB(id 1); id 500 is included
    mov r6, #1
#if !defined(RUNTIME_ARGS)
    ldr r7, =B
#endif
scan:
    str r6, [r7]
    ldrb r0, [r5, #0x23]
    str r0, [r7, #4]
    cmp r0, #0
    beq next
    ldr r1, [r5, #8]
    cmp r1, r6
    bne bad_task
    ldr r1, [r5, #0x18]
    ldr r2, [r5, #0x74]
    ldr r3, [r5, #0x78]
    str r1, [r7, #8]
    str r2, [r7, #12]
    str r3, [r7, #16]
    cmp r0, #8
    beq dormant
    cmp r0, #1
    cmpne r0, #2
    cmpne r0, #4
    cmpne r0, #6
    bne bad_task
    cmp r5, r9
    beq current
    cmp r1, #0xD0
    blo bad_task
    cmp r1, #0x1000000
    bhi bad_task
    tst r2, #3
    bne bad_task
    tst r3, #3
    bne bad_task
    subs ip, r2, r1
    blo bad_task
    cmp r3, ip                     @ SP >= stack bottom
    blo bad_task
    sub r0, r2, #0xD0
    cmp r3, r0                     @ entire saved frame <= stack top
    bhi bad_task
    @ Stack extent must be within firmware RAM or known USER DRAM alias.
    ldr r0, =0xC3000000
    cmp ip, r0
    blo user_stack
    cmp r2, #0xD0000000
    bhi bad_task
    b frame
user_stack:
    ldr r0, =0x44400000
    cmp ip, r0
    blo bad_task
    ldr r0, =0x46400100
    cmp r2, r0
    bhi bad_task
frame:
    ldr r0, [r3, #0xC4]
    ldr r8, [r3, #0xCC]
    str r0, [r7, #20]
    str r8, [r7, #24]
    and r1, r0, #31
    cmp r1, #0x13
    cmpne r1, #0x10
    cmpne r1, #0x1f
    bne bad_task
    tst r8, #1
    bne bad_task
    tst r0, #0x20
    bne thumb_pc
    tst r8, #3
    bne bad_task
thumb_pc:
#ifdef PRODUCER_TRACE
    @ Entry-only exclusion is insufficient for producer state initialization.
    @ Reject the WHOLE writer and lookup, including both native continuations.
    ldr r0, =0xC031EBF8
    sub r0, r8, r0
    cmp r0, #0xD0
    blo busy_pc
#else
    @ Conservatively refuse PC == site as well as every displaced halfword.
    adr r0, sites
    mov r1, #3
pc_loop:
    ldr r2, [r0], #12
    sub r2, r8, r2
    cmp r2, #8
    blo busy_pc
    subs r1, r1, #1
    bne pc_loop
#endif
    ldr r0, [r4, #40]
    add r0, r0, #1
    str r0, [r4, #40]
    b next
current:
    mov r0, #1
    str r0, [r4, #36]
    str r0, [r7, #28]
    b next
dormant:
    mov r0, #2
    str r0, [r7, #28]
next:
    str r6, [r4, #24]
    add r5, r5, #132
    add r7, r7, #32
    add r6, r6, #1
    cmp r6, #500
    bls scan
    ldr r0, [r4, #36]
    cmp r0, #1
    bne bad_context
    ldr r5, [r4]
#ifdef PRODUCER_TRACE
    cmp r5, #1
    bne bad_request                @ installation only; shared journal owns removal
#else
    cmp r5, #0
    beq success
    cmp r5, #3
    bhi bad_request
#endif
    ldr r6, [r4, #76]              @ checked retained 64-KiB USER owner
    ldr r0, =0xFFFF
    tst r6, r0
    bne bad_request
    ldr r0, =0x44400000
    cmp r6, r0
    blo bad_request
    ldr r0, =0x463F0000
    cmp r6, r0
    bhi bad_request
    add r7, r4, #64
    adr r8, sites
    mov r9, #SITE_COUNT
verify:
    ldr r3, [r7], #4
    tst r3, #3
    bne bad_request
    sub r0, r3, r6
    cmp r0, #0x1000
    blo bad_request
    cmp r0, #ENTRY_LIMIT
    bhs bad_request
    ldm r8!, {r0-r2}
    cmp r5, #2
    ldreq r1, =JUMP_WORD
    moveq r2, r3
    ldr ip, [r0]
    cmp ip, r1
    bne foreign
    ldr ip, [r0, #4]
    cmp ip, r2
    bne foreign
    subs r9, r9, #1
    bne verify
    @ No scheduling/native calls between verification and six stores.
    add r7, r4, #64
    adr r8, sites
    mov r9, #SITE_COUNT
write_sites:
    ldr r3, [r7], #4
    ldm r8!, {r0-r2}
    cmp r5, #2
    ldrne r1, =JUMP_WORD
    movne r2, r3
    str r2, [r0, #4]
    str r1, [r0]
    subs r9, r9, #1
    bne write_sites
    @ Audited routines preserve incoming I/F masks; D publication before I.
    ldr ip, =0xC000E91C
    blx ip
    ldr ip, =0xC000EABC
    blx ip
    cmp r5, #3
    bne success
    add ip, r6, #0x3000
    blx ip                         @ finite checker, all paths return
roundtrip_restore:
    mov r5, #2
    add r7, r4, #64
    adr r8, sites
    mov r9, #SITE_COUNT
    b write_sites                  @ restore before any scheduler can run
success:
    mov r0, #2
    b done
bad_cpu:
    mov r0, #0x10
    b done
bad_context:
    mov r0, #0x11
    b done
bad_task:
    mov r0, #0x12
    b task_error
busy_pc:
    mov r0, #0x13
task_error:
    str r6, [r4, #32]
    b done
foreign:
    mov r0, #0x14
    b done
bad_request:
    mov r0, #0x15
done:
    dmb sy
    str r0, [r4, #4]
    msr cpsr_c, r10
    mov sp, r11
    pop {r4-r11, pc}
    .ltorg
    .balign 4
sites:
#ifdef PRODUCER_TRACE
    .word 0xC031EBF8, 0xE92D0030, 0xE1A0C000
    .word 0xC031EC58, 0xE92D0070, 0xE1A0C000
#else
    .word 0xC05E1D38, 0x3FFFF1B1, 0x6902BF1C
    .word 0xC05E23A8, 0x428A6942, 0x6900D805
    .word 0xC05E23C0, 0x69406902, 0x1A501812
#endif
