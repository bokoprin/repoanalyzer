#pragma once
#include <stdbool.h>
typedef void* osal_queue_t;
#define OSAL_QUEUE_DEF(mutex_func, name, depth, type) static int name
static inline osal_queue_t osal_queue_create(void* qdef) { return qdef; }
static inline bool osal_queue_send(osal_queue_t q, void const* event, bool in_isr) { (void) q; (void) event; (void) in_isr; return true; }
static inline bool osal_queue_receive(osal_queue_t q, void* event, unsigned timeout_ms) { (void) q; (void) event; (void) timeout_ms; return true; }
