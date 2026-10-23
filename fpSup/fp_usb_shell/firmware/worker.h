/* Firmware calls only, for the USB shell worker. Placement/rendezvous words
 * are supplied per camera below; keep the worker implementation shared.
 * Default preserves the established fp 5.02 build bytes. */
#ifndef FPSUP_CAMERA
#define FPSUP_CAMERA 502
#endif

#if FPSUP_CAMERA == 502
#include "worker_fp_502.h"
#elif FPSUP_CAMERA == 10302
#include "worker_fpl_302.h"
#else
#error Unsupported FPSUP_CAMERA
#endif