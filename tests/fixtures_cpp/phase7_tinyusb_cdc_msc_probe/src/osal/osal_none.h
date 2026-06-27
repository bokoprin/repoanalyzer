#ifndef OSAL_NONE_H_
#define OSAL_NONE_H_
#include "common/tusb_common.h"

typedef struct {
  uint8_t occupied;
} osal_queue_t;

#define OSAL_QUEUE_DEF(name) static osal_queue_t name

static bool osal_queue_send(osal_queue_t* q, void const* event, bool in_isr) {
  (void) event;
  (void) in_isr;
  q->occupied = 1;
  return true;
}

static bool osal_queue_receive(osal_queue_t* q, void* event) {
  (void) event;
  if (!q->occupied) {
    return false;
  }
  q->occupied = 0;
  return true;
}

#endif
