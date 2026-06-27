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
#else
void feature_fallback() {
    init_device();
}
#endif

#ifndef DISABLE_DEFAULT_HELPER
void default_helper() {
    init_device();
}
#else
void disabled_default_fallback() {
    init_device();
}
#endif

#if FEATURE_ALT
void alt_entry() {
    init_device();
}
#else
void alt_fallback() {
    init_device();
}
#endif

#if FEATURE_ZERO
void zero_entry() {
    init_device();
}
#else
void zero_fallback() {
    init_device();
}
#endif

#ifdef UNRESOLVED_FEATURE
void unresolved_entry() {
    init_device();
}
#endif
