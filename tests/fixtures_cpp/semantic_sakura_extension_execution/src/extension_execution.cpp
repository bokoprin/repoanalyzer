namespace sakura {

enum EFunctionCode {
    F_DEFAULT = 0,
    F_FILEOPEN2 = 10,
    F_SEARCH_NEXT = 100,
    F_GREP = 102,
    F_USERMACRO_0 = 3000,
    F_PLUGIN_FIRST = 4000,
    F_EXECEXTCOMMAND = 5000,
};
using HINSTANCE = void*;
using HWND = void*;
using LPARAM = long;
using BOOL = int;
const int MAX_CUSTMACRO = 10;
const int STAND_KEYMACRO = -1;
const int PP_COMMAND = 0;

struct MacroFuncInfo {
    EFunctionCode m_nFuncID;
    const wchar_t* m_pszFuncName;
};

class CEditView {};

class CMacroManagerBase {
public:
    BOOL LoadKeyMacro(HINSTANCE, const wchar_t*) { return 1; }
    BOOL LoadKeyMacroStr(HINSTANCE, const wchar_t*) { return 1; }
    void ExecKeyMacro2(CEditView*, int) {}
};

class CKeyMacroMgr : public CMacroManagerBase {
public:
    void Append(EFunctionCode, const LPARAM*, CEditView*) {}
    BOOL SaveKeyMacro(HINSTANCE, const wchar_t*) { return 1; }
};

class CMacroFactory {
public:
    static CMacroFactory* getInstance();
    CMacroManagerBase* Create(const wchar_t*) { return new CMacroManagerBase; }
};

class CShareData {
public:
    static CShareData* getInstance();
    bool BeReloadWhenExecuteMacro(int) { return true; }
    int GetMacroFilename(int, wchar_t*, int) { return 1; }
};

class CSMacroMgr {
public:
    static MacroFuncInfo m_MacroFuncInfoCommandArr[];
    CMacroManagerBase* m_pKeyMacro = nullptr;
    CMacroManagerBase* m_cSavedKeyMacro[MAX_CUSTMACRO] = {};
    int Append(int idx, EFunctionCode nFuncID, const LPARAM* lParams, CEditView* pcEditView);
    BOOL Exec(int idx, HINSTANCE hInstance, CEditView* pcEditView, int flags);
    BOOL Load(int idx, HINSTANCE hInstance, const wchar_t* pszPath, const wchar_t* pszType);
    BOOL Save(int idx, HINSTANCE hInstance, const wchar_t* pszPath);
};

MacroFuncInfo CSMacroMgr::m_MacroFuncInfoCommandArr[] = {
    {F_FILEOPEN2, L"FileOpen"},
    {F_SEARCH_NEXT, L"SearchNext"},
    {F_GREP, L"Grep"},
};

int CSMacroMgr::Append(int idx, EFunctionCode nFuncID, const LPARAM* lParams, CEditView* pcEditView) {
    CKeyMacroMgr* pKeyMacro = new CKeyMacroMgr;
    pKeyMacro->Append(nFuncID, lParams, pcEditView);
    return 1;
}

BOOL CSMacroMgr::Load(int idx, HINSTANCE hInstance, const wchar_t* pszPath, const wchar_t* pszType) {
    CMacroManagerBase* pMacro = CMacroFactory::getInstance()->Create(pszType);
    if (pszType == nullptr) {
        return pMacro->LoadKeyMacro(hInstance, pszPath);
    }
    return pMacro->LoadKeyMacroStr(hInstance, pszPath);
}

BOOL CSMacroMgr::Save(int idx, HINSTANCE hInstance, const wchar_t* pszPath) {
    CKeyMacroMgr* pKeyMacro = new CKeyMacroMgr;
    return pKeyMacro->SaveKeyMacro(hInstance, pszPath);
}

BOOL CSMacroMgr::Exec(int idx, HINSTANCE hInstance, CEditView* pcEditView, int flags) {
    if (m_cSavedKeyMacro[idx] == nullptr || CShareData::getInstance()->BeReloadWhenExecuteMacro(idx)) {
        wchar_t path[260] = {};
        CShareData::getInstance()->GetMacroFilename(idx, path, 260);
        if (!Load(idx, hInstance, path, nullptr)) {
            return 0;
        }
    }
    m_cSavedKeyMacro[idx]->ExecKeyMacro2(pcEditView, flags);
    return 1;
}

class CPlug {
public:
    int m_id = 0;
    int GetFunctionCode() { return F_PLUGIN_FIRST; }
    static int GetPluginFunctionCode(int id, int index) { return F_PLUGIN_FIRST + id + index; }
    void Invoke(CEditView*, int) {}
};

class CJackManager {
public:
    static CJackManager* getInstance();
    void RegisterPlug(const wchar_t* jackName, CPlug* plug);
    void InvokePlugins(int jack, CEditView* view);
    CPlug* GetCommandById(int id);
    int GetCommandCode(int index) const;
    void GetUsablePlug(int jack, int plugId, CPlug** plugs);
};

void CJackManager::RegisterPlug(const wchar_t* jackName, CPlug* plug) {
    int plugid = plug->GetFunctionCode();
    int method = CPlug::GetPluginFunctionCode(plug->m_id, 0);
    plugs.push_back(plug);
}

void CJackManager::InvokePlugins(int jack, CEditView* view) {
    CPlug* plug = nullptr;
    GetUsablePlug(jack, 0, &plug);
    plug->Invoke(view, 0);
}

CPlug* CJackManager::GetCommandById(int id) {
    return new CPlug;
}

int CJackManager::GetCommandCode(int index) const {
    return F_PLUGIN_FIRST + index;
}

void CJackManager::GetUsablePlug(int jack, int plugId, CPlug** plugs) {}

class CViewCommander {
public:
    CSMacroMgr* m_pcSMacroMgr;
    CEditView* m_view;
    bool HandleCommand(EFunctionCode nCommand);
    void Command_EXECEXTCOMMAND(const wchar_t* path);
};

void ShellExecuteW(HWND, const wchar_t*, const wchar_t*, const wchar_t*, const wchar_t*, int) {}
void CreateProcessW(const wchar_t*, wchar_t*) {}

bool CViewCommander::HandleCommand(EFunctionCode nCommand) {
    LPARAM lparams[] = {0, 0, 0, 0};
    if (nCommand != F_EXECEXTCOMMAND) {
        m_pcSMacroMgr->Append(STAND_KEYMACRO, nCommand, lparams, m_view);
    }
    if (F_USERMACRO_0 <= nCommand) {
        m_pcSMacroMgr->Exec(nCommand - F_USERMACRO_0, nullptr, m_view, 0);
    }
    if (F_PLUGIN_FIRST <= nCommand) {
        CPlug* plug = CJackManager::getInstance()->GetCommandById(nCommand);
        plug->Invoke(m_view, 0);
    }
    return true;
}

void CViewCommander::Command_EXECEXTCOMMAND(const wchar_t* path) {
    ShellExecuteW(nullptr, L"open", path, nullptr, nullptr, 1);
    CreateProcessW(path, nullptr);
}

}
