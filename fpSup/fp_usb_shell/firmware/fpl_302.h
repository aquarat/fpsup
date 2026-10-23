/* SIGMA fp L 3.02: statically matched loader ABI, not camera-tested.
 * All entry points below are ARM. No cave/layout or complete-card support is
 * implied. Source/evidence and remaining work: docs/FPL_PORT.md. */
#define FW_H_GET      0xC001D740
#define FW_H_ADDR     0xC001D7F0
#define FW_H_FREE     0xC001D7A0
#define FW_F_MGR      0xC04408B8
#define FW_F_VOL      0xC04408F8
#define FW_F_CTOR     0xC03660A8
#define FW_F_OPEN     0xC03661C8
#define FW_F_READ     0xC0366278
#define FW_F_CLOSE    0xC0366238
#define FW_F_DTOR     0xC03660E8
#define FW_DCACHE     0xC000E91C
#define FW_ICACHE     0xC000EABC
#define FW_TICK_US    0xC0029320
#define FW_AR_START   0xC03DA970

/* --- stage2: pool publication, channel allocator, power-off, journal policy ---
 * Static counterparts from the same research pass; the allocator/channel
 * forms are shared addresses with fp (the allocator audit executed the real
 * instructions).  Everything below is ARM, statically matched, and the
 * power-off manager's callback invocation is separately audited
 * (docs/FPL_POFF_AUDIT.md).  fw L has NO cave: the fp counterpart range lies
 * inside the IMU firmware image, which stock code owns and may recopy.  So
 * the journal exclusion is EMPTY (FW_CAVE_LO == FW_CAVE_HI): every firmware
 * word stage2 overwrites is journaled, and resident code lives in memory the
 * payload allocates (pass-2 pool offsets), never in the image. */
#define FW_FRAMEBUF   0xC37588BC   /* the pool publication word           */
#define FW_MEM_HEAP   0xC001CF78   /* (class) -> channel                  */
#define FW_MEM_GET    0xC001D038   /* (channel, size, align, out, [sp])   */
#define FW_POFF_MGR   0xC00239B8   /* () -> XC_PowerOffMgr                */
#define FW_POFF_ADD   0xC0024038   /* (mgr, obj, forced) -> 1 registered  */
#define FW_CAVE_LO    0xC072B8E4   /* == FW_CAVE_HI: nothing is excluded  */
#define FW_CAVE_HI    0xC072B8E4
#define FW_LH_SITE    0xC03DA638   /* bl AR_START: the loader hook site  */
