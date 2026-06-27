#include "hw/bsp/board_api.h"
#include "tusb.h"
#include "class/cdc/cdc_device.h"

void led_blinking_task(void);
void cdc_task(void);

int main(void) {
  board_init();
  tusb_rhport_init_t dev_init = {.role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_AUTO};
  tusb_init(BOARD_TUD_RHPORT, &dev_init);
  board_init_after_tusb();
  while (1) {
    tud_task();
    led_blinking_task();
    cdc_task();
  }
}

void tud_mount_cb(void) {
  board_led_write(true);
}

void tud_umount_cb(void) {
  board_led_write(false);
}

void cdc_task(void) {
  if (tud_cdc_available()) {
    char buf[64];
    uint32_t count = tud_cdc_read(buf, sizeof(buf));
    tud_cdc_write(buf, count);
    tud_cdc_write_flush();
  }
}

void led_blinking_task(void) {
  board_button_read();
}
