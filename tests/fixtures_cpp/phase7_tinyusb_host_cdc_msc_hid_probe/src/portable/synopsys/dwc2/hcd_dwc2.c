#include <stdint.h>
#include <stdbool.h>
#include "host/hcd.h"

#define DWC2_HOST_REG ((volatile uint32_t*)0x50000000u)

bool hcd_init(uint8_t rhport, void* rh_init) {
  (void) rhport;
  (void) rh_init;
  DWC2_HOST_REG[0] = 1;
  return true;
}

void hcd_int_enable(uint8_t rhport) {
  (void) rhport;
  DWC2_HOST_REG[1] = 1;
}

bool hcd_edpt_xfer(uint8_t dev_addr, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes) {
  (void) dev_addr;
  (void) ep_addr;
  (void) buffer;
  DWC2_HOST_REG[2] = total_bytes;
  return true;
}
