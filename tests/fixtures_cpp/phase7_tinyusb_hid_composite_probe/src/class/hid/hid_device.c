#include "common/tusb_common.h"
#include "device/usbd.h"
#include "tusb_config.h"

#if CFG_TUD_HID
typedef struct {
  uint8_t itf_num;
  uint8_t ep_in;
  uint16_t report_desc_len;
} hidd_interface_t;

static hidd_interface_t _hidd_itf[CFG_TUD_HID];

bool hidd_init(void) { return true; }
bool hidd_open(uint8_t rhport, uint8_t itf) {
  (void) rhport;
  _hidd_itf[0].itf_num = itf;
  _hidd_itf[0].ep_in = 0x81;
  return itf == 0;
}
bool hidd_xfer_cb(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes) {
  (void) rhport;
  (void) ep_addr;
  return xferred_bytes > 0;
}

bool tud_hid_ready(void) {
  return tud_ready() && !usbd_edpt_busy(0, _hidd_itf[0].ep_in);
}

bool tud_hid_report(uint8_t report_id, void const* report, uint16_t len) {
  (void) report_id;
  return usbd_edpt_xfer(0, _hidd_itf[0].ep_in, report, len);
}

bool tud_hid_keyboard_report(uint8_t report_id, uint8_t modifier, uint8_t const keycode[6]) {
  (void) modifier;
  return tud_hid_report(report_id, keycode, 6);
}

bool tud_hid_mouse_report(uint8_t report_id, uint8_t buttons, int8_t x, int8_t y, int8_t vertical, int8_t horizontal) {
  uint8_t report[5] = { buttons, (uint8_t)x, (uint8_t)y, (uint8_t)vertical, (uint8_t)horizontal };
  return tud_hid_report(report_id, report, sizeof(report));
}

TU_ATTR_WEAK void tud_hid_set_protocol_cb(uint8_t instance, uint8_t protocol) { (void) instance; (void) protocol; }
TU_ATTR_WEAK bool tud_hid_set_idle_cb(uint8_t instance, uint8_t idle_rate) { (void) instance; (void) idle_rate; return true; }
TU_ATTR_WEAK void tud_hid_report_failed_cb(uint8_t instance, uint8_t report_type, uint8_t const* report, uint16_t xferred_bytes) {
  (void) instance; (void) report_type; (void) report; (void) xferred_bytes;
}
#endif
