#include "config_profile_api.h"

namespace sakura {
static DLLSHAREDATA g_share;
DLLSHAREDATA& GetDllShareData() { return g_share; }
bool fexist(const WCHAR* path) { return true; }
std::wstring GetExeFileName() { return L"sakura.exe"; }
std::wstring GetIniFileName() { return L"user/sakura.ini"; }
void CopyFile(const WCHAR* from, const WCHAR* to, BOOL failIfExists) {}
void CDataProfile::SetReadingMode() {}
void CDataProfile::SetWritingMode() {}
bool CDataProfile::IsReadingMode() { return true; }
bool CDataProfile::ReadProfile(const WCHAR* path) { return true; }
void CDataProfile::WriteProfile(const WCHAR* path, const WCHAR* comment) {}
bool CDataProfile::IOProfileData(const WCHAR* section, const WCHAR* key, int& value) { return true; }
bool CDataProfile::IOProfileData(const WCHAR* section, const WCHAR* key, StringBufferW value) { return true; }
void CSelectLang::ChangeLang(const WCHAR* dllName) {}
CShareData* CShareData::getInstance() { static CShareData inst; return &inst; }
void CShareData::ConvertLangValues(std::vector<std::wstring>& values, bool toInternal) {}
void CShareData::RefreshString() {}

std::wstring GetIniFileNameForIO(bool bWrite) {
    std::wstring iniPath = GetExeFileName();
    std::wstring privateIniPath = GetIniFileName();
    if (bWrite || fexist(privateIniPath.c_str())) {
        return privateIniPath;
    }
    return iniPath;
}

bool CShareData_IO::LoadShareData() {
    return ShareData_IO_2(true);
}

void CShareData_IO::SaveShareData() {
    ShareData_IO_2(false);
}

bool CShareData_IO::ShareData_IO_2(bool bRead) {
    CShareData* pcShare = CShareData::getInstance();
    CDataProfile cProfile;
    if (bRead) {
        cProfile.SetReadingMode();
    } else {
        cProfile.SetWritingMode();
    }
    std::wstring iniPath = GetIniFileNameForIO(!bRead);
    const WCHAR* szIniFileName = iniPath.c_str();
    if (bRead) {
        if (!cProfile.ReadProfile(szIniFileName)) {
            DLLSHAREDATA* pShareData = &GetDllShareData();
            cProfile.IOProfileData(L"Common", L"szLanguageDll", StringBufferW(pShareData->m_Common.m_sWindow.m_szLanguageDll));
            std::vector<std::wstring> values;
            pcShare->ConvertLangValues(values, true);
            CSelectLang::ChangeLang(pShareData->m_Common.m_sWindow.m_szLanguageDll);
            pcShare->ConvertLangValues(values, false);
            pcShare->RefreshString();
            return false;
        }
        WCHAR backup[260];
        CopyFile(szIniFileName, backup, 0);
    }
    if (bRead) {
        DLLSHAREDATA* pShareData = &GetDllShareData();
        cProfile.IOProfileData(L"Common", L"szLanguageDll", StringBufferW(pShareData->m_Common.m_sWindow.m_szLanguageDll));
        CSelectLang::ChangeLang(pShareData->m_Common.m_sWindow.m_szLanguageDll);
        pcShare->RefreshString();
    }
    ShareData_IO_Mru(cProfile);
    ShareData_IO_Common(cProfile);
    if (!bRead) {
        if (!GetDllShareData().m_Common.m_sOthers.m_bIniReadOnly) {
            cProfile.WriteProfile(szIniFileName, L"sakura.ini settings");
        }
    }
    return true;
}

void CShareData_IO::ShareData_IO_Mru(CDataProfile& cProfile) {
    DLLSHAREDATA* pShare = &GetDllShareData();
    const WCHAR* pszSecName = L"MRU";
    cProfile.IOProfileData(pszSecName, L"_MRU_Counts", pShare->m_sHistory.m_nMRUArrNum);
    for (int i = 0; i < pShare->m_sHistory.m_nMRUArrNum; ++i) {
        cProfile.IOProfileData(pszSecName, L"MRU.nCharCode", pShare->m_sHistory.m_fiMRUArr[i].m_nCharCode);
        cProfile.IOProfileData(pszSecName, L"MRU.szPath", StringBufferW(pShare->m_sHistory.m_fiMRUArr[i].m_szPath));
    }
    if (cProfile.IsReadingMode()) {
        pShare->m_sHistory.m_nMRUArrNum = 0;
    }
}

void CShareData_IO::ShareData_IO_Common(CDataProfile& cProfile) {
    DLLSHAREDATA* pShare = &GetDllShareData();
    cProfile.IOProfileData(L"Common", L"szLanguageDll", StringBufferW(pShare->m_Common.m_sWindow.m_szLanguageDll));
    cProfile.IOProfileData(L"Common", L"bIniReadOnly", (int&)pShare->m_Common.m_sOthers.m_bIniReadOnly);
}
}
