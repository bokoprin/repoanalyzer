from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class EvidenceCase:
    id: str
    question: str
    mode: str | None = None
    expected: dict[str, Any] = field(default_factory=dict)
    answerability: str | None = None
    required_unknowns: list[str] = field(default_factory=list)


def load_cases(path: str | Path) -> list[EvidenceCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("cases", [])
    cases: list[EvidenceCase] = []
    for item in raw:
        cases.append(
            EvidenceCase(
                id=str(item["id"]),
                question=str(item["question"]),
                mode=item.get("mode"),
                expected=item.get("expected", {}) or {},
                answerability=item.get("answerability"),
                required_unknowns=list(item.get("required_unknowns", []) or []),
            )
        )
    return cases
