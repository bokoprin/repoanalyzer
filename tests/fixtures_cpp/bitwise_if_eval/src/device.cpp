#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if FLAGS & ENABLE_A
void bit_and_entry() {
    init_device();
}
#endif

#if FLAGS & DISABLED_FLAG
void inactive_bit_and_entry() {
    init_device();
}
#else
void bit_and_fallback() {
    init_device();
}
#endif

#if FLAGS | DISABLED_FLAG
void bit_or_entry() {
    init_device();
}
#endif

#if FLAGS ^ ENABLE_A
void bit_xor_entry() {
    init_device();
}
#endif

#if FLAGS ^ FLAGS
void inactive_bit_xor_entry() {
    init_device();
}
#else
void bit_xor_fallback() {
    init_device();
}
#endif

#if ~ZERO_VALUE & ENABLE_A
void bit_not_entry() {
    init_device();
}
#endif

#if SHIFT_BASE << SHIFT_AMOUNT == 8
void left_shift_entry() {
    init_device();
}
#endif

#if FLAGS >> 1 == 1
void right_shift_entry() {
    init_device();
}
#endif

#if SHIFT_BASE << NEGATIVE_SHIFT == 1
void negative_shift_entry() {
    init_device();
}
#endif

#if UNKNOWN_FLAGS & ENABLE_A
void unresolved_bitwise_entry() {
    init_device();
}
#endif
