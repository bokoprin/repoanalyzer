#pragma once
#include <stdbool.h>
static inline void board_init(void) {}
static inline void board_led_write(bool state) { (void) state; }
static inline unsigned board_button_read(void) { return 1; }
static inline unsigned tusb_time_millis_api(void) { return 0; }
