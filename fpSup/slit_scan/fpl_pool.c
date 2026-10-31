/* fp L 3.02 page-only provider for the shared FPUI applier.
 * Compiled in one translation unit by build_adapter.py. The shared string
 * machine code, task-PC guard and loader restore body are embedded unchanged.
 * Entry must run under serialized GUI ownership. Every allocation is retained.
 * This initial adapter admits stock string sites only, never a foreign layer.
 */
#include "ui_pool.h"

#define FPL_READ(a) (*(volatile const uint32_t *)(uintptr_t)(a))
#define FPL_WRITE(a, v) (*(volatile uint32_t *)(uintptr_t)(a) = (v))
#define FPL_NBU 0xC18D01A0u
#define FPL_POOL 0xC18D01B4u
#define FPL_MANAGER 0xC3075684u

static uint32_t fpl_heap(uint32_t a, uint32_t bytes) {
    return !(a & 3u) && a >= 0x44400000u && a <= 0x46400100u && bytes <= 0x46400100u-a;
}
static uint32_t fpl_cached(uint32_t a) {
    return !(a & 3u) && a >= 0xC3000000u && a < 0xD0000000u;
}
static uint32_t fpl_site(uint32_t i) {
    return i < 2 ? 0xC05E1D38u + 4u*i : i < 4 ? 0xC05E23A8u + 4u*(i-2) : 0xC05E23C0u + 4u*(i-4);
}
static uint32_t fpl_stock(uint32_t i) {
    if (i == 0) return 0x3FFFF1B1u;
    if (i == 1) return 0x6902BF1Cu;
    if (i == 2) return 0x428A6942u;
    if (i == 3) return 0x6900D805u;
    if (i == 4) return 0x69406902u;
    return 0x1A501812u;
}
static uint32_t fpl_sites_stock(void) {
    for (uint32_t i = 0; i < 6; ++i)
        if (FPL_READ(fpl_site(i)) != fpl_stock(i)) return 0;
    return 1;
}

/* One shared object in both lists; exact code and six unique original words.
 * No registration, journal extension, flash write, or fp cave access. */
