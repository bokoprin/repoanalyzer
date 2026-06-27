namespace sakura {

enum EFunctionCode {
    F_DEFAULT = 0,
    F_SEARCH_NEXT = 100,
    F_SEARCH_PREV = 101,
    F_GREP = 102,
    F_DISABLE = 999,
};

struct ACCEL {
    int fVirt;
    int key;
    int cmd;
};
using HACCEL = void*;
struct KEYDATA { int m_nKeyCode; int m_nFuncCodeArr[8]; };

HACCEL CreateAcceleratorTable(ACCEL*, int) { return nullptr; }
EFunctionCode GetFuncCodeAt(KEYDATA& data, int status, bool getDefault = true) {
    return static_cast<EFunctionCode>(data.m_nFuncCodeArr[status]);
}

class CKeyBind {
public:
    HACCEL CreateAccerelator(int nKeyNameArrNum, KEYDATA* pKeyNameArr);
    EFunctionCode GetFuncCode(unsigned short nAccelCmd, int nKeyNameArrNum, KEYDATA* pKeyNameArr, bool bGetDefFuncCode = true);
};

HACCEL CKeyBind::CreateAccerelator(int nKeyNameArrNum, KEYDATA* pKeyNameArr) {
    ACCEL* pAccelArr = new ACCEL[nKeyNameArrNum];
    int k = 0;
    for (int i = 0; i < nKeyNameArrNum; ++i) {
        for (int j = 0; j < 8; ++j) {
            if (0 != GetFuncCodeAt(pKeyNameArr[i], j)) {
                pAccelArr[k].key = pKeyNameArr[i].m_nKeyCode;
                pAccelArr[k].cmd = pKeyNameArr[i].m_nKeyCode | (((unsigned short)j) << 8);
                k++;
            }
        }
    }
    return CreateAcceleratorTable(pAccelArr, k);
}

EFunctionCode CKeyBind::GetFuncCode(unsigned short nAccelCmd, int nKeyNameArrNum, KEYDATA* pKeyNameArr, bool bGetDefFuncCode) {
    int nCmd = nAccelCmd & 0xff;
    int nSts = (nAccelCmd >> 8) & 0xff;
    return GetFuncCodeAt(pKeyNameArr[nCmd], nSts, bGetDefFuncCode);
}

class CMenuDrawer {
public:
    CMenuDrawer();
};

CMenuDrawer::CMenuDrawer() {
    static const int tbd[] = {
        /* 224 */ F_DISABLE,
        /* 225 */ F_SEARCH_NEXT,
        /* 226 */ F_SEARCH_PREV,
        /* 227 */ F_GREP,
    };
}

class CViewCommander {
public:
    bool HandleCommand(EFunctionCode nCommand);
    void Command_SEARCH_NEXT();
    void Command_SEARCH_PREV();
    void Command_GREP();
};

bool CViewCommander::HandleCommand(EFunctionCode nCommand) {
    switch (nCommand) {
    case F_SEARCH_NEXT: Command_SEARCH_NEXT(); break;
    case F_SEARCH_PREV: Command_SEARCH_PREV(); break;
    case F_GREP: Command_GREP(); break;
    default: break;
    }
    return true;
}

void CViewCommander::Command_SEARCH_NEXT() {}
void CViewCommander::Command_SEARCH_PREV() {}
void CViewCommander::Command_GREP() {}

class CMainWindow {
public:
    bool OnCommand(unsigned long wParam, CViewCommander& commander) {
        EFunctionCode nCommand = static_cast<EFunctionCode>(wParam & 0xffff);
        return commander.HandleCommand(nCommand);
    }
};

}
