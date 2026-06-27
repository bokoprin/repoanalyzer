from __future__ import annotations

import re

from repoanalyzer.ingest.perl_tree_sitter import extract_perl_definitions_with_tree_sitter
from repoanalyzer.ingest.tree_sitter_common import extract_definitions_with_tree_sitter
from repoanalyzer.models import ScannedFile, SymbolRecord, SymbolReferenceRecord

_DEF_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("), "function"),
    (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\b"), "class"),
    (re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("), "function"),
    (re.compile(r"^\s*(?:struct|enum|interface)\s+([A-Za-z_][A-Za-z0-9_]*)\b"), "type"),
    (
        re.compile(
            r"^\s*[A-Za-z_][A-Za-z0-9_<>\*&:\s]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*\)\s*\{?\s*$",
        ),
        "function",
    ),
    (
        re.compile(
            r"^\s*(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:function|\()",
        ),
        "function",
    ),
    (re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_\-]*)\b", re.IGNORECASE), "function"),
    (
        re.compile(r"^\s*(?:fun|fn|func)\s+([A-Za-z_][A-Za-z0-9_]*)\b"),
        "function",
    ),
]
_PERL_SUB_RE = re.compile(r"^\s*sub\s+([A-Za-z_][A-Za-z0-9_:]*)\b")
_PERL_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z_][A-Za-z0-9_:]*)\b")
_TREE_SITTER_SYMBOL_LANGUAGES = {
    "javascript",
    "typescript",
    "java",
    "csharp",
    "cpp",
    "c",
    "go",
    "rust",
    "php",
    "kotlin",
    "swift",
    "sql",
    "shell",
    "powershell",
}


def extract_symbols(
    scanned_file: ScannedFile,
    perl_tree_sitter: bool = True,
) -> tuple[list[SymbolRecord], list[SymbolReferenceRecord]]:
    if scanned_file.language == "perl":
        return _extract_perl_symbols(scanned_file=scanned_file, perl_tree_sitter=perl_tree_sitter)
    if scanned_file.language in _TREE_SITTER_SYMBOL_LANGUAGES:
        return _extract_tree_sitter_symbols(scanned_file=scanned_file)
    return _extract_generic_symbols(scanned_file=scanned_file)


def _extract_generic_symbols(
    scanned_file: ScannedFile,
) -> tuple[list[SymbolRecord], list[SymbolReferenceRecord]]:
    lines = scanned_file.text.splitlines()
    symbols: list[SymbolRecord] = []
    def_line_map: dict[str, set[int]] = {}

    for line_number, line in enumerate(lines, start=1):
        for pattern, kind in _DEF_PATTERNS:
            matched = pattern.match(line)
            if not matched:
                continue
            name = matched.group(1)
            signature = line.strip()[:200]
            symbols.append(
                SymbolRecord(
                    path=scanned_file.relative_path,
                    name=name,
                    kind=kind,
                    start_line=line_number,
                    end_line=line_number,
                    signature=signature,
                )
            )
            def_line_map.setdefault(name, set()).add(line_number)
            break
    references = _extract_references(
        scanned_file=scanned_file,
        symbols=symbols,
        def_line_map=def_line_map,
    )
    return symbols, references


def _extract_perl_symbols(
    scanned_file: ScannedFile,
    perl_tree_sitter: bool,
) -> tuple[list[SymbolRecord], list[SymbolReferenceRecord]]:
    lines = scanned_file.text.splitlines()
    symbols: list[SymbolRecord] = []
    def_line_map: dict[str, set[int]] = {}

    if perl_tree_sitter:
        for definition in extract_perl_definitions_with_tree_sitter(scanned_file.text):
            signature_line = (
                lines[definition.start_line - 1].strip()[:200]
                if 1 <= definition.start_line <= len(lines)
                else definition.name
            )
            symbols.append(
                SymbolRecord(
                    path=scanned_file.relative_path,
                    name=definition.name,
                    kind=definition.kind,
                    start_line=definition.start_line,
                    end_line=definition.end_line,
                    signature=signature_line,
                )
            )
            def_line_map.setdefault(definition.name, set()).add(definition.start_line)

    for line_number, line in enumerate(lines, start=1):
        for pattern, kind in ((_PERL_SUB_RE, "function"), (_PERL_PACKAGE_RE, "module")):
            matched = pattern.match(line)
            if not matched:
                continue
            name = matched.group(1)
            key = (name, kind, line_number)
            if any(
                symbol.name == key[0] and symbol.kind == key[1] and symbol.start_line == key[2]
                for symbol in symbols
            ):
                break
            symbols.append(
                SymbolRecord(
                    path=scanned_file.relative_path,
                    name=name,
                    kind=kind,
                    start_line=line_number,
                    end_line=line_number,
                    signature=line.strip()[:200],
                )
            )
            def_line_map.setdefault(name, set()).add(line_number)
            break

    symbols.sort(key=lambda item: (item.start_line, item.end_line, item.name))
    references = _extract_references(
        scanned_file=scanned_file,
        symbols=symbols,
        def_line_map=def_line_map,
    )
    return symbols, references


