/* Experimental queue-boundary trace. Not an exposure or DMA completion clock.
 * All mutation/readout requires the admitted single CPU with IRQ/FIQ excluded.
 * A commit is written last; retained lookup records own their producer copy. */
#include <stdint.h>
#define PT_MAGIC 0x31545046u /* FPT1, private RAM ABI, not an FPLS version */
#define PT_CAP 64u
#define PT_OWNER 0xC343B6C4u
#define PT_PRODUCER 1u
#define PT_LOOKUP 2u
#define PT_HIT 1u
#define PT_ZERO 2u
#define PT_MISS 4u
#define PT_STALE 8u
#define PT_CONTEXT 16u
#define PT_EXHAUSTED 32u
#define PT_MISMATCH 64u
#define PT_CLOCK 128u
struct pt_time { uint32_t valid, seconds, ticks; };
struct pt_producer {
    uint32_t commit, generation_lo, generation_hi, key, value, slot;
    struct pt_time before, after;
    uint32_t cpsr, task, caller, flags;
};
struct pt_lookup {
    uint32_t commit, ordinal_lo, ordinal_hi, key, result, flags;
    uint32_t pool, record, task, matched, selected, consumed;
    uint32_t caller_sp, reserved;
    struct pt_time before, after;
    struct pt_producer producer;
};
struct pt_state {
    uint32_t magic, busy, generation_lo, generation_hi, ordinal_lo, ordinal_hi;
    uint32_t next, overwritten, rejected, exhausted;
    struct pt_producer slots[10];
    struct pt_lookup lookups[PT_CAP];
    struct pt_producer publications[PT_CAP];
    uint32_t publication_next, publication_evicted;
    struct { uint32_t index, lo, hi; } handoff[501];
};
/* The assembly owns this per-invocation stack object, never shared scratch. */
struct pt_call {
    uint32_t cpsr, registers, kind, cursor, key, owner, result, task;
    uint32_t pool, record, flags, entered;
    struct pt_time before;
    uint32_t reserved;
};
_Static_assert(sizeof(struct pt_call) == 64, "wrapper stack ABI");
_Static_assert(sizeof(struct pt_state) <= 0x8000, "bounded retained state");
_Static_assert(sizeof(struct pt_state) == 20012, "owned manifest state extent");
_Static_assert(sizeof(struct pt_lookup) == 144, "export record ABI");