static uint32_t fpl_journal_for(uint32_t draw) {
    if (FPL_READ(FPL_MANAGER) != 0xC0726CECu) return 0;
    uint32_t found = 0, coverage = 0, drew = 0;
#ifdef FPL_SLIT_TRACE
    uint32_t traced = 0;
#endif
#ifdef FPL_SLIT_RECORDING
    uint32_t vd = 0;
#endif
    const uint32_t *code = fpl_restore_image();
    for (uint32_t i = 0; i < 10; ++i) {
        uint32_t obj = FPL_READ(FPL_MANAGER+12+4*i), both = 0;
        if (!obj) break;
        if (!fpl_heap(obj, 12+FPL_RESTORE_BYTES+4)) continue;
        for (uint32_t j = 0; j < 10; ++j) {
            uint32_t forced = FPL_READ(FPL_MANAGER+52+4*j);
            if (!forced) break;
            if (forced == obj) ++both;
        }
        if (!both || FPL_READ(obj) != obj-8 || FPL_READ(obj+4) != obj+12) continue;
        if (both != 1 || ++found != 1 || FPL_READ(obj+8) != obj+12+FPL_RESTORE_BYTES) return 0;
        for (uint32_t j = 0; j < FPL_RESTORE_BYTES/4; ++j)
            if (FPL_READ(obj+12+4*j) != code[j]) return 0;
        uint32_t start = obj+12+FPL_RESTORE_BYTES, p = start, terminated = 0;
        for (uint32_t j = 0; j <= 64; ++j) {
            if (!fpl_heap(p, 8)) return 0;
            uint32_t a = FPL_READ(p), n;
            if (!a) { terminated = 1; break; }
            n = FPL_READ(p+4);
            if (j == 64 || (a & 3u) || (n & 3u) || !n || n > 4096 ||
                !((a >= 0xC0000000u && a < 0xC3000000u && n <= 0xC3000000u-a) ||
                  (a == 0xC38D37CCu && n == 4 && FPL_READ(p+8) == 0xC2E55A70u)
#ifdef FPL_SLIT_RECORDING
                  || (a == 0xC31D6DD8u && n == 4 && FPL_READ(p+8) == 0)
#endif
                  ) ||
                 p-start > 16384u-8u-n || !fpl_heap(p, 8+n)) return 0;
            if (a == 0xC38D37CCu && ++drew != 1) return 0;
#ifdef FPL_SLIT_RECORDING
            if (a == 0xC31D6DD8u && ++vd != 1) return 0;
#endif
            for (uint32_t k = 0; k < 6; ++k) {
                uint32_t at = fpl_site(k);
                if (at >= a && at-a < n) {
                    if ((coverage & (1u << k)) || FPL_READ(p+8+at-a) != fpl_stock(k)) return 0;
                    coverage |= 1u << k;
                }
            }
#ifdef FPL_SLIT_TRACE
            for (uint32_t k=0;k<4;++k) {
                uint32_t at=k<2 ? 0xC031EBF8u+4*k : 0xC031EC58u+4*(k-2);
                uint32_t stock=k&1 ? 0xE1A0C000u : k==0 ? 0xE92D0030u : 0xE92D0070u;
                if (at>=a && at-a<n) {
                    if ((traced&(1u<<k)) || FPL_READ(p+8+at-a)!=stock) return 0;
                    traced|=1u<<k;
                }
            }
#endif
            p += 8+n;
        }
        if (!terminated) return 0;
    }
    return found == 1 && coverage == 63 && (!draw || drew == 1)
#ifdef FPL_SLIT_RECORDING
           && vd == 1
#endif
#ifdef FPL_SLIT_TRACE
           && traced == 15
#endif
           ;
}
static uint32_t fpl_journal(void) { return fpl_journal_for(0); }

