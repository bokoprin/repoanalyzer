#include "typec/usbc.h"
#define CFG_TUC_TASK_QUEUE_SZ 16
void usbc_int_set(bool enabled);
OSAL_QUEUE_DEF(usbc_int_set, _usbc_qdef, CFG_TUC_TASK_QUEUE_SZ, tcd_event_t);
tu_static osal_queue_t _usbc_q;
static bool _usbc_inited = false;
static bool _port_inited[TUP_TYPEC_RHPORTS_NUM];
static uint8_t _rx_buf[64] TU_ATTR_ALIGNED(4);
static uint8_t _tx_buf[64] TU_ATTR_ALIGNED(4);

TU_ATTR_WEAK bool tuc_pd_data_received_cb(uint8_t rhport, pd_header_t const* header, uint8_t const* dobj, uint8_t const* p_end) {
  (void) rhport; (void) header; (void) dobj; (void) p_end; return false;
}
TU_ATTR_WEAK bool tuc_pd_control_received_cb(uint8_t rhport, pd_header_t const* header) {
  (void) rhport; (void) header; return false;
}
TU_ATTR_WEAK void tcd_connect(uint8_t rhport) { (void) rhport; }
TU_ATTR_WEAK void tcd_disconnect(uint8_t rhport) { (void) rhport; }

bool tuc_inited(uint8_t rhport) { return _usbc_inited && _port_inited[rhport]; }
bool tuc_connect(uint8_t rhport) { TU_VERIFY(tuc_inited(rhport)); tcd_connect(rhport); return true; }
bool tuc_disconnect(uint8_t rhport) { TU_VERIFY(tuc_inited(rhport)); tcd_disconnect(rhport); return true; }

bool tuc_init(uint8_t rhport, uint32_t port_type) {
  if (!_usbc_inited) { _usbc_q = osal_queue_create(&_usbc_qdef); _usbc_inited = true; }
  TU_ASSERT(tcd_init(rhport, port_type));
  tcd_int_enable(rhport);
  _port_inited[rhport] = true;
  return true;
}

void tuc_task_ext(uint32_t timeout_ms, bool in_isr) {
  (void) in_isr;
  while (1) {
    tcd_event_t event;
    if (!osal_queue_receive(_usbc_q, &event, timeout_ms)) return;
    switch (event.event_id) {
      case TCD_EVENT_CC_CHANGED:
        break;
      case TCD_EVENT_RX_COMPLETE:
        if (event.xfer_complete.result == XFER_RESULT_SUCCESS) {
          pd_header_t const* header = (pd_header_t const*) _rx_buf;
          if (header->n_data_obj == 0) {
            parse_msg_control(event.rhport, header);
          } else {
            uint8_t const* p_end = _rx_buf + event.xfer_complete.xferred_bytes;
            uint8_t const* dobj = _rx_buf + sizeof(pd_header_t);
            parse_msg_data(event.rhport, header, dobj, p_end);
          }
        }
        tcd_msg_receive(event.rhport, _rx_buf, sizeof(_rx_buf));
        break;
      case TCD_EVENT_TX_COMPLETE:
        break;
      default: break;
    }
  }
}

bool parse_msg_data(uint8_t rhport, pd_header_t const* header, uint8_t const* dobj, uint8_t const* p_end) {
  tuc_pd_data_received_cb(rhport, header, dobj, p_end);
  return true;
}
bool parse_msg_control(uint8_t rhport, pd_header_t const* header) {
  tuc_pd_control_received_cb(rhport, header);
  return true;
}

bool usbc_msg_send(uint8_t rhport, pd_header_t const* header, void const* data) {
  uint16_t const n_data_obj = header->n_data_obj;
  return tcd_msg_send(rhport, _tx_buf, sizeof(pd_header_t) + n_data_obj * 4);
}

bool tuc_msg_request(uint8_t rhport, void const* rdo) {
  pd_header_t const header = {
    .msg_type = PD_DATA_REQUEST,
    .data_role = PD_DATA_ROLE_UFP,
    .specs_rev = PD_REV_30,
    .power_role = PD_POWER_ROLE_SINK,
    .msg_id = 0,
    .n_data_obj = 1,
    .extended = 0,
  };
  return usbc_msg_send(rhport, &header, rdo);
}

void tcd_event_handler(tcd_event_t const* event, bool in_isr) {
  switch (event->event_id) {
    case TCD_EVENT_CC_CHANGED:
      if (event->cc_changed.cc_state[0] || event->cc_changed.cc_state[1]) {
        tcd_msg_receive(event->rhport, _rx_buf, sizeof(_rx_buf));
      }
      break;
    default: break;
  }
  osal_queue_send(_usbc_q, event, in_isr);
}

void usbc_int_set(bool enabled) {
  if (enabled) { tcd_int_enable(0); } else { tcd_int_disable(0); }
}
