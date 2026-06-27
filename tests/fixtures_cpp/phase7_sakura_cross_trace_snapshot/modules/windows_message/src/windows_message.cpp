#include "windows_message_api.h"

int sakura::LOWORD(sakura::WPARAM value) { return int(value & 0xffff); }
long sakura::MAKELONG(int low, int high) { return low | (high << 16); }
sakura::HWND sakura::GetParent(sakura::HWND hwnd) { return hwnd; }
sakura::LRESULT sakura::DialogBoxParam(sakura::HINSTANCE instance, int resourceId, sakura::HWND parent, sakura::LRESULT (*proc)(sakura::HWND, sakura::UINT, sakura::WPARAM, sakura::LPARAM), sakura::LPARAM param) { return 1; }
sakura::BOOL sakura::EndDialog(sakura::HWND dialog, int result) { return 1; }
sakura::LRESULT sakura::SendMessageCmd(sakura::HWND hwnd, sakura::UINT message, sakura::WPARAM wParam, sakura::LPARAM lParam) { return 0; }
sakura::BOOL sakura::SetWindowSubclass(sakura::HWND hwnd, sakura::LRESULT (*proc)(sakura::HWND, sakura::UINT, sakura::WPARAM, sakura::LPARAM, sakura::UINT_PTR, sakura::DWORD_PTR), sakura::UINT_PTR id, sakura::DWORD_PTR data) { return 1; }

bool sakura::CSearchDialog::OpenDialog(HWND parent) {
    return DialogBoxParam(nullptr, IDD_SEARCH, parent, CSearchDialog::DlgProc, 0) != 0;
}

sakura::LRESULT sakura::CSearchDialog::DlgProc(HWND hDlg, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
    case WM_INITDIALOG:
        OnInitDialog(hDlg);
        return 1;
    case WM_COMMAND:
        switch (LOWORD(wParam)) {
        case IDC_BUTTON_FIND:
            OnFindNext(hDlg);
            return 1;
        case IDCANCEL:
            EndDialog(hDlg, IDCANCEL);
            return 1;
        }
        break;
    case WM_CLOSE:
        EndDialog(hDlg, IDCANCEL);
        return 1;
    }
    return 0;
}

void sakura::CSearchDialog::OnInitDialog(HWND hDlg) {
}

void sakura::CSearchDialog::OnFindNext(HWND hDlg) {
    SendMessageCmd(GetParent(hDlg), WM_COMMAND, F_SEARCH_NEXT, 0);
}

sakura::BOOL sakura::CViewCommander::HandleCommand(int command) {
    switch (command) {
    case F_SEARCH_NEXT:
        Command_SEARCH_NEXT();
        break;
    }
    return 1;
}

void sakura::CViewCommander::Command_SEARCH_NEXT() {
}

void sakura::CPropTypesColor::InitColorList(HWND hwndList) {
    SetWindowSubclass(hwndList, CPropTypesColor::ColorList_SubclassProc, 10, 0);
}

sakura::LRESULT sakura::CPropTypesColor::ColorList_SubclassProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam, UINT_PTR id, DWORD_PTR refData) {
    switch (uMsg) {
    case WM_COMMAND:
        return SendMessageCmd(GetParent(hwnd), WM_COMMAND, IDC_BUTTON_FIND, 0);
    default:
        break;
    }
    return 0;
}
