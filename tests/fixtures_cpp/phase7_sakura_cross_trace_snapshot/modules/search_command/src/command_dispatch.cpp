#include "command_dispatch_api.h"

namespace sakura {
CSearchAgent::CSearchAgent(CDocLineMgr* mgr) {}
const WCHAR* CSearchAgent::SearchString(const WCHAR* line, int lineLen, int idx, const CSearchStringPattern& pattern) { return nullptr; }
const WCHAR* CSearchAgent::SearchStringWord(const WCHAR* line, int lineLen, int idx, const CSearchStringPattern& pattern) { return nullptr; }
int CSearchAgent::SearchWord(int begin, ESearchDirection direction, CLogicRange* matchRange, const CSearchStringPattern& pattern) {
    const WCHAR* line = nullptr;
    SearchString(line, 0, 0, pattern);
    SearchStringWord(line, 0, 0, pattern);
    return 1;
}

int CLayoutMgr::SearchWord(int nLine, int nIdx, ESearchDirection direction, CLayoutRange* matchRange, const CSearchStringPattern& pattern) {
    CDocLineMgr mgr;
    CLogicRange logicRange;
    CSearchAgent(&mgr).SearchWord(nIdx, direction, &logicRange, pattern);
    return 1;
}

CEditDoc* CEditView::GetDocument() { return nullptr; }
CViewCommander::CViewCommander(CEditView* view) : m_pCommanderView(view) {}
CEditDoc* CViewCommander::GetDocument() { return m_pCommanderView->GetDocument(); }

BOOL CViewCommander::HandleCommand(EFunctionCode nCommand, bool bRedraw, LPARAM lparam1, LPARAM lparam2) {
    BOOL bRet = 1;
    switch (nCommand) {
    case F_SEARCH_DIALOG:        Command_SEARCH_DIALOG(); break;
    case F_SEARCH_BOX:           Command_SEARCH_BOX(); break;
    case F_SEARCH_NEXT:          Command_SEARCH_NEXT(true, bRedraw, false, (HWND)lparam1, (const WCHAR*)lparam2); break;
    case F_SEARCH_PREV:          Command_SEARCH_PREV(bRedraw, (HWND)lparam1); break;
    case F_GREP:                 Command_GREP(); break;
    case F_GREP_REPLACE:
        Command_GREP_REPLACE();
        return bRet;
    }
    return bRet;
}

void CViewCommander::Command_SEARCH_DIALOG() {}
void CViewCommander::Command_SEARCH_BOX() {}
void CViewCommander::Command_SEARCH_PREV(bool bRedraw, HWND hwndParent) {}
void CViewCommander::Command_GREP() {}
void CViewCommander::Command_GREP_REPLACE() {}
void CViewCommander::Command_SEARCH_NEXT(bool bChangeCurRegexp, bool bRedraw, bool bReplaceAll, HWND hwndParent, const WCHAR* pszNotFoundMessage) {
    CLayoutRange range;
    GetDocument()->m_cLayoutMgr.SearchWord(0, 0, SEARCH_FORWARD, &range, m_sSearchPattern);
}
}
