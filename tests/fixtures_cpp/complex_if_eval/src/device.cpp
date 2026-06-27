#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if defined(FEATURE_EXTRA) && FEATURE_ALT
void complex_active_entry() {
    init_device();
}
#else
void complex_inactive_fallback() {
    init_device();
}
#endif

#if defined(FEATURE_EXTRA) && FEATURE_ZERO
void zero_and_entry() {
    init_device();
}
#else
void zero_and_fallback() {
    init_device();
}
#endif

#if defined(FEATURE_EXTRA) || UNRESOLVED_FEATURE
void true_or_unknown_entry() {
    init_device();
}
#else
void true_or_unknown_fallback() {
    init_device();
}
#endif

#if !FEATURE_ZERO && FEATURE_ALT
void not_zero_and_alt_entry() {
    init_device();
}
#endif

#if !defined(DISABLE_BY_MACRO) || FEATURE_ZERO
void disabled_by_macro_entry() {
    init_device();
}
#else
void disabled_by_macro_fallback() {
    init_device();
}
#endif

#if defined(UNKNOWN_FEATURE) || FEATURE_ZERO
void unresolved_complex_entry() {
    init_device();
}
#endif
