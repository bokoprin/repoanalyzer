#ifndef DCD_H_
#define DCD_H_
#include "common/tusb_common.h"

enum {
  DCD_EVENT_BUS_RESET = 1,
  DCD_EVENT_XFER_COMPLETE = 2
};

typedef struct dcd_event_s {
  uint8_t rhport;
  uint8_t event_id;
  uint8_t ep_addr;
  uint32_t xferred_bytes;
} dcd_event_t;

void dcd_init(uint8_t rhport);
void dcd_int_enable(uint8_t rhport);
bool dcd_edpt_xfer(uint8_t rhport, uint8_t ep_addr, uint8_t* buffer, uint16_t total_bytes);
void dcd_edpt_stall(uint8_t rhport, uint8_t ep_addr);
void dcd_edpt_clear_stall(uint8_t rhport, uint8_t ep_addr);
void dcd_event_handler(dcd_event_t const* event, bool in_isr);
#endif
