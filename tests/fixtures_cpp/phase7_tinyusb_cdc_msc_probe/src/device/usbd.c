#include "device/usbd.h"
#include "device/dcd.h"
#include "osal/osal_none.h"
#include "tusb_config.h"

typedef struct {
  char const* name;
  bool (*init)(void);
  bool (*open)(uint8_t rhport, uint8_t itf);
  bool (*xfer_cb)(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes);
} usbd_class_driver_t;

bool cdcd_init(void);
bool cdcd_open(uint8_t rhport, uint8_t itf);
bool cdcd_xfer_cb(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes);
bool mscd_init(void);
bool mscd_open(uint8_t rhport, uint8_t itf);
bool mscd_xfer_cb(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes);
bool hidd_init(void);
bool hidd_open(uint8_t rhport, uint8_t itf);

static usbd_class_driver_t const _usbd_driver[] = {
#if CFG_TUD_CDC
  { "CDC", cdcd_init, cdcd_open, cdcd_xfer_cb },
#endif
#if CFG_TUD_MSC
  { "MSC", mscd_init, mscd_open, mscd_xfer_cb },
#endif
#if CFG_TUD_HID
  { "HID", hidd_init, hidd_open, 0 },
#endif
};

typedef struct {
  uint8_t itf2drv[CFG_TUD_INTERFACE_MAX];
  uint8_t ep2drv[CFG_TUD_ENDPOINT_MAX][2];
  uint8_t ep_busy[CFG_TUD_ENDPOINT_MAX][2];
} usbd_device_t;

static usbd_device_t _usbd_dev;
static bool _mounted;
OSAL_QUEUE_DEF(_usbd_q);

static usbd_class_driver_t const* get_driver(uint8_t drv_id) {
  return &_usbd_driver[drv_id];
}

bool tu_bind_driver_to_ep_itf(uint8_t drv_id, uint8_t ep2drv[][2], uint8_t itf2drv[], uint8_t max_itf, uint8_t const* desc, uint16_t len) {
  (void) max_itf;
  (void) desc;
  (void) len;
  itf2drv[drv_id] = drv_id;
  ep2drv[drv_id][0] = drv_id;
  ep2drv[drv_id][1] = drv_id;
  return true;
}

bool usbd_edpt_claim(uint8_t rhport, uint8_t ep_addr) {
  (void) rhport;
  uint8_t epnum = ep_addr & 0x0f;
  uint8_t ep_dir = (ep_addr & 0x80) ? 1 : 0;
  if (_usbd_dev.ep_busy[epnum][ep_dir]) {
    return false;
  }
  _usbd_dev.ep_busy[epnum][ep_dir] = 1;
  return true;
}

void usbd_edpt_release(uint8_t rhport, uint8_t ep_addr) {
  (void) rhport;
  uint8_t epnum = ep_addr & 0x0f;
  uint8_t ep_dir = (ep_addr & 0x80) ? 1 : 0;
  _usbd_dev.ep_busy[epnum][ep_dir] = 0;
}

bool usbd_edpt_busy(uint8_t rhport, uint8_t ep_addr) {
  (void) rhport;
  uint8_t epnum = ep_addr & 0x0f;
  uint8_t ep_dir = (ep_addr & 0x80) ? 1 : 0;
  return _usbd_dev.ep_busy[epnum][ep_dir] != 0;
}

bool usbd_edpt_xfer(uint8_t rhport, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes) {
  if (!usbd_edpt_claim(rhport, ep_addr)) {
    return false;
  }
  if (!dcd_edpt_xfer(rhport, ep_addr, buffer, total_bytes)) {
    usbd_edpt_release(rhport, ep_addr);
    return false;
  }
  return true;
}

void usbd_edpt_stall(uint8_t rhport, uint8_t ep_addr) {
  dcd_edpt_stall(rhport, ep_addr);
}

void usbd_edpt_clear_stall(uint8_t rhport, uint8_t ep_addr) {
  dcd_edpt_clear_stall(rhport, ep_addr);
}

bool usbd_open_configuration(uint8_t rhport, uint8_t const* desc_cfg) {
  uint8_t drv_id;
  for (drv_id = 0; drv_id < 2; drv_id++) {
    usbd_class_driver_t const* driver = get_driver(drv_id);
    if (driver->open(rhport, drv_id)) {
      return tu_bind_driver_to_ep_itf(drv_id, _usbd_dev.ep2drv, _usbd_dev.itf2drv, CFG_TUD_INTERFACE_MAX, desc_cfg, 9);
    }
  }
  return false;
}

void dcd_event_xfer_complete(uint8_t rhport, uint8_t ep_addr, uint32_t xferred_bytes) {
  uint8_t epnum = ep_addr & 0x0f;
  uint8_t ep_dir = (ep_addr & 0x80) ? 1 : 0;
  usbd_edpt_release(rhport, ep_addr);
  usbd_class_driver_t const* driver = get_driver(_usbd_dev.ep2drv[epnum][ep_dir]);
  driver->xfer_cb(rhport, ep_addr, xferred_bytes);
}

void dcd_event_handler(dcd_event_t const* event, bool in_isr) {
  osal_queue_send(&_usbd_q, event, in_isr);
}


bool tud_inited(void) {
  return true;
}

void tud_task(void) {
  dcd_event_t event;
  uint8_t const* configuration = tud_descriptor_configuration_cb(0);
  (void) configuration;
  if (osal_queue_receive(&_usbd_q, &event)) {
    if (event.event_id == DCD_EVENT_XFER_COMPLETE) {
      dcd_event_xfer_complete(event.rhport, event.ep_addr, event.xferred_bytes);
    }
  }
  _mounted = true;
  tud_mount_cb();
}

bool tud_mounted(void) {
  return _mounted;
}

TU_ATTR_WEAK void tud_mount_cb(void) {}
TU_ATTR_WEAK void tud_umount_cb(void) {}
