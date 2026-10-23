/* fp L 3.02 service adapter; no loader, allocator algorithm or task fork. */
#include "../firmware/fpl_302.h"
#define RL_H_GET FW_H_GET
#define RL_H_ADDR FW_H_ADDR
#define RL_DCACHE FW_DCACHE
#define RL_ICACHE FW_ICACHE
#include "../../gyro/retained_launch.inc.S"
