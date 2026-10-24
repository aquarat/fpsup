/* Gyro2, format v2 (2026-10-15; design GYRO2_CAMERA_DESIGN.md 13): each
 * CinemaDNG frame carries its own gyro samples, the level (accelerometer)
 * readings and Vd frame syncs between them, the sensor mode as the camera
 * reports it, and the lens's calibrated focal length.
 *
 * A loader v3 sup (projects/usb-shell-sup/notes/LOADER_V3.md).  The firmware
 * serializes a take's DNG header once into a template, and for every frame,
 * on the RAW-complete event in the MovRec task, patches the template and DMAs
 * it in front of the frame's RAW (C038C77C).  Its tag observers -- lens, AE,
 * AF, AWB, colour -- get every step of that from the Subject (FUN_c00577f0),
 * and so does ours, tag_observer, with no code patched (type 3 = CinemaDNG):
 *
 *     mode 0  FUN_c038a138   the tags are added: ours, GTAG (UNDEFINED), sized
 *                            for GTAG_FRAMES frames at the take's rate
 *     mode 2  C0378F70       the template is serialized: take_start finds GTAG
 *     mode 3  C038C700       each frame, before the DMA: frame writes the block
 *
 * The firmware's own copy carries the block into the frame -- before
 * XC_StillCreateFile__v2 and before the lossless sup sees the frame.
 *
 * Block, at the tag value's first word boundary (layout: the plugin's
 * common/src/cdng.rs and fsg2.rs):
 *     +0   'FSG2'        cleared first, written last: the commit
 *     +4   u8 2, u8 2    block version, payload kind 2;  +6 u16 WRITER (our build)
 *     +8   u32 len       the payload's length
 *     +12  payload       48-byte header (fmt 2), n x i16 x, y, z, then events
 * No CRC: the bytes are ours alone and written in one go before the DMA.
 *
 * Time is never stored.  A sample's time is its index from the start of the
 * take times the sample period; base_idx is the first sample's index and
 * frame_mark is where the frame's notify fell.  Blocks tile the stream: when more is
 * due than the tag holds (a take's first frame reaches BACKFILL back; a
 * stall), a block carries the oldest and ends before its frame_mark, and the
 * next frames catch up.
 *
 * Gyro: the coprocessor's ring, as fpSup gyro/gyro_drain.S reads it (proven
 * bit-exact against the gcsv logger): ring = [[0xC31E3FCC] + 0x60]; [ring] - ring
 * is the byte offset of the next record, records are 8 bytes {x, y, pad, z}
 * from ring + 4, 600 of them (240 ms).  The frame interval is at most ~111 ms
 * (9 fps), so reading it once per frame keeps up; a gap over LOST_US marks the
 * block lost because the ring has gone round.
 *
 * Position-independent: adr and pc-relative only.  Header bytes are read
 * with ldrb (TIFF entries are 2 mod 4). */
.syntax unified
.arm
.text

.equ SVC_BOOT_ID,  4
.equ SVC_CLAIM,    8
.equ SVC_CHAIN,    16
.equ SVC_CAVE,     20
.equ SVC_PUBLISH,  24
.equ SL_CHAIN,     1

.equ F_TICK,       0xC002B6E0

.equ GYRO_DESC_PTR, 0xC31E3FCC         /* -> P; P+0x60 -> the ring              */
.equ GYRO_SPAN,    0x12C0             /* 600 records of eight bytes            */
.equ BACKFILL,     250                /* records before the first frame (100 ms) */
.equ AVAIL,        584                /* records the ring still holds safely: 600
                                         less the few being overwritten now      */
.equ US_PER_REC,   400                /* 400.085 us; whole us is close enough to
                                         count laps                              */
.equ LAP_US,       240051             /* 600 records                           */
.equ MAX_LAPS,     16                 /* a drain gap past this is not counted   */

/* The two buffers, in the block past the file (the loader zeroes it). */
.equ GLOG_N,       8192               /* gyro records, 6 bytes: 48 KB, 3.3 s    */
.equ GLOG_BYTES,   (GLOG_N * 6)
.equ LAG_MARGIN,   1024               /* a reader this close to being lapped: lost */
.equ ELOG_N,       256                /* level readings, 12 bytes: 5 s at 47 Hz */
.equ ELOG_BYTES,   (ELOG_N * 12)

/* snapshot(): what it hands back */
.equ S_W,      0
.equ S_DHEAD,  4
.equ S_LU,     8
.equ S_RING,   12
.equ S_MARK,   16
.equ S_FLAGS,  20
.equ S_GONE,   24                     /* records before this are in neither place */
.equ SNAP_BYTES, 32

.equ MAGIC,        0x32475346         /* 'FSG2'                                */
.equ GTAG,         0x4653             /* our MakerNote tag (UNDEFINED), added at
                                         record start by the tag observer      */
.equ FRAME_BYTES,  60                 /* outer 12 + payload header 48          */
.equ WRITER,       6                  /* build.py VERSION, in the block for diagnostics */
.equ LINE,         32                 /* Cortex-A9 D-cache line                */

.equ PERIOD_PS,    400085400          /* 2499.466 Hz, measured (Gyro1)         */
.equ GSCALE_BITS,  0x39109F6C         /* 0.000137923 rad/s per count (Gyro1)   */
.equ ASCALE_BITS,  0x3A800000         /* 0.0009765625 g per count              */

.equ F_LOST,       1
.equ F_FIRST,      4

/* P2: the level.  The MMA8452Q driver publishes x, y, z at 0xC377790C and
 * releases its lock; 0xC050D4C8 is the first instruction after (fpSup
 * gyro/accel_hook.S): r4 points at the three values, lr is dead. */
.equ ACCEL_SITE,   0xC050D4C8
.equ EV_MAX,       24                 /* per block: 4 frames' span at 9 fps    */
.equ VEV_MAX,      6                  /* Vd events per block                   */
.equ EV_RESERVE,   (EV_MAX * 10 + VEV_MAX * 8)  /* level: pos, type, len, 3 x i16; Vd: pos, type, len, tick */
.equ EVENT_LEVEL,  1
.equ EVENT_VD,     3                  /* the sensor's Vd interrupt (IRQ 0x79); 2 is focus */

/* The sensor's frame sync, Vd (IRQ 0x79): once a frame, at a fixed point of
 * the readout (2026-10-07, A001_012/016: +-5 us, no double fires; it moves
 * with the readout, not with the exposure).  Each frame's time comes from
 * it.  The handler is Thumb: push.w; movw; movt.  The movt (4 bytes, word
 * aligned) becomes a BLX to our ARM code, which replays it.  Gyro1 hooked
 * the same word (GYRO_RESEARCH.md section 6). */
.equ VD_SITE,      0xC0125480         /* movt r4, #0xC31D, in FUN_c0125478     */
.equ VLOG_N,       64                 /* {position, TickTimer}                 */
.equ VLOG_BYTES,   (VLOG_N * 8)
.equ SL_EXCL,      2

