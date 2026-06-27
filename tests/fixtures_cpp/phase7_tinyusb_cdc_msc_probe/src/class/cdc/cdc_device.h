#ifndef CDC_DEVICE_H_
#define CDC_DEVICE_H_
#include "common/tusb_common.h"
uint32_t tud_cdc_available(void);
uint32_t tud_cdc_read(void* buffer, uint32_t bufsize);
uint32_t tud_cdc_write(void const* buffer, uint32_t bufsize);
void tud_cdc_write_flush(void);
#endif
