/* Called AFTER the unchanged native draw method, on its observed owner task.
 * Experimental RAM-only menu coordinator: no recording or timing backend.
 * The table wrapper, callback, names, controller and FPUI bytes are retained.
 */
struct slit_runtime {
    uint32_t magic, phase, error, busy, command, app, key, block, bytes;
    uint32_t tcb, entry, stock_offset, installed_page, ticks;
    struct slit_controller controller;
    struct uia_outcome outcome;
};
_Static_assert(sizeof(struct slit_runtime) <= 1024, "owned runtime reservation");
_Static_assert(__builtin_offsetof(struct slit_runtime, controller) == 56, "runtime ABI");

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
    s->busy = 0;
    return s->phase;
}
