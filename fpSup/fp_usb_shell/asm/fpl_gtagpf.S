.syntax unified
.arm
.text
.global entry
/* Persistent fp L 3.02 per-frame GTAG observer: adds ONE UNDEFINED GTAG
 * (0x4653) of N bytes at each CinemaDNG take start (mode 0/type 3), locates
 * its value in the serialized header template at mode 2/type 3, and rewrites
 * the tag's N value bytes in that template on EVERY mode 3/type 3 frame
 * notify (which the firmware sends before the frame's template DMA).  The
 * per-frame payload is 'FPLP', counter, ~counter, N, then (i*7+3)&255 from
 * byte 16, where counter is this take's frame index: the number of mode-3
 * notifies since the last mode 0, counting skipped ones, so a skip cannot
 * shift later frames' counters.  A frame whose notify never wrote shows
 * counter 0 (the uploaded initial payload).  Never detaches itself (returns
 * 1); the host clears its own Subject slot after the take.
 *
 * Owner-authorized experiment (24 October, resuming the paused M3 slice):
 * card contents may be lost; firmware is never written.  Native addresses:
 * docs/FPL_GYRO2_BINDINGS.md (Subject/attach/notify/DataPool/add-tag/template
 * words).  Parser = the shared gyr2.S algorithm (rd16/rd32/find_entry/
 * find_gtag), with one change: it returns the RAW value offset (byte writes
 * need no alignment) and room = the tag's count; mode 3 refuses a write when
 * N exceeds room or the template, so it never overruns the tag's own value
 * extent.  Offsets read from the template are bounds-checked before any
 * addition, and templates over 1 MiB are not parsed.  NOT a fail-closed gate.
 *
 * GYRO build (-DGYRO=1): the same install, add and locate, but mode 3 writes
 * a diagnostic gyro block instead of the pattern, at the tag value's first
 * word boundary.  Mode 2 arms the SHARED drain (gyro/gyro_drain.S, latched
 * head) at the coprocessor ring's current head; each frame notify then drains
 * exactly the records published since the previous frame, up to the block's
 * capacity, into the template, so frame f's DNG carries the gyro records that
 * arrived between notifies f-1 and f.  Frame 1 instead reaches back exactly
 * one block's capacity from its own latched head (Gyro2's BACKFILL idea): the
 * mode-2 arming can precede frame 1 by more than the 240 ms ring (live, 24
 * October: 331 ms, one lap lost), and a fixed reach-back under the ring
 * cannot span a lap.  No hook, task or timer: the recording
 * task's own frame notify is the only caller.  The block is a measurement
 * format, not FSG2: fp L's rate, scales and axes are what it measures.
 *   +0  'FPLG', cleared first and written last (the commit)
 *   +4  frame index        +8  tick at notify (us)  +C  tick at previous
 *       notify, or at mode 2 for frame 1
 *   +10 consumed head before the drain (-1: not yet armed; frame 1: the
 *       reach-back head, latched - 8 * capacity)
 *   +14 head latched for this drain    +18 head re-read after it
 *   +1C records due (shared g_gcount delta)   +20 records written
 *   +24 records dropped for capacity          +28 pad errors (shared)
 *   +2C status: 0 ok, 3..6 P/R/head invalid before (no drain), 7 invalid
 *       after, or the drain did not consume up to the latch
 *   +30 tick after the drain   +34 capacity (records)
 *   +38 take total written     +3C take total dropped
 *   +40 records, 8 bytes each in the shared drain's layout {x, y, 0, z}
 * Heads are published ring addresses (R + 8*(j+1)); the host derives laps and
 * rate from heads, ticks and counts.  Equal heads may hide a whole lap.
 *
 * entry    echo handler (shell task): native attach of OBJ to the Subject.
 * observer OBJ's vt+0xC, called inline as (obs, DataPool) on every notify.
 *
 * VARS (PARAM), hex offsets:
 *   00 install state  1 running 2 attached 3 no empty slot 4 already present
 *                     5 unexpected Subject 6 attach did not verify
 *   04 Subject        08 slot index      0C empty slots before attach
 *   10 observer calls 14 last mode       18 last type
 *   1C mode0 seen     20 adds ok         24 builder (last)
 *   28 size before    2C add return      30 size after    34 N
 *   38 mode2 seen     3C located         40 template ptr (mode 2)
 *   44 template len (mode 2)             48 value offset 4C room (=count)
 *   50 mode3 seen     54 writes done     58 last counter written
 *   5C template ptr (last mode 3)        60 template len (last mode 3)
 *   64 ptr mismatches 68 skipped writes
 *   6C ring of the last 8 mode-3 events, 4 words each
 *      {frame index, template ptr, template len, wrote flag}
 *   EC ring index (next slot, unbounded)
 *   F0 frame index (mode-3 notifies since the last mode 0)
 *   GYRO only: F4 block offset in the template, F8 capacity (records),
 *   FC tick at the previous frame notify (or mode 2)
 * OBJ (PARAM+0x100): vptr -> VT (PARAM+0x110); VT slots 0..2 -> ret0, +C -> observer.
 */
