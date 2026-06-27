#include "api.h"

namespace app {
using LocalAlias = HeaderDevice;
typedef HeaderDevice LegacyDevice;

void phase3_driver() {
    LocalAlias local;
    local.start();

    LegacyDevice legacy;
    legacy.start();

    HeaderDevice header_alias;
    header_alias.start();

    Device::reset();
    registerCallback(callback_target);

    void (*fp)() = callback_target;
    fp();

    header_inline_target();
}
}
