#include "tusb.h"
#include "usb_descriptors.h"
#include "hw/bsp/board_api.h"

int main(void) {
  board_init();
  tusb_init();
  while (1) {
    tud_task();
    if (tud_hid_ready()) {
      uint8_t keycode[6] = { 0 };
      tud_hid_keyboard_report(REPORT_ID_KEYBOARD, 0, keycode);
      tud_hid_mouse_report(REPORT_ID_MOUSE, 0, 1, 1, 0, 0);
    }
  }
}

void tud_hid_report_complete_cb(uint8_t instance, uint8_t const* report, uint16_t len) {
  (void) instance;
  (void) report;
  (void) len;
}

uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, uint8_t report_type, uint8_t* buffer, uint16_t reqlen) {
  (void) instance;
  (void) report_id;
  (void) report_type;
  (void) buffer;
  return reqlen;
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, uint8_t report_type, uint8_t const* buffer, uint16_t bufsize) {
  (void) instance;
  (void) report_id;
  (void) report_type;
  (void) buffer;
  (void) bufsize;
}
