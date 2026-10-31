/* Opt-in FPLS v4 queue-boundary trace; finite fp L 3.02 live trials passed.
 * No installer, native calls or allocation in this translation unit.
 * Native leaves are executed by producer_trace.S, not approximated here.
 * Installation must prove journal coverage, whole-leaf quiescence, initialized
 * native owner, single CPU and code publication. This file does not arm hooks.
 * Evidence and limits: docs/FPL_PRODUCER_PROVENANCE.md. */
#include "producer_trace.h"
#define RD(a) (*(volatile const uint32_t *)(uintptr_t)(a))
static void barrier(void) { __asm__ volatile("dmb sy" ::: "memory"); }
static void sat(uint32_t *p) { if (*p != 0xffffffffu) ++*p; }
static uint32_t advance(uint32_t *lo, uint32_t *hi) {
    if (*lo == 0xffffffffu && *hi == 0xffffffffu) return 0;
    if (++*lo == 0) ++*hi;
    return 1;
}
static uint32_t ram(uint32_t p, uint32_t n) {
    return !(p&3) && ((p >= 0x44400000u && p <= 0x46400100u-n) ||
                     (p >= 0xC3000000u && p <= 0xD0000000u-n));
}
static uint32_t task_id(uint32_t task) {
    if (task < 0xC30008BCu || task >= 0xC3000838u+501u*132u ||
        (task-0xC3000838u)%132u) return 0;
    return (task-0xC3000838u)/132u;
}
static void invalidate(struct pt_state *s) {
    for (uint32_t i=0;i<10;++i) s->slots[i].commit=0;
    for (uint32_t i=0;i<=500;++i) s->handoff[i].index=0;
    barrier();
}
static struct pt_time clock_now(void) {
    struct pt_time t = {0,0,0};
    if (RD(0xC30337ECu) != 0x2D810000u || RD(0xC30337F8u) != 0x2D810080u ||
        RD(0xC2F09408u) != 12000000u) return t;
    uint32_t a=RD(0x2D810054u), sec=RD(0xC3076D98u), pending=RD(0x2D810084u);
    uint32_t b=RD(0x2D810054u);
    if (a >= 12000000u || b >= 12000000u || b < a) return t;
    t.valid=1; t.seconds=sec+!!(pending&32); t.ticks=b;
    return t;
}
static void consumer(struct pt_call *c, const uint32_t *regs) {
    /* C0310C58 saved original consumer r4/r5/LR before obtaining the owner. */
    if ((c->cpsr&31) != 0x13 || regs[13] != 0xC0310C70u) return;
    uint32_t task=c->task, sp=c->registers+56;
    if (!task_id(task)) return;
    uint32_t top=RD(task+0x74), bytes=RD(task+0x18);
    if (bytes < 12 || bytes > 0x1000000u || top < bytes ||
        !ram(top-bytes,bytes) || sp < top-bytes || sp > top-12) return;
    uint32_t pool=RD(sp), record=RD(sp+4);
    if (RD(sp+8) != 0xC038C8E8u || !ram(pool,0x4008) ||
        RD(pool) != 0xC07333D4u || !ram(record,0x50) || RD(record+0x4c) != c->key) return;
    c->pool=pool; c->record=record;
}
void pt_before(struct pt_state *s, struct pt_call *c, uint32_t kind) {
    const uint32_t *regs=(const uint32_t *)(uintptr_t)c->registers;
    c->kind=kind; c->owner=regs[0]; c->key=regs[1]; c->entered=0;
    c->pool=0; c->record=0; c->flags=0; c->cursor=0;
    c->task=RD(0xC3000098u); c->before=clock_now();
    if (s->magic != PT_MAGIC) return;
    if (kind == PT_LOOKUP) s->handoff[task_id(c->task)].index=0;
    if (s->busy) { s->busy=2; sat(&s->rejected); invalidate(s); return; }
    s->busy=1; c->entered=1;
    c->reserved=s->rejected;
    if (c->owner != PT_OWNER || RD(PT_OWNER+0x194) != 1 || RD(PT_OWNER+0x18c) >= 10) {
        c->flags=PT_CONTEXT; return;
    }
    c->cursor=RD(PT_OWNER+0x18c);
    if (kind == PT_LOOKUP) consumer(c,regs);
}
void pt_after(struct pt_state *s, struct pt_call *c) {
    if (!c->entered) return;
    struct pt_time after=clock_now();
    if (s->busy != 1 || c->reserved != s->rejected) c->flags|=PT_CONTEXT;
    if (c->flags) { sat(&s->rejected); invalidate(s); s->busy=0; return; }
    if (c->kind == PT_PRODUCER) {
        struct pt_producer *p=&s->slots[c->cursor];
        p->commit=0; barrier();
        if (!advance(&s->generation_lo,&s->generation_hi)) {
            s->exhausted=1; s->busy=0; return;
        }
        p->generation_lo=s->generation_lo; p->generation_hi=s->generation_hi;
        p->key=c->key; p->value=RD(PT_OWNER+0x164+4*c->cursor); p->slot=c->cursor;
        p->before=c->before; p->after=after; p->cpsr=c->cpsr; p->task=c->task;
        p->caller=RD(c->registers+52); p->flags=0;
        if (RD(PT_OWNER+0x13c+4*c->cursor) != c->key ||
            RD(PT_OWNER+0x18c) != (c->cursor+1)%10) p->flags|=PT_MISMATCH;
        if (!p->before.valid || !p->after.valid) p->flags|=PT_CLOCK;
        barrier(); p->commit=PT_MAGIC;
        struct pt_producer *event=&s->publications[s->publication_next];
        if (event->commit) sat(&s->publication_evicted);
        event->commit=0; barrier();
        const uint32_t *src=(const uint32_t *)p;
        uint32_t *dst=(uint32_t *)event;
        for (uint32_t i=1;i<sizeof(*p)/4;++i) dst[i]=src[i];
        barrier(); event->commit=PT_MAGIC;
        s->publication_next=(s->publication_next+1)%PT_CAP;
    } else {
        struct pt_lookup *l=&s->lookups[s->next];
        if (l->commit && !l->consumed) sat(&s->overwritten);
        l->commit=0; barrier();
        if (!advance(&s->ordinal_lo,&s->ordinal_hi)) {
            s->exhausted=1; s->busy=0; return;
        }
        l->ordinal_lo=s->ordinal_lo; l->ordinal_hi=s->ordinal_hi;
        l->key=c->key; l->result=c->result; l->pool=c->pool; l->record=c->record;
        l->task=c->task; l->matched=0; l->selected=10; l->consumed=0;
        l->caller_sp=c->registers+56+12; l->reserved=0;
        l->before=c->before; l->after=after;
        uint32_t max=0;
        for (uint32_t i=0;i<10;++i) {
            if (RD(PT_OWNER+0x13c+4*i) != c->key) continue;
            l->matched|=1u<<i;
            uint32_t v=RD(PT_OWNER+0x164+4*i);
            if (v > max) { max=v; l->selected=i; }
        }
        l->flags=max ? PT_HIT : l->matched ? PT_ZERO : PT_MISS;
        if (!c->pool) l->flags|=PT_CONTEXT;
        if (c->result != (max ? max : RD(PT_OWNER+0x10))) l->flags|=PT_MISMATCH;
        uint32_t *zero=(uint32_t *)&l->producer;
        for (uint32_t i=0;i<sizeof(l->producer)/4;++i) zero[i]=0;
        if (max) {
            const struct pt_producer *p=&s->slots[l->selected];
            if (p->commit != PT_MAGIC || p->key != c->key || p->value != max || p->flags&PT_MISMATCH)
                l->flags|=PT_STALE;
            else l->producer=*p;
        }
        if (s->exhausted) l->flags|=PT_EXHAUSTED;
        if (!c->before.valid || !after.valid) l->flags|=PT_CLOCK;
        barrier(); l->commit=PT_MAGIC;
        if (c->pool) {
            uint32_t id=task_id(c->task);
            s->handoff[id].lo=l->ordinal_lo; s->handoff[id].hi=l->ordinal_hi;
            barrier(); s->handoff[id].index=s->next+1;
        }
        s->next=(s->next+1)%PT_CAP;
    }
    barrier(); s->busy=0;
}

