#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if MODE == 2
void mode_two_entry() {
    init_device();
}
#else
void mode_two_fallback() {
    init_device();
}
#endif

#if MODE != 2
void mode_not_two_entry() {
    init_device();
}
#else
void mode_not_two_fallback() {
    init_device();
}
#endif

#if MINOR >= 5 && MODE < 3
void range_entry() {
    init_device();
}
#endif

#if LEVEL > 0
void level_positive_entry() {
    init_device();
}
#else
void level_nonpositive_fallback() {
    init_device();
}
#endif

#if HEX_VALUE == 16
void hex_entry() {
    init_device();
}
#endif

#if NEGATIVE_VALUE < 0
void negative_entry() {
    init_device();
}
#endif

#if UNKNOWN_VERSION >= 2
void unresolved_compare_entry() {
    init_device();
}
#endif
