#include "tusb.h"
#include "tusb_config.h"
#include "usb_descriptors.h"

#define REPORT_ID_KEYBOARD 1
#define REPORT_ID_MOUSE 2
#define REPORT_ID_CONSUMER_CONTROL 3
#define REPORT_ID_GAMEPAD 4

#define TUD_CONFIG_DESCRIPTOR(config_num, itf_count, stridx, total_len, attr, power_ma) config_num, itf_count, stridx, total_len, attr, power_ma
#define TUD_HID_DESCRIPTOR(itf, stridx, protocol, report_len, ep_in, ep_size, interval) itf, stridx, protocol, report_len, ep_in, ep_size, interval
#define TUD_HID_REPORT_DESC_KEYBOARD(report_id) report_id
#define TUD_HID_REPORT_DESC_MOUSE(report_id) report_id
#define TUD_HID_REPORT_DESC_CONSUMER(report_id) report_id
#define TUD_HID_REPORT_DESC_GAMEPAD(report_id) report_id
#define HID_REPORT_ID(id) id
#define TUD_CONFIG_DESC_LEN 9
#define TUD_HID_DESC_LEN 9

enum {
  ITF_NUM_HID = 0,
  ITF_NUM_TOTAL
};

#define EPNUM_HID 0x81
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_HID_DESC_LEN)

static uint8_t const desc_device[] = { 18, 1, CFG_TUD_ENDPOINT0_SIZE };
uint8_t const desc_hid_report[] = {
  TUD_HID_REPORT_DESC_KEYBOARD(HID_REPORT_ID(REPORT_ID_KEYBOARD)),
  TUD_HID_REPORT_DESC_MOUSE(HID_REPORT_ID(REPORT_ID_MOUSE)),
  TUD_HID_REPORT_DESC_CONSUMER(HID_REPORT_ID(REPORT_ID_CONSUMER_CONTROL)),
  TUD_HID_REPORT_DESC_GAMEPAD(HID_REPORT_ID(REPORT_ID_GAMEPAD)),
};

uint8_t const desc_configuration[] = {
  TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, TUSB_DESC_CONFIG_ATT_REMOTE_WAKEUP, 100),
  TUD_HID_DESCRIPTOR(ITF_NUM_HID, 0, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_report), EPNUM_HID, CFG_TUD_HID_EP_BUFSIZE, 5),
};

uint8_t const* tud_descriptor_device_cb(void) {
  return desc_device;
}

uint8_t const* tud_hid_descriptor_report_cb(uint8_t instance) {
  (void) instance;
  return desc_hid_report;
}

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
  (void) index;
  return desc_configuration;
}
