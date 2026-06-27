#pragma once
#include <memory>

namespace sakura {
using WCHAR = wchar_t;
using ECodeType = int;
using LONGLONG = long long;

struct CEol { int GetLen() const; };
struct SSearchOption { bool bRegularExp; bool bWordOnly; bool bLoHiCase; };
struct SGrepOption { bool bGrepPaste; bool bGrepBackup; bool bGrepOutputFileOnly; int nGrepOutputLineType; int nGrepCharSet; };
struct STypeConfigMini { int m_encoding; };

class CMemory {
public:
    const void* GetRawPtr() const;
    int GetRawLength() const;
};

class CNativeW {
public:
    const WCHAR* GetStringPtr() const;
    int GetStringLength() const;
    void SetString(const WCHAR* text, int length);
    void AppendString(const WCHAR* text, int length);
    void AppendNativeData(const CNativeW& text);
};

class CSearchStringPattern {};

class CSearchAgent {
public:
    static const WCHAR* SearchString(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern);
    static const WCHAR* SearchStringWord(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern);
};

class CBregexp {
public:
    int Replace(const WCHAR* pLine, int nLineLen, int nIndex);
    bool Match(const WCHAR* pLine, int nLineLen, int nIndex);
    int GetIndex() const;
    int GetMatchLen() const;
    const WCHAR* GetString() const;
    int GetStringLen() const;
};

class CCodeBase {
public:
    void UnicodeToCode(const CNativeW& source, CMemory* dest);
};

class CCodeFactory {
public:
    static CCodeBase* CreateCodeBase(ECodeType code, int flags);
};

class CBinaryOutputStream {
public:
    CBinaryOutputStream(const WCHAR* path, bool overwrite);
    void Write(const void* data, int length);
    void Close();
};

class CFileLoad {
public:
    CFileLoad(int encoding);
    ECodeType FileOpen(const WCHAR* path, bool bigFile, int charset, int flags, bool* bom);
    bool ReadLine(CNativeW* buffer, CEol* eol);
    int GetFileSize() const;
    int GetPercent() const;
    void FileClose();
};

class CDocTypeManager {
public:
    bool GetTypeConfigMini(const WCHAR* path, const STypeConfigMini** type);
};

class CEditWnd {
public:
    static CEditWnd* getInstance();
    void SetDrawSwitchOfAllViews(bool enabled);
};

class CGrepAgent {
public:
    int DoGrepReplaceFile(
        const WCHAR* pszKey,
        const CNativeW& cmGrepReplace,
        const WCHAR* pszFile,
        const SSearchOption& sSearchOption,
        const SGrepOption& sGrepOption,
        const CSearchStringPattern& pattern,
        CBregexp* pRegexp,
        int* pnHitCount,
        const WCHAR* pszFullPath,
        CNativeW& cmemMessage,
        CNativeW& cUnicodeBuffer
    );
    void SetGrepResult(CNativeW& cmemMessage, const WCHAR* pszFilePath, LONGLONG nLine, int nColumn);
};
}
