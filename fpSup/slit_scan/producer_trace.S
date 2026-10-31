/* Opt-in native queue-boundary trace, no installer. Code is position independent
 * in an owned 64KiB block, text at +1000, state at +8000. No staging references.
 * Pre/post instrumentation brackets the ORIGINAL native leaf under I/F exclusion.
 * Even rejection replays both displaced instructions and executes entry+8.
 * Frame allocation tolerates the firmware's incoming SP mod 8 == 4. */
.syntax unified
.arm
.text
.global pt_writer, pt_lookup
.macro trace name, kind, continuation, saved
\name:
    push {r0-r12, lr}
    mov r11, sp
    mrs r10, cpsr
    cpsid if
    bic sp, sp, #7
    sub sp, sp, #64
    str r10, [sp]
    str r11, [sp, #4]
    mov r0, pc
    lsr r0, r0, #16
    lsl r0, r0, #16
    add r0, r0, #0x8000
    mov r1, sp
    mov r2, #\kind
    bl pt_before
    ldm r11, {r0-r6}
    bl .Lreplay\@
    mrs r9, cpsr
    stm r11, {r0-r3}
    str ip, [r11, #48]
    str r0, [sp, #24]
    mov r0, pc
    lsr r0, r0, #16
    lsl r0, r0, #16
    add r0, r0, #0x8000
    mov r1, sp
    bl pt_after
    msr cpsr_f, r9
    msr cpsr_c, r10
    mov sp, r11
    pop {r0-r12, pc}
.Lreplay\@:
    push {\saved}
    mov ip, r0
    ldr pc, .Lcontinue\@
.Lcontinue\@:
    .word \continuation
.endm
trace pt_writer, 1, 0xC031EC00, "r4,r5"
trace pt_lookup, 2, 0xC031EC60, "r4,r5,r6"
