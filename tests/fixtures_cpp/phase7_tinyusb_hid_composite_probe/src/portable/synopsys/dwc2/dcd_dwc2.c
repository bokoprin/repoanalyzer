#include "device/dcd.h"

void dcd_init(uint8_t rhport) {
  (void) rhport;
}

void dcd_int_enable(uint8_t rhport) {
  (void) rhport;
}


bool dcd_edpt_xfer(uint8_t rhport, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes) {
  (void) buffer;
  dcd_event_t event = { .rhport = rhport, .event_id = DCD_EVENT_XFER_COMPLETE, .ep_addr = ep_addr, .xferred_bytes = total_bytes };
  dcd_event_handler(&event, true);
  return true;
}

void dcd_edpt_stall(uint8_t rhport, uint8_t ep_addr) {
  (void) rhport;
  (void) ep_addr;
}

void dcd_edpt_clear_stall(uint8_t rhport, uint8_t ep_addr) {
  (void) rhport;
  (void) ep_addr;
}
