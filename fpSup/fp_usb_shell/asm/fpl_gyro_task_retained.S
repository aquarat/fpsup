/* fp L 3.02 only. The shared wrapper does not establish fp Base support.
 * Reuse the model's cache profile directly: loader.h defaults to fp Base.
 * Native task/query bindings are explicit here until that profile owns them.
 * RT_RUNTIME_OWNED is opt-in; the default still requires compile-time OWNED. */
#include "../firmware/fpl_302.h"
#define RT_CREATE  0xC036E320
#define RT_ATTACH  0xC036E3D0
#define RT_REF_TSK 0xC01F54CC
#define RT_REF_FLG 0xC01F5460
#define RT_DCACHE  FW_DCACHE
#define RT_ICACHE  FW_ICACHE
#include "../../gyro/retained_task.inc.S"
