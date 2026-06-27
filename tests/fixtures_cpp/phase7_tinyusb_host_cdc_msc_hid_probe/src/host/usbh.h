#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef struct tusb_desc_interface_s tusb_desc_interface_t;
typedef struct tusb_desc_configuration_s tusb_desc_configuration_t;

typedef struct {
  char const* name;
  void (*init)(void);
  void (*deinit)(void);
  uint16_t (*open)(uint8_t rhport, uint8_t dev_addr, tusb_desc_interface_t const* desc_itf, uint16_t max_len);
  void (*set_config)(uint8_t dev_addr, uint8_t itf_num);
  void (*xfer_cb)(uint8_t dev_addr, uint8_t ep_addr, uint8_t result, uint32_t xferred_bytes);
  void (*close)(uint8_t dev_addr);
} usbh_class_driver_t;

bool tuh_init(uint8_t rhport);
void tuh_task(void);
void tuh_task_ext(uint32_t timeout_ms, bool in_isr);
bool tuh_edpt_xfer(uint8_t dev_addr, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes);
void tuh_mount_cb(uint8_t dev_addr);
