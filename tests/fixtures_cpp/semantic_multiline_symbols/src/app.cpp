namespace app {

void init_device() {
}

class Device {
public:
    Device();
    ~Device();
    static void global_init();
    void
    start(
        int mode
    );
};

Device::Device() {
}

Device::~Device() {
}

void Device::global_init() {
    init_device();
}

void
Device::start(
    int mode
) {
    init_device();
}

void run() {
    Device::global_init();
    Device dev(1);
    dev.start();
}

}
