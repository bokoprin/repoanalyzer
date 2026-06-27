#pragma once

namespace sakura {
using WCHAR = wchar_t;
using HWND = void*;

class CNativeW {
public:
    const WCHAR* GetStringPtr() const;
    int GetStringLength() const;
};

class CSearchStringPattern {
};

class CSearchAgent {
public:
    static const WCHAR* SearchString(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern);
    static const WCHAR* SearchStringWord(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern);
};

class CViewCommander {
public:
    void Command_ADDTAIL(const WCHAR* text, int length);
};

class CEditView {
public:
    CViewCommander& GetCommander();
};

class CEditWnd {
public:
    static CEditWnd* getInstance();
    void SetDrawSwitchOfAllViews(bool enabled);
};

class CGrepAgent {
public:
    void AddTail(CEditView* pcEditView, const CNativeW& cmem, bool bAddStdout);
    int DoGrepTree(CEditView* pcViewDst, const CSearchStringPattern& pattern);
    int DoGrepFile(CEditView* pcViewDst, const CSearchStringPattern& pattern);
};
}
