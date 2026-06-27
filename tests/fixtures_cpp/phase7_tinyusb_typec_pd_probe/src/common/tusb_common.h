#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define TU_ATTR_WEAK __attribute__((weak))
#define TU_ATTR_PACKED __attribute__((packed))
#define TU_ATTR_ALWAYS_INLINE inline
#define TU_ATTR_ALIGNED(n) __attribute__((aligned(n)))
#define tu_static static
#define TU_VERIFY(x) do { if (!(x)) return false; } while (0)
#define TU_ASSERT(x) do { if (!(x)) return false; } while (0)
#define TU_LOG(level, ...)
#define TU_LOG_INT(level, value)
#define tu_memclr(buf, size)
#define tu_le32toh(x) (x)
#define tu_unaligned_read32(p) (*(uint32_t const*)(p))
typedef enum { XFER_RESULT_SUCCESS = 0 } xfer_result_t;