#ifndef PARAM
#error PARAM required
#endif
#ifndef SRC
#error SRC required
#endif
#ifndef N
#error N required
#endif
#if defined(SLIT_PRODUCER) && (!defined(SLIT_LOOKUP) || N != 640)
#error "SLIT_PRODUCER requires the 640-byte FPLS v4 observation"
#endif
#if defined(SLIT_LOOKUP) && (!defined(SLIT_QUEUE) || (!defined(SLIT_PRODUCER) && N != 464))
#error "SLIT_LOOKUP requires SLIT_QUEUE and the 464-byte FPLS v3 observation"
#endif
#if defined(SLIT_QUEUE) && (!defined(SLIT) || (!defined(SLIT_LOOKUP) && N != 336))
#error "SLIT_QUEUE requires SLIT and the 336-byte FPLS v2 measurement"
#endif
#if defined(SLIT) && ((!defined(SLIT_QUEUE) && N != 64) || defined(GYRO))
#error "SLIT is the distinct 64-byte FPLS observation format"
#endif
.equ OBJ,         PARAM + 0x100
.equ F_SUBJECT,   0xC0054E28
.equ F_ATTACH,    0xC00CF208
.equ SUBJECT,     0xC31AB0D0
.equ SLOTS,       9
.equ DP_EVENT,    0x40
.equ DP_BUILDER,  0x2C
.equ F_SIZE,      0xC00B6510
.equ F_ADD_TAG,   0xC00B6B20
.equ TEMPLATE_PTR, 0xC358E9E8
.equ TEMPLATE_LEN, 0xC358E9E4
.equ GTAG,        0x4653
.equ MAGIC,       0x504C5046             @ 'FPLP'
.equ MAX_TEMPLATE, 0x100000
#if defined(GYRO) && (N - 3 - 0x40) / 8 >= 584
#error "frame 1's reach-back must stay well inside the 600-record ring"
#endif
#ifdef GYRO
.equ F_TICK,      0xC0029320             @ us; fp C002B6E0, same instructions
.equ GYRO_GLOBAL, 0xC31E23CC             @ -> P (FPL_GYRO_BINDINGS.md)
.equ GYRO_P,      0x2E006004
.equ GYRO_R,      0x2E00644C             @ [P+0x60]
.equ GMAGIC,      0x474C5046             @ 'FPLG'
.equ HDR,         0x40
.equ LINE,        32
#endif
.macro addr reg, value
    movw \reg, #:lower16:\value
    movt \reg, #:upper16:\value
.endm

entry:
    push {r4-r8, lr}
#ifdef SLIT
    mov r4, r0                  @ owned parameter block, never loader staging
#else
    addr r4, PARAM
