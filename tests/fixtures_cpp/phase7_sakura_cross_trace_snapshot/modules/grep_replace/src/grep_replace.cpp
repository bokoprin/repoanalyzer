#include "grep_replace_api.h"

namespace sakura {
int CEol::GetLen() const { return 0; }
const void* CMemory::GetRawPtr() const { return nullptr; }
int CMemory::GetRawLength() const { return 0; }
const WCHAR* CNativeW::GetStringPtr() const { return nullptr; }
int CNativeW::GetStringLength() const { return 0; }
void CNativeW::SetString(const WCHAR* text, int length) {}
void CNativeW::AppendString(const WCHAR* text, int length) {}
void CNativeW::AppendNativeData(const CNativeW& text) {}
const WCHAR* CSearchAgent::SearchString(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern) { return nullptr; }
const WCHAR* CSearchAgent::SearchStringWord(const WCHAR* pLine, int nLineLen, int nIdxPos, const CSearchStringPattern& pattern) { return nullptr; }
int CBregexp::Replace(const WCHAR* pLine, int nLineLen, int nIndex) { return 0; }
bool CBregexp::Match(const WCHAR* pLine, int nLineLen, int nIndex) { return false; }
int CBregexp::GetIndex() const { return 0; }
int CBregexp::GetMatchLen() const { return 0; }
const WCHAR* CBregexp::GetString() const { return nullptr; }
int CBregexp::GetStringLen() const { return 0; }
void CCodeBase::UnicodeToCode(const CNativeW& source, CMemory* dest) {}
CCodeBase* CCodeFactory::CreateCodeBase(ECodeType code, int flags) { return nullptr; }
CBinaryOutputStream::CBinaryOutputStream(const WCHAR* path, bool overwrite) {}
void CBinaryOutputStream::Write(const void* data, int length) {}
void CBinaryOutputStream::Close() {}
CFileLoad::CFileLoad(int encoding) {}
ECodeType CFileLoad::FileOpen(const WCHAR* path, bool bigFile, int charset, int flags, bool* bom) { return 0; }
bool CFileLoad::ReadLine(CNativeW* buffer, CEol* eol) { return false; }
int CFileLoad::GetFileSize() const { return 0; }
int CFileLoad::GetPercent() const { return 0; }
void CFileLoad::FileClose() {}
bool CDocTypeManager::GetTypeConfigMini(const WCHAR* path, const STypeConfigMini** type) { return true; }
CEditWnd* CEditWnd::getInstance() { return nullptr; }
void CEditWnd::SetDrawSwitchOfAllViews(bool enabled) {}
void CGrepAgent::SetGrepResult(CNativeW& cmemMessage, const WCHAR* pszFilePath, LONGLONG nLine, int nColumn) {}

class CWriteData {
public:
    CWriteData(int& hit, const WCHAR* name_, ECodeType code_, bool bBom_, bool bOldSave_, CNativeW& message) {}
    void AppendBuffer(const CNativeW& strLine) { OutputHead(); Output(strLine); }
    void OutputHead() { out = new CBinaryOutputStream(fileName, true); out->Write(nullptr, 0); }
    void Output(const CNativeW& strLine) { CMemory dest; pcCodeBase->UnicodeToCode(strLine, &dest); out->Write(dest.GetRawPtr(), dest.GetRawLength()); }
    void Close() { out->Close(); }
private:
    int& nHitCount;
    const WCHAR* fileName;
    CBinaryOutputStream* out;
    std::unique_ptr<CCodeBase> pcCodeBase;
    CNativeW& memMessage;
};

int CGrepAgent::DoGrepReplaceFile(
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
) {
    int nHitCount = 0;
    const STypeConfigMini* type = nullptr;
    if (!CDocTypeManager().GetTypeConfigMini(pszFile, &type)) {
        return -1;
    }
    CFileLoad cfl(type->m_encoding);
    bool bBom = false;
    ECodeType nCharCode = cfl.FileOpen(pszFullPath, true, sGrepOption.nGrepCharSet, 0, &bBom);
    CWriteData output(nHitCount, pszFullPath, nCharCode, bBom, sGrepOption.bGrepBackup, cmemMessage);
    CEol cEol;
    CNativeW cOutBuffer;
    while (cfl.ReadLine(&cUnicodeBuffer, &cEol)) {
        const WCHAR* pLine = cUnicodeBuffer.GetStringPtr();
        int nLineLen = cUnicodeBuffer.GetStringLength();
        cOutBuffer.SetString(L"", 0);
        if (sSearchOption.bRegularExp) {
            if (pRegexp->Replace(pLine, nLineLen, 0) || pRegexp->Match(pLine, nLineLen, 0)) {
                output.OutputHead();
                SetGrepResult(cmemMessage, pszFullPath, 1, pRegexp->GetIndex() + 1);
                cOutBuffer.AppendNativeData(cmGrepReplace);
            }
        } else if (sSearchOption.bWordOnly) {
            const WCHAR* pszRes = CSearchAgent::SearchStringWord(pLine, nLineLen, 0, pattern);
            if (pszRes) {
                output.OutputHead();
                cOutBuffer.AppendNativeData(cmGrepReplace);
            }
        } else {
            const WCHAR* pszRes = CSearchAgent::SearchString(pLine, nLineLen, 0, pattern);
            if (pszRes) {
                output.OutputHead();
                SetGrepResult(cmemMessage, pszFullPath, 1, 1);
                cOutBuffer.AppendNativeData(cmGrepReplace);
            }
        }
        output.AppendBuffer(cOutBuffer);
        CEditWnd::getInstance()->SetDrawSwitchOfAllViews(true);
    }
    cfl.FileClose();
    output.Close();
    return nHitCount;
}
}
