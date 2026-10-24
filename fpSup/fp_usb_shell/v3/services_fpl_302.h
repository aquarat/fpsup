/* Opt-in fp L 3.02 headless services. No UI/cave/global publication binding.
 * Allocator and file ABIs: FPL_ALLOCATOR_AUDIT.md. Directory wrappers are
 * verified against the stock dir caller and native dispatch in test_fpl_v3.
 */
#ifdef SL_ALLSUPS
#error "fp L headless services do not support the manager/UI"
#endif
#define tick_us()        FW(0xC0029320, u32 (*)(void))()
#define dcache()         FW(0xC000E91C, void (*)(void))()
#define icache()         FW(0xC000EABC, void (*)(void))()
#define mem_heap(c)      FW(0xC001CF78, void *(*)(u32))(c)
#define mem_get(h, n)    FW(0xC001D038, void *(*)(void *, u32, u32, u32, u32))(h, n, 0, 0, 0)
#define mem_free(h, p)   FW(0xC001D2B8, void (*)(void *, void *))(h, p)
#define poff_mgr()       FW(0xC00239B8, void *(*)(void))()
#define poff_add(m,o,f)  FW(0xC0024038, u32 (*)(void *, void *, u32))(m,o,f)
#define f_ctor(o,v)     FW(0xC03660A8, void (*)(void *, u32))(o,v)
#define f_open(o,p)     FW(0xC03661C8, u32 (*)(void *, const char *, u32))(o,p,1)
#define f_create(o,p)   FW(0xC03661C8, u32 (*)(void *, const char *, u32))(o,p,7)
#define f_write(o,b,n)  FW(0xC0366300, u32 (*)(void *, const void *, u32))(o,b,n)
#define f_read(o,b,n,a) FW(0xC0366278, u32 (*)(void *, void *, u32, u32 *))(o,b,n,a)
#define f_close(o)     FW(0xC0366238, void (*)(void *))(o)
#define f_dtor(o)      FW(0xC03660E8, void (*)(void *, u32))(o,2)
#define dir_ctor(h,d)  FW(0xC0366B30, void *(*)(void *, u32))(h,d)
#define dir_open(h,p)  FW(0xC0366BA8, u32 (*)(void *, const char *))(h,p)
#define dir_next(h,e)  FW(0xC0366C10, u32 (*)(void *, void *))(h,e)
#define dir_dtor(h)    FW(0xC0366B58, void (*)(void *, u32))(h,2)
