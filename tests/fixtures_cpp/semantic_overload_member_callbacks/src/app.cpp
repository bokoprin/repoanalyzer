namespace app {

void init_device() {}
void set_mode(int mode) { init_device(); }
void set_mode(const char* mode) { init_device(); }
void on_event() { init_device(); }
void on_error() { init_device(); }

class Device {
public:
    Device(int id) { init_device(); }
    void start() { init_device(); }
    static void global_init() { init_device(); }
};

void register_callback(void (*cb)());

void setup() {
    set_mode(1);
    set_mode("safe");
    int x = 0;
    set_mode(x);
    Device dev(1);
    Device* ptr;
    dev.start();
    ptr->start();
    Device::global_init();
    register_callback(on_event);
}

void dispatch(bool err) {
    void (*handler)() = on_event;
    if (err) handler = on_error;
    handler();
}

struct Ops { void (*start)(); void (*stop)(); };
Ops ops = { .start = on_event, .stop = on_error };

}
