from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from repoanalyzer.core.models import CodeFact
from .macro_eval import eval_guard_detailed
from .preprocessor_model import ConditionalGuard

_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_]\w*\b")
_RESERVED = {"defined", "sizeof", "and", "or", "not"}


@dataclass(frozen=True)
class ProfileTargetStatus:
    profile: str
    status: str
    macro_values: dict[str, str]
    build_guard_chain: list[dict[str, Any]]
    facts: list[CodeFact]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "status": self.status,
            "macro_values": dict(self.macro_values),
            "build_guard_chain": list(self.build_guard_chain),
            "facts": [fact.to_dict() for fact in self.facts[:10]],
        }


def build_guard_chain_payload(
    guards: Iterable[ConditionalGuard],
    macros: Mapping[str, str | None],
    *,
    fact_build_status: str,
) -> list[dict[str, Any]]:
    """Return JSON-friendly provenance for active/inactive/conditional guards.

    The preprocessor model already decides whether a line is active for the
    indexed target profile.  This helper preserves *why* by keeping the guard
    expression, evaluated status, macro values used by the evaluator, and any
    unresolved/unsupported details.
    """

    chain: list[dict[str, Any]] = []
    for guard in guards:
        directive = guard.directive
        expression = guard.expression
        if directive == "else":
            evaluation_status = guard.status or guard.effective_status or fact_build_status
            evaluation_reason = guard.evaluation_reason
            unresolved = list(guard.unresolved_symbols)
            unsupported = guard.unsupported_kind
        else:
            eval_directive = directive if directive in {"if", "ifdef", "ifndef", "elif"} else "if"
            evaluation = eval_guard_detailed(eval_directive, expression, macros)
            evaluation_status = evaluation.status
            evaluation_reason = evaluation.reason
            unresolved = list(evaluation.unresolved_symbols)
            unsupported = evaluation.unsupported_kind
        identifiers = _macro_identifiers(expression)
        evaluated_with = {
            name: _macro_value_for_payload(macros[name])
            for name in identifiers
            if name in macros
        }
        item: dict[str, Any] = {
            "directive": directive,
            "branch_role": guard.branch_role or directive,
            "expression": expression,
            "line": guard.line,
            "local_status": guard.status or evaluation_status,
            "effective_status": guard.effective_status or fact_build_status,
            "evaluation_status": evaluation_status,
            "evaluated_with": evaluated_with,
        }
        if guard.parent_status:
            item["parent_status"] = guard.parent_status
        if evaluation_reason:
            item["evaluation_reason"] = evaluation_reason
        if unsupported:
            item["unsupported_kind"] = unsupported
        if unresolved:
            item["unresolved_symbols"] = unresolved
        missing = sorted(name for name in identifiers if name not in macros)
        if missing:
            item["missing_macro_values"] = missing
        chain.append({key: value for key, value in item.items() if value not in (None, [], {})})
    return chain


def build_guard_summary(chain: list[dict[str, Any]]) -> dict[str, Any]:
    expressions = [str(item.get("expression")) for item in chain if item.get("expression")]
    macro_values: dict[str, str] = {}
    for item in chain:
        for name, value in (item.get("evaluated_with") or {}).items():
            macro_values[str(name)] = str(value)
    return {
        "guard_expressions": _dedupe(expressions),
        "guard_macro_values": dict(sorted(macro_values.items())),
    }


def status_for_target_facts(facts: list[CodeFact]) -> str:
    if any(_build_status(fact) == "active" for fact in facts):
        return "active"
    if any(_build_status(fact) == "conditional" for fact in facts):
        return "conditional"
    if any(_build_status(fact) == "inactive" for fact in facts):
        return "inactive"
    return "unknown"


def target_status_from_facts(facts: list[CodeFact]) -> ProfileTargetStatus:
    profile = _profile_from_facts(facts)
    status = status_for_target_facts(facts)
    macro_values = _macro_values_from_facts(facts)
    chain = _first_guard_chain(facts)
    return ProfileTargetStatus(profile=profile, status=status, macro_values=macro_values, build_guard_chain=chain, facts=facts)


def diff_profile_target(left_facts: list[CodeFact], right_facts: list[CodeFact]) -> dict[str, Any]:
    left = target_status_from_facts(left_facts)
    right = target_status_from_facts(right_facts)
    return {
        "schema_version": "target_profile_diff.v1",
        "left": left.to_dict(),
        "right": right.to_dict(),
        "status_changed": left.status != right.status,
        "macro_differences": _macro_diff(left.macro_values, right.macro_values),
    }


def _macro_identifiers(expression: str) -> list[str]:
    identifiers = []
    for token in _IDENTIFIER_RE.findall(expression or ""):
        if token in _RESERVED:
            continue
        if token not in identifiers:
            identifiers.append(token)
    return identifiers


def _macro_value_for_payload(value: str | None) -> str:
    return "1" if value is None else str(value)


def _build_status(fact: CodeFact) -> str:
    return str((fact.payload or {}).get("build_status") or "active")


def _profile_from_facts(facts: list[CodeFact]) -> str:
    for fact in facts:
        payload = fact.payload or {}
        for value in (
            payload.get("target_profile"),
            payload.get("target_profile_name"),
            (payload.get("tu_context") or {}).get("target_profile") if isinstance(payload.get("tu_context"), dict) else None,
        ):
            if isinstance(value, str) and value:
                return value
    return "not_tracked"


def _macro_values_from_facts(facts: list[CodeFact]) -> dict[str, str]:
    values: dict[str, str] = {}
    for fact in facts:
        payload = fact.payload or {}
        contexts = [payload]
        if isinstance(payload.get("tu_context"), dict):
            contexts.append(payload["tu_context"])
        for context in contexts:
            for name, value in (context.get("macro_values") or {}).items():
                values[str(name)] = str(value)
            for item in context.get("build_guard_chain") or []:
                for name, value in (item.get("evaluated_with") or {}).items():
                    values[str(name)] = str(value)
        for item in payload.get("build_guard_chain") or []:
            for name, value in (item.get("evaluated_with") or {}).items():
                values[str(name)] = str(value)
    return dict(sorted(values.items()))


def _first_guard_chain(facts: list[CodeFact]) -> list[dict[str, Any]]:
    for fact in facts:
        chain = (fact.payload or {}).get("build_guard_chain")
        if isinstance(chain, list) and chain:
            return chain
    return []


def _macro_diff(left: dict[str, str], right: dict[str, str]) -> dict[str, dict[str, str | None]]:
    out: dict[str, dict[str, str | None]] = {}
    for name in sorted(set(left) | set(right)):
        if left.get(name) != right.get(name):
            out[name] = {"left": left.get(name), "right": right.get(name)}
    return out


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
