#pragma once

namespace sakura {
using HWND = void*;
using HINSTANCE = void*;
using UINT = unsigned int;
using WPARAM = unsigned long;
using LPARAM = long;
using LRESULT = long;
using BOOL = int;
using UINT_PTR = unsigned long;
using DWORD_PTR = unsigned long;

constexpr UINT WM_INITDIALOG = 0x0110;
constexpr UINT WM_COMMAND = 0x0111;
constexpr UINT WM_NOTIFY = 0x004E;
constexpr UINT WM_CLOSE = 0x0010;
constexpr int IDD_SEARCH = 100;
constexpr int IDC_BUTTON_FIND = 1001;
constexpr int IDCANCEL = 2;
constexpr int F_SEARCH_NEXT = 2001;

int LOWORD(WPARAM value);
long MAKELONG(int low, int high);
HWND GetParent(HWND hwnd);
LRESULT DialogBoxParam(HINSTANCE instance, int resourceId, HWND parent, LRESULT (*proc)(HWND, UINT, WPARAM, LPARAM), LPARAM param);
BOOL EndDialog(HWND dialog, int result);
LRESULT SendMessageCmd(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam);
BOOL SetWindowSubclass(HWND hwnd, LRESULT (*proc)(HWND, UINT, WPARAM, LPARAM, UINT_PTR, DWORD_PTR), UINT_PTR id, DWORD_PTR data);

class CViewCommander {
public:
    BOOL HandleCommand(int command);
    void Command_SEARCH_NEXT();
};

class CSearchDialog {
public:
    bool OpenDialog(HWND parent);
    static LRESULT DlgProc(HWND hDlg, UINT uMsg, WPARAM wParam, LPARAM lParam);
    static void OnInitDialog(HWND hDlg);
    static void OnFindNext(HWND hDlg);
};

class CPropTypesColor {
public:
    void InitColorList(HWND hwndList);
    static LRESULT ColorList_SubclassProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam, UINT_PTR id, DWORD_PTR refData);
};
}
