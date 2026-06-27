#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if FEATURE_SELECTOR ? 1 : 0
void ternary_entry() {
    init_device();
}
#endif

#if FEATURE_FUNC(1)
void function_like_entry() {
    init_device();
}
#endif

#if UNKNOWN_VALUE + 1 == 2
void unresolved_entry() {
    init_device();
}
#endif
