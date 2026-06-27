#pragma once
#include "typec/tcd.h"
#define TUSB_TYPEC_PORT_DISCONNECTED 0
bool tuc_init(uint8_t rhport, uint32_t port_type);
bool tuc_connect(uint8_t rhport);
bool tuc_disconnect(uint8_t rhport);
void tuc_task_ext(uint32_t timeout_ms, bool in_isr);
static inline void tuc_task(void) { tuc_task_ext(0, false); }
bool tuc_msg_request(uint8_t rhport, void const* rdo);
