#include "search_api.h"

namespace sakura {
int CLayoutMgr::SearchWord(int start) {
    return start;
}

void Inner::method() {
}

CEditDoc* CViewCommander::GetDocument() {
    return nullptr;
}

void CViewCommander::Command_SEARCH_NEXT() {
    GetDocument()->m_cLayoutMgr.SearchWord(1);
}

void CViewCommander::Command_MEMBER_CHAIN() {
    object.member.method();
    ptr->member.method();
}
}
