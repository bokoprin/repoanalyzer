from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repoanalyzer.evidence.claims import Claim


@dataclass(frozen=True)
class ClaimCase:
    id: str
    claim: Claim
    verdict: str | None = None
    reason_code: str | None = None
    expected: dict[str, Any] = field(default_factory=dict)


def load_claim_cases(path: str | Path) -> list[ClaimCase]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get("cases", [])
    cases: list[ClaimCase] = []
    for item in raw:
        cases.append(
            ClaimCase(
                id=str(item["id"]),
                claim=Claim.from_dict(item["claim"]),
                verdict=item.get("verdict"),
                reason_code=item.get("reason_code"),
                expected=item.get("expected", {}) or {},
            )
        )
    return cases
