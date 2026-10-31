/* Called AFTER the unchanged native draw method, on its observed owner task.
 * The optional recording backend shares this owner/controller/lifetime.
 * The table wrapper, callback, names, controller and FPUI bytes are retained.
 */
struct slit_runtime {
    uint32_t magic, phase, error, busy, command, app, key, block, bytes;
    uint32_t tcb, entry, stock_offset, installed_page, ticks;
    struct slit_controller controller;
    struct uia_outcome outcome;
#ifdef FPL_SLIT_RECORDING
    struct slit_recording recording __attribute__((aligned(512)));
#endif
};
_Static_assert(sizeof(struct slit_runtime) <= 1024, "owned runtime reservation");
_Static_assert(__builtin_offsetof(struct slit_runtime, controller) == 56, "runtime ABI");
#ifdef FPL_SLIT_RECORDING
_Static_assert(__builtin_offsetof(struct slit_runtime, recording) == 512, "shutdown ABI");

/* Entered through the owned 16-byte argument veneer by native early Vd.
 * Bounded: no allocation, queue, lock, native call or host dependency. */
void slit_vd(struct slit_runtime *s) {
    struct slit_recording *r = &s->recording;
    uint32_t mask = slit_mask(), now = FPL_READ(0xC3076D98u);
    if (!r->armed || r->shutdown || s->command != 1 || s->phase != 2 || s->error ||
        s->controller.state != SLIT_ACTIVE || !r->chosen ||
        s->controller.requested != r->chosen || !r->mode_ok ||
        slit_recording_now() != 1 || FPL_READ(0xC3033A40u) != 2 ||
        now-r->heartbeat > 2 || FPL_READ(SLIT_SLOT) != r->callback) {
        slit_restore_timing(r, 4);
        r->chosen = 0;
    } else if (FPL_READ(0x30100020u) != SLIT_T20 ||
               FPL_READ(0x30100004u) != (r->active ? r->trial : SLIT_T04)) {
        slit_restore_timing(r, 5);
        r->chosen = 0;
    } else {
        uint32_t tick = FPL_READ(0x2D810054u);
#ifdef FPL_SLIT_QUEUE
        /* A different native IRQ advances this counter. Record its raw value;
         * neither +1 nor a fixed DNG offset is a capture association. */
        uint32_t *q = r->queue[r->queue_count & 15];
        q[0] = FPL_READ(0xC343B858u) == 1 ? FPL_READ(0xC343B6D4u) : 0xffffffffu;
        q[1] = FPL_READ(0x30100004u); q[2] = tick; q[3] = r->count+1;
        slit_barrier(); ++r->queue_count;
#endif
        if (r->active && r->count > 9) {
            uint32_t delta = tick >= r->last_tick ? tick-r->last_tick : tick+12000000-r->last_tick;
            r->samples[r->intervals++ & 31] = delta;
        }
        r->last_tick = tick;
        if (++r->count == 8) {
            FPL_WRITE(0x30100004u, r->trial);
            slit_barrier(); r->active = 1;
        }
    }
    slit_unmask(mask);
}

