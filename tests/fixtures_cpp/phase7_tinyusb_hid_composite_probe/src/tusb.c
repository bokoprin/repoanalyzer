#include "tusb.h"
#include "device/dcd.h"

static bool _tinyusb_inited;

bool tusb_init(uint8_t rhport, tusb_rhport_init_t const* init) {
  if (init->role == TUSB_ROLE_DEVICE) {
    dcd_init(rhport);
    dcd_int_enable(rhport);
    _tinyusb_inited = true;
  }
  return _tinyusb_inited;
}
