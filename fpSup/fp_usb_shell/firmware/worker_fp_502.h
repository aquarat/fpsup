/* SIGMA fp 5.02: established USB shell worker ABI. All entry points below are
 * ARM unless the individual comment says Thumb. Source/evidence: the shared
 * load-chain records; every value is the historical fp constant.
 *
 * FW_WSTATE_* are the worker's fixed rendezvous words, in the fp cave:
 * firmware RAM nobody allocated, which survives warm restarts. The pool
 * publication triplet (FW_WFRAMEBUF, +4 size, +8 code) is how the host tools
 * find the worker's allocations. */
#define FW_WCRETSK    0xC0016A58   /* tk_cre_tsk(descriptor) -> id          */
#define FW_WSTATSK    0xC0016BC0   /* tk_sta_tsk(id, code)                  */
#define FW_WDELAY     0xC01F89C4    /* delay(ms), yields the CPU            */
#define FW_WENDX      0xC01E6D49   /* EndTransfer(logical ep)     [thumb]   */
#define FW_WSTARTX    0xC01E6B81   /* StartTransfer(physical ep)  [thumb]   */
#define FW_WWAIT      0xC01E4E81   /* Wait(logical ep, timeout)   [thumb]    */
#define FW_WSHINIT    0xC03D9A10   /* shell context one-time init           */
#define FW_WSHPUSH    0xC03D9AC0   /* push an output sink                    */
#define FW_WSHPOP     0xC03D9B20   /* pop the output sink                    */
#define FW_WSHRUN     0xC03D9C20   /* tokenise, dispatch and run one line   */
#define FW_WVSNPRINT  0xC0013F48   /* vsnprintf(buf, size, fmt, va)         */
#define FW_WCRC32     0xC06AE998   /* crc32(buf, len) leaf                   */
#define FW_WH_GET     0xC001D740   /* (desc, class, size, 0)                */
#define FW_WH_ADDR    0xC001D7F0   /* (desc) -> address                      */
#define FW_WDCACHE    0xC000E91C   /* D-cache clean/invalidate + barriers    */
#define FW_WICACHE    0xC000EABC   /* whole I-cache invalidate + barriers     */

/* --- the PTP gadget's pipes (the firmware owns the descriptors) ---------- */
#define FW_WTRB_OUT   0xC31E3268   /* TRB table[1]: EP 0x01 OUT             */
#define FW_WTRB_IN    0xC31E326C   /* TRB table[2]: EP 0x82 IN              */
#define FW_WUSB_STATE 0xC31E3748   /* 4 means the link is suspended         */
#define FW_WDALEPENA  0x2100C720   /* DWC3: bit N = physical endpoint N      */
#define FW_WOUT_BUSY  0xC31E3974   /* driver's bulk-OUT in-use word         */
#define FW_WSHELL_CTX 0xC3756904   /* firmware shell context singleton      */
#define FW_WEP_MASK   0x24          /* physical 2 (0x01 OUT) | 5 (0x82 IN)  */
#define FW_WPHYS_OUT  2
#define FW_WPHYS_IN   5
#define FW_WLOG_OUT   1
#define FW_WLOG_IN    2
#define FW_WTRB_ARMED 0x813
/* Preserve established fp behavior pending separate live alias validation. */
#define FW_WFRAME_CPU_OFFSET 0x40000000

/* --- the worker's fixed words (the cave) ----------------------------------
 * FW_WFRAMEBUF is the pool publication triplet: +0 pool, +4 size, +8 code.
 * FW_WSTATE is the 16-word state block; the four words after it are
 * CAP_LEN (+0x40), SWAP_MAGIC (+0x44), SWAP_ADDR (+0x48), CAP_PTR (+0x4C). */
#define FW_WSTATE     0xC072F000
#define FW_WCAP_LEN   0xC072F040
#define FW_WSWAP_MAGIC 0xC072F044
#define FW_WSWAP_ADDR 0xC072F048
#define FW_WCAP_PTR   0xC072F04C
#define FW_WFRAMEBUF  0xC072F050

/* --- the fallback bootstrap (the gyro callback site), fp only ------------ */
#define FW_WBOOTSTRAP 1             /* the callback-hook bootstrap exists   */
#define FW_WHOOK_SITE  0xC00D0794  /* gyro callback, borrowed once          */
#define FW_WHOOK_ORIG  0xFA046FD7  /* the BLX this site normally holds     */
#define FW_WHOOK_TARGET 0xC01EC6F9 /* what that BLX called (thumb)          */
