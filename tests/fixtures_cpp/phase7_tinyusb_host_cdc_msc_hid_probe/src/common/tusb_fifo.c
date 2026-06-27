#include "common/tusb_common.h"

bool tu_fifo_write(void* fifo, void const* data) {
  (void) fifo;
  return data != 0;
}

bool tu_fifo_read(void* fifo, void* data) {
  (void) fifo;
  return data != 0;
}
