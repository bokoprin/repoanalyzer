from __future__ import annotations

import re

from repoanalyzer.models import ScannedFile, SymbolRecord

_FIELD_DECL_RE = re.compile(
    r"^\s*(?:const\s+)?(?:struct\s+|class\s+)?([A-Za-z_][A-Za-z0-9_:<>*&\s]*)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:[;=,\[])"
)
_FIELD_ACCESS_RE = re.compile(r"(?:->|\.)([A-Za-z_][A-Za-z0-9_]*)")
_SETTING_HINT_RE = re.compile(
    r"(setting|option|config|sharedata|commonsetting|searchoption|replaceoption)",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(r"\b(struct|class)\s+([A-Za-z_][A-Za-z0-9_:]*)")


def infer_file_role_v2(path: str) -> str:
    lowered = path.replace("\\", "/").lower()
    if lowered.startswith(("externals/", "vendor/")):
        return "external"
    if lowered.startswith(("tests/", "test/")):
        return "test"
    if lowered.startswith(("docs/", "help/")) or lowered.endswith((".md", ".txt", ".html", ".khp")):
        return "doc"
    if lowered.endswith((".h", ".hpp", ".hh", ".hxx")):
        return "header"
    if lowered.endswith((".cpp", ".cc", ".cxx", ".c", ".py", ".cs", ".java", ".ts", ".js")):
        return "source"
    if any(token in lowered for token in ("config", "setting", "option")):
        return "config"
    return "unknown"


def extract_field_accesses_v2(
    scanned_file: ScannedFile,
    symbols: list[SymbolRecord],
) -> list[tuple[str, str, int, str, str, str]]:
    lines = scanned_file.text.splitlines()
    owner_by_line = _owner_ranges(lines=lines, symbols=symbols)
    rows: list[tuple[str, str, int, str, str, str]] = []
    for line_no, line in enumerate(lines, start=1):
        owner_type = owner_by_line.get(line_no, "")
        decl_match = _FIELD_DECL_RE.match(line)
        if decl_match:
            field_name = decl_match.group(2)
            if _looks_like_setting_field(field_name, owner_type, line):
                rows.append(
                    (
                        field_name,
                        owner_type,
                        line_no,
                        "declaration",
                        _nearest_symbol_name(symbols, line_no),
                        line.strip()[:240],
                    )
                )
        for match in _FIELD_ACCESS_RE.finditer(line):
            field_name = match.group(1)
            if not _looks_like_setting_field(field_name, owner_type, line):
                continue
            rows.append(
                (
                    field_name,
                    owner_type,
                    line_no,
                    _classify_access_kind(line=line, field_name=field_name),
                    _nearest_symbol_name(symbols, line_no),
                    line.strip()[:240],
                )
            )
    return _dedupe_rows(rows)


def extract_config_relations_v2(
    scanned_file: ScannedFile,
    field_accesses: list[tuple[str, str, int, str, str, str]],
) -> list[tuple[str, str, int, str, float, str]]:
    del scanned_file
    rows: list[tuple[str, str, int, str, float, str]] = []
    for field_name, owner_type, line, access_kind, symbol_name, context in field_accesses:
        relation_kind = _relation_kind_for_access(access_kind)
        confidence = 0.55
        lowered = f"{field_name} {owner_type} {context}".lower()
        if _SETTING_HINT_RE.search(lowered):
            confidence += 0.2
        if field_name.lower().startswith(("m_", "s_")):
            confidence += 0.1
        key_or_type = owner_type or field_name
        rows.append(
            (
                key_or_type,
                relation_kind,
                line,
                symbol_name,
                min(confidence, 0.99),
                context,
            )
        )
    return rows


def make_snippet_spans_v2(
    path: str,
    symbols: list[SymbolRecord],
    field_accesses: list[tuple[str, str, int, str, str, str]],
    config_relations: list[tuple[str, str, int, str, float, str]],
    call_edges: list[tuple[str, str, int, str]],
) -> list[tuple[str, str, int, int, int]]:
    rows: list[tuple[str, str, int, int, int]] = []
    for symbol in symbols:
        key = f"{symbol.kind}:{symbol.name}:{symbol.start_line}"
        rows.append(
            (
                "symbol",
                key,
                symbol.start_line,
                max(symbol.end_line, symbol.start_line),
                symbol.start_line,
            )
        )
    for field_name, owner_type, line, access_kind, _symbol_name, _context in field_accesses:
        key = f"field:{owner_type}:{field_name}:{access_kind}:{line}"
        rows.append(("field_access", key, line, line, line))
    for config_key, relation_kind, line, symbol_name, _confidence, _context in config_relations:
        key = f"config:{config_key}:{relation_kind}:{symbol_name}:{line}"
        rows.append(("config_relation", key, line, line, line))
    for caller, callee, line, kind in call_edges:
        key = f"call:{caller}:{callee}:{kind}:{line}"
        rows.append(("call_edge", key, line, line, line))
    return rows


def _owner_ranges(lines: list[str], symbols: list[SymbolRecord]) -> dict[int, str]:
    owner_by_line: dict[int, str] = {}
    current_owner = ""
    brace_depth = 0
    for line_no, line in enumerate(lines, start=1):
        match = _OWNER_RE.search(line)
        if match:
            current_owner = match.group(2)
        brace_depth += line.count("{")
        if current_owner:
            owner_by_line[line_no] = current_owner
        brace_depth -= line.count("}")
        if brace_depth <= 0 and "}" in line:
            current_owner = ""
    for symbol in symbols:
        if symbol.kind in {"class", "type", "struct"}:
            for line_no in range(symbol.start_line, max(symbol.end_line, symbol.start_line) + 1):
                owner_by_line.setdefault(line_no, symbol.name)
    return owner_by_line


def _nearest_symbol_name(symbols: list[SymbolRecord], line_no: int) -> str:
    current = ""
    for symbol in symbols:
        if symbol.start_line > line_no:
            break
        current = symbol.name
        if symbol.start_line <= line_no <= max(symbol.end_line, symbol.start_line):
            return symbol.name
    return current


def _looks_like_setting_field(field_name: str, owner_type: str, context: str) -> bool:
    lowered = f"{field_name} {owner_type} {context}".lower()
    if field_name.startswith(("m_", "s_")):
        return True
    return _SETTING_HINT_RE.search(lowered) is not None


def _classify_access_kind(*, line: str, field_name: str) -> str:
    lowered = line.lower()
    if re.search(rf"(?:->|\\.){re.escape(field_name)}\s*=", line):
        return "write"
    if "return" in lowered and field_name.lower() in lowered:
        return "return"
    if any(token in lowered for token in ("apply", "set", "copy", "reflect", "sync", "update")):
        return "apply"
    if any(token in lowered for token in ("load", "read", "use", "get")):
        return "read"
    return "read"


def _relation_kind_for_access(access_kind: str) -> str:
    if access_kind == "declaration":
        return "storage"
    if access_kind in {"write", "apply"}:
        return "apply"
    return "read"


def _dedupe_rows(
    rows: list[tuple[str, str, int, str, str, str]],
) -> list[tuple[str, str, int, str, str, str]]:
    seen: set[tuple[str, str, int, str]] = set()
    deduped: list[tuple[str, str, int, str, str, str]] = []
    for row in rows:
        key = (row[0], row[1], row[2], row[3])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
