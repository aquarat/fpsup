/* OFFLINE ONLY. Exact 3572-byte predecessor -> scratch guard candidate.
 * Entered by BX at reviewed next_round; no universal worker entry ABI.
 * STATUS is temporary owned staging, including descriptor at +16.
 * Candidate RECORD is retained inside the new allocation. Never self-free.
 */
.syntax unified
.arm
.text
.global entry
entry:
    push {r4-r10, lr}
    ldr r5, =STATUS
    ldr r0, [r5]
    ldr r1, =COOKIE
    cmp r0, r1
    bne abort
    ldr r0, =0xC37588BC
    ldm r0, {r1-r3}
    ldr r6, =POOL
    cmp r1, r6
    bne abort
    ldr r0, =0x100000
    cmp r2, r0
    bne abort
    ldr r7, =OLD
    cmp r3, r7
    bne abort
    add r0, r6, #0x1000
    cmp r4, r0
    bne abort
    ldr r0, [r4]
    ldr r1, =0x4C485356
    cmp r0, r1
    bne abort
    ldr r0, [r4, #0x80]
    cmp r0, #0
    bne abort
    ldr r0, [r4, #0xC0]
    ldr r1, =STUB
    cmp r0, r1
    bne abort
    ldr r8, =EXPECTED
    mov r9, r7
    ldr r10, =3572
verify_old:
    ldr r0, [r8], #4
    ldr r1, [r9], #4
    cmp r0, r1
    bne abort
    subs r10, r10, #4
    bne verify_old
    add r0, r5, #16
    mov r1, #0
    ldr r2, =NEW_SIZE
    mov r3, #0
    ldr ip, =0xC001D740
    blx ip
    add r0, r5, #16
    ldr ip, =0xC001D7F0
    blx ip
    cmp r0, #0
    beq refused
    mov r6, r0
    /* Audited allocator supplies alignment/bounds; reject malformed results. */
    tst r6, #63
    bne release
    ldr r8, =SOURCE
    mov r9, r6
    ldr r10, =NEW_SIZE
copy:
    ldr r0, [r8], #4
    str r0, [r9], #4
    subs r10, r10, #4
    bne copy
    ldr r8, =SOURCE
    mov r9, r6
    ldr r10, =NEW_SIZE
verify_new:
    ldr r0, [r8], #4
    ldr r1, [r9], #4
    cmp r0, r1
    bne release
    subs r10, r10, #4
    bne verify_new
    ldr r8, =RECORD
    add r8, r6, r8
    add r0, r5, #16
    ldm r0, {r0-r3}
    stm r8, {r0-r3}          @ retained descriptor: ptr,class,ptr,size
    ldr r0, =COOKIE
    str r0, [r8, #16]        @ immutable generation token for this trial
    str r7, [r8, #20]        @ retained predecessor, never freed here
    mov r0, #1
    str r0, [r8, #24]        @ PREPARED, not proof of candidate execution
    ldr ip, =0xC000E91C
    blx ip
    ldr ip, =0xC000EABC
    blx ip
    dsb sy
    isb sy
    ldr r9, =0xC37588C4
    ldr r0, [r9]
    cmp r0, r7
    bne release
publish:
    str r6, [r9]            @ ONLY authoritative publication word
    dsb sy
    str r6, [r5, #4]        @ diagnostic hint, not commit/ack
    ldr r0, =NEW_SERVE
    add ip, r6, r0
    pop {r4-r10, lr}
unwind:
    pop {r4-r10, lr}        @ discard exactly old serve's frame
    bx ip                   @ new serve establishes one replacement frame
release:
    add r0, r5, #16         @ cleanup executes outside candidate
    mov r1, #2
    ldr ip, =0xC001D7A0
    blx ip
    mov r0, #0
    str r0, [r5, #16]       @ free leaves stale pointers; invalidate ours
    str r0, [r5, #24]
refused:
    mov r0, #3
    str r0, [r5, #8]
abort:
    pop {r4-r10, lr}
    ldr ip, =(OLD + 292)
    bx ip                   @ keep the original serve frame on abort
    .ltorg