/* A4: our own MakerNote tag, added at each CinemaDNG take start by a tag
 * observer on the firmware's Subject (the lens, AE, AF, AWB and colour
 * observers add theirs the same way).  The template then has a fixed place
 * for the block, sized for the take's frame rate.  Offline research
 * 2026-10-15 (scratchpad a4_observer.md, a4_headerlen.md, a4_fps.md). */
#if defined(GYR2_FPL_OBSERVER)
#include "profiles/fpl302_observer.inc.S"
#else
.equ F_SUBJECT,    0xC00577F0         /* () -> the Subject (built on first use) */
.equ F_ATTACH,     0xC00D2958         /* (subject, obs); a full Subject asserts */
.equ SUBJ_SLOTS,   9                  /* words at subject+0                     */
.equ DP_EVENT,     0x40               /* DataPool vt: -> {mode, type, flag}     */
.equ DP_BUILDER,   0x2C               /* DataPool vt: the CinemaDNG builder     */
.equ EV_TAKE_TYPE, 3                  /* type 3: CinemaDNG (movie start FUN_c038a138) */
.equ EV_BUILD,     0                  /* mode 0: the tags are being added       */
.equ EV_SERIALIZED, 2                 /* mode 2: the template is serialized (C0378F70) */
.equ EV_FRAME,     3                  /* mode 3: a frame, before its DMA (C038C700) */
.equ TEMPLATE_PTR, 0xC358DBA8         /* MovRec singleton 0xC358DB98 + 0x10: the template */
.equ TEMPLATE_LEN, 0xC358DBA4         /* + 0xC: its length (C0378EC8)           */
.equ F_ADD_TAG,    0xC00BA378         /* (builder, ifd, tag, type, [sp] count, [sp+4] src): copies */
.equ IFD_MAKERNOTE, 5
.equ F_RATE,       0xC00C9BD0         /* (u32 out[2]) -> the take's rate, num/den,
                                         as the DNG's 0xC764 (sups that change the
                                         cadence hook it)                        */
.equ GTAG_MAX,     4096               /* the frame's header room is 0x15400; stock
                                         0x1339D + LinearizationTable 0x20C +
                                         lossless 0xFD4C at most 2,252 leaves ~5 KB */
.equ GTAG_FRAMES,  4                  /* a tag holds 4 frames' samples: a first
                                         frame's backfill and stalls catch up    */
.equ HZ,           2500               /* samples a second, rounded up           */
#endif

/* P3: the take's sensor mode (fpSup gyro/gcsv_json.S, profilegen.S). */
.equ SENSOR_MODE_FN, 0xC032C720       /* () -> the running mode, 0 = none      */
.equ MODE_OBJ,     0xC343B588
.equ F_TIMING,     0xC0320FC8         /* (obj, mode) -> +4 hmax (u16)          */
.equ F_GEOM,       0xC0321028         /* (obj, mode) -> +4 w, +8 lines, +0x44 binH, +0x48 binV */
.equ SENSOR_W,     6000
.equ SENSOR_H,     4000
.equ LENS_FOCAL,   0xC307CDF0         /* u32, tenths of a mm: the focal length the
                                         lens's correction data was measured at */

/* adr reaches about 1 KB; this reaches anywhere in the file, still
 * position-independent: a same-section difference is a constant. */
.macro ADRF reg, label
    ldr     \reg, .Llit\@
    add     \reg, pc, \reg
    b       .Lend\@
.Llit\@: .word \label - .Llit\@
.Lend\@:
.endm

/* vars: words in this file, zero at load */
.equ V_SVC,    0
.equ V_BOOT,   4
.equ V_SP8,    8
.equ V_SRC,    12
.equ V_WOFF,   16                     /* block offset in the template, 0 = none */
.equ V_NEWTAKE, 20                    /* take_start ran: the next frame starts a take */
.equ V_SP24,   24
.equ V_FRAMES, 28                     /* blocks written this take              */
.equ V_CALLS,  32
.equ V_SKIPS,  36
.equ V_SP40,   40
.equ V_LTICK,  44                     /* TickTimer at the last frame           */
.equ V_NOW,    48
.equ V_CLIP,   52                     /* TickTimer at the take's first frame   */
.equ V_W,      56                     /* gyro records drained ever (global index) */
.equ V_DHEAD,  60                     /* ring offset drained up to; -1 = not yet */
.equ V_MAXN,   64                     /* samples the tail can hold             */
.equ V_LOSTS,  68                     /* blocks marked lost                    */
.equ V_LU,     72                     /* records before this index were lost   */
.equ V_ANEXT,  76                     /* the accel site's layer below, 0 = none */
.equ V_EW,     80                     /* level readings written (level task)    */
.equ V_ER,     84                     /* level readings taken (MovRec task)     */
.equ V_PREV,   88                     /* the last frame's mark (global)         */
.equ V_ORIGIN, 92                     /* the take's first record (global)       */
.equ V_SPARE,  96
.equ V_MHM,    100                    /* mode | hmax << 16                      */
.equ V_WL,     104                    /* readout width | lines << 16            */
.equ V_BIN,    108                    /* binning h | v << 16                    */
.equ V_SP112,  112
.equ V_SP116,  116
.equ V_LDRAIN, 120                    /* TickTimer at the last drain            */
.equ V_SEQ,    124                    /* odd while drain() publishes            */
.equ V_PW,     128                    /* the set before that publish            */
.equ V_PDH,    132
.equ V_PLU,    136
.equ V_VW,     140                    /* Vd records written (IRQ 0x79)          */
.equ V_VR,     144                    /* Vd records taken (MovRec task)         */
.equ V_OBS,    148                    /* our tag observer: its vptr             */
.equ V_OVT,    152                    /* and its vtable: 0, 0, 0, handler       */
.equ V_TAGS,   168                    /* tags added (CinemaDNG take starts)     */
.equ V_TAGN,   172                    /* the last tag's size                    */
.equ VARS_BYTES, 176

/* ------------------------------------------------------------------ entry */
#ifndef GYR2_FPL_OBSERVER
/* r0 = block, r1 = service table.  Returns 0 = KEEP, 1 = RELEASE.
 * Claim, learn the layer below, get a veneer -- and only then write. */
