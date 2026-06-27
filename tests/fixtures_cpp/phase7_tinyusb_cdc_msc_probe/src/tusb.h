#ifndef TUSB_H_
#define TUSB_H_
#include "common/tusb_common.h"
#include "device/usbd.h"
typedef struct tusb_rhport_init_s {
  uint8_t role;
  uint8_t speed;
} tusb_rhport_init_t;
bool tusb_init(uint8_t rhport, tusb_rhport_init_t const* init);
void tud_task(void);
bool tud_mounted(void);
#endif
