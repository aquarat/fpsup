/* fp L 3.02 adapter to the shared finite conditional capture body.
 * These are explicit profile inputs, not a claim of coherent/live cancellation.
 * No task, allocation, loader or transport policy belongs to this adapter. */
#ifndef LAT_DESC_SLOT
#define LAT_DESC_SLOT 0xC31E23CC
#endif
#ifndef LAT_DESC_ROOT
#define LAT_DESC_ROOT 0x2E006004
#endif
#ifndef LAT_RING_BASE
#define LAT_RING_BASE 0x2E00644C
#endif
#ifndef LAT_DELAY
#define LAT_DELAY 0xC01F5244
#endif
#include "../../gyro/latched_capture.inc.S"