#endif
    mov r0, #1
    str r0, [r4]
    ldr r0, =N
    str r0, [r4, #0x34]
    addr ip, F_SUBJECT
    blx ip
    str r0, [r4, #4]
    addr r1, SUBJECT
    cmp r0, r1
    movne r0, #5
    bne install_done
    mov r5, r0
#ifdef SLIT
    add r6, r4, #0x100
#else
    addr r6, OBJ
#endif
    mov r7, #0                  @ index
    mov r8, #0                  @ empty slots
scan:
    ldr r0, [r5, r7, lsl #2]
    cmp r0, r6
    moveq r0, #4
    beq install_done
    cmp r0, #0
    addeq r8, r8, #1
    add r7, r7, #1
    cmp r7, #SLOTS
    blo scan
    str r8, [r4, #12]
    cmp r8, #0
    moveq r0, #3
    beq install_done
    mov r0, r5
    mov r1, r6
    addr ip, F_ATTACH
    blx ip
    mov r7, #0
verify:
    ldr r0, [r5, r7, lsl #2]
    cmp r0, r6
    beq attached
    add r7, r7, #1
    cmp r7, #SLOTS
    blo verify
    mov r0, #6
    b install_done
attached:
    str r7, [r4, #8]
    mov r0, #2
install_done:
    str r0, [r4]
    mov r0, #0
    pop {r4-r8, pc}

observer:
    push {r4-r8, lr}
    sub sp, sp, #8
    mov r5, r1                  @ DataPool
#ifdef SLIT
    sub r4, r0, #0x100
    ldr r0, [r4, #0x120]        @ retained slit_runtime
    ldr r0, [r0, #0x204]        @ shared shutdown flag
    cmp r0, #0
    bne out
#else
    addr r4, PARAM
#endif
    ldr r0, [r4, #0x10]
    add r0, r0, #1
    str r0, [r4, #0x10]
    ldr r0, [r5]
    ldr ip, [r0, #DP_EVENT]
    mov r0, r5
    blx ip
    cmp r0, #0
    beq out
    ldr r1, [r0]                @ mode
    ldr r2, [r0, #4]            @ type
    str r1, [r4, #0x14]
    str r2, [r4, #0x18]
    cmp r2, #3                  @ CinemaDNG take events only
    bne out
    cmp r1, #0
    beq do_build
    cmp r1, #2
    beq do_serialized
    cmp r1, #3
    beq do_frame
    b out

do_build:
    ldr r0, [r4, #0x1C]
    add r0, r0, #1
    str r0, [r4, #0x1C]
    mov r0, #0
    str r0, [r4, #0xF0]         @ a new take: frame index restarts
#ifdef SLIT
    str r0, [r4, #0x3C]         @ never reuse the previous take's template
    ldr r0, [r4, #0x120]
    ldr r0, [r0, #0x4C]         @ requested, not posted selection
    cmp r0, #1
    blo out
    cmp r0, #4
    bhi out
#endif
    ldr r0, [r5]
    ldr ip, [r0, #DP_BUILDER]
    mov r0, r5
    blx ip
    movs r6, r0
    beq out                     @ no CinemaDNG builder: nothing to do
    str r6, [r4, #0x24]
    mov r0, r6
    addr ip, F_SIZE
    blx ip
    str r0, [r4, #0x28]
    ldr r0, =N
    str r0, [sp]
#ifdef SLIT
    add r0, r4, #0x200          @ immutable zero source, retained through copy
#else
    addr r0, SRC
#endif
    str r0, [sp, #4]
    mov r0, r6
    mov r1, #5                  @ MakerNote IFD
    movw r2, #GTAG
    mov r3, #7                  @ UNDEFINED
    addr ip, F_ADD_TAG
    blx ip
    str r0, [r4, #0x2C]
    mov r0, r6
    addr ip, F_SIZE
    blx ip
    str r0, [r4, #0x30]
    ldr r0, [r4, #0x2C]
    cmp r0, #0
    beq out
    ldr r0, [r4, #0x20]
    add r0, r0, #1
    str r0, [r4, #0x20]
    b out

do_serialized:
    ldr r0, [r4, #0x38]
    add r0, r0, #1
    str r0, [r4, #0x38]
    mov r0, #0
    str r0, [r4, #0x3C]         @ located: cleared until it is
    str r0, [r4, #0x48]
    str r0, [r4, #0x4C]
    addr r0, TEMPLATE_PTR
    ldr r6, [r0]
    addr r0, TEMPLATE_LEN
    ldr r7, [r0]
    str r6, [r4, #0x40]
    str r7, [r4, #0x44]
    cmp r6, #0
    beq out
    cmp r7, #0x100
    blo out
    cmp r7, #MAX_TEMPLATE
    bhi out
    mov r0, r6
    mov r1, r7
    bl find_gtag
    cmp r0, #0
    beq out
    str r0, [r4, #0x48]         @ value offset in the template
    str r1, [r4, #0x4C]         @ room = the tag's count
    mov r0, #1
    str r0, [r4, #0x3C]
#ifdef GYRO
    bl gyro_arm
#endif
    b out

do_frame:
    ldr r0, [r4, #0x50]
    add r0, r0, #1
    str r0, [r4, #0x50]
    ldr r0, [r4, #0xF0]
    add r0, r0, #1
    str r0, [r4, #0xF0]         @ this frame's index, written or not
    addr r0, TEMPLATE_PTR
    ldr r6, [r0]
    addr r0, TEMPLATE_LEN
    ldr r7, [r0]
    str r6, [r4, #0x5C]
    str r7, [r4, #0x60]
    ldr r0, [r4, #0x3C]
    cmp r0, #0
    beq frame_skip              @ mode 2 never located the tag
    ldr r0, [r4, #0x40]
    cmp r6, r0
    bne frame_mismatch          @ not the template mode 2 parsed
    ldr r8, [r4, #0x48]
    ldr r0, [r4, #0x34]         @ N
    ldr r1, [r4, #0x4C]
    cmp r0, r1
    bhi frame_skip              @ would overrun the tag's own value: refuse
    add r1, r8, r0
    cmp r1, r7
    bhi frame_skip              @ would overrun the template: refuse
    ldr r2, [r4, #0xF0]         @ this frame's counter = its index
#if defined(SLIT)
    bl slit_frame
    ldr r2, [r4, #0xF0]
#elif defined(GYRO)
    mov r0, r2
    bl gyro_frame
    ldr r2, [r4, #0xF0]
#else
    add r5, r6, r8              @ the tag's value in the template
    addr r3, MAGIC
    strb r3, [r5]
    lsr r3, r3, #8
    strb r3, [r5, #1]
    lsr r3, r3, #8
    strb r3, [r5, #2]
    lsr r3, r3, #8
    strb r3, [r5, #3]
    strb r2, [r5, #4]
    lsr r3, r2, #8
    strb r3, [r5, #5]
    lsr r3, r3, #8
    strb r3, [r5, #6]
    lsr r3, r3, #8
    strb r3, [r5, #7]
    mvn r3, r2
    strb r3, [r5, #8]
    lsr r3, r3, #8
    strb r3, [r5, #9]
    lsr r3, r3, #8
    strb r3, [r5, #10]
    lsr r3, r3, #8
    strb r3, [r5, #11]
    strb r0, [r5, #12]
    lsr r3, r0, #8
    strb r3, [r5, #13]
    lsr r3, r3, #8
    strb r3, [r5, #14]
    lsr r3, r3, #8
    strb r3, [r5, #15]
    mov r1, #115                @ (16*7+3)&255: the pattern's first byte
    mov r0, #16
1:  strb r1, [r5, r0]
    add r1, r1, #7              @ low byte stays (i*7+3)&255 mod 256
    add r0, r0, #1
    ldr r3, [r4, #0x34]
    cmp r0, r3
    blo 1b
#endif
    str r2, [r4, #0x58]
    ldr r0, [r4, #0x54]
    add r0, r0, #1
    str r0, [r4, #0x54]
    mov r0, r2
    mov r1, r6
    mov r2, r7
    mov r3, #1
    bl ring
    b out

frame_mismatch:
    ldr r0, [r4, #0x64]
    add r0, r0, #1
    str r0, [r4, #0x64]
    ldr r0, [r4, #0xF0]
    mov r1, r6
    mov r2, r7
    mov r3, #0
    bl ring
    b out

frame_skip:
    ldr r0, [r4, #0x68]
    add r0, r0, #1
    str r0, [r4, #0x68]
    ldr r0, [r4, #0xF0]
    mov r1, r6
    mov r2, r7
    mov r3, #0
    bl ring
    b out

out:
    mov r0, #1                  @ never detach
    add sp, sp, #8
    pop {r4-r8, pc}

/* ring: append {r0, r1, r2, r3} at PARAM+0x6C + (index & 7)*16 and bump the
 * index at PARAM+0xEC.  r4 must hold PARAM.  Clobbers ip. */
ring:
    push {lr}
    ldr ip, [r4, #0xEC]
    and ip, ip, #7
    lsl ip, ip, #4
    add ip, ip, r4
    add ip, ip, #0x6C
    str r0, [ip]
    str r1, [ip, #4]
    str r2, [ip, #8]
    str r3, [ip, #12]
    ldr r0, [r4, #0xEC]
    add r0, r0, #1
    str r0, [r4, #0xEC]
    pop {pc}

/* ---- the shared gyr2.S parser, adapted (see header).  r0/r1 in, r0/r1 out. */
/* rd16: r1 = base, r2 = offset -> r0.  Clobbers r2, r3. */
rd16:
    add r3, r1, r2
    ldrb r0, [r3]
    ldrb r2, [r3, #1]
    orr r0, r0, r2, lsl #8
    bx lr
/* rd32: r1 = base, r2 = offset -> r0.  Clobbers r2, r3. */
rd32:
    add r3, r1, r2
    ldrb r0, [r3]
    ldrb r2, [r3, #1]
    orr r0, r0, r2, lsl #8
    ldrb r2, [r3, #2]
    orr r0, r0, r2, lsl #16
    ldrb r2, [r3, #3]
    orr r0, r0, r2, lsl #24
    bx lr
/* find_entry: r1 = base, r4 = length, r5 = IFD offset, r6 = tag.
 * r0 = the entry's offset, or 0.  Clobbers r0, r2, r3, r7, r8. */
find_entry:
    push {lr}
    cmp r5, r4                  @ r4 <= MAX_TEMPLATE: no sum below can wrap
    bhs 8f
    add r2, r5, #2
    cmp r2, r4
    bhs 8f
    mov r2, r5
    bl rd16
    mov r7, r0                  @ entry count
    mov r3, #12
    mla r8, r7, r3, r5
    add r8, r8, #2              @ end of the entries
    cmp r8, r4
    bhi 8f
    add r8, r5, #2              @ the first entry
1:  cmp r7, #0
    beq 8f
    mov r2, r8
    bl rd16
    cmp r0, r6
    moveq r0, r8
    popeq {pc}
    add r8, r8, #12
    sub r7, r7, #1
    b 1b
8:  mov r0, #0
    pop {pc}

/* find_gtag: r0 = template, r1 = length.  r0 = the GTAG value's offset in the
 * template (raw, not aligned), r1 = its count; r0 = 0 when any step is
 * missing or out of bounds.  Clobbers r4-r11, ip. */
find_gtag:
    push {r4-r11, ip, lr}
    mov r9, r0                  @ template
    mov r4, r1                  @ length
    mov r1, r9
    cmp r4, #0x100
    blo 90f
    cmp r4, #MAX_TEMPLATE
    bhi 90f
    ldr r0, [r9]
    ldr r2, =0x002A4949         @ 'II', 42
    cmp r0, r2
    bne 90f
    mov r2, #4
    bl rd32
    mov r5, r0                  @ IFD0
    ldr r6, =0x8769             @ Exif
    bl find_entry
    cmp r0, #0
    beq 90f
    add r2, r0, #8
    mov r1, r9
    bl rd32
    mov r5, r0                  @ Exif IFD
    ldr r6, =0x927C             @ MakerNote
    bl find_entry
    cmp r0, #0
    beq 90f
    mov r10, r0                 @ MakerNote entry
    add r2, r10, #2
    mov r1, r9
    bl rd16
    cmp r0, #7                  @ UNDEFINED
    bne 90f
    add r2, r10, #4
    bl rd32
    mov r11, r0                 @ MakerNote length
    add r2, r10, #8
    bl rd32
    mov r10, r0                 @ MakerNote offset
    cmp r10, r4
    bhs 90f
    sub r0, r4, r10
    cmp r11, r0
    bhi 90f                     @ length beyond the template (no addition)
    cmp r11, #12
    blo 90f
    add r2, r9, r10             @ 'SIGMA', 0, 0, 0
    ldrb r0, [r2]
    cmp r0, #'S'
    bne 90f
    ldrb r0, [r2, #4]
    cmp r0, #'A'
    bne 90f
    add r5, r10, #10            @ the MakerNote IFD
    ldr r6, =GTAG
    bl find_entry
    cmp r0, #0
    beq 90f
    mov r7, r0                  @ GTAG entry
    add r2, r7, #2
    mov r1, r9
    bl rd16
    cmp r0, #7                  @ UNDEFINED
    bne 90f
    add r2, r7, #4
    bl rd32
    mov r8, r0                  @ count
    add r2, r7, #8
    bl rd32                     @ value offset, from the template start
    cmp r8, #4                  @ inline: no room anyway
    bls 90f
    add r1, r0, r8              @ its end
    cmp r1, r0
    blo 90f                     @ wrapped
    cmp r1, r4
    bhi 90f
    mov r1, r8                  @ room = count
    pop {r4-r11, ip, pc}
90: mov r0, #0
    mov r1, #0
    pop {r4-r11, ip, pc}

ret0:
    mov r0, #0
    bx lr

#ifdef SLIT
#ifdef SLIT_QUEUE
#define SLIT_MMIO ip
#else
#define SLIT_MMIO r9
#endif
/* FPLS v1: a per-DNG NOTIFY observation, NOT sensor-frame timing association.
 * Fields after the identity header: requested, active, Vd count, trial,
 * timing04, timing20, seconds, timer5, last Vd timer5, reason,
 * association (=0 unknown), version (=1). No FrameRate/TimeCodes rewrite.
 * In particular a transition/preroll frame must never be labelled slow merely
 * because the registers were slow when its later DNG notification arrived.
 * r4 PARAM, r6 template, r8 byte offset; same shared parser and native observer.
 */
slit_frame:
    push {r4-r10, lr}
    sub sp, sp, #N
#ifdef SLIT_QUEUE
    /* r5 is the actual DataPool supplied by native notification. Its +4004
     * sequence was written by C038C8EC after the buffer-key lookup. That lookup
     * can fall back to the current counter: this remains observation, not proof. */
    mov r9, r5
#endif
    mrs r10, cpsr
    cpsid if
    ldr r5, [r4, #0x120]
    add r7, r5, #0x200
    ldr r0, =0x534c5046          @ FPLS
    str r0, [sp]
    ldr r0, [r4, #0xF0]
    str r0, [sp, #4]
    mvn r0, r0
    str r0, [sp, #8]
    mov r0, #N
    str r0, [sp, #12]
    ldr r0, [r5, #0x4C]
    str r0, [sp, #16]
    ldr r0, [r7, #12]
    str r0, [sp, #20]
    ldr r0, [r7, #24]
    str r0, [sp, #24]
    ldr r0, [r7, #16]
    str r0, [sp, #28]
    addr SLIT_MMIO, 0x30100000
    ldr r0, [SLIT_MMIO, #4]
    str r0, [sp, #32]
    ldr r0, [SLIT_MMIO, #0x20]
    str r0, [sp, #36]
    addr SLIT_MMIO, 0xC3076D98
    ldr r0, [SLIT_MMIO]
    str r0, [sp, #40]
    addr SLIT_MMIO, 0x2D810054
    ldr r0, [SLIT_MMIO]
    str r0, [sp, #44]
    ldr r0, [r7, #60]
    str r0, [sp, #48]
    ldr r0, [r7, #40]
    str r0, [sp, #52]
    mov r0, #0
    str r0, [sp, #56]
#ifdef SLIT_QUEUE
#ifdef SLIT_LOOKUP
#ifdef SLIT_PRODUCER
    mov r0, #4
#else
    mov r0, #3
#endif
#else
    mov r0, #2
#endif
#else
    mov r0, #1
#endif
    str r0, [sp, #60]
#ifdef SLIT_QUEUE
    mov r0, #0
    str r0, [sp, #64]           @ native sequence; valid only with flags=1
    str r0, [sp, #72]           @ current counter, not capture identity
    str r0, [sp, #76]
    addr ip, 0xC343B858         @ native counter-owner construction guard
    ldr r0, [ip]
    cmp r0, #1
    bne 3f
    ldr r0, [r9]
    addr ip, 0xC07333D4         @ exact native DataPool vtable
    cmp r0, ip
    bne 3f
    movw ip, #0x4004
    ldr r0, [r9, ip]
    str r0, [sp, #64]
    addr ip, 0xC343B6D4
    ldr r0, [ip]
    str r0, [sp, #72]
    mov r0, #1
    str r0, [sp, #76]
3:  ldr r0, [r7, #236]
    str r0, [sp, #68]
    add r9, r7, #240
    add ip, sp, #80
    mov r1, #0
4:  ldr r0, [r9, r1]
    str r0, [ip, r1]
    add r1, r1, #4
    cmp r1, #256
    blo 4b
#ifdef SLIT_LOOKUP
    /* Same observer, no new hook. The exact native call chain preserves the
     * frame record in saved r5. Reject any other caller or stack extent.
     * This is the queue at NOTIFY, not a claim about the earlier lookup. */
    mov r0, #0
    mov r1, #336
5:  str r0, [sp, r1]
    add r1, r1, #4
    cmp r1, #N
    blo 5b
    and r0, r10, #31
    cmp r0, #0x13
    bne lookup_clock
    add r9, sp, #N
    ldr r0, [r9, #60]           @ observer's incoming LR
    addr ip, 0xC0053660
    cmp r0, ip
    bne lookup_clock
    add r9, r9, #64            @ observer's incoming SP
    addr ip, 0xC3000098
    ldr ip, [ip]
    ldr r0, =0xC30008BC        @ current native TCB, 1..500
    cmp ip, r0
    blo lookup_clock
    ldr r0, =0xC3000838+501*132 @ exclusive TCB end
    cmp ip, r0
    bhs lookup_clock
    tst ip, #3
    bne lookup_clock
    ldr r0, [ip, #0x74]        @ stack top
    ldr r1, [ip, #0x18]        @ stack bytes
    cmp r1, #64
    blo lookup_clock
    cmp r1, #0x1000000
    bhi lookup_clock
    subs r2, r0, r1
    blo lookup_clock
    cmp r9, r2
    blo lookup_clock
    sub r0, r0, #64
    cmp r9, r0
    bhi lookup_clock
    ldr r0, [r9, #20]          @ C0053618 saved LR
    addr ip, 0xC00530C8
    cmp r0, ip
    bne lookup_clock
    ldr r0, [r9, #60]          @ C0053028 saved LR
    addr ip, 0xC038C91C
    cmp r0, ip
    bne lookup_clock
    ldr r0, [r9, #36]          @ consumer's r4: this DataPool
    /* DataPool was moved out of r9 for the Vd copy; observer keeps it in r5
     * only until slit_frame. Its value is on our saved-register stack. */
    ldr r1, [sp, #N+4]
    cmp r0, r1
    bne lookup_clock
    ldr r2, [r9, #40]          @ consumer's r5: frame record
    tst r2, #3
    bne lookup_clock
    ldr r0, =0xC3000000
    cmp r2, r0
    blo lookup_user_record
    ldr r0, =0xCFFFFFB0
    cmp r2, r0
    bhi lookup_clock
    b lookup_record
lookup_user_record:
    ldr r0, =0x44400000
    cmp r2, r0
    blo lookup_clock
    ldr r0, =0x464000B0
    cmp r2, r0
    bhi lookup_clock
lookup_record:
#ifdef SLIT_PRODUCER
    str r2, [sp, #448]         @ independently checked record / consumer stack
    add r0, r9, #64
    str r0, [sp, #452]
#endif
    ldr r0, [r2, #0x4c]
    str r0, [sp, #340]         @ exact key; no address normalization
    mov r0, #1
    str r0, [sp, #336]         @ stack provenance valid, queue may be absent
    ldr r0, [sp, #76]
    cmp r0, #1
    bne lookup_clock
    addr r9, 0xC343B6C4
    ldr r0, [r9, #0x18c]
    cmp r0, #10
    bhs lookup_clock
    str r0, [sp, #344]
    add ip, sp, #352
    mov r1, #0
lookup_ring:
    add r2, r9, #0x13c
    ldr r0, [r2, r1]
    str r0, [ip, r1]
    add r2, r9, #0x164
    ldr r0, [r2, r1]
    add r2, ip, #40
    str r0, [r2, r1]
    add r1, r1, #4
    cmp r1, #40
    blo lookup_ring
    mov r0, #3
    str r0, [sp, #336]         @ key + native ring snapshot valid
lookup_clock:
    /* Bounded counterpart of C0029120: two timer reads with pending status
     * between them. A rollover between reads refuses, rather than retrying.
     * Native pending bit 5 accounts for the not-yet-serviced second. */
    addr ip, 0xC30337EC
    ldr r0, [ip]
    addr r1, 0x2D810000
    cmp r0, r1
    bne lookup_done
    ldr r0, [ip, #12]
    add r2, r1, #0x80
    cmp r0, r2
    bne lookup_done
    addr ip, 0xC2F09408
    ldr r0, [ip]
    ldr r2, =12000000
    cmp r0, r2
    bne lookup_done
    ldr r3, [r1, #0x54]
    addr ip, 0xC3076D98
    ldr r0, [ip]
    ldr ip, [r1, #0x84]
    and ip, ip, #32
    str ip, [sp, #444]
    ldr r1, [r1, #0x54]
    cmp r3, r2
    bhs lookup_done
    cmp r1, r2
    bhs lookup_done
    cmp r1, r3
    blo lookup_done
    cmp ip, #0
    addne r0, r0, #1
    str r0, [sp, #436]
    str r1, [sp, #440]
    mov r0, #1
    str r0, [sp, #432]
lookup_done:
#ifdef SLIT_PRODUCER
    ldr r3, [sp, #448]
    cmp r3, #0
    beq producer_done
    ldr r0, [r4, #0x120]
    sub r0, r0, #0x8000
    ldr ip, [r0, #0x28]
    ldr r0, [r0, #0x24]
    add r0, r0, #0x8000
    add r1, sp, #464
    ldr r2, [sp, #N+4]        @ actual observer DataPool
    ldr r9, [sp, #452]
    sub sp, sp, #8
    str r9, [sp]
    blx ip
    add sp, sp, #8
producer_done:
#endif
#endif
#endif
    msr cpsr_c, r10
    add r5, r6, r8
    mov r1, #0
1:  ldrb r0, [sp, r1]
    strb r0, [r5, r1]
    add r1, r1, #1
    cmp r1, #N
    blo 1b
    bic r0, r5, #31
    add r1, r5, #N
2:  mcr p15, 0, r0, c7, c10, 1
    add r0, r0, #32
    cmp r0, r1
    blo 2b
    dsb sy
    add sp, sp, #N
    pop {r4-r10, pc}
#endif

#ifdef GYRO
/* gyro_arm: r4 = PARAM, after mode 2 located the tag.  Places the block,
 * resets the take's drain state and arms the shared drain at the ring's
 * current head (a failed check leaves it for frame 1 to arm).  Keeps r4-r11. */
gyro_arm:
    push {r4-r8, lr}
    ldr r0, [r4, #0x48]
    add r1, r0, #3
    bic r1, r1, #3              @ the value's first word boundary
    str r1, [r4, #0xF4]
    sub r2, r1, r0
    ldr r3, [r4, #0x34]
    sub r3, r3, r2
    subs r3, r3, #HDR
    movmi r3, #0
    lsr r3, r3, #3
    str r3, [r4, #0xF8]
    mov r0, #0
    str r0, s_cap               @ arming claims nothing
    str r0, tot_written
    str r0, tot_dropped
    str r0, frames_ok
    mvn r0, #0
    str r0, g_ghead             @ unarmed: the next drain takes the head
    adr r0, descriptor          @ owned view: the drain reads R from here
    str r0, descriptor_ptr
    ldr r0, =GYRO_R
    str r0, descriptor_ring
    bl validate
    str r0, arm_status
    cmp r0, #0
    bne 1f
    str r2, latch
    str r2, arm_head
    bl gyro_drain
1:  addr ip, F_TICK
    blx ip
    str r0, [r4, #0xFC]
    pop {r4-r8, pc}

/* gyro_frame: r4 = PARAM, r6 = template, r0 = frame index.  Writes this
 * frame's block (layout in the header).  Keeps r4-r11. */
gyro_frame:
    push {r4-r10, lr}
    mov r9, r0
    ldr r0, [r4, #0xF4]
    add r10, r6, r0             @ the block
    mov r0, #0
    str r0, [r10]               @ cleared first: half-written is no block
    str r10, s_block
    str r0, s_written
    str r0, s_dropped
    ldr r0, [r4, #0xF8]
    str r0, s_cap
    addr ip, F_TICK
    blx ip
    mov r8, r0                  @ tick at notify
    ldr r7, g_ghead             @ consumed head before
    ldr r5, g_gcount
    ldr r0, g_padbad
    str r0, [r10, #0x28]        @ for the delta below
    bl validate
    cmp r0, #0
    movne r1, #0
    strne r1, [r10, #0x14]
    strne r1, [r10, #0x18]
    bne 6f
    str r2, [r10, #0x14]
    str r2, latch
    cmp r9, #1
    bne 8f
    ldr r1, [r4, #0xF8]         @ frame 1: reach back one capacity, not to
    sub r7, r2, r1, lsl #3      @ the arming, which may be a lap ago
    ldr r3, =(GYRO_R + 8)
    cmp r7, r3
    addlo r7, r7, #0x1200       @ round the ring (0x12C0, in two immediates)
    addlo r7, r7, #0xC0
    str r7, g_ghead
8:  bl gyro_drain
    bl validate
    str r2, [r10, #0x18]
    cmp r0, #0
    movne r0, #7
    bne 6f
    ldr r1, g_ghead
    ldr r2, [r10, #0x14]
    cmp r1, r2
    movne r0, #7                @ not consumed up to the latch
6:  str r0, [r10, #0x2C]
    cmp r0, #0
    ldreq r1, frames_ok
    addeq r1, r1, #1
    streq r1, frames_ok
    str r0, last_status
    str r9, [r10, #0x04]
    str r8, [r10, #0x08]
    ldr r1, [r4, #0xFC]
    str r1, [r10, #0x0C]
    str r8, [r4, #0xFC]
    str r7, [r10, #0x10]
    ldr r1, g_gcount
    sub r1, r1, r5
    str r1, [r10, #0x1C]
    ldr r1, s_written
    str r1, [r10, #0x20]
    ldr r1, s_dropped
    str r1, [r10, #0x24]
    ldr r1, g_padbad
    ldr r2, [r10, #0x28]
    sub r1, r1, r2
    str r1, [r10, #0x28]
    ldr r1, [r4, #0xF8]
    str r1, [r10, #0x34]
    ldr r1, tot_written
    ldr r2, s_written
    add r1, r1, r2
    str r1, tot_written
    str r1, [r10, #0x38]
    ldr r1, tot_dropped
    ldr r2, s_dropped
    add r1, r1, r2
    str r1, tot_dropped
    str r1, [r10, #0x3C]
    addr ip, F_TICK
    blx ip
    str r0, [r10, #0x30]
    dmb
    ldr r0, =GMAGIC             @ the commit, last
    str r0, [r10]
    ldr r1, s_written           @ clean the block's lines for the DMA
    add r1, r10, r1, lsl #3
    add r1, r1, #HDR
    bic r0, r10, #(LINE - 1)
7:  mcr p15, 0, r0, c7, c10, 1  @ DCCMVAC
    add r0, r0, #LINE
    cmp r0, r1
    blo 7b
    dsb
    pop {r4-r10, pc}

/* Leaf, as fpl_gyro_capture.S: r0 status, r2 the validated head.  Never
 * dereferences an untrusted pointer. */
validate:
    ldr r1, =GYRO_GLOBAL
    ldr r1, [r1]
    mov r0, #3
    cmp r1, #0
    bxeq lr
    mov r0, #4
    ldr r2, =GYRO_P
    cmp r1, r2
    bxne lr
    ldr r1, [r1, #0x60]
    mov r0, #5
    ldr r2, =GYRO_R
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
 * commit(r0 count).  Keeps r4-r11.  A refused remainder is counted once. */
stream_claim:
    ldr r3, s_written
    ldr r1, s_cap
    subs r1, r1, r3
    movmi r1, #0
    cmp r1, r0
    movhi r1, r0
    cmp r1, #0
    ldreq r2, s_dropped
    addeq r2, r2, r0
    streq r2, s_dropped
    ldr r2, s_block
    add r2, r2, #HDR
    add r0, r2, r3, lsl #3
    bx lr
stream_commit:
    ldr r3, s_written
    add r3, r3, r0
    str r3, s_written
    bx lr

.ltorg
#define GYRO_DESC_LOCAL descriptor_ptr
#define GYRO_LATCH_LOCAL latch
#include "../../gyro/gyro_drain.S"
.balign 4
g_ghead:     .word -1
g_gcount:    .word 0
g_padbad:    .word 0
latch:       .word 0
s_block:     .word 0
s_cap:       .word 0
s_written:   .word 0
s_dropped:   .word 0
tot_written: .word 0
tot_dropped: .word 0
frames_ok:   .word 0
last_status: .word 0
arm_status:  .word 0
arm_head:    .word 0
descriptor_ptr: .word 0
descriptor:  .space 0x60
descriptor_ring: .word 0
#endif

.ltorg