static uintptr_t uis_reader(void) {
    uint32_t app = FPL_READ(0xC37B6B10u);
    if (!fpl_cached(app)) return 0;
    uint32_t count = FPL_READ(app+0x80), screens = FPL_READ(app+0x8C);
    if (!count || count > 512 || !fpl_cached(screens)) return 0;
    uint32_t screen = FPL_READ(screens);
    if (!fpl_cached(screen) || FPL_READ(screen+4) != app) return 0;
    uint32_t reader = FPL_READ(screen+0x24);
    if (!fpl_cached(reader) || FPL_READ(reader) != 0x01090000u ||
        FPL_READ(reader+0x10) != UIS_STOCK_LEN || FPL_READ(reader+0x14) != FPL_POOL ||
        FPL_READ(reader+0x24) != FPL_NBU) return 0;
    return reader;
}
static uint32_t uis_stock_has(uintptr_t s, uint32_t n, uint32_t at) {
    if (!s || !n || !uis_reader() || at >= UIS_STOCK_LEN || n >= UIS_STOCK_LEN-at) return 0;
    const uint8_t *from = (const uint8_t *)s, *stock = (const uint8_t *)(FPL_POOL+at);
    for (uint32_t i = 0; i <= n; ++i) if (from[i] != stock[i]) return 0;
    return stock[n] == 0;
}
static uint32_t uis_layer_base(uint32_t *base) {
    if (!base || !fpl_sites_stock() || !fpl_journal()) return UIS_HOOK;
    *base = UIS_LAYER_FIRST;
    return UIS_OK;
}
static uint32_t uis_layer_add(const uintptr_t *s, const uint32_t *n, uint32_t count, uint32_t *base) {
    uint32_t desc[4], bytes = 0;
    if (!s || !n || !base || !count || count > 64 || !fpl_sites_stock() || !fpl_journal()) return UIS_HOOK;
    for (uint32_t i = 0; i < count; ++i) {
        if (!s[i] || !n[i] || n[i] >= 64 || ((const uint8_t *)s[i])[n[i]]) return UIS_INVALID;
        for (uint32_t j = 0; j < n[i]; ++j) if (!((const uint8_t *)s[i])[j]) return UIS_INVALID;
        bytes += n[i]+1;
    }
    for (uint32_t i = 0; i < 4; ++i) desc[i] = 0;
    ((void (*)(uint32_t *, uint32_t, uint32_t, uint32_t))0xC001D740u)(desc, 0, 0x10000, 0x10000);
    uint32_t owner = ((uint32_t (*)(uint32_t *))0xC001D7F0u)(desc);
    if (!owner || (owner & 0xFFFFu) || !fpl_heap(owner, 0x10000) ||
        desc[0] != owner || desc[1] || desc[2] != owner || desc[3] != 0x10000) return UIS_NO_MEMORY;
    /* The allocator owns this block. Retain the descriptor even on refusal. */
    for (uint32_t i = 0; i < 4; ++i) FPL_WRITE(owner+4*i, desc[i]);
    uint32_t layer = owner+0x1000, table = owner+0x2000, data = table+4*count;
    const uint32_t *code = fpl_layer_image();
    for (uint32_t i = 0; i < FPL_LAYER_BYTES/4; ++i) FPL_WRITE(layer+4*i, code[i]);
    FPL_WRITE(layer, UIS_LAYER_LEGACY); FPL_WRITE(layer+4, 0);
    FPL_WRITE(layer+8, UIS_LAYER_VERSION); FPL_WRITE(layer+12, UIS_LAYER_FIRST);
    FPL_WRITE(layer+16, count); FPL_WRITE(layer+20, data); FPL_WRITE(layer+24, data+bytes);
    for (uint32_t i = 28; i <= 36; i += 4) FPL_WRITE(layer+i, 0);
    FPL_WRITE(layer+40, table);
    for (uint32_t i = 44; i <= 52; i += 4) FPL_WRITE(layer+i, 0); /* no fp QS settings */
    FPL_WRITE(layer+56, 72); FPL_WRITE(layer+60, FPL_RESOLVE);
    FPL_WRITE(layer+64, FPL_OWNS); FPL_WRITE(layer+68, FPL_REMAIN);
    uint32_t at = data;
    for (uint32_t i = 0; i < count; ++i) {
        FPL_WRITE(table+4*i, at);
        for (uint32_t j = 0; j <= n[i]; ++j) *(uint8_t *)(at+j) = ((const uint8_t *)s[i])[j];
        at += n[i]+1;
    }
    uint32_t *p = (uint32_t *)(owner+0x400);
    for (uint32_t i = 0; i < 256; ++i) p[i] = 0;
    p[0] = 1; p[16] = layer+FPL_RESOLVE; p[17] = layer+FPL_OWNS;
    p[18] = layer+FPL_REMAIN; p[19] = owner;
    ((void (*)(void))0xC000E91Cu)();
    ((void (*)(void))0xC000EABCu)();
    if (!fpl_journal() || fpl_guard(p, (uint32_t *)(owner+0x4000)) != 2 || p[1] != 2) return UIS_HOOK;
    *base = UIS_LAYER_FIRST;
    return UIS_OK;
}

/* Unreachable in the page-only applier; do not bind these to fp services. */
static uint32_t uis_qs_shared(uint32_t *id, uint32_t *issuer) {
    *id = 0; *issuer = 0; return UIS_INVALID;
}
static uint32_t uis_layer_add_qs(const uintptr_t *s, const uint32_t *n, uint32_t count,
                                uint32_t *base, uint32_t id, uint32_t value, uint32_t own) {
    (void)s; (void)n; (void)count; (void)base; (void)id; (void)value; (void)own;
    return UIS_INVALID;
}
