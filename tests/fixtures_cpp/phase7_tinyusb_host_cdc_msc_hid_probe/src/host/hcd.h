#pragma once
#include <stdint.h>
#include <stdbool.h>

typedef enum {
  HCD_EVENT_DEVICE_ATTACH,
  HCD_EVENT_DEVICE_REMOVE,
  HCD_EVENT_XFER_COMPLETE,
} hcd_eventid_t;

typedef struct {
  uint8_t ep_addr;
  uint32_t len;
  uint8_t result;
} hcd_xfer_complete_t;

typedef struct {
  hcd_eventid_t event_id;
  uint8_t rhport;
  uint8_t dev_addr;
  hcd_xfer_complete_t xfer_complete;
} hcd_event_t;

bool hcd_init(uint8_t rhport, void* rh_init);
void hcd_int_enable(uint8_t rhport);
void hcd_event_handler(hcd_event_t const* event, bool in_isr);
bool hcd_edpt_xfer(uint8_t dev_addr, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes);
