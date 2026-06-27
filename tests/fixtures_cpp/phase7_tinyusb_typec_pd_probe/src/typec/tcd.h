#pragma once
#include "common/tusb_common.h"
#include "typec/pd_types.h"
#include "osal/osal_none.h"
enum { TCD_EVENT_INVALID = 0, TCD_EVENT_CC_CHANGED, TCD_EVENT_RX_COMPLETE, TCD_EVENT_TX_COMPLETE };
typedef struct TU_ATTR_PACKED {
  uint8_t rhport;
  uint8_t event_id;
  union {
    struct { uint8_t cc_state[2]; } cc_changed;
    struct TU_ATTR_PACKED { uint16_t result:2; uint16_t xferred_bytes:14; } xfer_complete;
  };
} tcd_event_t;
bool tcd_init(uint8_t rhport, uint32_t port_type);
void tcd_int_enable(uint8_t rhport);
void tcd_int_disable(uint8_t rhport);
void tcd_connect(uint8_t rhport);
void tcd_disconnect(uint8_t rhport);
bool tcd_msg_receive(uint8_t rhport, uint8_t* buffer, uint16_t total_bytes);
bool tcd_msg_send(uint8_t rhport, uint8_t const* buffer, uint16_t total_bytes);
extern void tcd_event_handler(tcd_event_t const* event, bool in_isr);
TU_ATTR_ALWAYS_INLINE static inline void tcd_event_cc_changed(uint8_t rhport, uint8_t cc1, uint8_t cc2, bool in_isr) {
  tcd_event_t event = { .rhport = rhport, .event_id = TCD_EVENT_CC_CHANGED, .cc_changed = { .cc_state = {cc1, cc2} } };
  tcd_event_handler(&event, in_isr);
}
TU_ATTR_ALWAYS_INLINE static inline void tcd_event_rx_complete(uint8_t rhport, uint16_t xferred_bytes, uint8_t result, bool in_isr) {
  tcd_event_t event = { .rhport = rhport, .event_id = TCD_EVENT_RX_COMPLETE, .xfer_complete = { .xferred_bytes = xferred_bytes, .result = result } };
  tcd_event_handler(&event, in_isr);
}
TU_ATTR_ALWAYS_INLINE static inline void tcd_event_tx_complete(uint8_t rhport, uint16_t xferred_bytes, uint8_t result, bool in_isr) {
  tcd_event_t event = { .rhport = rhport, .event_id = TCD_EVENT_TX_COMPLETE, .xfer_complete = { .xferred_bytes = xferred_bytes, .result = result } };
  tcd_event_handler(&event, in_isr);
}
