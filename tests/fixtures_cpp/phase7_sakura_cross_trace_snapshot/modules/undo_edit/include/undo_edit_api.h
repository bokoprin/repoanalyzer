#pragma once

namespace sakura {
using BOOL = int;
using LPARAM = long;

enum EFunctionCode {
    F_WCHAR,
    F_UNDO,
    F_REDO
};

class CLogicPoint {};
class CLayoutPoint {};
class CLayoutRange {};
class COpeLineData {};

class COpe {
public:
    int GetCode();
    CLogicPoint m_ptCaretPos_PHY_Before;
    CLogicPoint m_ptCaretPos_PHY_After;
};

class COpeBlk {
public:
    int GetRefCount();
    void SetRefCount(int count);
    void AddRef();
    int GetNum();
    COpe* GetOpe(int index);
};

class COpeBuf {
public:
    COpeBlk* DoUndo(bool* modified);
    COpeBlk* DoRedo(bool* modified);
};

class CDocEditor {
public:
    COpeBuf m_cOpeBuf;
    void SetModified(bool modified, bool notify);
    bool IsEnableUndo();
    bool IsEnableRedo();
};

class CLayoutMgr {
public:
    void LogicToLayout(CLogicPoint point, CLayoutPoint* layout);
};

class CEditDoc {
public:
    CDocEditor m_cDocEditor;
    CLayoutMgr m_cLayoutMgr;
};

class CEditView;

class CViewCommander {
public:
    explicit CViewCommander(CEditView* view);
    BOOL HandleCommand(EFunctionCode nCommand, bool bRedraw, LPARAM lparam1);
    void Command_WCHAR(wchar_t ch);
    void Command_UNDO();
    void Command_REDO();
    CEditDoc* GetDocument();
    COpeBlk* GetOpeBlk();
    void SetOpeBlk(COpeBlk* block);
private:
    CEditView* m_pCommanderView;
};

class CEditView {
public:
    CEditDoc* GetDocument();
    void InsertData_CEditView(CLayoutPoint point, const wchar_t* data, int len, CLayoutPoint* newPoint, bool redraw);
    bool ReplaceData_CEditView3(CLayoutRange range, COpeLineData* deleted, COpeLineData* inserted, bool redraw);
    void SetUndoBuffer();
    CViewCommander m_cCommander;
};
}
