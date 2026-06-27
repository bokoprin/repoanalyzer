#ifndef BOARD_API_H_
#define BOARD_API_H_
#include "common/tusb_common.h"
void board_init(void);
void board_init_after_tusb(void);
uint32_t board_button_read(void);
void board_led_write(bool state);
#endif
