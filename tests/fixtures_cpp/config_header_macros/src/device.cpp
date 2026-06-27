#include "device.h"
#include "local_config.h"

void init_device() {
}

void start_device() {
    init_device();
}

#ifdef FEATURE_FORCED
void forced_entry() {
    init_device();
}
#else
void forced_fallback() {
    init_device();
}
#endif

#ifndef DISABLE_FROM_FORCED
void enabled_when_not_disabled() {
    init_device();
}
#else
void forced_disabled_fallback() {
    init_device();
}
#endif

#if FEATURE_FROM_DIRECT && FEATURE_EXPR_FROM_HEADER
void direct_entry() {
    init_device();
}
#else
void direct_fallback() {
    init_device();
}
#endif

#if FEATURE_ZERO_FROM_HEADER
void zero_header_entry() {
    init_device();
}
#else
void zero_header_fallback() {
    init_device();
}
#endif

#ifdef DISABLED_HEADER_DEFINE
void disabled_header_define_entry() {
    init_device();
}
#endif

#ifdef UNRESOLVED_FROM_CONFIG_TEST
void unresolved_config_entry() {
    init_device();
}
#endif
