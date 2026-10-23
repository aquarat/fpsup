/* Shared retained wrapper, caller-owned zeroed 64 KiB. Retain for entire boot.
 * Entry r0 is its own address. No allocator for OWNED, no hooks or release.
 * Single external owner; no concurrent commands/multi-host exclusion claimed.
 * Explicit bindings select services, not proof of another firmware's ABI.
 * docs/FPL_GYRO_RETAINED_TASK.md specifies immutable/readback extents. */
#if !defined(RT_CREATE) || !defined(RT_ATTACH) || !defined(RT_REF_TSK) || !defined(RT_REF_FLG) || !defined(RT_DCACHE) || !defined(RT_ICACHE)
#error "explicit retained task create/attach/ref_tsk/ref_flg/cache bindings required"
#endif
#ifndef RT_RUNTIME_OWNED
#define RT_RUNTIME_OWNED 0
#endif
#if RT_RUNTIME_OWNED != 0 && RT_RUNTIME_OWNED != 1
#error "RT_RUNTIME_OWNED must be 0 or 1"
#endif
#if RT_RUNTIME_OWNED
#ifdef OWNED
#error "runtime owner cannot also be fixed"
#endif
#ifndef RT_CAPTURE_REFS
#error "runtime capture reference table offset required"
#endif
#if RT_CAPTURE_REFS < 0 || RT_CAPTURE_REFS > 4076 || (RT_CAPTURE_REFS & 3)
#error "invalid runtime capture reference table offset"
#endif
#else
#ifndef OWNED
#error "explicit synthetic owned reservation required"
#endif
#if OWNED < 0x40000000 || OWNED > 0x7FFF0000 || (OWNED & 0xFFFF)
#error "invalid synthetic owned extent"
#endif
#endif
#ifndef CAPTURE_FILE
#error "actual relocatable capture binary required"
#endif
#ifndef SLEEP_REASON
#define SLEEP_REASON 0
#endif
.syntax unified
.arm
.text
.global entry
.equ PHASE, 0
.equ HOLDER, 4
.equ BODY, 8
.equ VT, 0x10
.equ CAPTURE, 0x20
.equ DONE, 0x24
.equ ONCE, 0x28
.equ REPEATS, 0x2C
.equ OBJECT, 0x30
.equ TASK_ID, 0x34
.equ FLAG_ID, 0x38
.equ OBS, 0x100

/* Resident owner is data copied with the wrapper, never an address of staging.
 * Check it against this copy's PC before dereferencing it. Scratch must differ
 * from dst; no implicit argument/register ABI is added to resident entries. */
.macro RT_OWNER dst, scratch, failure
#if RT_RUNTIME_OWNED
    ldr \dst, .Lruntime_owner
    mov \scratch, pc
    lsr \scratch, \scratch, #16
    lsl \scratch, \scratch, #16
    cmp \dst, \scratch
    bne \failure
#else
    ldr \dst, =OWNED
#endif
.endm

entry:
#if RT_RUNTIME_OWNED
.Lruntime_entry:
#endif
    push {r4-r8, lr}
#if RT_RUNTIME_OWNED
    /* r0 must be the loader-resolved entry, not echo argv or a parameter ptr.
     * Validate all references before the first owned read/write/native call. */
    adr r5, .Lruntime_entry
    cmp r0, r5
    bne entry_return
    cmp r0, #0x40000000
    blo entry_return
    adds r8, r0, #0x3000
    bcs entry_return
    cmp r8, #0x80000000
    bhi entry_return
    add r5, r0, #0x1000
    ldr r4, [r5, #(runtime_owner - resident_image)]
    movw r6, #0xFFFF
    tst r4, r6
    bne entry_return
    ldr r6, =0x44400000
    cmp r4, r6
    blo entry_return
    adds r7, r4, #0x10000
    bcs entry_return
    ldr r6, =0x46400100
    cmp r7, r6
    bhi entry_return
    cmp r4, r8
    cmplo r0, r7
    blo entry_return
    add r6, r0, #0x2000
    ldr r7, =RT_CAPTURE_REFS
    add r6, r6, r7
    ldr r7, [r6]
    add r8, r4, #0x4000
    cmp r7, r8
    bne entry_return
    ldr r7, [r6, #4]
    cmp r7, #2048
    bne entry_return
    ldr r7, [r6, #8]
    add r8, r4, #0x5000
    cmp r7, r8
    bne entry_return
    ldr r7, [r6, #12]
    cmp r7, #11264
    bne entry_return
    ldr r7, [r6, #16]
    movw r8, #1200
    cmp r7, r8
    bne entry_return
#else
    ldr r4, =OWNED
#endif
    ldr r0, [r4, #PHASE]
    cmp r0, #0
    bne entry_return
    mov r0, #1                       @ create attempted, never reset on failure
    str r0, [r4, #PHASE]
    ldr r5, =resident_image - (.Lsource_pc + 8)
.Lsource_pc:
    add r5, pc, r5
    add r6, r4, #0x1000
    mov r7, #0x2000
copy:
    ldr r0, [r5], #4
    str r0, [r6], #4
    subs r7, r7, #4
    bne copy
#if RT_RUNTIME_OWNED
    add r0, r4, #0x1000
    ldr r0, [r0, #(runtime_owner - resident_image)]
    cmp r0, r4
    bne entry_return                 @ attempted owner remains retained
#endif
    add r0, r4, #VT
    str r0, [r4, #BODY]
#if RT_RUNTIME_OWNED
    ldr r0, =body_entry - resident_image + 0x1000
    add r0, r4, r0
#else
    ldr r0, =OWNED + body_entry - resident_image + 0x1000
#endif
    str r0, [r4, #(VT+0xC)]
    add r0, r4, #0x2000
    str r0, [r4, #CAPTURE]
    ldr ip, =RT_DCACHE
    blx ip
    ldr ip, =RT_ICACHE
    blx ip
    add r0, r4, #HOLDER
    mov r1, #6
    mov r2, #0x2000
#if RT_RUNTIME_OWNED
    ldr r3, =task_name - resident_image + 0x1000
    add r3, r4, r3
#else
    ldr r3, =OWNED + task_name - resident_image + 0x1000
#endif
    ldr ip, =RT_CREATE
    blx ip
    ldr r0, [r4, #HOLDER]
    cmp r0, #0
    beq entry_return
    str r0, [r4, #OBJECT]            @ fixed identity for this reservation
    ldr r1, [r0]
    str r1, [r4, #TASK_ID]
    ldr r1, [r0, #0xC]
    str r1, [r4, #FLAG_ID]
    mov r0, #2                       @ created, start status is still unknown
    str r0, [r4, #PHASE]
entry_return:
    pop {r4-r8, pc}
    .ltorg

    .org 0x1000
resident_image:
activate:
    push {r4, lr}
    RT_OWNER r4, ip, activate_return
    ldr r0, [r4, #PHASE]
    cmp r0, #2
    bne activate_return
    mov r0, #3                       @ irrevocable attach attempt
    str r0, [r4, #PHASE]
    ldr r0, [r4, #HOLDER]
    ldr r1, [r4, #OBJECT]
    cmp r0, r1
    bne activate_return
    cmp r0, #0
    beq activate_return
    ldr r2, [r0]
    ldr r1, [r4, #TASK_ID]
    cmp r2, r1
    bne activate_return
    ldr r2, [r0, #0xC]
    ldr r1, [r4, #FLAG_ID]
    cmp r2, r1
    bne activate_return
    add r0, r4, #HOLDER
    add r1, r4, #BODY
    ldr ip, =RT_ATTACH
    blx ip
    mov r0, #4                       @ returned, NOT a boolean attach status
    str r0, [r4, #PHASE]
activate_return:
    pop {r4, pc}

body_entry:
    push {r4, lr}
    mov r4, sp
    bic sp, sp, #7
    RT_OWNER r0, ip, body_return
    ldr r1, [r0, #ONCE]
    cmp r1, #0
    bne body_repeat
    mov r1, #1                       @ single native worker owns this guard
    str r1, [r0, #ONCE]              @ BEFORE capture initializes its results
    ldr ip, [r0, #CAPTURE]
    blx ip
    RT_OWNER r0, ip, body_return
    mov r1, #1
    str r1, [r0, #DONE]              @ capture returned, body epilogue still runs
    b body_return
body_repeat:
    ldr r1, [r0, #REPEATS]
    add r1, r1, #1
    str r1, [r0, #REPEATS]
body_return:
    mov sp, r4
    pop {r4, pc}

/* r0 = five-word destination. Refuse to dereference a changed holder.
 * Tuple: holder, task ID, historical body+4, active body+8, flag ID. */
identity:
    RT_OWNER ip, r2, 99f
    ldr r1, [ip, #HOLDER]
    str r1, [r0]
    mov r2, #0
    str r2, [r0, #4]
    str r2, [r0, #8]
    str r2, [r0, #12]
    str r2, [r0, #16]
    cmp r1, #0
    bxeq lr
    ldr r2, [ip, #OBJECT]
    cmp r1, r2
    bxne lr
    ldm r1, {r1-r3, ip}
    add r0, r0, #4
    stm r0, {r1-r3, ip}
99:
    bx lr

/* One sample, fixed 0x60 bytes; exactly one call of each query at most.
 * Outputs prefilled A5, skipped-status INT_MIN; zero task ID never means self. */
sample:
    push {r4-r6, lr}
    mov r4, r0
    mov r2, #24
    ldr r1, =0xA5A5A5A5
sample_fill:
    str r1, [r0], #4
    subs r2, r2, #1
    bne sample_fill
    mov r1, #0x80000000
    str r1, [r4, #0x14]
    str r1, [r4, #0x18]
    mov r0, r4
    bl identity
    RT_OWNER r5, ip, sample_after
    ldr r0, [r4]
    cmp r0, #0
    beq sample_after
    ldr r1, [r5, #OBJECT]
    cmp r0, r1
    bne sample_after
    ldr r0, [r4, #4]
    cmp r0, #0
    beq sample_flag
    add r1, r4, #0x1C
    ldr ip, =RT_REF_TSK
    blx ip
    str r0, [r4, #0x14]
sample_flag:
    ldr r0, [r4, #0x10]
    add r1, r4, #0x3C
    ldr ip, =RT_REF_FLG
    blx ip
    str r0, [r4, #0x18]
sample_after:
    add r0, r4, #0x48
    bl identity
    pop {r4-r6, pc}

observe:
    push {r4-r8, lr}
    RT_OWNER r4, ip, 99f
    add r5, r4, #OBS
    mov r0, #0
    str r0, [r5, #4]                @ record in progress, not a host lock
    ldr r0, [r5]
    add r0, r0, #1
    str r0, [r5]
    ldr r0, [r4, #PHASE]
    str r0, [r5, #8]
    ldr r0, [r4, #DONE]
    str r0, [r5, #12]
    ldr r0, [r4, #ONCE]
    str r0, [r5, #16]
    add r0, r5, #0x20
    bl sample
    add r0, r5, #0x80
    bl sample
    ldr r0, [r4, #PHASE]
    str r0, [r5, #0xE8]
    ldr r0, [r4, #DONE]
    str r0, [r5, #0xEC]
    ldr r0, [r4, #ONCE]
    str r0, [r5, #0xF0]
    ldr r0, =SLEEP_REASON
    str r0, [r5, #0xE4]
    mov r6, #0                     @ independent evidence bits; NEVER release
    ldr r0, [r4, #OBJECT]
    cmp r0, #0
    beq observe_flags
    ldr r1, [r5, #0x20]
    cmp r0, r1
    bne observe_flags
    ldr r0, [r4, #TASK_ID]
    ldr r1, [r5, #0x24]
    cmp r0, r1
    bne observe_flags
    ldr r0, [r4, #FLAG_ID]
    ldr r1, [r5, #0x30]
    cmp r0, r1
    bne observe_flags
    add r7, r5, #0x20
    mov r8, #0
identity_compare:
    ldr r0, [r7, r8]
    add r1, r7, #0x48
    ldr r1, [r1, r8]
    cmp r0, r1
    bne observe_flags
    add r1, r7, #0x60
    ldr r1, [r1, r8]
    cmp r0, r1
    bne observe_flags
    add r1, r7, #0xA8
    ldr r1, [r1, r8]
    cmp r0, r1
    bne observe_flags
    add r8, r8, #4
    cmp r8, #20
    bne identity_compare
    orr r6, r6, #1
observe_flags:
    ldr r0, [r5, #0x38]             @ flag status A
    ldr r1, [r5, #0x98]             @ flag status B
    orrs r0, r0, r1
    orreq r6, r6, #4
    ldr r0, [r5, #0x34]             @ task status A
    ldr r1, [r5, #0x94]
    orrs r0, r0, r1
    bne observe_finish
    ldr r0, [r4, #OBJECT]
    cmp r0, #0
    beq observe_finish
    add r0, r0, #4
    ldr r1, [r5, #0x3C]             @ task exinf A
    cmp r0, r1
    bne observe_finish
    ldr r1, [r5, #0x9C]
    cmp r0, r1
    bne observe_finish
    orr r6, r6, #2
    cmp r6, #7
    bne observe_finish
    ldr r0, [r5, #8]
    cmp r0, #4
    bne observe_sleep
    ldr r0, [r5, #0xE8]
    cmp r0, #4
    bne observe_sleep
    ldr r0, [r5, #12]
    ldr r1, [r5, #0xEC]
    cmp r0, #1
    cmpeq r1, #1
    bne observe_sleep
    ldr r0, [r5, #16]
    ldr r1, [r5, #0xF0]
    cmp r0, #1
    cmpeq r1, #1
    bne observe_sleep
    ldr r0, [r5, #0x28]             @ historical body must be this body
    add r1, r4, #BODY
    cmp r0, r1
    bne observe_sleep
    ldr r0, [r5, #0x2C]             @ active body detached in all four tuples
    cmp r0, #0
    bne observe_sleep
    ldr r0, [r5, #0x64]             @ flag pattern A
    ldr r1, [r5, #0xC4]
    and r0, r0, r1
    tst r0, #1
    orrne r6, r6, #8
observe_sleep:
    ldr r0, [r5, #0xE4]
    cmp r0, #0
    beq observe_finish
    ldr r1, [r5, #0x4C]             @ wait reason A
    cmp r0, r1
    bne observe_finish
    ldr r1, [r5, #0xAC]
    cmp r0, r1
    bne observe_finish
    ldr r0, [r5, #0x48]             @ exact waiting state, not combined state
    ldr r1, [r5, #0xA8]
    cmp r0, #4
    cmpeq r1, #4
    bne observe_finish
    ldr r0, [r5, #0x50]             @ no waited object / queued wake
    ldr r1, [r5, #0xB0]
    orr r0, r0, r1
    ldr r1, [r5, #0x54]
    orr r0, r0, r1
    ldr r1, [r5, #0xB4]
    orrs r0, r0, r1
    orreq r6, r6, #16
observe_finish:
    str r6, [r5, #0xE0]
    dmb sy
    mov r0, #1
    str r0, [r5, #4]
99:
    pop {r4-r8, pc}
task_name: .ascii "GyrKeep\0"
    .ltorg
#if RT_RUNTIME_OWNED
    .balign 4
runtime_owner:
.Lruntime_owner:
    .word 0
#endif
    .org 0x2000
capture_image:
    .incbin CAPTURE_FILE
    .org 0x3000
image_end:
