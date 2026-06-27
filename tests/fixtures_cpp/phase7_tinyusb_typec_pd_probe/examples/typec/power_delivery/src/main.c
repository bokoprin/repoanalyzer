#include "hw/bsp/board_api.h"
#include "typec/usbc.h"
#define VOLTAGE_MAX_MV       5000
#define CURRENT_MAX_MA       500
#define CURRENT_OPERATING_MA 300
void typec_connect_task(void);
void led_blinking_task(void);
int main(void) {
  board_init();
  board_led_write(true);
  tuc_init(0, TUSB_TYPEC_PORT_DISCONNECTED);
  while (1) {
    typec_connect_task();
    led_blinking_task();
    tuc_task();
  }
}

bool tuc_pd_data_received_cb(uint8_t rhport, pd_header_t const* header, uint8_t const* dobj, uint8_t const* p_end) {
  switch (header->msg_type) {
    case PD_DATA_SOURCE_CAP: {
      uint8_t selected_pos = 1;
      bool voltage_available = false;
      for (size_t i = 0; i < header->n_data_obj; i++) {
        TU_VERIFY(dobj < p_end);
        uint32_t const pdo = tu_le32toh(tu_unaligned_read32(dobj));
        switch ((pdo >> 30) & 0x03ul) {
          case PD_PDO_TYPE_FIXED: {
            pd_pdo_fixed_t const* fixed = (pd_pdo_fixed_t const*) &pdo;
            uint32_t const voltage_mv = fixed->voltage_50mv * 50;
            uint32_t const current_ma = fixed->current_max_10ma * 10;
            if (voltage_mv <= VOLTAGE_MAX_MV) {
              voltage_available = true;
              if (current_ma >= CURRENT_MAX_MA) selected_pos = i + 1;
            }
            break;
          }
          case PD_PDO_TYPE_BATTERY: break;
          case PD_PDO_TYPE_VARIABLE: break;
          case PD_PDO_TYPE_APDO: break;
        }
        dobj += 4;
      }
      if (!voltage_available) break;
      pd_rdo_fixed_variable_t rdo = {
        .current_extremum_10ma = CURRENT_MAX_MA / 10,
        .current_operate_10ma = CURRENT_OPERATING_MA / 10,
        .object_position = selected_pos,
      };
      tuc_msg_request(rhport, &rdo);
      break;
    }
    default: break;
  }
  return true;
}

bool tuc_pd_control_received_cb(uint8_t rhport, pd_header_t const* header) {
  (void) rhport;
  switch (header->msg_type) {
    case PD_CTRL_ACCEPT: break;
    case PD_CTRL_REJECT: break;
    case PD_CTRL_PS_READY: break;
    default: break;
  }
  return true;
}

void typec_connect_task(void) {
  static bool connected = false;
  bool const connect = !connected;
  if (connect && tuc_connect(0)) connected = true;
  else if (!connect && tuc_disconnect(0)) connected = false;
}
void led_blinking_task(void) { board_led_write(true); }
