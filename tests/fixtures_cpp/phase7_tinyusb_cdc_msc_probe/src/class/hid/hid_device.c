#include "common/tusb_common.h"
#include "tusb_config.h"

#if CFG_TUD_HID
bool hidd_init(void) { return true; }
bool hidd_open(uint8_t rhport, uint8_t itf) {
  (void) rhport;
  return itf == 3;
}
#endif
