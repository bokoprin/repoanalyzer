#include "device.h"

void init_device() {
}

void start_device() {
    init_device();
}

#if ACTIVE_MODE == 2
void cli_alias_entry() {
    init_device();
}
#else
void cli_alias_fallback() {
    init_device();
}
#endif

#if ACTIVE_HEADER_MODE == 3
void header_alias_entry() {
    init_device();
}
#else
void header_alias_fallback() {
    init_device();
}
#endif

#if NEGATIVE_ALIAS < 0
void negative_alias_entry() {
    init_device();
}
#endif

#if ZERO_ALIAS
void zero_alias_entry() {
    init_device();
}
#else
void zero_alias_fallback() {
    init_device();
}
#endif

#if UNRESOLVED_ALIAS == 1
void unresolved_alias_entry() {
    init_device();
}
#endif

#if CYCLE_A == 1
void cycle_alias_entry() {
    init_device();
}
#endif
