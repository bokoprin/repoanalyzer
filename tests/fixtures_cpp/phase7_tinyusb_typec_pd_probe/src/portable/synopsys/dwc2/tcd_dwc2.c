#include "typec/tcd.h"
bool tcd_init(uint8_t rhport, uint32_t port_type) { (void) rhport; (void) port_type; return true; }
void tcd_int_enable(uint8_t rhport) { (void) rhport; }
void tcd_int_disable(uint8_t rhport) { (void) rhport; }
bool tcd_msg_receive(uint8_t rhport, uint8_t* buffer, uint16_t total_bytes) { (void) rhport; (void) buffer; (void) total_bytes; return true; }
bool tcd_msg_send(uint8_t rhport, uint8_t const* buffer, uint16_t total_bytes) { (void) rhport; (void) buffer; (void) total_bytes; return true; }
