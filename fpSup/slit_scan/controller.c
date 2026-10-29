#include "controller.h"
#include <stddef.h>

#if !defined(__arm__) || UINTPTR_MAX != UINT32_MAX
#error "fp L 3.02 ARM32 ABI required"
#endif
_Static_assert(sizeof(struct slit_controller) == 220, "owned controller ABI");
_Static_assert(offsetof(struct slit_controller, names) == 60, "owned name offset");
_Static_assert(offsetof(struct slit_descriptor, subscription) == 24, "native subscription offset");
#define INLINE static __attribute__((always_inline)) inline
typedef uint32_t (*lookup_fn)(uint32_t, const void *, struct slit_descriptor **);
typedef uint32_t (*register_fn)(uint32_t, uint32_t, const uint32_t *);
typedef uint32_t (*subscribe_fn)(uint32_t, const void *, const uint32_t *);
typedef void (*post_fn)(uint32_t, const void *, uint32_t);

INLINE uint32_t fail(struct slit_controller *s, uint32_t error) {
    s->error = error; s->state = SLIT_FAILED; return error;
}
INLINE uint32_t lookup(struct slit_controller *s, uint32_t i, struct slit_descriptor **d) {
    *d = 0;
    return ((lookup_fn)0xC05D8C69u)(s->app, s->names[i], d);
}
INLINE uint32_t identity(struct slit_controller *s, uint32_t i, struct slit_descriptor *d) {
    return d && d == s->descriptors[i] && d->name == (uint32_t)s->names[i] &&
           d->type == (i == 2 ? 2u : 0u);
}
INLINE uint32_t pair_ok(struct slit_controller *s, struct slit_descriptor *d) {
    const uint32_t *p = (const uint32_t *)d->subscription;
    return p && (uint32_t)p == s->pair && p[0] == s->callback && p[1] == (uint32_t)s;
}
INLINE void names(struct slit_controller *s) {
    /* Immutable once published. Kept in owned storage, never in staging. */
    for (uint32_t i = 0; i < 5; ++i)
        for (uint32_t j = 0; j < 6; ++j) s->names[i][j] = 0;
    s->names[0][0]=0x665F564D; s->names[0][1]=0x696C5370; s->names[0][2]=0x61635374; s->names[0][3]=0x6E;
    s->names[1][0]=0x665F564D; s->names[1][1]=0x696C5370; s->names[1][2]=0x79654B74;
    s->names[2][0]=0x665F564D; s->names[2][1]=0x696C5370; s->names[2][2]=0x78655474; s->names[2][3]=0x74;
    s->names[3][0]=0x4C435845; s->names[3][1]=0x5370665F; s->names[3][2]=0x5374696C; s->names[3][3]=0x006E6163;
    s->names[4][0]=0x5F425553; s->names[4][1]=0x665F564D; s->names[4][2]=0x696C5370; s->names[4][3]=0x61635374; s->names[4][4]=0x6E;
    s->labels[0][0]=0x0066664F; s->labels[0][1]=0;
    s->labels[1][0]=0x70662034; s->labels[1][1]=0x73;
    s->labels[2][0]=0x70662036; s->labels[2][1]=0x73;
    s->labels[3][0]=0x70662038; s->labels[3][1]=0x73;
    s->labels[4][0]=0x66203231; s->labels[4][1]=0x7370;
}

uint32_t slit_init(struct slit_controller *s, uint32_t app, uint32_t callback) {
    struct slit_descriptor *d;
    uint32_t def[3], pair[2];
    if (!s || s->state || !app || (app & 3) || !callback) return SLIT_INVALID;
    s->state = 1; s->app = app; s->callback = callback;
    names(s);
    /* Preflight the whole namespace before publishing any variable. */
    for (uint32_t i = 0; i < 5; ++i) {
        if (lookup(s, i, &d)) return fail(s, SLIT_NATIVE);
        if (d) return fail(s, SLIT_COLLISION);
    }
    for (uint32_t i = 0; i < 5; ++i) {
        def[0] = i == 2 ? 2 : 0;
        def[1] = (uint32_t)s->names[i];
        def[2] = i == 2 ? (uint32_t)s->labels[0] : 0;
        if (((register_fn)0xC05D74E9u)(app, 1, def)) return fail(s, SLIT_NATIVE);
        ++s->registered;
        if (lookup(s, i, &d)) return fail(s, SLIT_NATIVE);
        s->descriptors[i] = d;
        if (!identity(s, i, d) || d->subscription || (i != 2 && d->value))
            return fail(s, SLIT_IDENTITY);
    }
    pair[0] = callback; pair[1] = (uint32_t)s;
    uint32_t result = ((subscribe_fn)0xC05D8CF9u)(app, s->names[1], pair);
    s->pair = s->descriptors[1]->subscription;
    if (result) return fail(s, SLIT_NATIVE);
    if (!pair_ok(s, s->descriptors[1])) return fail(s, SLIT_IDENTITY);
    s->state = SLIT_ACTIVE;
    return 0;
}

uint32_t slit_key(struct slit_descriptor *d, struct slit_controller *s) {
    if (!s || s->state != SLIT_ACTIVE) return 0;
    if (!identity(s, 1, d) || !pair_ok(s, d)) return fail(s, SLIT_IDENTITY);
    uint32_t now = d->value, value = s->requested;
    if (value > 4) return fail(s, SLIT_IDENTITY);
    if (!now) return 0; /* native key action resets before each request */
    if (now == 1u) value = value == 4 ? 0 : value + 1;
    else if (now == UINT32_MAX) value = value == 0 ? 4 : value - 1;
    else return fail(s, SLIT_STEP);
    s->counter += now;
    s->requested = value;
    if (s->notifications != UINT32_MAX) ++s->notifications;
    return 0;
}

uint32_t slit_pump(struct slit_controller *s) {
    struct slit_descriptor *d;
    if (!s || s->state != SLIT_ACTIVE) return SLIT_INVALID;
    for (uint32_t i = 0; i < 5; ++i) {
        if (lookup(s, i, &d)) return fail(s, SLIT_NATIVE);
        if (!identity(s, i, d)) return fail(s, SLIT_IDENTITY);
        if (i == 1 ? !pair_ok(s, d) : d->subscription != 0) return fail(s, SLIT_IDENTITY);
    }
    uint32_t value = s->requested;
    if (value > 4) return fail(s, SLIT_IDENTITY);
    if (value != s->posted) {
        ((post_fn)0xC0590078u)(0, s->names[0], value);
        ((post_fn)0xC0590128u)(0, s->names[2], (uint32_t)s->labels[value]);
        s->posted = value;
    }
    return 0;
}

void slit_disable(struct slit_controller *s) {
    if (s && s->state == SLIT_ACTIVE) s->state = SLIT_DISABLED;
}
