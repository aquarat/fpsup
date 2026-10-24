/* OFFLINE QUIESCENT MODEL ONLY. FSB entry r0=owned block, r1=owned svc.
 * No live admission mechanism is supplied. Exclusive eight-byte claim; no
 * observer or chaining. The veneer replays the level-success mov and branch.
 */
.syntax unified
.arm
.text
/* Only `entry` is global: `adr` to a preemptible (global) symbol forces a
 * R_ARM_ALU_PC_G0 relocation the card loader's armasm cannot apply, so the
 * replay/table labels stay local and are read via armasm.symbols() by offset. */
.global entry
.equ SITE, 0xC0509730
.equ RESUME, 0xC0509748
entry:
    push {r4-r8, lr}
    sub sp, sp, #8
    mov r4, r0
    mov r5, r1
    adr r8, result
    ldr r0, [r8]
    cmp r0, #0
    bne done
    mov r0, #1
    str r0, [r8]                     @ one attempt in this owned product block
    ldr r6, =SITE
    adr r7, veneer
    tst r7, #3
    bne refuse
    ldr r0, =0x44400000
    cmp r4, r0
    blo refuse
    add r0, r7, #12                 @ entire veneer, direct USER address only
    cmp r0, r7
    blo refuse
    ldr r1, =0x46400100
    cmp r0, r1
    bhi refuse
    adr r3, stock
    ldm r3, {r0, r1}
    ldr r2, [r6]
    cmp r2, r0
    ldreq r2, [r6, #4]
    cmpeq r2, r1
    bne refuse                       @ do not invoke claim's stale-word repair
    mov r0, #2                      @ SL_EXCL, stack argument five
    str r0, [sp]
    mov r0, r5
    mov r1, r6
    mov r2, #8                      @ one claim includes BOTH displaced words
    ldr ip, [r5, #8]
    blx ip
    cmp r0, #0
    bne refuse
    mov r0, r5
    ldr ip, [r5, #24]               @ resident veneer publication BEFORE arming
    blx ip
    str r7, [r6, #4]               @ dangerous intermediate state: quiescent ONLY
    ldr r0, =0xE51FF004             @ ldr pc,[pc,#-4]; LR and flags untouched
    str r0, [r6]
    mov r0, r5
    ldr ip, [r5, #24]
    blx ip
    mov r0, #2
    str r0, [r8]
    b done
refuse:
    mov r0, #3
    str r0, [r8]
done:
    mov r0, #0                      @ SL_KEEP, including uncertain/refused state
    add sp, sp, #8
    pop {r4-r8, pc}
    .ltorg
.balign 4
veneer:
    mov r2, #0                      @ exact first displaced instruction (no S)
    ldr pc, [pc, #-4]               @ replay B to its original ABSOLUTE target
    .word RESUME
stock:
    .word 0xE3A02000, 0xEA000003
result:
    .word 0