entry:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r5, r1
    adr     r6, vars
    str     r5, [r6, #V_SVC]
    ldr     r0, [r5, #SVC_BOOT_ID]
    str     r0, [r6, #V_BOOT]
    mvn     r0, #0                      @ nothing drained yet
    str     r0, [r6, #V_DHEAD]

    mov     r0, #SL_CHAIN               @ claim(svc, ACCEL_SITE, 4, stock, CHAIN)
    sub     sp, sp, #8
    str     r0, [sp]
    mov     r0, r5
    ldr     r1, =ACCEL_SITE
    mov     r2, #4
    adr     r3, accel_stock
    ldr     ip, [r5, #SVC_CLAIM]
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    bne     9f

    /* Vd: sole owner (a Thumb site cannot stack), and needed: without it
     * the frames have no time. */
    mov     r0, #SL_EXCL                @ claim(svc, VD_SITE, 4, stock, EXCL)
    sub     sp, sp, #8
    str     r0, [sp]
    mov     r0, r5
    ldr     r1, =VD_SITE
    mov     r2, #4
    ADRF    r3, vd_stock
    ldr     ip, [r5, #SVC_CLAIM]
    blx     ip
    add     sp, sp, #8
    cmp     r0, #0
    bne     9f

    mov     r0, r5                      @ the accel site: 0 = we replay mov r2, #0
    ldr     r1, =ACCEL_SITE
    mov     r2, #0
    ldr     ip, [r5, #SVC_CHAIN]
    blx     ip
    str     r0, [r6, #V_ANEXT]

    mov     r0, r5
    mov     r1, #16                     @ two veneers
    ldr     ip, [r5, #SVC_CAVE]
    blx     ip
    cmp     r0, #0
    beq     9f
    mov     r7, r0                      @ two veneers: ldr pc, [pc, #-4]; .word x
    ldr     r1, =0xE51FF004
    str     r1, [r7]
    str     r1, [r7, #8]
    ADRF    r1, accel_hook
    str     r1, [r7, #4]
    ADRF    r1, vd_hook
    str     r1, [r7, #12]

    /* The tag observer: needs a free slot (a full Subject asserts).  The
     * attach calls are boot-time only, so the count does not change under us. */
    ldr     ip, =F_SUBJECT
    blx     ip
    movs    r8, r0
    beq     9f
    mov     r1, #0
    mov     r2, #0
10: ldr     r3, [r8, r1, lsl #2]
    cmp     r3, #0
    addeq   r2, r2, #1
    add     r1, r1, #1
    cmp     r1, #SUBJ_SLOTS
    blo     10b
    cmp     r2, #0
    beq     9f
    add     r1, r6, #V_OVT              @ vtable: 0, 0, 0, handler
    ADRF    r0, tag_observer
    str     r0, [r1, #12]
    str     r1, [r6, #V_OBS]
    mov     r0, r8
    add     r1, r6, #V_OBS
    ldr     ip, =F_ATTACH
    blx     ip

    ldr     r2, =ACCEL_SITE             @ each site: bl its veneer
    mov     r0, r7
    bl      put_bl
    ldr     r2, =VD_SITE                @ the Thumb site: blx to its veneer
    add     r0, r7, #8
    bl      put_blx_t

    mov     r0, r5
    ldr     ip, [r5, #SVC_PUBLISH]
    blx     ip
    mov     r0, #0                      @ SL_KEEP
    pop     {r4, r5, r6, r7, r8, pc}
9:  mov     r0, #1                      @ SL_RELEASE: nothing was written
    pop     {r4, r5, r6, r7, r8, pc}

/* put_blx_t: r2 = a word-aligned Thumb site, r0 = a word-aligned ARM target.
 * Writes a Thumb-2 BLX (T2) over the four bytes.  Clobbers r1, r3, ip. */
put_blx_t:
    push    {r4, r5}
    add     r1, r2, #4
    bic     r1, r1, #3
    sub     r1, r0, r1                  @ offset from Align(pc, 4)
    ubfx    r3, r1, #12, #10            @ imm10H
    ubfx    ip, r1, #24, #1             @ S
    orr     r3, r3, ip, lsl #10
    orr     r3, r3, #0xF000             @ first halfword: 11110 S imm10H
    ubfx    r4, r1, #23, #1             @ I1 = NOT(J1 XOR S): J1 = I1 XOR S XOR 1
    eor     r4, r4, ip
    eor     r4, r4, #1
    ubfx    r5, r1, #22, #1             @ J2 likewise from I2
    eor     r5, r5, ip
    eor     r5, r5, #1
    ubfx    r1, r1, #2, #10             @ imm10L
    lsl     r1, r1, #1                  @ H = 0
    orr     r1, r1, #0xC000             @ second halfword: 11 J1 0 J2 imm10L H
    orr     r1, r1, r4, lsl #13
    orr     r1, r1, r5, lsl #11
    orr     r3, r3, r1, lsl #16
    str     r3, [r2]
    pop     {r4, r5}
    bx      lr

/* put_bl: r2 = site, r0 = target.  Writes an ARM BL.  Clobbers r1. */
put_bl:
    sub     r1, r0, r2
    sub     r1, r1, #8
    asr     r1, r1, #2
    bic     r1, r1, #0xFF000000
    orr     r1, r1, #0xEB000000
    str     r1, [r2]
    bx      lr
    .ltorg                              @ entry's constants, within reach

/* Data sits between entry and hook so every adr stays within reach (an ARM
 * adr encodes a rotated 8-bit immediate: any word distance under 1 KB). */
.align 2
accel_stock: .word 0xE3A02000         @ mov r2, #0, from the image
vd_stock:   .word 0x341DF2CC          @ movt r4, #0xC31D (Thumb-2), from the image
#endif
vars:       .space VARS_BYTES

/* ------------------------------------------------------------------ frame */
/* One CinemaDNG frame's block, from tag_observer on the frame's notify
 * (mode 3, type 3, C038C700), which comes before the DMA at C038C77C
 * copies the template in front of the RAW.  r0 = the template, r1 = its
 * length.  take_start found our place in it at the take's start.
 *
 * Reads only: the gyro buffer (filled by drain(), on the level's hook) and
 * the coprocessor's ring for the last few records not yet drained.  The
 * block is [the last block's end, this frame's mark), as much as the tag
 * holds.  Keeps r4-r11. */
#ifdef GYR2_FPL_OBSERVER
/* Offline callable seam only. No installer, capture, calibration or hook code.
 * A caller-owned frame consumer is mandatory; no fp producer is substituted. */
frame:
    ldr     ip, =GYR2_FRAME_CALLBACK
    bx      ip
#else
frame:
    push    {r4, r5, r6, r7, r8, r9, r10, r11, lr}
    sub     sp, sp, #(SNAP_BYTES + 4)   @ the snapshot; 8-aligned with the 9 words
    mov     r4, r0
    mov     r11, r1
    ADRF    r10, vars
    ldr     r1, [r10, #V_CALLS]
    add     r1, r1, #1
    str     r1, [r10, #V_CALLS]
    ldr     ip, =F_TICK
    blx     ip
    str     r0, [r10, #V_NOW]
    str     r0, [r10, #V_LTICK]

    /* A new take: take_start has run since the last frame.  No pause rule:
     * with the gyro buffer a long stall inside a take loses nothing, and
     * calling it a new take would split the take (A001_041 stalled 200+ ms
     * under lossless). */
    ldr     r8, [r10, #V_NEWTAKE]
    cmp     r8, #0
    beq     10f
    mov     r1, #0
    str     r1, [r10, #V_NEWTAKE]
    str     r1, [r10, #V_FRAMES]
    ldr     r1, [r10, #V_NOW]
    str     r1, [r10, #V_CLIP]
    bl      mode_info

10: /* Not the template take_start looked in: no place this take. */
    ldr     r1, [r10, #V_SRC]
    cmp     r1, r4
    movne   r1, #0
    strne   r1, [r10, #V_WOFF]

30: /* Where the stream is now.  Only the level's hook moves gyro records
     * into the buffer; this hook reads.  If the level has gone quiet, the
     * undrained tail is read from the ring as long as the ring still holds
     * it (snapshot() marks the block lost past that). */
    mov     r0, sp
    bl      snapshot                    @ sp: W, dhead, lost_until, ring, mark, flags
    ldr     r5, [sp, #S_FLAGS]          @ F_LOST when the ring could not be read
    ldr     r6, [sp, #S_MARK]           @ r6 = this frame's mark (global)

    ldr     r7, [r10, #V_PREV]          @ r7 = this block's first record (global)
    cmp     r8, #0
    beq     31f
    ldr     r0, =BACKFILL               @ a take starts: reach back
    sub     r7, r6, r0
    str     r7, [r10, #V_ORIGIN]
31:
    /* The oldest record still good: not before a lost stretch, and not so
     * far behind the writer that the buffer may have gone round under us. */
    ldr     r0, [sp, #S_LU]
    ldr     r1, [sp, #S_W]
    ldr     r2, =(GLOG_N - LAG_MARGIN)
    sub     r1, r1, r2
    cmp     r1, r0                      @ global indices: compare as signed gaps
    movpl   r0, r1                      @ the later of the two
    ldr     r1, [sp, #S_GONE]           @ and not in the stretch the ring lost
    cmp     r1, r0
    movpl   r0, r1
    subs    r1, r7, r0
    bpl     32f
    orr     r5, r5, #F_LOST
    mov     r7, r0
    subs    r1, r6, r7                  @ nothing left at all
    movmi   r7, r6
32:
    ldr     r0, [r10, #V_WOFF]
    cmp     r0, #0
    bne     40f
    str     r6, [r10, #V_PREV]          @ no place this frame: the stream goes on
    ldr     r0, [r10, #V_SKIPS]
    add     r0, r0, #1
    str     r0, [r10, #V_SKIPS]
    b       90f

40: /* More due than the tag holds (a take's first frame, a stall): the
     * oldest go now, the rest with the next frames.  r6 = the block's end. */
    ldr     r1, [r10, #V_MAXN]
    sub     r2, r6, r7
    cmp     r2, r1
    addhi   r6, r7, r1
    str     r6, [r10, #V_PREV]
    ldr     r0, [r10, #V_FRAMES]
    add     r0, r0, #1
    str     r0, [r10, #V_FRAMES]
    cmp     r0, #1
    orreq   r5, r5, #F_FIRST
    tst     r5, #F_LOST
    ldrne   r0, [r10, #V_LOSTS]
    addne   r0, r0, #1
    strne   r0, [r10, #V_LOSTS]

    /* r11 = the block; the payload header at r11 + 12.  The magic goes
     * first, so a block left half-written is no block. */
    ldr     r0, [r10, #V_WOFF]
    add     r11, r4, r0
    mov     r0, #0
    str     r0, [r11]
    ldr     r0, =(2 | (2 << 8) | (WRITER << 16))   @ version 2, kind 2, our build
    str     r0, [r11, #4]
    mov     r0, #2                      @ fmt_version 2, orientation 0, flags
    orr     r0, r0, r5, lsl #16
    str     r0, [r11, #12]
    ldr     r0, [r10, #V_CLIP]
    str     r0, [r11, #16]
    ldr     r0, [r10, #V_FRAMES]
    sub     r0, r0, #1                  @ frame_seq, from 0
    str     r0, [r11, #20]
    ldr     r0, =PERIOD_PS
    str     r0, [r11, #24]
    ldr     r0, =GSCALE_BITS
    str     r0, [r11, #28]
    ldr     r0, =ASCALE_BITS
    str     r0, [r11, #32]
    ldr     r0, [r10, #V_MHM]           @ mode | hmax << 16
    str     r0, [r11, #36]
    ldr     r0, [r10, #V_WL]            @ width | lines << 16
    str     r0, [r11, #40]
    ldr     r0, [r10, #V_BIN]           @ binning h | v << 16
    str     r0, [r11, #44]
    ldr     r0, =LENS_FOCAL             @ calibrated focal | frame_mark << 16
    ldr     r0, [r0]
    cmp     r0, #0x10000
    movhs   r0, #0                      @ not a focal length: none
    ldr     r1, [sp, #S_MARK]
    sub     r1, r1, r7
    orr     r0, r0, r1, lsl #16
    str     r0, [r11, #48]
    ldr     r0, [r10, #V_ORIGIN]        @ base_idx, from the take's first record
    sub     r0, r7, r0
    str     r0, [r11, #52]
    sub     r2, r6, r7
    str     r2, [r11, #56]              @ n_samples (n_events written later)

    /* The samples: [r7, r6).  Below W from the gyro buffer, from W on from
     * the coprocessor's ring at dhead. */
    add     r1, r11, #60
    ADRF    r8, gbuf
    ldr     r9, [sp, #S_W]
50: cmp     r7, r6
    beq     51f
    subs    r0, r7, r9
    bpl     52f
    ldr     r0, =(GLOG_N - 1)           @ from the buffer
    and     r0, r7, r0
    add     r0, r0, r0, lsl #1          @ x 6
    add     r0, r8, r0, lsl #1
    ldrh    r2, [r0]
    strh    r2, [r1]
    ldrh    r2, [r0, #2]
    strh    r2, [r1, #2]
    ldrh    r2, [r0, #4]
    strh    r2, [r1, #4]
    b       53f
52: ldr     r2, [sp, #S_DHEAD]          @ from the ring: dhead + 8 * (r7 - W)
    add     r0, r2, r0, lsl #3
    ldr     r2, =GYRO_SPAN
54: cmp     r0, r2
    subhs   r0, r0, r2
    bhs     54b
    ldr     r2, [sp, #S_RING]
    add     r0, r2, r0
    add     r0, r0, #4
    ldrh    r2, [r0]
    strh    r2, [r1]
    ldrh    r2, [r0, #2]
    strh    r2, [r1, #2]
    ldrh    r2, [r0, #6]
    strh    r2, [r1, #4]
53: add     r1, r1, #6
    add     r7, r7, #1
    b       50b

51: ldr     r7, [r11, #52]              @ the block's first record, again
    ldr     r0, [r10, #V_ORIGIN]
    add     r7, r7, r0
    mov     r0, r1                      @ the level readings in [r7, r6)
    mov     r2, r7
    mov     r3, r6
    bl      put_events
    strh    r0, [r11, #58]
    mov     r2, r7                      @ then the frame syncs
    mov     r3, r6
    bl      put_vd
    ldrh    r2, [r11, #58]
    add     r2, r2, r0
    strh    r2, [r11, #58]
    sub     r6, r1, r11                 @ the payload's end, from the block
    sub     r0, r6, #12
    str     r0, [r11, #8]
    dmb
    ldr     r0, =MAGIC                  @ the commit, last
    str     r0, [r11]
    bic     r0, r11, #(LINE - 1)        @ clean the block's lines for the DMA
    add     r1, r11, r6
56: mcr     p15, 0, r0, c7, c10, 1      @ DCCMVAC
    add     r0, r0, #LINE
    cmp     r0, r1
    blo     56b
    dsb

90: add     sp, sp, #(SNAP_BYTES + 4)
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, pc}
#endif

/* take_start: the take's template is serialized (the mode-2 notify,
 * C0378F70, after C0378EC8 stored its length): find our tag in it once, so
 * no frame parses the header.  r10 = vars.  Keeps r4-r11. */
take_start:
    push    {r4, lr}
    ldr     r4, =TEMPLATE_PTR
    ldr     r4, [r4]
    ldr     r1, =TEMPLATE_LEN
    ldr     r1, [r1]
    str     r4, [r10, #V_SRC]
    mov     r0, #0
    str     r0, [r10, #V_WOFF]
    cmp     r4, #0
    beq     9f
    mov     r0, r4
    bl      find_gtag                   @ r0 = block offset or 0, r1 = its room
    cmp     r0, #0
    beq     9f
    subs    r2, r1, #(FRAME_BYTES + EV_RESERVE)
    bls     9f                          @ not even an empty block fits
    ldr     r3, =0xAAAAAAAB             @ samples that fit: room / 6
    umull   r1, r3, r2, r3
    lsr     r3, r3, #2
    str     r3, [r10, #V_MAXN]
    str     r0, [r10, #V_WOFF]
9:  mov     r0, #1
    str     r0, [r10, #V_NEWTAKE]
    pop     {r4, pc}

/* drain: move the coprocessor's new records into the gyro buffer.  Called
 * only from the level's hook, so the buffer has one writer and needs no lock
 * (an LDREX/STREX lock in the block's memory froze the boot, 2026-10-06).
 * r10 = vars.  Keeps r4-r11. */
#ifndef GYR2_FPL_OBSERVER
drain:
    push    {r4, r5, r6, r7, r8, r9, r11, lr}
    ldr     ip, =F_TICK
    blx     ip
    ldr     r1, [r10, #V_LDRAIN]
    str     r0, [r10, #V_LDRAIN]
    sub     r7, r0, r1                  @ microseconds since the last drain
    bl      ring_head
    cmn     r0, #1
    beq     80f
    mov     r4, r0                      @ head offset
    mov     r8, r2                      @ ring
    ldr     r6, [r10, #V_DHEAD]
    cmn     r6, #1
    bne     2f
    mov     r5, #0                      @ the first drain: start here
    mov     r9, #0
    b       70f
2:  subs    r5, r4, r6                  @ records since, modulo a lap
    ldrlo   r0, =GYRO_SPAN
    addlo   r5, r5, r0
    lsr     r5, r5, #3
    /* More than a lap since the last drain (nobody drained for 240 ms):
     * the time says how many; the indices stay true, the lost are counted. */
    mov     r3, #US_PER_REC
    mul     r3, r5, r3
    ldr     r1, =(LAP_US / 2)
    add     r3, r3, r1
    ldr     r1, =LAP_US
    mov     r11, #MAX_LAPS
3:  cmp     r7, r3
    bls     4f
    subs    r11, r11, #1                @ longer than any stall worth counting
    beq     4f
    add     r5, r5, #600
    add     r3, r3, r1
    b       3b
4:  mov     r9, #0                      @ r9 = records lost
    subs    r0, r5, #AVAIL
    movhi   r9, r0
    sub     r0, r5, r9                  @ r0 = records to copy, newest
    ldr     r11, [r10, #V_W]
    add     r11, r11, r9                @ the first copied record's index
    sub     r2, r4, r0, lsl #3          @ its ring offset
    cmp     r2, #0
    ldrlt   r1, =GYRO_SPAN
    addlt   r2, r2, r1
    add     r6, r8, #4                  @ the ring's first record
    add     r2, r6, r2
    ldr     r1, =GYRO_SPAN
    add     r3, r6, r1                  @ one past its last
    ADRF    ip, gbuf
5:  cmp     r0, #0
    beq     70f
    cmp     r2, r3
    movhs   r2, r6
    ldr     r1, =(GLOG_N - 1)
    and     r1, r11, r1
    add     r1, r1, r1, lsl #1
    add     r1, ip, r1, lsl #1
    ldrh    r7, [r2]
    strh    r7, [r1]
    ldrh    r7, [r2, #2]
    strh    r7, [r1, #2]
    ldrh    r7, [r2, #6]
    strh    r7, [r1, #4]
    add     r2, r2, #8
    add     r11, r11, #1
    sub     r0, r0, #1
    b       5b

70: /* Publish {W, dhead, lost_until} under the sequence word.  First keep
     * the current set: a reader that preempts this task while the word is odd
     * cannot wait for it, and reads the kept set instead. */
    ldr     r0, [r10, #V_W]
    str     r0, [r10, #V_PW]
    ldr     r0, [r10, #V_DHEAD]
    str     r0, [r10, #V_PDH]
    ldr     r0, [r10, #V_LU]
    str     r0, [r10, #V_PLU]
    dmb
    ldr     r0, [r10, #V_SEQ]
    add     r0, r0, #1
    str     r0, [r10, #V_SEQ]           @ odd: being written
    dmb
    ldr     r1, [r10, #V_W]
    add     r2, r1, r9
    cmp     r9, #0
    strne   r2, [r10, #V_LU]            @ everything before here is gone
    add     r1, r1, r5
    str     r1, [r10, #V_W]
    str     r4, [r10, #V_DHEAD]
    dmb
    add     r0, r0, #1
    str     r0, [r10, #V_SEQ]           @ even: consistent
80: pop     {r4, r5, r6, r7, r8, r9, r11, pc}

/* snapshot: r0 = SNAP_BYTES of room.  A consistent {W, dhead, lost_until}
 * (retried while drain() is writing them), the ring, and the mark: W plus
 * the records the ring holds that are not drained yet.  r10 = vars.
 * Keeps r4-r11. */
snapshot:
    push    {r4, r5, r6, r7, r8, lr}
    mov     r4, r0
    mov     r8, #8                      @ tries
1:  ldr     r5, [r10, #V_SEQ]
    dmb
    tst     r5, #1
    bne     2f
    ldr     r0, [r10, #V_W]
    ldr     r1, [r10, #V_DHEAD]
    ldr     r2, [r10, #V_LU]
    b       4f
2:  ldr     r0, [r10, #V_PW]            @ the writer is mid-way: its kept set
    ldr     r1, [r10, #V_PDH]
    ldr     r2, [r10, #V_PLU]
4:  dmb
    ldr     r3, [r10, #V_SEQ]
    cmp     r3, r5
    beq     3f
    subs    r8, r8, #1
    bne     1b
3:  str     r0, [r4, #S_W]
    str     r1, [r4, #S_DHEAD]
    str     r2, [r4, #S_LU]
    mov     r5, r0
    mov     r6, r1
    mov     r7, #0                      @ flags
    str     r2, [r4, #S_GONE]           @ nothing lost: no tighter than LU
    bl      ring_head
    str     r2, [r4, #S_RING]
    cmn     r0, #1
    beq     8f
    cmn     r6, #1                      @ nothing drained yet
    beq     8f
    subs    r8, r0, r6                  @ records not drained yet, modulo a lap
    ldrlo   r1, =GYRO_SPAN
    addlo   r8, r8, r1
    lsr     r8, r8, #3
    /* The level has gone quiet for more than a lap: the offsets alias.  The
     * time since its last drain says how many laps; what the ring no longer
     * holds is gone, but the mark stays at its true place. */
    ldr     ip, =F_TICK
    blx     ip
    ldr     r1, [r10, #V_LDRAIN]
    sub     r0, r0, r1                  @ microseconds since the last drain
    mov     r3, #US_PER_REC
    mul     r3, r8, r3
    ldr     r1, =(LAP_US / 2)
    add     r3, r3, r1
    ldr     r1, =LAP_US
    mov     r2, #MAX_LAPS
1:  cmp     r0, r3
    bls     2f
    subs    r2, r2, #1
    beq     2f
    add     r8, r8, #600
    add     r3, r3, r1
    b       1b
2:  subs    r0, r8, #AVAIL              @ more than the ring keeps
    bls     3f
    orr     r7, r7, #F_LOST
    add     r0, r5, r0
    str     r0, [r4, #S_GONE]           @ [W, W + n - AVAIL) is in neither place
3:  add     r0, r5, r8
    b       9f
8:  orr     r7, r7, #F_LOST
    mov     r0, r5
9:  str     r0, [r4, #S_MARK]
    str     r7, [r4, #S_FLAGS]
    pop     {r4, r5, r6, r7, r8, pc}

/* ring_head: r0 = the ring's next-record offset, or -1 when the ring cannot
 * be read; r2 = the ring.  Clobbers r0-r3. */
ring_head:
    ldr     r0, =GYRO_DESC_PTR
    ldr     r0, [r0]
    lsr     r1, r0, #22                 @ in the coprocessor's RAM, 0x2E000000..
    cmp     r1, #(0x2E000000 >> 22)
    bne     8f
    tst     r0, #3
    bne     8f
    ldr     r2, [r0, #0x60]
    lsr     r1, r2, #22
    cmp     r1, #(0x2E000000 >> 22)
    bne     8f
    tst     r2, #3
    bne     8f
    ldr     r0, [r2]
    sub     r0, r0, r2                  @ the next record's offset
    ldr     r3, =GYRO_SPAN
    cmp     r0, r3
    moveq   r0, #0                      @ at the very end: the coprocessor has
                                        @ not wrapped it yet -- the same as 0
                                        @ (fpSup gyro_drain.S accepts it too;
                                        @ seen once in 474 frames, A001_036 #404)
    bhi     8f
    tst     r0, #7
    bxeq    lr
8:  mvn     r0, #0
    bx      lr

/* accel_hook: in place of `mov r2, #0` at ACCEL_SITE.  r4 = the driver's
 * x, y, z.  Drains the gyro first, then records the reading at the stream's
 * position now -- its place among the gyro samples is its time.  Then the
 * layer below, or the displaced instruction.  The level buffer's only writer. */
accel_hook:
    push    {r0, r1, r2, r3, r5, r10, ip, lr}
    sub     sp, sp, #SNAP_BYTES
    ADRF    r10, vars
    bl      drain
    mov     r0, sp
    bl      snapshot
    ldr     r1, [sp, #S_FLAGS]
    tst     r1, #F_LOST                 @ no ring: no place to put it
    bne     91f
    ldr     r1, [sp, #S_MARK]
    ldr     r2, [r10, #V_EW]
    and     r3, r2, #(ELOG_N - 1)
    ADRF    ip, ebuf
    add     r3, r3, r3, lsl #1          @ x 12
    add     ip, ip, r3, lsl #2
    str     r1, [ip]                    @ position
    ldrh    r3, [r4]
    strh    r3, [ip, #4]
    ldrh    r3, [r4, #2]
    strh    r3, [ip, #6]
    ldrh    r3, [r4, #4]
    strh    r3, [ip, #8]
    dmb
    add     r2, r2, #1
    str     r2, [r10, #V_EW]
91: add     sp, sp, #SNAP_BYTES
    pop     {r0, r1, r2, r3, r5, r10, ip, lr}
    push    {r0, r1}
    ADRF    r0, vars
    ldr     r0, [r0, #V_ANEXT]
    cmp     r0, #0
    bne     92f
    pop     {r0, r1}
    mov     r2, #0                      @ the displaced instruction
    bx      lr
92: mov     ip, r0
    pop     {r0, r1}
    bx      ip                          @ the layer below replays it

#endif
/* tag_observer: vt+0xC of our observer, called as (obs, DataPool) on every
 * notify of the Subject: take starts, stills, every CinemaDNG frame.  Only
 * the CinemaDNG take start (mode 0, type 3) adds our tag; then the builder
 * is the CinemaDNG one and the template is not serialized yet.  Returns 1
 * (0 would detach us). */
tag_observer:
    push    {r4, r5, r6, r10, r11, lr}
    sub     sp, sp, #24
    mov     r4, r1
    ADRF    r10, vars
    ldr     r0, [r4]
    ldr     ip, [r0, #DP_EVENT]
    mov     r0, r4
    blx     ip
    cmp     r0, #0
    beq     9f
    ldr     r1, [r0, #4]                @ type: CinemaDNG only
    cmp     r1, #EV_TAKE_TYPE
    bne     9f
    ldr     r1, [r0]                    @ mode
    cmp     r1, #EV_FRAME
    beq     30f
    cmp     r1, #EV_SERIALIZED
    beq     20f
    cmp     r1, #EV_BUILD
    bne     9f
    ldr     r0, [r4]
    ldr     ip, [r0, #DP_BUILDER]
    mov     r0, r4
    blx     ip
    movs    r5, r0
    beq     9f
    /* The size: GTAG_FRAMES frames of samples at the take's rate, the
     * header, the events, and 3 for the word boundary. */
    mov     r0, #0
    str     r0, [sp, #8]
    str     r0, [sp, #12]
    add     r0, sp, #8
    ldr     ip, =F_RATE
    blx     ip
    ldr     r0, [sp, #8]                @ num
    ldr     r1, [sp, #12]               @ den
    ldr     r6, =GTAG_MAX
    cmp     r0, #0
    cmpne   r1, #0
    beq     1f
    ldr     r2, =HZ                     @ samples a frame = HZ * den / num, up
    mul     r1, r1, r2
    add     r1, r1, r0
    sub     r1, r1, #1
    bl      udiv
    mov     r1, #(GTAG_FRAMES * 6)
    mul     r0, r0, r1
    ldr     r6, =(FRAME_BYTES + EV_RESERVE + 3)
    add     r6, r6, r0
    ldr     r0, =GTAG_MAX
    cmp     r6, r0
    movhi   r6, r0
1:  ADRF    r0, zbuf                    @ copied now: zeros, our block's first state
    str     r6, [sp]
    str     r0, [sp, #4]
    mov     r0, r5
    mov     r1, #IFD_MAKERNOTE
    ldr     r2, =GTAG
    mov     r3, #7                      @ UNDEFINED
    ldr     ip, =F_ADD_TAG
    blx     ip
    ldr     r1, [r10, #V_TAGS]
    add     r1, r1, #1
    str     r1, [r10, #V_TAGS]
    str     r6, [r10, #V_TAGN]
    b       9f
20: bl      take_start
    b       9f
30: ldr     r0, =TEMPLATE_PTR           @ the frame's notify
    ldr     r0, [r0]
    ldr     r1, =TEMPLATE_LEN
    ldr     r1, [r1]
    bl      frame
9:  mov     r0, #1
    add     sp, sp, #24
    pop     {r4, r5, r6, r10, r11, pc}

/* udiv: r0 = r1 / r0 (unsigned, r0 != 0), shift-subtract.  Clobbers r1-r3. */
udiv:
    mov     r2, r0
    mov     r0, #0
    mov     r3, #1
1:  cmp     r2, r1
    bhi     2f
    tst     r2, #0x80000000
    bne     2f
    lsl     r2, r2, #1
    lsl     r3, r3, #1
    b       1b
2:  cmp     r1, r2
    subhs   r1, r1, r2
    orrhs   r0, r0, r3
    lsr     r2, r2, #1
    lsrs    r3, r3, #1
    bne     2b
    bx      lr

/* put_events: r0 = where events go, [r2, r3) = this block's records
 * (global).  Writes the readings whose position falls inside, as
 * {pos u16 from r2, type 1, len 6, x, y, z}; skips older ones; leaves later
 * ones for the next block.  Returns r0 = count, r1 = the next byte.
 * r10 = vars. */
#ifndef GYR2_FPL_OBSERVER
put_events:
    push    {r4, r5, r6, r7, r8, r9, r11, lr}
    mov     r1, r0
    mov     r8, r2
    mov     r9, r3
    mov     r4, #0                      @ count
    ldr     r5, [r10, #V_ER]
    ldr     r6, [r10, #V_EW]
    dmb
    sub     r0, r6, r5                  @ more than it holds: the oldest are gone
    cmp     r0, #ELOG_N
    subhi   r5, r6, #ELOG_N
    ADRF    r11, ebuf
1:  cmp     r5, r6
    beq     9f
    and     r0, r5, #(ELOG_N - 1)
    add     r0, r0, r0, lsl #1
    add     r7, r11, r0, lsl #2
    ldr     r0, [r7]                    @ position
    subs    r0, r0, r8
    bmi     8f                          @ before this block: gone by
    ldr     r2, [r7]
    subs    r2, r2, r9
    bpl     9f                          @ at or after this block's end: next one
    cmp     r4, #EV_MAX
    beq     8f                          @ room for no more: drop it
    strh    r0, [r1]
    mov     r0, #EVENT_LEVEL
    orr     r0, r0, #0x600              @ type 1, len 6
    strh    r0, [r1, #2]
    ldrh    r0, [r7, #4]
    strh    r0, [r1, #4]
    ldrh    r0, [r7, #6]
    strh    r0, [r1, #6]
    ldrh    r0, [r7, #8]
    strh    r0, [r1, #8]
    add     r1, r1, #10
    add     r4, r4, #1
8:  add     r5, r5, #1
    b       1b
9:  str     r5, [r10, #V_ER]
    mov     r0, r4
    pop     {r4, r5, r6, r7, r8, r9, r11, pc}

/* The frame sync.  Entered by a Thumb BLX from VD_SITE through an ARM
 * veneer; lr has the Thumb bit.  At interrupt level:
 * no waiting and no system calls.  Each records where the gyro stream is now
 * (the same global position as a level reading) and the TickTimer, then
 * replays the movt it displaced.  The only writer of its own ring. */
.macro SYNC_HOOK name, ring, wvar, reg
\name:
    push    {r0, r1, r2, r3, r5, r10, ip, lr}
    sub     sp, sp, #SNAP_BYTES
    ADRF    r10, vars
    mov     r0, sp
    bl      snapshot
    ldr     r1, [sp, #S_FLAGS]
    tst     r1, #F_LOST                 @ no place in the stream: nothing to say
    bne     1f
    ldr     ip, =F_TICK
    blx     ip
    ldr     r1, [sp, #S_MARK]
    ldr     r2, [r10, #\wvar]
    and     r3, r2, #(VLOG_N - 1)
    ADRF    ip, \ring
    add     ip, ip, r3, lsl #3
    str     r1, [ip]
    str     r0, [ip, #4]
    dmb
    add     r2, r2, #1
    str     r2, [r10, #\wvar]
1:  add     sp, sp, #SNAP_BYTES
    pop     {r0, r1, r2, r3, r5, r10, ip, lr}
    movt    \reg, #0xC31D              @ the displaced instruction
    bx      lr
.endm
    SYNC_HOOK vd_hook, vbuf, V_VW, r4

/* put_vd: r1 = where events go, [r2, r3) = this block's records
 * (global).  Like put_events, as {pos u16, type, len 4, TickTimer u32}.
 * Returns r0 = count, r1 = the next byte.  r10 = vars. */
.macro PUT_SYNC name, ring, wvar, rvar, type
\name:
    push    {r4, r5, r6, r7, r8, r9, lr}
    mov     r8, r2
    mov     r9, r3
    mov     r4, #0
    ldr     r5, [r10, #\rvar]
    ldr     r6, [r10, #\wvar]
    dmb
    sub     r0, r6, r5                  @ more than it holds: the oldest are gone
    cmp     r0, #VLOG_N
    subhi   r5, r6, #VLOG_N
    ADRF    r7, \ring
1:  cmp     r5, r6
    beq     9f
    and     r0, r5, #(VLOG_N - 1)
    add     ip, r7, r0, lsl #3
    ldr     r0, [ip]                    @ position
    subs    r0, r0, r8
    bmi     8f                          @ before this block: already past
    ldr     r2, [ip]
    subs    r2, r2, r9
    bpl     9f                          @ at or after the end: the next block's
    cmp     r4, #VEV_MAX
    beq     8f
    strh    r0, [r1]
    mov     r0, #\type
    orr     r0, r0, #0x400              @ len 4
    strh    r0, [r1, #2]
    ldr     r0, [ip, #4]
    strh    r0, [r1, #4]
    lsr     r0, r0, #16
    strh    r0, [r1, #6]
    add     r1, r1, #8
    add     r4, r4, #1
8:  add     r5, r5, #1
    b       1b
9:  str     r5, [r10, #\rvar]
    mov     r0, r4
    pop     {r4, r5, r6, r7, r8, r9, pc}
.endm
    PUT_SYNC put_vd, vbuf, V_VW, V_VR, EVENT_VD

/* mode_info: the running sensor mode as the camera's accessors give it, raw,
 * into V_MHM (mode | hmax << 16), V_WL (readout width | lines << 16) and
 * V_BIN (binning h | v << 16); the plugin works out the readout and the
 * window.  All 0 when no mode runs.  As fpSup gcsv_json.S calls them at
 * record start.  r10 = vars. */
mode_info:
    push    {r4, r5, r6, lr}
    mov     r0, #0
    str     r0, [r10, #V_MHM]
    str     r0, [r10, #V_WL]
    str     r0, [r10, #V_BIN]
    ldr     ip, =SENSOR_MODE_FN
    blx     ip
    movs    r4, r0
    beq     9f
    lsl     r4, r4, #16                 @ a mode number fits a halfword
    lsr     r4, r4, #16
    str     r4, [r10, #V_MHM]
    ldr     r0, =MODE_OBJ
    mov     r1, r4
    ldr     ip, =F_TIMING
    blx     ip
    cmp     r0, #0
    beq     9f
    ldrh    r5, [r0, #4]                @ hmax: sensor clocks a line
    orr     r5, r4, r5, lsl #16
    str     r5, [r10, #V_MHM]
    ldr     r0, =MODE_OBJ
    mov     r1, r4
    ldr     ip, =F_GEOM
    blx     ip
    cmp     r0, #0
    beq     9f
    ldrh    r5, [r0, #4]                @ readout width
    ldrh    r6, [r0, #8]                @ lines read
    orr     r5, r5, r6, lsl #16
    str     r5, [r10, #V_WL]
    ldrh    r5, [r0, #0x44]             @ binning, horizontal
    ldrh    r6, [r0, #0x48]             @ and vertical
    orr     r5, r5, r6, lsl #16
    str     r5, [r10, #V_BIN]
9:  pop     {r4, r5, r6, pc}
#endif

/* rd16 / rd32: r0 = [r1 + r2], byte-wise little-endian.  Clobbers r3. */
rd16:
    add     r3, r1, r2
    ldrb    r0, [r3]
    ldrb    r3, [r3, #1]
    orr     r0, r0, r3, lsl #8
    bx      lr
rd32:
    push    {r4, lr}
    add     r4, r1, r2
    ldrb    r0, [r4]
    ldrb    r3, [r4, #1]
    orr     r0, r0, r3, lsl #8
    ldrb    r3, [r4, #2]
    orr     r0, r0, r3, lsl #16
    ldrb    r3, [r4, #3]
    orr     r0, r0, r3, lsl #24
    pop     {r4, pc}

/* find_entry: r1 = template, r4 = len, r5 = IFD offset (count at +0),
 * r6 = tag.  r0 = the entry's offset, or 0.  Clobbers r0, r2, r3, r7, r8. */
find_entry:
    push    {r9, lr}
    add     r2, r5, #2
    cmp     r2, r4
    bhs     8f
    mov     r2, r5
    bl      rd16
    mov     r7, r0                      @ count
    mov     r3, #12
    mla     r8, r7, r3, r5
    add     r8, r8, #2                  @ end of the entries
    cmp     r8, r4
    bhi     8f
    add     r8, r5, #2                  @ the first entry
1:  cmp     r7, #0
    beq     8f
    mov     r2, r8
    bl      rd16
    cmp     r0, r6
    moveq   r0, r8
    popeq   {r9, pc}
    add     r8, r8, #12
    sub     r7, r7, #1
    b       1b
8:  mov     r0, #0
    pop     {r9, pc}

/* find_gtag: r0 = template, r1 = len.  Returns r0 = the word-aligned
 * offset of our MakerNote tag's value (the block's place), r1 = the bytes
 * from there to the value's end; r0 = 0 when any step is missing or out of
 * bounds.  The plugin aligns the same way (file offset = template offset). */
find_gtag:
    push    {r4, r5, r6, r7, r8, r9, r10, r11, ip, lr}
    mov     r9, r0
    mov     r4, r1
    mov     r1, r9
    cmp     r4, #0x100
    blo     90f
    ldr     r0, [r9]
    ldr     r2, =0x002A4949             @ 'II', 42
    cmp     r0, r2
    bne     90f
    mov     r2, #4
    bl      rd32
    mov     r5, r0                      @ IFD0
    mov     r6, #0x8700
    orr     r6, r6, #0x69               @ 0x8769 Exif
    bl      find_entry
    cmp     r0, #0
    beq     90f
    add     r2, r0, #8
    bl      rd32
    mov     r5, r0                      @ Exif IFD
    mov     r6, #0x9200
    orr     r6, r6, #0x7C               @ 0x927C MakerNote
    bl      find_entry
    cmp     r0, #0
    beq     90f
    mov     r10, r0
    add     r2, r10, #2
    bl      rd16
    cmp     r0, #7                      @ UNDEFINED
    bne     90f
    add     r2, r10, #4
    bl      rd32
    mov     r11, r0                     @ MakerNote length
    add     r2, r10, #8
    bl      rd32
    mov     r10, r0                     @ MakerNote offset
    add     r0, r10, r11
    cmp     r0, r4
    bhi     90f
    cmp     r11, #12
    blo     90f
    add     r2, r9, r10                 @ 'SIGMA', 0, 0, 0
    ldrb    r0, [r2]
    cmp     r0, #'S'
    bne     90f
    ldrb    r0, [r2, #4]
    cmp     r0, #'A'
    bne     90f
    add     r5, r10, #10                @ the MakerNote IFD's count
    ldr     r6, =GTAG
    bl      find_entry
    cmp     r0, #0
    beq     90f
    mov     r7, r0
    add     r2, r7, #2
    bl      rd16
    cmp     r0, #7                      @ UNDEFINED
    bne     90f
    add     r2, r7, #4
    bl      rd32
    mov     r8, r0                      @ count
    add     r2, r7, #8
    bl      rd32                        @ the value's offset, from the file start
    cmp     r8, #4                      @ inline: no room anyway
    bls     90f
    add     r8, r0, r8                  @ its end
    cmp     r8, r0
    blo     90f                         @ wrapped
    cmp     r8, r4
    bhi     90f
    add     r0, r0, #3
    bic     r0, r0, #3
    subs    r1, r8, r0
    bls     90f
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, ip, pc}
90: mov     r0, #0
    mov     r1, #0
    pop     {r4, r5, r6, r7, r8, r9, r10, r11, ip, pc}

    .ltorg

/* Past the file: the loader zeroes block_size - file_len (build.py). */
.align 3
gbuf:
#ifdef GYR2_FPL_OBSERVER
/* Owned zero source for tag-copy; unlike the sup, the probe carries its zeros. */
zbuf: .space GTAG_MAX
#else
.set ebuf, gbuf + GLOG_BYTES
.set vbuf, ebuf + ELOG_BYTES
.set zbuf, vbuf + VLOG_BYTES              /* GTAG_MAX zeros, never written */
#endif
