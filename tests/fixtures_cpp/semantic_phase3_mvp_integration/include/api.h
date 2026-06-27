#pragma once

namespace app {
class Device {
public:
    void start();
    static void reset();
};

using HeaderDevice = Device;

inline void header_inline_target() {
}

template <typename T>
T passthrough(T value) {
    return value;
}

void registerCallback(void (*cb)());
void callback_target();
}
