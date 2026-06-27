from __future__ import annotations

import re
from dataclasses import dataclass

from repoanalyzer.core.models import CodeFact

_FUNCTION_RE = re.compile(
    r"^\s*(?:template\s*<[^>]+>\s*)?"
    r"(?:(?:inline|static|constexpr|virtual|extern)\s+)*"
    r"(?P<ret>[A-Za-z_][\w:<>,~*&\s]*?)\s+"
    r"(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*"
    r"\([^;{}()]*\)\s*(?P<tail>[{;])?\s*$"
)

_CONTROL_WORDS = {"if", "for", "while", "switch", "catch", "return", "sizeof", "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast"}
_CALL_RE = re.compile(r"\b(?P<name>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\(")


@dataclass(frozen=True)
class FunctionRegion:
    name: str
    path: str
    start_line: int
    end_line: int
    declaration_or_definition: str


def _brace_delta(line: str) -> int:
    # Good enough for fixture-scale code. The parser is intentionally simple.
    return line.count("{") - line.count("}")


def extract_function_regions(path: str, text: str) -> list[FunctionRegion]:
    lines = text.splitlines()
    regions: list[FunctionRegion] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _FUNCTION_RE.match(line)
        if not m:
            i += 1
            continue
        name = m.group("name")
        short_name = name.split("::")[-1]
        if short_name in _CONTROL_WORDS:
            i += 1
            continue
        tail = m.group("tail")
        if tail == ";":
            regions.append(FunctionRegion(short_name, path, i + 1, i + 1, "declaration"))
            i += 1
            continue
        if tail == "{" or (i + 1 < len(lines) and lines[i + 1].strip().startswith("{")):
            start = i + 1
            depth = _brace_delta(line)
            j = i + 1
            if depth <= 0 and j < len(lines) and lines[j].strip().startswith("{"):
                depth += _brace_delta(lines[j])
                j += 1
            while j < len(lines) and depth > 0:
                depth += _brace_delta(lines[j])
                j += 1
            end = max(start, j)
            regions.append(FunctionRegion(short_name, path, start, end, "definition"))
            i = max(i + 1, j)
            continue
        i += 1
    return regions


def extract_symbols(path: str, text: str) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for region in extract_function_regions(path, text):
        facts.append(
            CodeFact(
                fact_type="symbol",
                path=path,
                start_line=region.start_line,
                end_line=region.end_line,
                symbol=region.name,
                qualified_name=region.name,
                kind="function",
                subject=region.name,
                predicate=region.declaration_or_definition,
                object="function",
                confidence="high" if region.declaration_or_definition == "definition" else "medium",
                source="regex_cpp_minimal",
                payload={"declaration_or_definition": region.declaration_or_definition},
            )
        )
    return facts


def extract_references_and_calls(path: str, text: str) -> list[CodeFact]:
    lines = text.splitlines()
    regions = extract_function_regions(path, text)
    facts: list[CodeFact] = []
    definition_lines = {r.start_line for r in regions}
    for region in regions:
        if region.declaration_or_definition != "definition":
            continue
        for lineno in range(region.start_line, region.end_line + 1):
            if lineno in definition_lines:
                continue
            if lineno < 1 or lineno > len(lines):
                continue
            line = lines[lineno - 1]
            for m in _CALL_RE.finditer(line):
                callee = m.group("name").split("::")[-1]
                if callee in _CONTROL_WORDS:
                    continue
                if callee == region.name:
                    # recursive call is still useful, but keep it explicit.
                    pass
                fact = CodeFact(
                    fact_type="call",
                    path=path,
                    start_line=lineno,
                    end_line=lineno,
                    caller=region.name,
                    callee=callee,
                    call_kind="direct",
                    subject=region.name,
                    predicate="calls",
                    object=callee,
                    confidence="high",
                    source="regex_cpp_minimal",
                )
                facts.append(fact)
                facts.append(
                    CodeFact(
                        fact_type="reference",
                        path=path,
                        start_line=lineno,
                        end_line=lineno,
                        symbol=callee,
                        subject=region.name,
                        predicate="references",
                        object=callee,
                        confidence="medium",
                        source="regex_cpp_minimal",
                        payload={"reference_kind": "call"},
                    )
                )
    return facts
