from __future__ import annotations

import re

from repoanalyzer.models import ScannedFile, SymbolRecord

_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_:.]*)\s*\(")
_SKIP_CALLEES = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "new",
    "catch",
    "sizeof",
    "print",
}


def extract_call_edges(
    scanned_file: ScannedFile,
    symbols: list[SymbolRecord],
) -> list[tuple[str, str, int, str]]:
    lines = scanned_file.text.splitlines()
    if not lines:
        return []
    function_symbols = [
        symbol
        for symbol in symbols
        if symbol.kind in {"function", "method"} or symbol.kind.startswith("perl-")
    ]
    ranges = sorted(function_symbols, key=lambda item: (item.start_line, item.end_line))

    edges: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, str, int]] = set()
    for line_no, line in enumerate(lines, start=1):
        caller = _resolve_caller(line_no, ranges)
        for match in _CALL_RE.finditer(line):
            callee = match.group(1)
            lowered = callee.lower()
            if lowered in _SKIP_CALLEES:
                continue
            if callee == caller:
                continue
            edge_key = (caller, callee, line_no)
            if edge_key in seen:
                continue
            seen.add(edge_key)
            edges.append((caller, callee, line_no, f"{scanned_file.language}-call"))
    return edges


def _resolve_caller(line_no: int, symbols: list[SymbolRecord]) -> str:
    current: SymbolRecord | None = None
    for symbol in symbols:
        if symbol.start_line > line_no:
            break
        if symbol.start_line <= line_no <= max(symbol.end_line, symbol.start_line):
            return symbol.name
        current = symbol
    if current is not None:
        return current.name
    return "<module>"
