#include "common/tusb_common.h"

int32_t tud_msc_read10_cb(uint8_t lun, uint32_t lba, uint32_t offset, void* buffer, uint32_t bufsize) {
  (void) lun;
  (void) lba;
  (void) offset;
  (void) buffer;
  return (int32_t) bufsize;
}

int32_t tud_msc_write10_cb(uint8_t lun, uint32_t lba, uint32_t offset, uint8_t* buffer, uint32_t bufsize) {
  (void) lun;
  (void) lba;
  (void) offset;
  (void) buffer;
  return (int32_t) bufsize;
}
