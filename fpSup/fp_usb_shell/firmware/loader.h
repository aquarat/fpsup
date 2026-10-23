/* Firmware calls only. Placement/scratch is supplied separately by the builder.
 * Keep the loader implementation shared; add model addresses in these headers.
 * Default preserves direct assembly and existing fp 5.02 build callers. */
#ifndef FPSUP_CAMERA
#define FPSUP_CAMERA 502
#endif

#if FPSUP_CAMERA == 502
#include "fp_502.h"
#elif FPSUP_CAMERA == 10302
#include "fpl_302.h"
#else
#error Unsupported FPSUP_CAMERA
#endif
