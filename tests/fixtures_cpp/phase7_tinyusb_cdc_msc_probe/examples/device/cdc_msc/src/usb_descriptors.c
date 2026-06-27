#include "tusb.h"
#include "tusb_config.h"

#define TUD_CONFIG_DESCRIPTOR(config_num, itf_count, stridx, total_len, attr, power_ma) config_num, itf_count, stridx, total_len, attr, power_ma
#define TUD_CDC_DESCRIPTOR(itf, stridx, ep_notif, ep_notif_size, ep_out, ep_in, ep_size) itf, stridx, ep_notif, ep_notif_size, ep_out, ep_in, ep_size
#define TUD_MSC_DESCRIPTOR(itf, stridx, ep_out, ep_in, ep_size) itf, stridx, ep_out, ep_in, ep_size
#define TUD_CONFIG_DESC_LEN 9
#define TUD_CDC_DESC_LEN 66
#define TUD_MSC_DESC_LEN 23

enum {
  ITF_NUM_CDC = 0,
  ITF_NUM_CDC_DATA,
  ITF_NUM_MSC,
  ITF_NUM_TOTAL
};

#define EPNUM_CDC_NOTIF 0x81
#define EPNUM_CDC_OUT   0x02
#define EPNUM_CDC_IN    0x82
#define EPNUM_MSC_OUT   0x03
#define EPNUM_MSC_IN    0x83
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_MSC_DESC_LEN)

static uint8_t const desc_device[] = { 18, 1, CFG_TUD_ENDPOINT0_SIZE };
static uint8_t const desc_fs_configuration[] = {
  TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
  TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 16, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
  TUD_MSC_DESCRIPTOR(ITF_NUM_MSC, 5, EPNUM_MSC_OUT, EPNUM_MSC_IN, 64),
};

uint8_t const* tud_descriptor_device_cb(void) {
  return desc_device;
}

uint8_t const* tud_descriptor_configuration_cb(uint8_t index) {
  (void) index;
  return desc_fs_configuration;
}
