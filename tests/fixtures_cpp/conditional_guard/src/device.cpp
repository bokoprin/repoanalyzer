#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#ifdef FEATURE_EXTRA
void feature_entry() {
    init_device();
}
#endif

#ifndef DISABLE_DEFAULT_HELPER
void default_helper() {
    init_device();
}
#endif

#if FEATURE_ALT
void alt_entry() {
    init_device();
}
#endif

#if 0
void ghost_entry() {
    init_device();
}
#else
void fallback_entry() {
    init_device();
}
#endif
