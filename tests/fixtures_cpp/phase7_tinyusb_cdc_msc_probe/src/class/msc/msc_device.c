#include "common/tusb_common.h"
#include "tusb_config.h"

#if CFG_TUD_MSC
bool mscd_init(void) { return true; }
bool mscd_open(uint8_t rhport, uint8_t itf) {
  (void) rhport;
  return itf == 2;
}
bool mscd_xfer_cb(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes) {
  (void) rhport;
  (void) ep_addr;
  return xferred_bytes > 0;
}
#endif
