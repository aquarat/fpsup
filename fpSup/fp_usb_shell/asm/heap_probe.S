.syntax unified
.arm
.text
#include "../firmware/loader.h"

/* Finite allocator/execution experiment, NOT a loader or resident payload.
 * No file loading, hooks, tasks, settings or fixed scratch addresses. The
 * caller must own and publish this entire body before calling heap_probe.
 * Firmware calls use the selected loader ABI; placements are caller-owned.
 *
 * Saves/restores even a stock caller's 4-byte-misaligned SP. Descriptor lives
 * on that stack. Only the leaf below runs from the allocation; it returns
 * before H_FREE. Result data stays beside this body, never in freed storage.
 * The caller must restore any borrowed firmware bytes AFTER copying results.
 * Offline tests stub allocator/cache services: no camera execution established.
 */
.macro CALL_FW target
    movw    ip, #:lower16:\target
    movt    ip, #:upper16:\target
    blx     ip
.endm

.global heap_probe, heap_leaf, heap_leaf_end, heap_result, heap_probe_end
heap_probe:
    push    {r4-r10, lr}
    mov     r8, sp
    bic     sp, sp, #7
    sub     sp, sp, #16
    mov     r7, sp
    adr     r4, .Lresult
    mov     r0, #0
    mov     r1, #0
1:  str     r0, [r4, r1]
    add     r1, r1, #4
    cmp     r1, #64
    blo     1b
    str     r0, [r7]
    str     r0, [r7, #4]
    str     r0, [r7, #8]
    str     r0, [r7, #12]
    movw    r0, #0x5046
    movt    r0, #0x5845              @ FPEX
    str     r0, [r4]
    mov     r0, #1
    str     r0, [r4, #4]            @ result ABI version
    str     r0, [r4, #8]            @ status 1: no allocation yet
    mov     r2, #0x1000
    str     r2, [r4, #16]
    movw    r6, #:lower16:(.Lleaf_end - .Lleaf)
    str     r6, [r4, #20]
    mov     r0, r7
    mov     r1, #0                  @ USER class, never RAW
    mov     r3, #0
    CALL_FW FW_H_GET
    mov     r0, r7
    CALL_FW FW_H_ADDR
    movs    r5, r0
    beq     probe_return           @ match existing loader: no free on null
    str     r5, [r4, #12]
    mov     r0, #2                 @ status 2: unusable alignment
    str     r0, [r4, #8]
    tst     r5, #3
    bne     probe_free
    adr     r0, .Lleaf
    mov     r1, r5
    mov     r2, r6
2:  ldr     r3, [r0], #4
    str     r3, [r1], #4
    subs    r2, r2, #4
    bne     2b
    str     r5, [r4, #28]           @ expected execution address
    CALL_FW FW_DCACHE
    CALL_FW FW_ICACHE
    mov     r0, r4
    blx     r5
    str     r0, [r4, #40]           @ actual leaf return value
    mov     r0, #3
    str     r0, [r4, #8]            @ returned from allocated leaf
probe_free:
    mov     r0, r7
    mov     r1, #2
    CALL_FW FW_H_FREE
    mov     r0, #1
    str     r0, [r4, #44]           @ free call returned (not allocator status)
probe_return:
    mov     r0, r4                  @ caller may copy result before restoration
    mov     sp, r8
    pop     {r4-r10, pc}

/* All references within this copied body are PC-relative or through r0. */
heap_leaf:
.Lleaf:
    adr     r1, .Lleaf
    str     r1, [r0, #24]
    mov     r1, sp
    str     r1, [r0, #32]
    movw    r1, #0x4148
    movt    r1, #0x5045              @ execution marker, written only by leaf
    str     r1, [r0, #36]
    movw    r0, #0x4B4F
    movt    r0, #0x2159              @ OKY! return marker
    bx      lr
heap_leaf_end:
.Lleaf_end:
.balign 4
heap_result:
.Lresult:
    .space 64
heap_probe_end:
