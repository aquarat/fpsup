/* Finite allocate/init/enter launcher. No activation, release or retry.
 * Loader ABI: r0 = this entry. One caller owns this writable staging image.
 * The embedded runtime template and offsets are supplied by the offline build.
 * Result: phase, H_ADDR, descriptor[4], returned wrapper phase, reserved.
 * Phases: 0 fresh, 1 get attempted, 2 returned descriptor, 3 refusal,
 * 4 invalid input/result, 5 retained entry intent, 6 entry returned.
 */
#if !defined(RL_H_GET) || !defined(RL_H_ADDR) || !defined(RL_DCACHE) || !defined(RL_ICACHE)
#error "explicit allocator/cache bindings required"
#endif
#if !defined(RL_TEMPLATE) || !defined(RL_OWNER_OFF) || !defined(RL_REFS_OFF)
#error "runtime template and symbol-derived references required"
#endif
#if RL_OWNER_OFF < 0x1000 || RL_OWNER_OFF > 0x1FFC || (RL_OWNER_OFF & 3)
#error "invalid owner reference offset"
#endif
#if RL_REFS_OFF < 0x2000 || RL_REFS_OFF > 0x2FEC || (RL_REFS_OFF & 3)
#error "invalid capture references offset"
#endif
.syntax unified
.arm
.text
.global entry, result, embedded_image, image_end
entry:
.Lentry:
    push {r4-r10, lr}
    mov r10, sp
    bic sp, sp, #7
    sub sp, sp, #16
    adr r8, .Lentry
    cmp r0, r8
    bne return
    cmp r8, #0x40000000
    blo return
    ldr r0, =image_end - entry
    adds r9, r8, r0
    bcs return
    cmp r9, #0x80000000
    bhi return
    ldr r4, =result - entry
    add r4, r8, r4
    ldr r0, [r4]
    cmp r0, #0
    bne return
    mov r0, #1
    str r0, [r4]                       @ staged irreversible intent
    dmb sy
    ldr r6, =embedded_image - entry
    add r6, r8, r6
    ldr r0, =RL_OWNER_OFF
    ldr r1, [r6, r0]
    cmp r1, #0
    bne invalid
    ldr r0, =RL_REFS_OFF
    add r0, r6, r0
    mov r2, #5
check_refs:
    ldr r1, [r0], #4
    cmp r1, #0
    bne invalid
    subs r2, r2, #1
    bne check_refs
    mov r0, sp
    mov r1, #0
    mov r2, #0x10000
    mov r3, #0x10000
    ldr ip, =RL_H_GET
    blx ip
after_get:
    ldm sp, {r0-r3}
    add r7, r4, #8
    stm r7, {r0-r3}                   @ preserve even if H_ADDR fails
    mov r0, sp
    ldr ip, =RL_H_ADDR
    blx ip
    str r0, [r4, #4]
    mov r0, #2
    str r0, [r4]
    dmb sy
validate_descriptor:
    ldr r5, [r4, #4]
    ldr r0, [r4, #8]
    cmp r0, r5
    bne invalid
    ldr r0, [r4, #12]
    cmp r0, #0
    bne invalid
    ldr r0, [r4, #16]
    cmp r0, r5
    bne invalid
    ldr r0, [r4, #20]
    cmp r0, #0x10000
    bne invalid
    cmp r5, #0
    beq refused
    movw r0, #0xFFFF
    tst r5, r0
    bne invalid
    ldr r0, =0x44400000
    cmp r5, r0
    blo invalid
    adds r7, r5, #0x10000
    bcs invalid
    ldr r0, =0x46400100
    cmp r7, r0
    bhi invalid
    cmp r5, r9
    cmplo r8, r7
    blo invalid                       @ includes launcher/result/whole template
    mov r0, r5
    mov r1, #0
zero_owner:
    str r1, [r0], #4
    cmp r0, r7
    blo zero_owner
    add r0, r5, #0x5000
    add r2, r0, #11264
    ldr r1, =0xA5A5A5A5
sentinels:
    str r1, [r0], #4
    cmp r0, r2
    blo sentinels
    ldr r0, =RL_OWNER_OFF
    str r5, [r6, r0]
    ldr r0, =RL_REFS_OFF
    add r0, r6, r0
    add r1, r5, #0x4000
    str r1, [r0]
    mov r1, #2048
    str r1, [r0, #4]
    add r1, r5, #0x5000
    str r1, [r0, #8]
    mov r1, #11264
    str r1, [r0, #12]
    movw r1, #1200
    str r1, [r0, #16]
    mov r0, #5
    str r0, [r4]
    bl copy_result                    @ descriptor/intent retained before entry
    ldr ip, =RL_DCACHE
    blx ip
    ldr ip, =RL_ICACHE
    blx ip
invoke:
    mov r0, r6                       @ ordinary shared loader entry ABI
    blx r6
    ldr r0, [r5]
    str r0, [r4, #24]                @ raw wrapper phase, not runnable proof
    mov r0, #6
    str r0, [r4]
    bl copy_result
    b return
refused:
    mov r0, #3
    str r0, [r4]
    b return
invalid:
    mov r0, #4
    str r0, [r4]
return:
    mov sp, r10
    pop {r4-r10, pc}

copy_result:
    mov r0, r4
    add r1, r5, #0x400
    mov r2, #8
1:  ldr r3, [r0], #4
    str r3, [r1], #4
    subs r2, r2, #1
    bne 1b
    dmb sy
    bx lr
    .ltorg
    .balign 8
result:
    .space 32
    .balign 1024
embedded_image:
    .incbin RL_TEMPLATE
image_end:
