namespace app {

class Base { public: virtual void run(); };
class A : public Base { public: void run() override; };
class B : public Base { public: void run() override; };

void Base::run() {}
void A::run() {}
void B::run() {}

void dispatch(Base* b) {
    b->run();
}

}
