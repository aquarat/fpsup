/* SIGMA fp L 3.02: USB shell worker ABI, from the fp-vs-fp L research
 * correspondence. Shell, MEM1 and file transfers were camera-proven October
 * 20; lifecycle/mode-switch ownership remains unresolved. The static audit is
 * docs/FPL_WORKER_AUDIT.md; live evidence is FPL_USB_DIAG_2026-10-19.md.
 * All entry points below are ARM unless
 * the individual comment says Thumb.
 *
 * THE CAVE IS GONE. fp keeps the worker's fixed rendezvous words in
 * unallocated DRAM (its "cave"); fp L's counterpart range is IMU-owned image
 * space, so nothing of ours may live at a fixed image address. The fp L
 * rendezvous is the pool publication word FW_WFRAMEBUF (0xC37588BC, the
 * shell bufmem descriptor, captured zero at boot): the worker publishes
 * +0 pool, +4 size, +8 code there. STATE and its four trailing words are
 * POOL-RELATIVE offsets (FW_WSTATE_OFF etc.) into that same published pool,
 * not fixed addresses; host tools reach them through [FW_WFRAMEBUF].
 * Double-spawn protection is the publication word being nonzero -- the
 * AutoRun provably runs twice per boot on this camera -- not the fp STATE
 * magic, which lives where only the pool is known after publication. */
#define FW_WCRETSK    0xC0016A58   /* tk_cre_tsk stub+syscall: SAME as fp      */
#define FW_WSTATSK    0xC0016BC0   /* tk_sta_tsk: SAME as fp                   */
#define FW_WDELAY     0xC01F5244   /* delay(ms), yields the CPU                */
#define FW_WENDX      0xC01E35C9   /* EndTransfer(logical ep)     [thumb]      */
#define FW_WSTARTX    0xC01E3401   /* StartTransfer(physical ep)  [thumb]     */
#define FW_WWAIT      0xC01E1701   /* Wait(logical ep, timeout)   [thumb]      */
#define FW_WSHINIT    0xC03D9C28   /* shell context one-time init             */
#define FW_WSHPUSH    0xC03D9CD8   /* push an output sink                       */
#define FW_WSHPOP     0xC03D9D38   /* pop the output sink                       */
#define FW_WSHRUN     0xC03D9E38   /* tokenise, dispatch and run one line      */
#define FW_WVSNPRINT  0xC0013F48   /* vsnprintf: SAME as fp                    */
#define FW_WCRC32     0xC06AC4D8   /* crc32(buf, len) leaf, table 0xC2E4B40C  */
#define FW_WH_GET     0xC001D740   /* (desc, class, size, 0): SAME as fp       */
#define FW_WH_ADDR    0xC001D7F0   /* (desc) -> address: SAME as fp            */
#define FW_WDCACHE    0xC000E91C   /* D-cache clean/invalidate: SAME as fp     */
#define FW_WICACHE    0xC000EABC   /* whole I-cache invalidate: SAME as fp     */

/* --- the PTP gadget's pipes (the firmware owns the descriptors) ---------- */
#define FW_WTRB_OUT   0xC31E1668   /* TRB table[1]: EP 0x01 OUT              */
#define FW_WTRB_IN    0xC31E166C   /* TRB table[2]: EP 0x82 IN               */
#define FW_WUSB_STATE 0xC31E1B48   /* 4 means the link is suspended           */
#define FW_WDALEPENA  0x2100C720   /* DWC3 MMIO: SAME as fp                   */
#define FW_WOUT_BUSY  0xC31E1D74   /* driver's bulk-OUT in-use word           */
#define FW_WSHELL_CTX 0xC3757744   /* firmware shell context singleton         */
#define FW_WEP_MASK   0x24          /* physical 2 (0x01 OUT) | 5 (0x82 IN): verify */
#define FW_WPHYS_OUT  2
#define FW_WPHYS_IN   5
#define FW_WLOG_OUT   1
#define FW_WLOG_IN    2
#define FW_WTRB_ARMED 0x813
/* H_ADDR returns the CPU-accessible non-cacheable buffer. Stock USB accesses
 * that pointer directly; +0x40000000 is NOT its fallback-MMU alias. This is
 * separate from the unchanged CPU-to-USB-bus subtraction. See
 * docs/FPL_USB_DIAG_2026-10-19.md; corrected mapping is live-verified. */
#define FW_WFRAME_CPU_OFFSET 0

/* --- the worker's rendezvous (NO cave: published, not fixed) --------------- */
#define FW_WFRAMEBUF  0xC37588BC   /* +0 pool, +4 size, +8 code               */
/* STATE and its words are offsets into the published pool. 0x10000.. is the
 * file-staging region; the offsets below sit in the worker's own header area
 * of the pool, between the frame buffer (+0x0000) and the capture buffer
 * (+0x2000).  Each offset is ARM-imm8-rotatable (the PW macro adds it with a
 * single `addne`): keep that property when moving anything here. */
#define FW_WSTATE_OFF     0x1000    /* 16-word state block                  */
#define FW_WCAP_LEN_OFF   0x1040    /* bytes captured from the shell         */
#define FW_WSWAP_MAGIC_OFF 0x1080
#define FW_WSWAP_ADDR_OFF 0x10C0
#define FW_WCAP_PTR_OFF   0x1100

/* --- the fallback bootstrap: fp L has no mapped gyro callback site --------- */
/* FW_WBOOTSTRAP deliberately undefined: the loader path places the worker. */
