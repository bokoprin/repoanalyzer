from __future__ import annotations

from typing import Any

from repoanalyzer.evidence.claims import ClaimVerdict
from repoanalyzer.evidence_eval.matchers import fact_matches


def _unknown_types(verdict: ClaimVerdict) -> set[str]:
    return {u.unknown_type for u in verdict.unknowns if hasattr(u, "unknown_type")}


def evaluate_verdict(verdict: ClaimVerdict, expected_verdict: str | None, expected_reason: str | None, expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if expected_verdict and verdict.verdict != expected_verdict:
        failures.append(f"verdict mismatch: expected {expected_verdict}, got {verdict.verdict}")
    if expected_reason and verdict.reason_code != expected_reason:
        failures.append(f"reason_code mismatch: expected {expected_reason}, got {verdict.reason_code}")
    for pattern in expected.get("supporting_must_include", []) or []:
        if not any(fact_matches(fact, pattern) for fact in verdict.supporting_facts):
            failures.append(f"missing supporting fact: {pattern}")
    for pattern in expected.get("contradicting_must_include", []) or []:
        if not any(fact_matches(fact, pattern) for fact in verdict.contradicting_facts):
            failures.append(f"missing contradicting fact: {pattern}")
    unknown_types = _unknown_types(verdict)
    for required in expected.get("required_unknowns", []) or []:
        if required not in unknown_types:
            failures.append(f"missing required unknown: {required}")
    for snippet in expected.get("required_constraints_contains", []) or []:
        if not any(snippet in constraint for constraint in verdict.response_constraints):
            failures.append(f"missing response constraint containing: {snippet}")
    return {"ok": not failures, "failures": failures}
