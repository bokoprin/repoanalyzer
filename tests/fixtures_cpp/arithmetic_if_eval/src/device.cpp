#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if BASE + OFFSET == 3
void additive_entry() {
    init_device();
}
#else
void additive_fallback() {
    init_device();
}
#endif

#if BASE - OFFSET == 1
void subtract_entry() {
    init_device();
}
#endif

#if SCALE * 2 == 8
void multiply_entry() {
    init_device();
}
#endif

#if DIVIDEND / DIVISOR == 3
void division_entry() {
    init_device();
}
#endif

#if MOD_VALUE % 3 == 1
void modulo_entry() {
    init_device();
}
#endif

#if (BASE + OFFSET) * SCALE == 12
void parenthesized_entry() {
    init_device();
}
#endif

#if -BASE + OFFSET < 0
void unary_minus_entry() {
    init_device();
}
#endif

#if BASE + OFFSET == 4
void inactive_arithmetic_entry() {
    init_device();
}
#else
void arithmetic_else_entry() {
    init_device();
}
#endif

#if UNKNOWN_VALUE + 1 == 2
void unresolved_arithmetic_entry() {
    init_device();
}
#endif

#if DIVIDEND / ZERO == 1
void division_by_zero_entry() {
    init_device();
}
#endif
