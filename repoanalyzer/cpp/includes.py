from __future__ import annotations

import re

from repoanalyzer.core.models import CodeFact

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+[<"](?P<target>[^>"]+)[>"]')


def extract_includes(path: str, text: str) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _INCLUDE_RE.match(line)
        if not m:
            continue
        target = m.group("target")
        facts.append(
            CodeFact(
                fact_type="include",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=path,
                predicate="includes",
                object=target,
                confidence="medium",
                source="regex_cpp_minimal",
                payload={"target": target},
            )
        )
    return facts
