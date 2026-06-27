#pragma once

namespace sakura {
class CLayoutMgr {
public:
    int SearchWord(int start);
};

class CEditDoc {
public:
    CLayoutMgr m_cLayoutMgr;
};

class Inner {
public:
    void method();
};

class Outer {
public:
    Inner member;
};

class CViewCommander {
public:
    CEditDoc* GetDocument();
    void Command_SEARCH_NEXT();
    void Command_MEMBER_CHAIN();
private:
    Outer object;
    Outer* ptr;
};
}
