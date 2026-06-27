#pragma once
#include <cstddef>
#include <memory>

namespace sakura {
using LPCWSTR = const wchar_t*;
using WCHAR = wchar_t;
using HANDLE = void*;
using DWORD = unsigned long;
using ULONGLONG = unsigned long long;

constexpr int GENERIC_READ = 1;
constexpr int FILE_SHARE_READ = 2;
constexpr int FILE_SHARE_WRITE = 4;
constexpr int OPEN_EXISTING = 3;
constexpr int FILE_FLAG_SEQUENTIAL_SCAN = 8;
constexpr int PAGE_READONLY = 1;
constexpr int FILE_MAP_READ = 1;
constexpr HANDLE INVALID_HANDLE_VALUE = (HANDLE)-1;

enum ECodeType {
    CODE_ERROR,
    CODE_DEFAULT,
    CODE_AUTODETECT,
    CODE_SJIS,
    CODE_UTF8,
    CP_UTF7
};

enum EConvertResult {
    RESULT_FAILURE,
    RESULT_COMPLETE,
    RESULT_LOSESOME
};

enum EEolType {
    next_line,
    line_separator,
    paragraph_separator
};

struct SEncodingConfig {
    ECodeType m_eDefaultCodetype;
};

class CMemory {
public:
    CMemory();
    CMemory(const char* data, int len);
    void SetRawDataHoldBuffer(const char* data, int len);
    void AppendRawData(const char* data, int len);
    int GetRawLength();
};

class CNativeW {
public:
    void SetString(const wchar_t* text);
    int GetStringLength();
    const wchar_t* GetStringPtr();
};

class CEol {
public:
    void SetType(EEolType type);
    int GetLen();
};

class CharsetDetector {
public:
    bool IsAvailable();
    ECodeType Detect(const char* data, int len);
};

class CESI {
public:
    explicit CESI(const SEncodingConfig& config);
    ECodeType CheckKanjiCode(const char* buff, int size);
};

class CBinaryInputStream {
public:
    explicit CBinaryInputStream(const WCHAR* path);
    explicit operator bool() const;
    int GetLength();
    void Read(char* buffer, int size);
    void Close();
};

class CCodeBase {
public:
    void GetEol(CMemory* mem, EEolType type);
};

class CCodeFactory {
public:
    static CCodeBase* CreateCodeBase(ECodeType code, int flag);
};

class CCodePage {
public:
    static int GetEncodingTrait(ECodeType code);
};

class CIoBridge {
public:
    static EConvertResult FileToImpl(CMemory& input, CNativeW* output, CCodeBase* codeBase, int flag);
};

HANDLE CreateFile(LPCWSTR path, int access, int share, void* security, int disposition, int flags, void* templateFile);
DWORD GetFileSize(HANDLE file, DWORD* highPart);
HANDLE CreateFileMapping(HANDLE file, void* attrs, int protect, int high, int low, void* name);
const char* MapViewOfFile(HANDLE mapping, int access, int high, int low, int bytes);
void CloseHandle(HANDLE handle);
void UnmapViewOfFile(const char* view);

class CFileLoad {
public:
    explicit CFileLoad(const SEncodingConfig& encode);
    ~CFileLoad();
    ECodeType FileOpen(LPCWSTR pFileName, bool bBigFile, ECodeType CharCode, int nFlag, bool* pbBomExist);
    EConvertResult ReadLine(CNativeW* pUnicodeBuffer, CEol* pcEol);
    EConvertResult ReadLine_core(CNativeW* pUnicodeBuffer, CEol* pcEol);
    const char* GetNextLineCharCode(const char* data, int len, int* lineLen, int* offset, CEol* eol, int* eolLen);
    void FileClose();
private:
    const SEncodingConfig* m_pEencoding;
    HANDLE m_hFile;
    HANDLE m_hFileMapping;
    const char* m_pReadBufTop;
    int m_nFileSize;
    int m_nFileDataLen;
    int m_nReadBufOffsetEnd;
    int m_nReadBufOffsetCurrent;
    ECodeType m_CharCode;
    CCodeBase* m_pCodeBase;
    int m_encodingTrait;
    bool m_bBomExist;
    int m_nFlag;
    CMemory m_cLineBuffer;
    CMemory m_memEols[3];
};

class CCodeMediator {
public:
    explicit CCodeMediator(const SEncodingConfig& config);
    ECodeType CheckKanjiCode(const char* buff, int size);
    ECodeType CheckKanjiCodeOfFile(const WCHAR* pszFile);
private:
    SEncodingConfig m_sEncodingConfig;
};
}
