#pragma once
#include <string>
#include <vector>

namespace sakura {
using WCHAR = wchar_t;
using BOOL = int;
constexpr int _MAX_PATH = 260;

struct StringBufferW {
    explicit StringBufferW(WCHAR* buffer) {}
};

struct WindowSetting {
    WCHAR m_szLanguageDll[128];
};
struct OtherSetting {
    bool m_bIniReadOnly;
};
struct CommonSetting {
    WindowSetting m_sWindow;
    OtherSetting m_sOthers;
};
struct EditInfo {
    int m_nCharCode;
    WCHAR m_szPath[260];
};
struct HistorySetting {
    int m_nMRUArrNum;
    EditInfo m_fiMRUArr[4];
};
struct DLLSHAREDATA {
    CommonSetting m_Common;
    HistorySetting m_sHistory;
};

DLLSHAREDATA& GetDllShareData();
bool fexist(const WCHAR* path);
std::wstring GetExeFileName();
std::wstring GetIniFileName();
void CopyFile(const WCHAR* from, const WCHAR* to, BOOL failIfExists);

class CDataProfile {
public:
    void SetReadingMode();
    void SetWritingMode();
    bool IsReadingMode();
    bool ReadProfile(const WCHAR* path);
    void WriteProfile(const WCHAR* path, const WCHAR* comment);
    bool IOProfileData(const WCHAR* section, const WCHAR* key, int& value);
    bool IOProfileData(const WCHAR* section, const WCHAR* key, StringBufferW value);
};

class CSelectLang {
public:
    static void ChangeLang(const WCHAR* dllName);
};

class CShareData {
public:
    static CShareData* getInstance();
    void ConvertLangValues(std::vector<std::wstring>& values, bool toInternal);
    void RefreshString();
};

class CShareData_IO {
public:
    bool LoadShareData();
    void SaveShareData();
    bool ShareData_IO_2(bool bRead);
    void ShareData_IO_Mru(CDataProfile& profile);
    void ShareData_IO_Common(CDataProfile& profile);
};

std::wstring GetIniFileNameForIO(bool bWrite);
}
