/* fp L 3.02 narrow recording backend. No stock exposure setting is changed.
 * Native getters run only on the drawing owner, never in a key/IRQ callback.
 * Timing arithmetic/restoration follows fpl_vd_probe.S and fpl_slit_scan.py.
 * The real status BYTE, mode getters and exact MMIO pair qualify a take;
 * template-owner words and GUI selections are not recorder events.
 */
#define SLIT_SLOT 0xC31D6DD8u
#define SLIT_T04 0x020B047Bu
#define SLIT_T20 0x165B0000u
struct slit_recording {
    uint32_t enabled, shutdown, callback, active, trial, armed;
    uint32_t count, idle_seen, take_seen, chosen, reason, restores;
    uint32_t heartbeat, start_second, mode_ok, last_tick, intervals;
    uint32_t samples[32];
    uint32_t mode[4], summary, refused[4];
    uint32_t observer;
};
_Static_assert(__builtin_offsetof(struct slit_recording, observer) == 232, "observer shutdown ABI");
/* Shared restore uses only the first six words at owner+0x8200. */
static uint32_t slit_mask(void) {
    uint32_t mask;
    __asm__ volatile("mrs %0, cpsr\n cpsid if" : "=r"(mask) :: "memory");
    return mask;
}
static void slit_unmask(uint32_t mask) {
    __asm__ volatile("msr cpsr_c, %0" :: "r"(mask) : "memory");
}
static void slit_barrier(void) { __asm__ volatile("dsb sy" ::: "memory"); }
static uint32_t slit_recording_now(void) {
    return *(volatile const uint8_t *)0xC30338CCu;
}
static uint32_t slit_trial(uint32_t index) {
    uint32_t scale = index == 1 ? 6 : index == 2 ? 4 : index == 3 ? 3 : 2;
    return ((524u*scale-1)<<16) | (1148u*scale-1);
}
static void slit_restore_timing(struct slit_recording *r, uint32_t reason) {
    /* Caller excludes IRQ/FIQ; never replay timing into a foreign mode. */
    if (r->active) {
        if (FPL_READ(0x30100020u) == SLIT_T20 &&
            FPL_READ(0x30100004u) == r->trial) {
            FPL_WRITE(0x30100004u, SLIT_T04);
            ++r->restores;
        }
        r->active = 0;
    }
    if (r->callback && FPL_READ(SLIT_SLOT) == r->callback) FPL_WRITE(SLIT_SLOT, 0);
    r->armed = 0; r->reason = reason;
    slit_barrier();
}

static uint32_t slit_modes(struct slit_recording *r) {
    uint32_t settings = ((uint32_t (*)(void))0xC0055120u)();
    r->mode[0] = ((uint32_t (*)(uint32_t))0xC00594C8u)(settings);
    r->mode[1] = ((uint32_t (*)(uint32_t))0xC0059560u)(settings);
    r->mode[2] = ((uint32_t (*)(uint32_t))0xC0059690u)(settings);
    r->mode[3] = ((uint32_t (*)(uint32_t))0xC0059728u)(settings);
    /* The native menu is app 5 even with the physical switch in CINE.
     * Permit its mode preview; activation independently requires CINE app 2. */
    uint32_t app = FPL_READ(0xC3033A40u);
    return (app == 2 || app == 5) && r->mode[0] == 0 && r->mode[1] == 4 &&
           r->mode[2] == 3 && r->mode[3] == 12;
}
