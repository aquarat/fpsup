/* Bounded exposure lifetime core; deliberately absent from the card runtime.
 * Native setters dispatch notifications and may block. Never mask around them,
 * spin waiting for a preempted owner, discard dirty state, or free this owner.
 * FPL_EXPOSURE_MODEL is a test-only admission, not a live profile override. */
#include "exposure.h"
#ifndef FPL_EXPOSURE_MODEL
#define FPL_EXPOSURE_MODEL 0
#endif
#define READ(a) (*(volatile uint32_t *)(a))
static uint32_t mask(void) {
    uint32_t v; __asm__ volatile("mrs %0, cpsr\n cpsid if" : "=r"(v) :: "memory"); return v;
}
static void unmask(uint32_t v) { __asm__ volatile("dsb sy\n msr cpsr_c, %0" :: "r"(v) : "memory"); }
static uint32_t context(struct slit_exposure *s) {
    uint32_t cpsr; __asm__ volatile("mrs %0, cpsr" : "=r"(cpsr));
    /* Model uses the observed SVC owner. A task pointer alone is insufficient:
     * IRQ/FIQ and masked task calls cannot safely enter notification machinery. */
    return (cpsr & 0xffu) == 0x13u && s->task && READ(0xC3000098u) == s->task;
}
static uint32_t settings(void) { return ((uint32_t (*)(void))0xC0055120u)(); }
static void read_tuple(uint32_t p, struct slit_exp_tuple *v) {
    v->mode = ((uint32_t (*)(uint32_t))0xC0055A10u)(p);
    ((void (*)(uint32_t *, uint32_t))0xC0055BE8u)(&v->numerator, p);
    v->iso = ((uint32_t (*)(uint32_t))0xC0056190u)(p);
}
static uint32_t equal(const struct slit_exp_tuple *a, const struct slit_exp_tuple *b) {
    return a->mode == b->mode && a->numerator == b->numerator &&
           a->denominator == b->denominator && a->iso == b->iso;
}
static void mode(uint32_t p, uint32_t v) { ((void (*)(uint32_t,uint32_t,uint32_t))0xC00559D8u)(p,v,1); }
static void shutter(uint32_t p, const struct slit_exp_tuple *v) {
    ((void (*)(uint32_t,uint32_t,uint32_t,uint32_t))0xC0055BA0u)(p,v->numerator,v->denominator,1);
}
static void iso(uint32_t p, uint32_t v) { ((void (*)(uint32_t,uint32_t,uint32_t))0xC0056158u)(p,v,1); }
static uint32_t finish_restore(struct slit_exposure *s, uint32_t p) {
    struct slit_exp_tuple actual;
    s->phase = EXP_RESTORING; s->work = 0;
    shutter(p, &s->original); iso(p, s->original.iso); mode(p, s->original.mode);
    /* Mode can change the already-restored shutter: verify the FINAL tuple. */
    read_tuple(p, &actual);
    uint32_t m = mask();
    if (!equal(&actual, &s->original)) {
        s->closing = 1; s->phase = EXP_FAULT; s->error = EXP_VERIFY;
    } else {
        s->dirty = 0; s->phase = s->closing ? EXP_CLOSED : EXP_IDLE; s->error = EXP_OK;
    }
    s->busy = 0; unmask(m); return s->error;
}
uint32_t slit_exposure_restore(struct slit_exposure *s) {
    if (!context(s)) return EXP_CONTEXT;
    uint32_t m = mask();
    if (s->busy) { unmask(m); return EXP_BUSY; }
    if (!s->dirty) {
        s->work = 0; s->phase = s->closing ? EXP_CLOSED : EXP_IDLE;
        unmask(m); return EXP_OK;
    }
    if (!s->valid) { s->closing = 1; s->phase = EXP_FAULT; unmask(m); return EXP_VERIFY; }
    s->busy = 1; unmask(m);
    return finish_restore(s, settings());
}
uint32_t slit_exposure_before_persist(struct slit_exposure *s) {
    /* Latch even on a foreign/IRQ/reentrant request; the in-flight owner must
     * finish its current call, cancel remaining work, and restore on return. */
    uint32_t m = mask(); s->closing = 1; s->work = 0; unmask(m);
    return slit_exposure_restore(s);
}
uint32_t slit_exposure_dispatch(struct slit_exposure *s, uint32_t fn, uint32_t a, uint32_t b) {
    uint32_t rc = slit_exposure_before_persist(s);
    if (rc != EXP_OK) return rc;
    /* This is only an ordering contract; native callers ignore a refusal.
     * Do not turn it into an installed wrapper until that is resolved. */
    uint32_t m = mask();
    if (s->busy || s->dirty || s->work) { unmask(m); return EXP_BUSY; }
    s->busy = 1; unmask(m);
    uint32_t result = ((uint32_t (*)(uint32_t,uint32_t))fn)(a,b);
    m = mask(); s->native_result = result; s->busy = 0; unmask(m);
    return EXP_OK;
}
uint32_t slit_exposure_borrow(struct slit_exposure *s, uint32_t index, uint32_t base, uint32_t gain) {
    if (!FPL_EXPOSURE_MODEL) return EXP_UNQUALIFIED;
    if (!context(s)) return EXP_CONTEXT;
    if (index < 1 || index > 4 || (base != 250 && base != 500 && base != 1000) ||
        (gain != 100 && gain != 200 && gain != 400 && gain != 800 && gain != 1600 && gain != 3200))
        return EXP_ARGUMENT;
    uint32_t m = mask();
    if (s->closing) { unmask(m); return EXP_CLOSING; }
    if (s->busy || s->dirty) { unmask(m); return EXP_BUSY; }
    s->busy = 1; s->work = 0; unmask(m);
    uint32_t p = settings();
    if (READ(0xC3033A40u) != 2 || *(volatile uint8_t *)0xC30338CCu ||
        ((uint32_t (*)(uint32_t))0xC00594C8u)(p) != 0 ||
        ((uint32_t (*)(uint32_t))0xC0059560u)(p) != 4 ||
        ((uint32_t (*)(uint32_t))0xC0059690u)(p) != 3 ||
        ((uint32_t (*)(uint32_t))0xC0059728u)(p) != 12) {
        m = mask(); s->busy = 0; unmask(m); return EXP_MODE;
    }
    read_tuple(p, &s->original);
    /* Same quantized choices as the established host Capture.stock_shutter. */
    uint32_t den = index == 1 ? 1600 : index == 2 ? 1000 : index == 3 ? 800 : 500;
    if (base == 500) den *= 2;
    if (base == 1000) den *= 4;
    s->requested.mode = 1; s->requested.numerator = 1;
    s->requested.denominator = den; s->requested.iso = gain;
    m = mask();
    if (s->closing) { s->busy = 0; s->phase = EXP_CLOSED; unmask(m); return EXP_CLOSING; }
    s->valid = 1; s->dirty = 1; s->work = 3; s->phase = EXP_BORROWING; unmask(m);
    mode(p, 1);
    if (!s->closing) { s->work = 2; shutter(p, &s->requested); }
    if (!s->closing) { s->work = 1; iso(p, gain); }
    struct slit_exp_tuple actual; read_tuple(p, &actual);
    m = mask(); s->work = 0;
    if (s->closing || !equal(&actual, &s->requested)) {
        uint32_t cause = s->closing ? EXP_CLOSING : EXP_VERIFY;
        s->closing = 1; unmask(m);
        uint32_t rc = finish_restore(s, p);
        return rc == EXP_OK ? cause : rc;
    }
    s->phase = EXP_BORROWED; s->busy = 0; unmask(m); return EXP_OK;
}
