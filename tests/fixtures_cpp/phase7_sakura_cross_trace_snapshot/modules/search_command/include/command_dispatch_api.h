#pragma once

namespace sakura {
using BOOL = int;
using LPARAM = long;
using HWND = void*;
using WCHAR = wchar_t;

enum EFunctionCode {
    F_SEARCH_DIALOG,
    F_SEARCH_BOX,
    F_SEARCH_NEXT,
    F_SEARCH_PREV,
    F_GREP,
    F_GREP_REPLACE
};

enum ESearchDirection {
    SEARCH_FORWARD,
    SEARCH_BACKWARD
};

class CSearchStringPattern {};
class CLogicRange {};
class CLayoutRange {};
class CLayoutMgr;
class CDocLineMgr {};

class CSearchAgent {
public:
    explicit CSearchAgent(CDocLineMgr* mgr);
    int SearchWord(int begin, ESearchDirection direction, CLogicRange* matchRange, const CSearchStringPattern& pattern);
    static const WCHAR* SearchString(const WCHAR* line, int lineLen, int idx, const CSearchStringPattern& pattern);
    static const WCHAR* SearchStringWord(const WCHAR* line, int lineLen, int idx, const CSearchStringPattern& pattern);
};

class CLayoutMgr {
public:
    int SearchWord(int nLine, int nIdx, ESearchDirection direction, CLayoutRange* matchRange, const CSearchStringPattern& pattern);
};

class CEditDoc {
public:
    CLayoutMgr m_cLayoutMgr;
    CDocLineMgr m_cDocLineMgr;
};

class CEditView {
public:
    CEditDoc* GetDocument();
};

class CViewCommander {
public:
    explicit CViewCommander(CEditView* view);
    BOOL HandleCommand(EFunctionCode nCommand, bool bRedraw, LPARAM lparam1, LPARAM lparam2);
    void Command_SEARCH_DIALOG();
    void Command_SEARCH_BOX();
    void Command_SEARCH_NEXT(bool bChangeCurRegexp, bool bRedraw, bool bReplaceAll, HWND hwndParent, const WCHAR* pszNotFoundMessage);
    void Command_SEARCH_PREV(bool bRedraw, HWND hwndParent);
    void Command_GREP();
    void Command_GREP_REPLACE();
    CEditDoc* GetDocument();
private:
    CEditView* m_pCommanderView;
    CSearchStringPattern m_sSearchPattern;
};
}
