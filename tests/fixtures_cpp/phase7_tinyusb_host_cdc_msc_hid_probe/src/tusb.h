#pragma once
#include <stdint.h>
#include <stdbool.h>
#define TUSB_ROLE_HOST 2
bool tusb_init(uint8_t rhport, uint8_t role);
void tuh_task(void);
void tuh_task_ext(uint32_t timeout_ms, bool in_isr);
