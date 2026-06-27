from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repoanalyzer.core.models import CodeFact
from repoanalyzer.cpp.build_provenance import diff_profile_target
from repoanalyzer.query._semantic import name_matches
from repoanalyzer.query._store import open_store


@dataclass(frozen=True)
class TargetProfileDiffReport:
    target: str
    left_repo: str
    right_repo: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "target_profile_diff_report.v1",
            "target": self.target,
            "left_repo": self.left_repo,
            "right_repo": self.right_repo,
            **self.payload,
        }


def build_target_profile_diff(left_repo: str | Path, right_repo: str | Path, target: str) -> TargetProfileDiffReport:
    left_root = Path(left_repo).expanduser().resolve()
    right_root = Path(right_repo).expanduser().resolve()
    left_facts = _facts_for_target(left_root, target)
    right_facts = _facts_for_target(right_root, target)
    payload = diff_profile_target(left_facts, right_facts)
    return TargetProfileDiffReport(
        target=target,
        left_repo=str(left_root),
        right_repo=str(right_root),
        payload={key: value for key, value in payload.items() if key != "schema_version"},
    )


def _facts_for_target(repo: Path, target: str) -> list[CodeFact]:
    facts = open_store(repo).all_facts()
    matched: list[CodeFact] = []
    for fact in facts:
        if _fact_matches_target(fact, target):
            matched.append(fact)
    definition_facts = [fact for fact in matched if fact.predicate == "definition" or fact.payload.get("declaration_or_definition") == "definition"]
    call_facts = [fact for fact in matched if fact.fact_type == "call"]
    return definition_facts or call_facts or matched


def _fact_matches_target(fact: CodeFact, target: str) -> bool:
    values = [fact.symbol, fact.qualified_name, fact.subject, fact.object, fact.caller, fact.callee]
    for value in values:
        if isinstance(value, str) and name_matches(value, target):
            return True
    payload = fact.payload or {}
    for key in ("symbol", "qualified_name", "caller_qualified_name", "callee_qualified_name"):
        value = payload.get(key)
        if isinstance(value, str) and name_matches(value, target):
            return True
    return False
