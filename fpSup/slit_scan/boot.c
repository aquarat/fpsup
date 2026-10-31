/* Ordinary-boot initializer, called from OWNED code, never from a GUI callback.
 * All referenced bytes and native borrowers survive until the boot ends.
 * The aligned BSS drawing-vtable publication is the narrow product admission
 * authority: any nonstock value refuses, without dereferencing that value.
 * This is not the general v3/USB retained-instance discovery protocol. */
#define SLIT_DRAW 0xC38D37CCu
#define SLIT_VTABLE 0xC2E55A70u
#define SLIT_TCB (0xC3000838u + 39u*132u)

uint32_t slit_boot(uint32_t owner, uint32_t tick, uint32_t key, uint32_t bytes) {
    if ((owner & 0xffffu) || !fpl_heap(owner, 0x10000) || !bytes || bytes > 0x7c00 ||
        tick < owner+0x3000 || tick >= owner+0x8000 || (tick & 3) ||
        key < owner+0x3000 || key >= owner+0x8000 || (key & 3)) return 0x300;
    uint32_t reader = uis_reader(), entry = 0;
    if (!reader || FPL_READ(SLIT_DRAW) != SLIT_VTABLE ||
        FPL_READ(SLIT_DRAW+12) != 1 || !fpl_cached(FPL_READ(SLIT_DRAW+8)) ||
        FPL_READ(SLIT_TCB+8) != 39 || FPL_READ(SLIT_TCB+0x18) != 0x4000 ||
        !fpl_sites_stock() || !fpl_journal_for(1)) return 0x301;
    uint32_t count = FPL_READ(reader+0xa8), table = FPL_READ(reader+0xac);
    if (!count || count > 512 || !fpl_cached(table)) return 0x302;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t p = table+44*i, name = FPL_READ(p+4);
        if (name < FPL_POOL || name > FPL_POOL+UIS_STOCK_LEN-7) return 0x302;
        const uint8_t *n = (const uint8_t *)name;
        if (n[0]=='M' && n[1]=='a' && n[2]=='i' && n[3]=='n' &&
            n[4]=='B' && n[5]=='2' && !n[6]) {
            if (entry || FPL_READ(p+8) != 0x76ff04) return 0x302;
            entry = p;
        }
    }
    if (!entry) return 0x302;
    struct slit_runtime *s = (struct slit_runtime *)(owner+0x8000);
    s->magic = 0x534c4954; s->command = 1; s->app = FPL_READ(0xC37B6B10u);
    s->key = key; s->block = owner+0x8400; s->bytes = bytes;
    s->tcb = SLIT_TCB; s->entry = entry; s->stock_offset = 0x76ff04;
#ifdef FPL_SLIT_RECORDING
    if (FPL_READ(SLIT_SLOT) || FPL_READ(SLIT_SLOT+4) != 1) return 0x303;
    s->recording.enabled = 1;
    s->recording.callback = owner+0x1800;
    s->recording.refused[0] = 0x75666552; /* Refused */
    s->recording.refused[1] = 0x00646573;
    /* Parameter block/source are zeroed owned storage, outside all copied
     * extents; the shared native observer remains borrowed until shutdown. */
    uint32_t param = owner+0x2400, tag = (uint32_t)fpl_tag_image();
    s->recording.observer = param+0x100;
    FPL_WRITE(param+0x100, param+0x110);
    for (uint32_t i=0; i<3; ++i) FPL_WRITE(param+0x110+4*i, tag+FPL_TAG_RET0);
    FPL_WRITE(param+0x11c, tag+FPL_TAG_OBSERVER);
    FPL_WRITE(param+0x120, (uint32_t)s);
#endif
    FPL_WRITE(owner+0x400, 1);
    FPL_WRITE(owner+0x408, FPL_READ(SLIT_DRAW+8));
    FPL_WRITE(owner+0x40c, tick); FPL_WRITE(owner+0x410, (uint32_t)s);
    FPL_WRITE(owner+0x414, SLIT_TCB);
#ifdef FPL_SLIT_TRACE
    uint32_t trace=FPL_READ(owner+0x24);
    if ((trace&0xffff) || !fpl_heap(trace,0x10000) || trace==owner) return 0x304;
    uint32_t guard=FPL_READ(trace+16);
    if (guard<trace+0x1000 || guard>=trace+0x4000 || (guard&3) ||
        FPL_READ(trace+0x8000)!=0x31545046u || !fpl_journal_for(1)) return 0x304;
    if (((uint32_t (*)(uint32_t,uint32_t))guard)(trace+0x400,trace+0x4000)!=2) return 0x305;
#endif
    ((void (*)(void))0xC000E91Cu)();
    ((void (*)(void))0xC000EABCu)();
    /* The shared drawing wrapper rechecks identity with IRQ/FIQ excluded and
     * arms last. Failure retains the block; it registers/allocates nothing. */
    return ((uint32_t (*)(void))(owner+0x1000))();
}
