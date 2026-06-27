#include "tusb.h"
#include "host/usbh.h"

int main(void) {
  tusb_init(BOARD_TUH_RHPORT, TUSB_ROLE_HOST);
  while (1) {
    tuh_task();
  }
  return 0;
}

void tuh_mount_cb(uint8_t dev_addr) {
  (void) dev_addr;
}
