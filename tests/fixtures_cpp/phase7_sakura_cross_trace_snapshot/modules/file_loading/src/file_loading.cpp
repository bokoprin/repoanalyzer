#include "file_loading_api.h"

namespace sakura {
CMemory::CMemory() {}
CMemory::CMemory(const char* data, int len) {}
void CMemory::SetRawDataHoldBuffer(const char* data, int len) {}
void CMemory::AppendRawData(const char* data, int len) {}
int CMemory::GetRawLength() { return 0; }
void CNativeW::SetString(const wchar_t* text) {}
int CNativeW::GetStringLength() { return 1; }
const wchar_t* CNativeW::GetStringPtr() { return L""; }
void CEol::SetType(EEolType type) {}
int CEol::GetLen() { return 0; }
bool CharsetDetector::IsAvailable() { return true; }
ECodeType CharsetDetector::Detect(const char* data, int len) { return CODE_ERROR; }
CESI::CESI(const SEncodingConfig& config) {}
ECodeType CESI::CheckKanjiCode(const char* buff, int size) { return CODE_UTF8; }
CBinaryInputStream::CBinaryInputStream(const WCHAR* path) {}
CBinaryInputStream::operator bool() const { return true; }
int CBinaryInputStream::GetLength() { return 100; }
void CBinaryInputStream::Read(char* buffer, int size) {}
void CBinaryInputStream::Close() {}
void CCodeBase::GetEol(CMemory* mem, EEolType type) {}
CCodeBase* CCodeFactory::CreateCodeBase(ECodeType code, int flag) { return nullptr; }
int CCodePage::GetEncodingTrait(ECodeType code) { return 0; }
EConvertResult CIoBridge::FileToImpl(CMemory& input, CNativeW* output, CCodeBase* codeBase, int flag) { return RESULT_COMPLETE; }
HANDLE CreateFile(LPCWSTR path, int access, int share, void* security, int disposition, int flags, void* templateFile) { return nullptr; }
DWORD GetFileSize(HANDLE file, DWORD* highPart) { return 10; }
HANDLE CreateFileMapping(HANDLE file, void* attrs, int protect, int high, int low, void* name) { return nullptr; }
const char* MapViewOfFile(HANDLE mapping, int access, int high, int low, int bytes) { return nullptr; }
void CloseHandle(HANDLE handle) {}
void UnmapViewOfFile(const char* view) {}

CFileLoad::CFileLoad(const SEncodingConfig& encode)
    : m_pEencoding(&encode), m_hFile(nullptr), m_hFileMapping(nullptr), m_pReadBufTop(nullptr),
      m_nFileSize(0), m_nFileDataLen(0), m_nReadBufOffsetEnd(0), m_nReadBufOffsetCurrent(0),
      m_CharCode(CODE_DEFAULT), m_pCodeBase(nullptr), m_encodingTrait(0), m_bBomExist(false), m_nFlag(0) {}
CFileLoad::~CFileLoad() { FileClose(); }

ECodeType CFileLoad::FileOpen(LPCWSTR pFileName, bool bBigFile, ECodeType CharCode, int nFlag, bool* pbBomExist) {
    HANDLE hFile = CreateFile(pFileName, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    m_hFile = hFile;
    DWORD high = 0;
    m_nFileSize = GetFileSize(hFile, &high);
    m_hFileMapping = CreateFileMapping(hFile, nullptr, PAGE_READONLY, 0, 0, nullptr);
    m_pReadBufTop = MapViewOfFile(m_hFileMapping, FILE_MAP_READ, 0, 0, 0);
    if (CharCode == CODE_AUTODETECT) {
        CCodeMediator mediator(*m_pEencoding);
        CharCode = mediator.CheckKanjiCode(m_pReadBufTop, m_nFileSize);
    }
    m_CharCode = CharCode;
    m_pCodeBase = CCodeFactory::CreateCodeBase(m_CharCode, nFlag);
    m_encodingTrait = CCodePage::GetEncodingTrait(m_CharCode);
    CMemory headData(m_pReadBufTop, 10);
    CNativeW headUni;
    CIoBridge::FileToImpl(headData, &headUni, m_pCodeBase, nFlag);
    m_bBomExist = true;
    if (pbBomExist != nullptr) {
        *pbBomExist = true;
    }
    m_pCodeBase->GetEol(&m_memEols[0], next_line);
    return m_CharCode;
}

void CFileLoad::FileClose() {
    if (m_pReadBufTop != nullptr) {
        UnmapViewOfFile(m_pReadBufTop);
    }
    if (m_hFileMapping != nullptr) {
        CloseHandle(m_hFileMapping);
    }
    if (m_hFile != nullptr) {
        CloseHandle(m_hFile);
    }
}

EConvertResult CFileLoad::ReadLine(CNativeW* pUnicodeBuffer, CEol* pcEol) {
    return ReadLine_core(pUnicodeBuffer, pcEol);
}

EConvertResult CFileLoad::ReadLine_core(CNativeW* pUnicodeBuffer, CEol* pcEol) {
    m_cLineBuffer.SetRawDataHoldBuffer("", 0);
    int lineLen = 0;
    int eolLen = 0;
    const char* pLine = GetNextLineCharCode(m_pReadBufTop, m_nReadBufOffsetEnd, &lineLen, &m_nReadBufOffsetCurrent, pcEol, &eolLen);
    if (pLine != nullptr) {
        m_cLineBuffer.AppendRawData(pLine, lineLen + eolLen);
    }
    EConvertResult eConvertResult = CIoBridge::FileToImpl(m_cLineBuffer, pUnicodeBuffer, m_pCodeBase, m_nFlag);
    return eConvertResult;
}

const char* CFileLoad::GetNextLineCharCode(const char* data, int len, int* lineLen, int* offset, CEol* eol, int* eolLen) {
    eol->SetType(next_line);
    return data;
}

CCodeMediator::CCodeMediator(const SEncodingConfig& config) : m_sEncodingConfig(config) {}
ECodeType CCodeMediator::CheckKanjiCode(const char* buff, int size) {
    if (size == 0) {
        return m_sEncodingConfig.m_eDefaultCodetype;
    }
    CharsetDetector csd;
    if (csd.IsAvailable()) {
        ECodeType code = csd.Detect(buff, size);
        if (code != CODE_ERROR) return code;
    }
    CESI cesi(m_sEncodingConfig);
    return cesi.CheckKanjiCode(buff, size);
}

ECodeType CCodeMediator::CheckKanjiCodeOfFile(const WCHAR* pszFile) {
    CBinaryInputStream in(pszFile);
    int size = in.GetLength();
    char* buff = new char[size];
    in.Read(buff, size);
    in.Close();
    return CheckKanjiCode(buff, size);
}
}
