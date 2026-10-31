/* Offline-qualified controller contract. No install entry or native borrower.
 * Storage must be retained for the entire boot, including failed restoration. */
#include <stdint.h>
enum slit_exp_result {
    EXP_OK, EXP_UNQUALIFIED, EXP_CONTEXT, EXP_BUSY, EXP_CLOSING,
    EXP_MODE, EXP_ARGUMENT, EXP_VERIFY
};
enum slit_exp_phase { EXP_IDLE, EXP_BORROWING, EXP_BORROWED, EXP_RESTORING, EXP_CLOSED, EXP_FAULT };
struct slit_exp_tuple { uint32_t mode, numerator, denominator, iso; };
struct slit_exposure {
    uint32_t task;
    volatile uint32_t busy, closing, dirty, valid, work, phase, error;
    struct slit_exp_tuple original, requested;
    uint32_t native_result;
};
_Static_assert(sizeof(struct slit_exposure) == 68, "retained exposure state ABI");
_Static_assert(__builtin_offsetof(struct slit_exposure, native_result) == 64, "dispatch result ABI");
uint32_t slit_exposure_borrow(struct slit_exposure *, uint32_t index, uint32_t shutter, uint32_t iso);
uint32_t slit_exposure_restore(struct slit_exposure *);
uint32_t slit_exposure_before_persist(struct slit_exposure *);
/* Status is NOT the native return value. On refusal the caller must not
 * continue persistence/shutdown. Native callers do not implement this contract
 * yet, so this function must not be installed as their callback. */
uint32_t slit_exposure_dispatch(struct slit_exposure *, uint32_t original, uint32_t arg0, uint32_t arg1);
