from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_ABSOLUTE_RE = re.compile(r"\b(always|never|definitely|certainly|guaranteed|all|none|no\s+.*?calls?)\b|必ず|絶対|すべて|全て|一切|呼ばない", re.IGNORECASE)
_UNSUPPORTED_RE = re.compile(r"\bI\s+(?:think|guess|assume)\b|たぶん|おそらく|推測", re.IGNORECASE)


@dataclass(frozen=True)
class PolicyViolation:
    violation_type: str
    severity: str
    message: str
    span: list[int] | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "violation_type": self.violation_type,
            "severity": self.severity,
            "message": self.message,
            "span": self.span,
            "evidence": dict(self.evidence),
        }
        return {k: v for k, v in data.items() if v not in (None, [], {})}


def evaluate_answer_policy(text: str, *, safety_level: str, overall_verdict: str) -> list[PolicyViolation]:
    violations: list[PolicyViolation] = []
    if safety_level in {"must_qualify", "needs_more_evidence", "unsafe"}:
        for match in _ABSOLUTE_RE.finditer(text):
            violations.append(
                PolicyViolation(
                    "absolute_language_on_unsettled_claims",
                    "high" if safety_level == "unsafe" else "medium",
                    "Avoid absolute wording when claims are conditional, unknown, stale, or contradicted.",
                    [match.start(), match.end()],
                    {"matched_text": match.group(0), "safety_level": safety_level, "overall_verdict": overall_verdict},
                )
            )
    if overall_verdict == "unknown":
        for match in _UNSUPPORTED_RE.finditer(text):
            violations.append(
                PolicyViolation(
                    "speculative_answer_without_verifiable_claims",
                    "medium",
                    "Speculative wording was found while no verifiable supported claim was established.",
                    [match.start(), match.end()],
                    {"matched_text": match.group(0)},
                )
            )
    return violations


def policy_actions(violations: list[PolicyViolation]) -> list[str]:
    actions: list[str] = []
    for violation in violations:
        if violation.violation_type == "absolute_language_on_unsettled_claims":
            actions.append("remove_or_qualify_absolute_language")
        elif violation.violation_type == "speculative_answer_without_verifiable_claims":
            actions.append("replace_speculation_with_unknown_or_collect_evidence")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
