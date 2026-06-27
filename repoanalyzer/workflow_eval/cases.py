from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WorkflowCase:
    id: str
    question: str
    answer_text: str | None = None
    expected: dict[str, Any] = field(default_factory=dict)


def load_workflow_cases(path: str | Path) -> list[WorkflowCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("cases", [])
    cases: list[WorkflowCase] = []
    for item in raw:
        cases.append(
            WorkflowCase(
                id=str(item["id"]),
                question=str(item.get("question") or ""),
                answer_text=item.get("answer_text"),
                expected=dict(item.get("expected") or {}),
            )
        )
    return cases
