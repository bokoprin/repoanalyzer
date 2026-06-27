#include "undo_edit_api.h"

namespace sakura {
int COpe::GetCode() { return 0; }
int COpeBlk::GetRefCount() { return 0; }
void COpeBlk::SetRefCount(int count) {}
void COpeBlk::AddRef() {}
int COpeBlk::GetNum() { return 1; }
COpe* COpeBlk::GetOpe(int index) { return nullptr; }
COpeBlk* COpeBuf::DoUndo(bool* modified) { return nullptr; }
COpeBlk* COpeBuf::DoRedo(bool* modified) { return nullptr; }
void CDocEditor::SetModified(bool modified, bool notify) {}
bool CDocEditor::IsEnableUndo() { return true; }
bool CDocEditor::IsEnableRedo() { return true; }
void CLayoutMgr::LogicToLayout(CLogicPoint point, CLayoutPoint* layout) {}
CEditDoc* CEditView::GetDocument() { return nullptr; }
void CEditView::InsertData_CEditView(CLayoutPoint point, const wchar_t* data, int len, CLayoutPoint* newPoint, bool redraw) {}
bool CEditView::ReplaceData_CEditView3(CLayoutRange range, COpeLineData* deleted, COpeLineData* inserted, bool redraw) { return true; }
void CEditView::SetUndoBuffer() {}
CViewCommander::CViewCommander(CEditView* view) : m_pCommanderView(view) {}
CEditDoc* CViewCommander::GetDocument() { return m_pCommanderView->GetDocument(); }
COpeBlk* CViewCommander::GetOpeBlk() { return nullptr; }
void CViewCommander::SetOpeBlk(COpeBlk* block) {}

BOOL CViewCommander::HandleCommand(EFunctionCode nCommand, bool bRedraw, LPARAM lparam1) {
    BOOL bRet = 1;
    switch (nCommand) {
    case F_WCHAR: Command_WCHAR((wchar_t)lparam1); break;
    case F_UNDO:  Command_UNDO(); break;
    case F_REDO:  Command_REDO(); break;
    }
    return bRet;
}

void CViewCommander::Command_WCHAR(wchar_t ch) {
    GetDocument()->m_cDocEditor.SetModified(true, true);
    CLayoutPoint pt;
    CLayoutPoint ptLayoutNew;
    const wchar_t* data = &ch;
    m_pCommanderView->InsertData_CEditView(pt, data, 1, &ptLayoutNew, true);
}

void CViewCommander::Command_UNDO() {
    COpeBlk* opeBlk = m_pCommanderView->m_cCommander.GetOpeBlk();
    if (opeBlk) {
        int nCount = opeBlk->GetRefCount();
        opeBlk->SetRefCount(1);
        m_pCommanderView->SetUndoBuffer();
        if (m_pCommanderView->m_cCommander.GetOpeBlk() == nullptr && 0 < nCount) {
            m_pCommanderView->m_cCommander.SetOpeBlk(new COpeBlk());
            m_pCommanderView->m_cCommander.GetOpeBlk()->SetRefCount(nCount);
        }
    }
    bool bIsModified = false;
    m_pCommanderView->m_bDoing_UndoRedo = true;
    COpeBlk* pcOpeBlk = GetDocument()->m_cDocEditor.m_cOpeBuf.DoUndo(&bIsModified);
    COpe* pcOpe = pcOpeBlk->GetOpe(0);
    CLayoutRange range;
    COpeLineData deleted;
    m_pCommanderView->ReplaceData_CEditView3(range, &deleted, nullptr, true);
    GetDocument()->m_cDocEditor.SetModified(bIsModified, true);
    m_pCommanderView->m_bDoing_UndoRedo = false;
}

void CViewCommander::Command_REDO() {
    COpeBlk* opeBlk = m_pCommanderView->m_cCommander.GetOpeBlk();
    if (opeBlk) {
        int nCount = opeBlk->GetRefCount();
        opeBlk->SetRefCount(1);
        m_pCommanderView->SetUndoBuffer();
        if (m_pCommanderView->m_cCommander.GetOpeBlk() == nullptr && 0 < nCount) {
            m_pCommanderView->m_cCommander.SetOpeBlk(new COpeBlk());
            m_pCommanderView->m_cCommander.GetOpeBlk()->SetRefCount(nCount);
        }
    }
    bool bIsModified = false;
    m_pCommanderView->m_bDoing_UndoRedo = true;
    COpeBlk* pcOpeBlk = GetDocument()->m_cDocEditor.m_cOpeBuf.DoRedo(&bIsModified);
    COpe* pcOpe = pcOpeBlk->GetOpe(0);
    CLayoutRange range;
    COpeLineData inserted;
    m_pCommanderView->ReplaceData_CEditView3(range, nullptr, &inserted, true);
    GetDocument()->m_cDocEditor.SetModified(bIsModified, true);
    m_pCommanderView->m_bDoing_UndoRedo = false;
}
}
