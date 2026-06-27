#include <stdint.h>
#include "host/usbh.h"

void cdch_init(void) {
}

void cdch_deinit(void) {
}

uint16_t cdch_open(uint8_t rhport, uint8_t dev_addr, tusb_desc_interface_t const* desc_itf, uint16_t max_len) {
  (void) rhport;
  (void) dev_addr;
  (void) desc_itf;
  return max_len ? 16 : 0;
}

void cdch_set_config(uint8_t dev_addr, uint8_t itf_num) {
  (void) dev_addr;
  (void) itf_num;
}

void cdch_xfer_cb(uint8_t dev_addr, uint8_t ep_addr, uint8_t result, uint32_t xferred_bytes) {
  (void) dev_addr;
  (void) ep_addr;
  (void) result;
  (void) xferred_bytes;
}

void cdch_close(uint8_t dev_addr) {
  (void) dev_addr;
}
