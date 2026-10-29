#ifndef FP_SLIT_CONTROLLER_H
#define FP_SLIT_CONTROLLER_H
#include <stdint.h>

struct slit_descriptor {
    uint32_t type, name, value, index, components[2], subscription, derived;
};
struct slit_controller {
    uint32_t state, error, app, callback, pair;
    /* counter is the cumulative signed step count, not the key variable.
     * Native events write key=0 then key=+/-1; only +/-1 advances selection. */
    volatile uint32_t requested, counter, notifications;
    uint32_t posted, registered;
    struct slit_descriptor *descriptors[5];
    uint32_t names[5][6], labels[5][2];
};
enum { SLIT_ACTIVE = 2, SLIT_DISABLED = 3, SLIT_FAILED = 4 };
enum { SLIT_INVALID = 0x100, SLIT_COLLISION, SLIT_NATIVE, SLIT_IDENTITY, SLIT_STEP };

/* Fresh zeroed, allocator-owned state, callback code and names must survive the
 * entire GUI registry lifetime, even if registration/subscription fails.
 * Init requires serialized GUI ownership; it is not an IRQ-masked operation.
 * No page, timing, stock setting, hook or power-off callback is installed here.
 * pump runs in the owner's task, never recursively from a native notification.
 * Native queues borrow immutable names/labels; pump proves enqueue, not redraw.
 * Disable gates callbacks; it does NOT unsubscribe/free or prove quiescence. */
uint32_t slit_init(struct slit_controller *, uint32_t app, uint32_t callback);
uint32_t slit_key(struct slit_descriptor *, struct slit_controller *);
uint32_t slit_pump(struct slit_controller *);
void slit_disable(struct slit_controller *);
#endif
