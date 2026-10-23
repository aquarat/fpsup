/* SIGMA fp 5.02: established loader ABI. All entry points below are ARM.
 * Source/evidence and scope: docs/FPL_PORT.md. */
#define FW_H_GET      0xC001D740
#define FW_H_ADDR     0xC001D7F0
#define FW_H_FREE     0xC001D7A0
#define FW_F_MGR      0xC0444658
#define FW_F_VOL      0xC0444698
#define FW_F_CTOR     0xC0365E90
#define FW_F_OPEN     0xC0365FB0
#define FW_F_READ     0xC0366060
#define FW_F_CLOSE    0xC0366020
#define FW_F_DTOR     0xC0365ED0
#define FW_DCACHE     0xC000E91C
#define FW_ICACHE     0xC000EABC
#define FW_TICK_US    0xC002B6E0
#define FW_AR_START   0xC03DA758

/* --- stage2: pool publication, channel allocator, power-off, journal policy ---
 * Same provenance; the evidence for the correspondences is in the shared
 * load-chain records.  Everything below is ARM.  FW_CAVE_LO/FW_CAVE_HI name
 * the journal EXCLUSION: firmware words inside that half-open range are hook
 * bodies and the loader, not hook sites, and must NOT be written back at
 * power-off while the firmware may still branch into them. */
#define FW_FRAMEBUF   0xC3757A7C   /* the pool publication word           */
#define FW_MEM_HEAP   0xC001CF78   /* (class) -> channel                  */
#define FW_MEM_GET    0xC001D038   /* (channel, size, align, out, [sp])   */
#define FW_POFF_MGR   0xC0023A98   /* () -> XC_PowerOffMgr                */
#define FW_POFF_ADD   0xC0024118   /* (mgr, obj, forced) -> 1 registered  */
#define FW_CAVE_LO    0xC072D000
#define FW_CAVE_HI    0xC0735000
#define FW_LH_SITE    0xC03DA420   /* bl AR_START: the loader hook site  */
