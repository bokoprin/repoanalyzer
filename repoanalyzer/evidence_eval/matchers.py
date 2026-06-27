from __future__ import annotations

from typing import Any

from repoanalyzer.core.models import CodeFact, EvidenceBundle


def _fact_value(fact: CodeFact, key: str) -> Any:
    if hasattr(fact, key):
        return getattr(fact, key)
    if key in fact.payload:
        return fact.payload[key]
    if key == "route":
        return fact.route
    return None


def _payload_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def fact_matches(fact: CodeFact, pattern: dict[str, Any]) -> bool:
    payload_contains = pattern.get("payload_contains") or {}
    payload_path_equals = pattern.get("payload_path_equals") or {}
    payload_list_contains = pattern.get("payload_list_contains") or {}

    for key, expected in pattern.items():
        if key in {"payload_contains", "payload_path_equals", "payload_list_contains"}:
            continue
        actual = _fact_value(fact, key)
        if actual != expected:
            return False
    for key, expected in payload_contains.items():
        if fact.payload.get(key) != expected:
            return False
    for path, expected in payload_path_equals.items():
        if _payload_path(fact.payload, path) != expected:
            return False
    for key, expected in payload_list_contains.items():
        value = fact.payload.get(key)
        if not isinstance(value, list) or expected not in value:
            return False
    return True


def evaluate_bundle(bundle: EvidenceBundle, expected: dict[str, Any], required_unknowns: list[str], answerability: str | None) -> dict[str, Any]:
    failures: list[str] = []
    facts = bundle.facts
    for pattern in expected.get("must_include", []) or []:
        if not any(fact_matches(fact, pattern) for fact in facts):
            failures.append(f"missing expected fact: {pattern}")
    for pattern in expected.get("must_not_include", []) or []:
        if any(fact_matches(fact, pattern) for fact in facts):
            failures.append(f"unexpected fact present: {pattern}")
    unknown_types = {u.unknown_type for u in bundle.unknowns}
    for required in required_unknowns:
        if required not in unknown_types:
            failures.append(f"missing required unknown: {required}")
    for snippet in expected.get("required_constraints_contains", []) or []:
        if not any(snippet in constraint for constraint in bundle.response_constraints):
            failures.append(f"missing response constraint containing: {snippet}")
    if answerability and bundle.answerability != answerability:
        failures.append(f"answerability mismatch: expected {answerability}, got {bundle.answerability}")
    return {"ok": not failures, "failures": failures}
