#include "tusb.h"
#include "host/usbh.h"

bool tusb_init(uint8_t rhport, uint8_t role) {
  if (role == TUSB_ROLE_HOST) {
    return tuh_init(rhport);
  }
  return false;
}
