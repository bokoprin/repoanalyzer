#ifndef TUSB_COMMON_H_
#define TUSB_COMMON_H_
#include "tusb_option.h"
typedef unsigned char uint8_t;
typedef unsigned short uint16_t;
typedef unsigned int uint32_t;
typedef int bool;
#define true 1
#define false 0
#define TU_ATTR_WEAK __attribute__((weak))
#endif
