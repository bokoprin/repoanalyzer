#include <stdint.h>
#include <stdbool.h>
#include "examples/host/cdc_msc_hid/src/tusb_config.h"
#include "host/usbh.h"
#include "host/hcd.h"
#include "osal/osal_none.h"

#define DRIVER_NAME(_name) _name
#define TU_ATTR_WEAK __attribute__((weak))
#define CFG_TUSB_OS_HAS_SCHEDULER 0
#define TUSB_INDEX_INVALID_8 0xff
#define OPT_OS_NONE 1

typedef struct tusb_desc_interface_s { uint8_t bInterfaceNumber; } tusb_desc_interface_t;
typedef struct tusb_desc_configuration_s { uint16_t wTotalLength; } tusb_desc_configuration_t;
typedef struct { uint8_t dev_addr; uint8_t ep_addr; uint8_t result; uint32_t actual_len; } tuh_xfer_t;

typedef bool (*tuh_xfer_cb_t)(tuh_xfer_t* xfer);

void cdch_init(void); void cdch_deinit(void); uint16_t cdch_open(uint8_t rhport, uint8_t dev_addr, tusb_desc_interface_t const* desc_itf, uint16_t max_len); void cdch_set_config(uint8_t dev_addr, uint8_t itf_num); void cdch_xfer_cb(uint8_t dev_addr, uint8_t ep_addr, uint8_t result, uint32_t xferred_bytes); void cdch_close(uint8_t dev_addr);
void msch_init(void); void msch_deinit(void); uint16_t msch_open(uint8_t rhport, uint8_t dev_addr, tusb_desc_interface_t const* desc_itf, uint16_t max_len); void msch_set_config(uint8_t dev_addr, uint8_t itf_num); void msch_xfer_cb(uint8_t dev_addr, uint8_t ep_addr, uint8_t result, uint32_t xferred_bytes); void msch_close(uint8_t dev_addr);
void hidh_init(void); void hidh_deinit(void); uint16_t hidh_open(uint8_t rhport, uint8_t dev_addr, tusb_desc_interface_t const* desc_itf, uint16_t max_len); void hidh_set_config(uint8_t dev_addr, uint8_t itf_num); void hidh_xfer_cb(uint8_t dev_addr, uint8_t ep_addr, uint8_t result, uint32_t xferred_bytes); void hidh_close(uint8_t dev_addr);

TU_ATTR_WEAK void tuh_mount_cb(uint8_t dev_addr) { (void) dev_addr; }

static usbh_class_driver_t const usbh_class_drivers[] = {
#if CFG_TUH_CDC
  {
    .name = DRIVER_NAME("CDC"),
    .init = cdch_init,
    .deinit = cdch_deinit,
    .open = cdch_open,
    .set_config = cdch_set_config,
    .xfer_cb = cdch_xfer_cb,
    .close = cdch_close,
  },
#endif
#if CFG_TUH_MSC
  {
    .name = DRIVER_NAME("MSC"),
    .init = msch_init,
    .deinit = msch_deinit,
    .open = msch_open,
    .set_config = msch_set_config,
    .xfer_cb = msch_xfer_cb,
    .close = msch_close,
  },
#endif
#if CFG_TUH_HID
  {
    .name = DRIVER_NAME("HID"),
    .init = hidh_init,
    .deinit = hidh_deinit,
    .open = hidh_open,
    .set_config = hidh_set_config,
    .xfer_cb = hidh_xfer_cb,
    .close = hidh_close,
  },
#endif
};

#define BUILTIN_DRIVER_COUNT 3
#define TOTAL_DRIVER_COUNT BUILTIN_DRIVER_COUNT

typedef struct {
  uint8_t ep2drv[CFG_TUH_ENDPOINT_MAX][2];
  uint8_t itf2drv[CFG_TUH_INTERFACE_MAX];
  uint8_t configured;
} usbh_device_t;

typedef struct {
  uint8_t enumerating_daddr;
} usbh_data_t;

static osal_queue_t _usbh_q;
OSAL_QUEUE_DEF(_usbh_qdef, CFG_TUH_TASK_QUEUE_SZ, hcd_event_t);
static usbh_data_t _usbh_data;
static usbh_device_t _usbh_devices[2];

static usbh_device_t* get_device(uint8_t dev_addr) {
  return &_usbh_devices[dev_addr];
}

static inline usbh_class_driver_t const* get_driver(uint8_t drv_id) {
  if (drv_id < BUILTIN_DRIVER_COUNT) {
    return &usbh_class_drivers[drv_id];
  }
  return 0;
}

void tu_bind_driver_to_ep_itf(uint8_t drv_id, uint8_t ep2drv[CFG_TUH_ENDPOINT_MAX][2], uint8_t itf2drv[CFG_TUH_INTERFACE_MAX], uint8_t itf_max, uint8_t const* desc, uint16_t desc_len) {
  (void) itf_max;
  (void) desc;
  (void) desc_len;
  ep2drv[1][0] = drv_id;
  ep2drv[1][1] = drv_id;
  itf2drv[0] = drv_id;
}

