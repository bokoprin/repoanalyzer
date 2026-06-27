#ifndef USBD_H_
#define USBD_H_
#include "common/tusb_common.h"
bool tud_inited(void);
void tud_task(void);
bool tud_mounted(void);
void tud_mount_cb(void);
void tud_umount_cb(void);
uint8_t const* tud_descriptor_device_cb(void);
uint8_t const* tud_descriptor_configuration_cb(uint8_t index);
#endif
