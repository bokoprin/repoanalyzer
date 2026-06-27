#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if FEATURE_A
void a_entry() {
    init_device();
}
#elif FEATURE_B
void b_entry() {
    init_device();
}
#else
void fallback_entry() {
    init_device();
}
#endif

#if UNKNOWN_FEATURE
void unknown_entry() {
    init_device();
}
#elif FEATURE_B
void maybe_b_entry() {
    init_device();
}
#else
void maybe_fallback_entry() {
    init_device();
}
#endif
