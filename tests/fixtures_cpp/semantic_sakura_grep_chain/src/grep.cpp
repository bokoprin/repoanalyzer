#include "grep_api.h"

namespace sakura {
const WCHAR* CNativeW::GetStringPtr() const { return nullptr; }
int CNativeW::GetStringLength() const { return 0; }
const WCHAR* CSearchAgent::SearchString(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern) { return nullptr; }
const WCHAR* CSearchAgent::SearchStringWord(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern) { return nullptr; }
void CViewCommander::Command_ADDTAIL(const WCHAR* text, int length) {}
CViewCommander& CEditView::GetCommander() { static CViewCommander commander; return commander; }
CEditWnd* CEditWnd::getInstance() { return nullptr; }
void CEditWnd::SetDrawSwitchOfAllViews(bool enabled) {}

void CGrepAgent::AddTail(CEditView* pcEditView, const CNativeW& cmem, bool bAddStdout) {
    pcEditView->GetCommander().Command_ADDTAIL(cmem.GetStringPtr(), cmem.GetStringLength());
}

int CGrepAgent::DoGrepFile(CEditView* pcViewDst, const CSearchStringPattern& pattern) {
    const WCHAR* pLine = nullptr;
    int nLineLen = 0;
    CSearchAgent::SearchString(pLine, nLineLen, 0, pattern);
    return 1;
}

int CGrepAgent::DoGrepTree(CEditView* pcViewDst, const CSearchStringPattern& pattern) {
    CEditWnd::getInstance()->SetDrawSwitchOfAllViews(true);
    DoGrepFile(pcViewDst, pattern);
    CNativeW message;
    AddTail(pcViewDst, message, false);
    return 0;
}
}