static void slit_record_tick(struct slit_runtime *s) {
    struct slit_recording *r = &s->recording;
    if (!r->enabled) return;
    uint32_t selected = s->controller.requested;
    uint32_t usable = !r->shutdown && s->command == 1 && s->phase == 2 && !s->error &&
                      s->controller.state == SLIT_ACTIVE;
    uint32_t param = r->observer-0x100;
    /* Attach once while idle, on the task owner, before any take's mode 0.
     * No retries on a full list or uncertain native attach. Never free a native
     * borrower, even when selection is Off or a later runtime failure occurs. */
    if (usable && !slit_recording_now() && !FPL_READ(param))
        ((uint32_t (*)(uint32_t))fpl_tag_image())(param);
    usable = usable && FPL_READ(param) == 2;
    /* Off never invokes a settings function. Failures still run cleanup. */
    r->mode_ok = usable && selected && selected <= 4 ? slit_modes(r) : 0;
    uint32_t mask = slit_mask(), now = FPL_READ(0xC3076D98u);
    usable = usable && !r->shutdown;
    r->heartbeat = now;
    uint32_t rec = slit_recording_now();
    if (!usable || !selected || !r->mode_ok || rec != 1 ||
        (r->armed && selected != r->chosen)) {
        slit_restore_timing(r, !usable ? 6 : !selected ? 0 : !r->mode_ok ? 1 : 2);
        r->chosen = 0;
    }
    if (!rec) { r->idle_seen = 1; r->take_seen = 0; }
    else if (rec == 1 && r->idle_seen && !r->take_seen) {
        r->take_seen = 1; r->start_second = now; r->chosen = selected;
        r->count = 0; r->intervals = 0;
#ifdef FPL_SLIT_QUEUE
        r->queue_count = 0;
        for (uint32_t i=0; i<16; ++i)
            for (uint32_t j=0; j<4; ++j) r->queue[i][j] = 0;
#endif
        /* A disabled/unsupported start consumes this take; never activate
         * halfway through it when the user later changes a menu setting. */
        if (!usable || !selected || !r->mode_ok || FPL_READ(0xC3033A40u) != 2) r->chosen = 0;
    }
    if (usable && r->chosen && r->chosen == selected && r->mode_ok && rec == 1 &&
        !r->armed && !r->count && now-r->start_second <= 2 && FPL_READ(0xC3033A40u) == 2) {
        if (!FPL_READ(SLIT_SLOT) && FPL_READ(SLIT_SLOT+4) == 1 &&
            FPL_READ(0x30100004u) == SLIT_T04 && FPL_READ(0x30100020u) == SLIT_T20) {
            r->trial = slit_trial(selected); r->armed = 1; r->reason = 0;
            slit_barrier(); FPL_WRITE(SLIT_SLOT, r->callback); slit_barrier();
        } else r->reason = 3;
    }
    if (rec && now-r->start_second > 2 && !r->armed && !r->count) r->chosen = 0;
    slit_unmask(mask);
    /* Immutable borrowed status text, initialized before queue publication. */
    uint32_t summary = selected && !r->mode_ok ? 5 : selected;
    /* slit_pump posts the selected label first. Reassert Refused for EACH
     * changed selection, even when the unsupported-mode state is unchanged. */
    uint32_t summary_key = summary | (selected << 8);
    if (usable && selected <= 4 && summary <= 5 && r->summary != summary_key) {
        ((post_fn)0xC0590128u)(0, s->controller.names[2], (uint32_t)
            (summary == 5 ? r->refused : s->controller.labels[summary]));
        r->summary = summary_key;
    }
}
#endif

uint32_t slit_tick(struct slit_runtime *s) {
    if (!s || s->magic != 0x534C4954u || s->busy) return 0;
    if (FPL_READ(0xC3000098u) != s->tcb || FPL_READ(0xC37B6B10u) != s->app) return 0;
    s->busy = 1;
    ++s->ticks;
    if (s->command == 2) {
        slit_disable(&s->controller);
        s->phase = 3;
    } else if (s->command == 1 && !s->phase) {
        /* Native registry mutation must finish before publishing the row. */
        s->phase = 1;
        if (!fpl_cached(s->entry) || FPL_READ(s->entry+8) != s->stock_offset ||
            !uis_reader()) {
            s->error = 0x200;
        } else {
            s->error = slit_init(&s->controller, s->app, s->key);
            if (!s->error) s->error = uia_apply(s->block, s->bytes, &s->outcome);
        }
        if (s->error) {
            slit_disable(&s->controller);
            s->phase = 4;
        } else {
            s->installed_page = s->outcome.page;
            s->phase = 2;
        }
    } else if (s->command == 1 && s->phase == 2) {
        s->error = slit_pump(&s->controller);
        if (s->error) { slit_disable(&s->controller); s->phase = 4; }
    }
#ifdef FPL_SLIT_RECORDING
    slit_record_tick(s);
#endif
    s->busy = 0;
    return s->phase;
}