def _extract_tree_sitter_symbols(
    scanned_file: ScannedFile,
) -> tuple[list[SymbolRecord], list[SymbolReferenceRecord]]:
    lines = scanned_file.text.splitlines()
    symbols: list[SymbolRecord] = []
    def_line_map: dict[str, set[int]] = {}

    for definition in extract_definitions_with_tree_sitter(
        text=scanned_file.text,
        language=scanned_file.language,
    ):
        signature_line = (
            lines[definition.start_line - 1].strip()[:200]
            if 1 <= definition.start_line <= len(lines)
            else definition.name
        )
        symbols.append(
            SymbolRecord(
                path=scanned_file.relative_path,
                name=definition.name,
                kind=definition.kind,
                start_line=definition.start_line,
                end_line=definition.end_line,
                signature=signature_line,
            )
        )
        def_line_map.setdefault(definition.name, set()).add(definition.start_line)

    for line_number, line in enumerate(lines, start=1):
        for pattern, kind in _DEF_PATTERNS:
            matched = pattern.match(line)
            if not matched:
                continue
            name = matched.group(1)
            if any(
                symbol.name == name and symbol.kind == kind and symbol.start_line == line_number
                for symbol in symbols
            ):
                break
            symbols.append(
                SymbolRecord(
                    path=scanned_file.relative_path,
                    name=name,
                    kind=kind,
                    start_line=line_number,
                    end_line=line_number,
                    signature=line.strip()[:200],
                )
            )
            def_line_map.setdefault(name, set()).add(line_number)
            break

    symbols.sort(key=lambda item: (item.start_line, item.end_line, item.kind, item.name))
    references = _extract_references(
        scanned_file=scanned_file,
        symbols=symbols,
        def_line_map=def_line_map,
    )
    return symbols, references


def _extract_references(
    scanned_file: ScannedFile,
    symbols: list[SymbolRecord],
    def_line_map: dict[str, set[int]],
) -> list[SymbolReferenceRecord]:
    lines = scanned_file.text.splitlines()
    references: list[SymbolReferenceRecord] = []
    symbol_names = sorted({symbol.name for symbol in symbols})
    if not symbol_names:
        return references

    compiled_names = {
        name: _compile_reference_pattern(name)
        for name in symbol_names
    }
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        for name in symbol_names:
            if line_number in def_line_map.get(name, set()):
                continue
            if compiled_names[name].search(line):
                references.append(
                    SymbolReferenceRecord(
                        path=scanned_file.relative_path,
                        name=name,
                        line=line_number,
                        context=stripped[:200],
                    )
                )
    return references


def _compile_reference_pattern(name: str) -> re.Pattern[str]:
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return re.compile(rf"\b{re.escape(name)}\b")
    return re.compile(re.escape(name))


def build_symbol_aliases(
    scanned_file: ScannedFile,
    symbols: list[SymbolRecord],
) -> list[tuple[str, str, str, int]]:
    scope = (
        scanned_file.relative_path.rsplit("/", 1)[0]
        if "/" in scanned_file.relative_path
        else "."
    )
    aliases: list[tuple[str, str, str, int]] = []
    seen: set[tuple[str, str, str, int]] = set()

    for symbol in symbols:
        normalized = normalize_symbol_name(symbol.name, scanned_file.language)
        _append_alias(
            aliases=aliases,
            seen=seen,
            raw_name=symbol.name,
            normalized_name=normalized,
            scope=scope,
            line=symbol.start_line,
        )
        if "." in normalized:
            short_name = normalized.rsplit(".", 1)[-1]
            _append_alias(
                aliases=aliases,
                seen=seen,
                raw_name=short_name,
                normalized_name=normalized,
                scope=scope,
                line=symbol.start_line,
            )
    return aliases


def normalize_symbol_name(name: str, language: str) -> str:
    normalized = name.strip()
    if not normalized:
        return normalized
    if language == "perl":
        normalized = re.sub(r"^[\$\@\%]+", "", normalized)
    normalized = normalized.replace("::", ".")
    normalized = normalized.replace("/", ".")
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"\.{2,}", ".", normalized).strip(".")
    return normalized or name.strip()


def _append_alias(
    aliases: list[tuple[str, str, str, int]],
    seen: set[tuple[str, str, str, int]],
    raw_name: str,
    normalized_name: str,
    scope: str,
    line: int,
) -> None:
    record = (raw_name, normalized_name, scope, line)
    if record in seen:
        return
    seen.add(record)
    aliases.append(record)