/* Caller supplies the independently checked native notification stack identity.
 * A per-task invocation handoff, not a search for a matching old key. Every
 * lookup invalidates the previous handoff, including refused/reentrant calls. */
void pt_export(struct pt_state *s, uint32_t *out, uint32_t pool,
               uint32_t record, uint32_t caller_sp) {
    for (uint32_t i=0;i<44;++i) out[i]=0;
    out[0]=1; /* unavailable; never silently reuse an older invocation */
    if (s->magic != PT_MAGIC || s->busy) return;
    out[1]=s->overwritten; out[2]=s->rejected; out[3]=s->exhausted;
    out[4]=s->generation_lo; out[5]=s->generation_hi; out[6]=s->publication_evicted;
    uint32_t id=task_id(RD(0xC3000098u)), index=s->handoff[id].index;
    s->handoff[id].index=0;
    if (!id || !index || index>PT_CAP) return;
    struct pt_lookup *l=&s->lookups[index-1];
    if (l->commit != PT_MAGIC || l->consumed || l->ordinal_lo!=s->handoff[id].lo ||
        l->ordinal_hi!=s->handoff[id].hi || l->pool!=pool || l->record!=record ||
        l->caller_sp!=caller_sp || l->flags&(PT_CONTEXT|PT_MISMATCH) ||
        !ram(record,0x50) || RD(record+0x4c)!=l->key ||
        !ram(pool,0x4008) || RD(pool+0x4004)!=l->result) return;
    const uint32_t *src=(const uint32_t *)l;
    for (uint32_t i=0;i<sizeof(*l)/4;++i) out[8+i]=src[i];
    l->consumed=1; barrier(); out[0]=2;
}