static void enum_new_device(hcd_event_t* event);
static void process_enumeration(tuh_xfer_t* xfer);
static bool enum_parse_configuration_desc(uint8_t dev_addr, tusb_desc_configuration_t const* desc_cfg);
void usbh_driver_set_config_complete(uint8_t dev_addr, uint8_t itf_num);

bool tuh_descriptor_get_device(uint8_t dev_addr, uint8_t* buffer, uint16_t len, void (*complete_cb)(tuh_xfer_t*), uintptr_t user_data);
bool tuh_address_set(uint8_t dev_addr, uint8_t new_addr, void (*complete_cb)(tuh_xfer_t*), uintptr_t user_data);
bool tuh_descriptor_get_configuration(uint8_t dev_addr, uint8_t config_idx, uint8_t* buffer, uint16_t len, void (*complete_cb)(tuh_xfer_t*), uintptr_t user_data);
bool tuh_configuration_set(uint8_t dev_addr, uint8_t config_num, void (*complete_cb)(tuh_xfer_t*), uintptr_t user_data);

bool tuh_init(uint8_t rhport) {
  _usbh_q = osal_queue_create(&_usbh_qdef);
  for (uint8_t drv_id = 0; drv_id < TOTAL_DRIVER_COUNT; drv_id++) {
    usbh_class_driver_t const* driver = get_driver(drv_id);
    driver->init();
  }
  hcd_init(rhport, 0);
  hcd_int_enable(rhport);
  return true;
}

void hcd_event_handler(hcd_event_t const* event, bool in_isr) {
  osal_queue_send(_usbh_q, event, in_isr);
}

void tuh_task(void) {
  tuh_task_ext(0, false);
}

void tuh_task_ext(uint32_t timeout_ms, bool in_isr) {
  (void) in_isr;
  hcd_event_t event;
  if (!osal_queue_receive(_usbh_q, &event, timeout_ms)) {
    return;
  }
  switch (event.event_id) {
    case HCD_EVENT_DEVICE_ATTACH:
      _usbh_data.enumerating_daddr = 0;
      enum_new_device(&event);
      break;
    case HCD_EVENT_XFER_COMPLETE: {
      uint8_t epnum = event.xfer_complete.ep_addr & 0x0f;
      uint8_t ep_dir = (event.xfer_complete.ep_addr & 0x80) ? 1 : 0;
      usbh_device_t* dev = get_device(event.dev_addr);
      uint8_t drv_id = dev->ep2drv[epnum][ep_dir];
      usbh_class_driver_t const* driver = get_driver(drv_id);
      driver->xfer_cb(event.dev_addr, event.xfer_complete.ep_addr, event.xfer_complete.result, event.xfer_complete.len);
      break;
    }
    default:
      break;
  }
}

bool tuh_edpt_xfer(uint8_t dev_addr, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes) {
  return hcd_edpt_xfer(dev_addr, ep_addr, buffer, total_bytes);
}

static void enum_new_device(hcd_event_t* event) {
  (void) event;
  tuh_xfer_t xfer = { .dev_addr = 0 };
  process_enumeration(&xfer);
}

static void process_enumeration(tuh_xfer_t* xfer) {
  uint8_t daddr = xfer->dev_addr;
  uint8_t buffer[64];
  tuh_descriptor_get_device(0, buffer, 8, process_enumeration, 1);
  tuh_address_set(0, 1, process_enumeration, 2);
  tuh_descriptor_get_device(1, buffer, 18, process_enumeration, 3);
  tuh_descriptor_get_configuration(1, 0, buffer, 9, process_enumeration, 4);
  tuh_descriptor_get_configuration(1, 0, buffer, 64, process_enumeration, 5);
  tuh_configuration_set(1, 1, process_enumeration, 6);
  enum_parse_configuration_desc(daddr, (tusb_desc_configuration_t const*) buffer);
  usbh_driver_set_config_complete(daddr, TUSB_INDEX_INVALID_8);
}

static bool enum_parse_configuration_desc(uint8_t dev_addr, tusb_desc_configuration_t const* desc_cfg) {
  usbh_device_t* dev = get_device(dev_addr);
  tusb_desc_interface_t const* desc_itf = (tusb_desc_interface_t const*) desc_cfg;
  uint16_t remaining_len = 64;
  for (uint8_t drv_id = 0; drv_id < TOTAL_DRIVER_COUNT; drv_id++) {
    usbh_class_driver_t const* driver = get_driver(drv_id);
    uint16_t drv_len = driver->open(BOARD_TUH_RHPORT, dev_addr, desc_itf, remaining_len);
    if (drv_len) {
      tu_bind_driver_to_ep_itf(drv_id, dev->ep2drv, dev->itf2drv, CFG_TUH_INTERFACE_MAX, (uint8_t const*) desc_itf, drv_len);
      break;
    }
  }
  return true;
}

void usbh_driver_set_config_complete(uint8_t dev_addr, uint8_t itf_num) {
  usbh_device_t* dev = get_device(dev_addr);
  for (itf_num++; itf_num < CFG_TUH_INTERFACE_MAX; itf_num++) {
    uint8_t drv_id = dev->itf2drv[itf_num];
    usbh_class_driver_t const* driver = get_driver(drv_id);
    driver->set_config(dev_addr, itf_num);
    break;
  }
  dev->configured = 1;
  tuh_mount_cb(dev_addr);
}
