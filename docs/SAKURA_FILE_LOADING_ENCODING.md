# Sakura file loading / encoding evidence

This phase adds deterministic evidence for Sakura-Editor-style file loading and
character encoding detection.  The goal is not to emulate Sakura's file I/O, but
to expose enough structured evidence for an LLM to safely explain the flow:

```text
CFileLoad::FileOpen
  -> CreateFile / GetFileSize
  -> CreateFileMapping / MapViewOfFile
  -> CCodeMediator::CheckKanjiCode when CODE_AUTODETECT is selected
  -> CCodeFactory::CreateCodeBase
  -> CCodePage::GetEncodingTrait
  -> BOM / encoded EOL setup

CFileLoad::ReadLine_core
  -> GetNextLineCharCode
  -> CIoBridge::FileToImpl

CCodeMediator::CheckKanjiCode
  -> CharsetDetector::Detect
  -> CESI::CheckKanjiCode fallback
```

## Semantic relations

The lightweight C/C++ analyzer now emits relation facts for the following roles:

- `opens_file`
- `reads_file_size`
- `maps_file_buffer`
- `detects_character_encoding`
- `uses_encoding_detector`
- `creates_encoding_converter`
- `determines_encoding_trait`
- `converts_file_to_internal_encoding`
- `reads_file_line`
- `scans_line_boundary`
- `configures_eol_detection`
- `closes_file`
- `checks_autodetect_requested`
- `stores_detected_encoding`
- `tracks_bom_status`

These are semantic evidence relations.  They should not be described as
unconditional runtime calls when they represent state checks or assignments such
as `CharCode == CODE_AUTODETECT`, `m_CharCode = CharCode`, or BOM status writes.

## Query

The evidence collector recognizes questions such as:

```text
ファイル読み込み・文字コード判定はどう行われる？
```

It returns a `file_loading_encoding` bundle with three trace kinds:

- `file_open_encoding_trace`
- `line_read_conversion_trace`
- `encoding_detector_trace`

