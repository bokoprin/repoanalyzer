from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.models import CodeFact, UnknownFact
from repoanalyzer.store.status import repo_index_status


def is_conditional_fact(fact: CodeFact) -> bool:
    return fact.payload.get("build_status") == "conditional"


def build_context_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    unknowns: list[UnknownFact] = []
    unknowns.extend(conditional_build_unknowns(facts))
    unknowns.extend(source_without_compile_commands_unknowns(facts))
    unknowns.extend(header_unattributed_unknowns(facts))
    unknowns.extend(unresolved_include_unknowns(facts))
    unknowns.extend(unsupported_preprocessor_expression_unknowns(facts))
    return unknowns


def conditional_build_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    conditional = [fact for fact in facts if is_conditional_fact(fact)]
    if not conditional:
        return []

    expressions: list[str] = []
    affects: list[str] = []
    for fact in conditional:
        for expression in fact.payload.get("guard_expressions", []) or []:
            if expression and expression not in expressions:
                expressions.append(str(expression))
        affected = _affected_label(fact)
        if affected and affected not in affects:
            affects.append(affected)

    message = f"{len(conditional)} fact(s) are conditional on unresolved preprocessor guard(s)."
    if expressions:
        message += " Guard expression(s): " + ", ".join(expressions) + "."

    return [
        UnknownFact(
            "conditional_build_evidence",
            message,
            severity="medium",
            affects=affects,
        )
    ]


def source_without_compile_commands_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    affected = []
    for fact in facts:
        context = fact.payload.get("tu_context") or {}
        if context.get("kind") == "source_without_compile_commands":
            label = _affected_label(fact) or fact.path
            if label not in affected:
                affected.append(label)
    if not affected:
        return []
    return [
        UnknownFact(
            "source_without_compile_commands",
            "Some facts come from source files scanned without compile_commands.json; target-build precision is lower.",
            severity="medium",
            affects=affected,
        )
    ]


def header_unattributed_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    affected = []
    for fact in facts:
        context = fact.payload.get("tu_context") or {}
        if context.get("kind") == "header_standalone" and context.get("precision") == "header_unattributed":
            label = _affected_label(fact) or fact.path
            if label not in affected:
                affected.append(label)
    if not affected:
        return []
    return [
        UnknownFact(
            "header_unattributed_evidence",
            "Some header facts are indexed without a precise translation-unit projection; macro-dependent availability may vary by TU.",
            severity="medium",
            affects=affected,
        )
    ]


def unresolved_include_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    affected = []
    for fact in facts:
        if fact.fact_type != "include" or fact.payload.get("resolution_status") != "unresolved":
            continue
        label = _affected_label(fact) or fact.path
        if label not in affected:
            affected.append(label)
    if not affected:
        return []
    return [
        UnknownFact(
            "unresolved_include_evidence",
            "Some include facts could not be resolved with the current compile_commands include paths.",
            severity="low",
            affects=affected,
        )
    ]


def unsupported_preprocessor_expression_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    affected: list[str] = []
    kinds: list[str] = []
    expressions: list[str] = []
    for fact in facts:
        if fact.payload.get("build_status") != "conditional":
            continue
        fact_kinds = fact.payload.get("unsupported_preprocessor_kinds") or []
        if not fact_kinds:
            for guard in fact.payload.get("guard_stack") or []:
                if isinstance(guard, dict) and guard.get("unsupported_kind"):
                    fact_kinds.append(str(guard["unsupported_kind"]))
        if not fact_kinds:
            continue
        label = _affected_label(fact) or fact.path
        if label not in affected:
            affected.append(label)
        for kind in fact_kinds:
            if kind not in kinds:
                kinds.append(kind)
        for expression in fact.payload.get("guard_expressions", []) or []:
            expression = str(expression)
            if expression and expression not in expressions:
                expressions.append(expression)
    if not affected:
        return []

    message = "Some facts are conditional because their preprocessor guard expression is outside the supported evaluator subset."
    if kinds:
        message += " Unsupported kind(s): " + ", ".join(kinds) + "."
    if expressions:
        message += " Guard expression(s): " + ", ".join(expressions) + "."
    return [
        UnknownFact(
            "unsupported_preprocessor_expression",
            message,
            severity="medium",
            affects=affected,
        )
    ]


def _affected_label(fact: CodeFact) -> str | None:
    if fact.caller and fact.callee:
        return f"{fact.caller}->{fact.callee}"
    if fact.symbol:
        return fact.symbol
    if fact.qualified_name:
        return fact.qualified_name
    if fact.subject or fact.object:
        return "->".join(part for part in [fact.subject, fact.object] if part)
    return None


def index_freshness_unknowns(repo: str | Path) -> list[UnknownFact]:
    status = repo_index_status(repo)
    if status.clean or status.status == "missing_index":
        return []
    affected = [item.path for item in status.stale[:10]]
    affected.extend(item.path for item in status.missing[:10])
    affected.extend(item.path for item in status.new[:10])
    parts = []
    if status.stale:
        parts.append(f"stale={len(status.stale)}")
    if status.missing:
        parts.append(f"missing={len(status.missing)}")
    if status.new:
        parts.append(f"new={len(status.new)}")
    return [
        UnknownFact(
            "index_freshness",
            "The current repository files differ from the indexed file manifest (" + ", ".join(parts) + "); re-ingest before claiming repository completeness.",
            severity="high",
            affects=affected,
        )
    ]
