#include "class/cdc/cdc_device.h"
#include "tusb_config.h"

#if CFG_TUD_CDC
bool cdcd_init(void) { return true; }
bool cdcd_open(uint8_t rhport, uint8_t itf) {
  (void) rhport;
  return itf == 0;
}
bool cdcd_xfer_cb(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes) {
  (void) rhport;
  (void) ep_addr;
  return xferred_bytes > 0;
}
uint32_t tud_cdc_available(void) { return 0; }
uint32_t tud_cdc_read(void* buffer, uint32_t bufsize) { (void) buffer; return bufsize; }
uint32_t tud_cdc_write(void const* buffer, uint32_t bufsize) { (void) buffer; return bufsize; }
void tud_cdc_write_flush(void) {}
TU_ATTR_WEAK void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts) {
  (void) itf;
  (void) dtr;
  (void) rts;
}
#endif
