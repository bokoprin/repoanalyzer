from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace
from typing import Any, Iterable

from repoanalyzer.core.models import CodeFact, SupportProfile, UnknownFact
from repoanalyzer.evidence.constraints import constraints_from_unknowns

SOURCE_COVERAGE_WEAK_STATUSES = {"partially_supported", "upstream_missing", "compact_only", "unknown"}
SEMANTIC_WEAK_STATUSES = {"unresolved", "candidate_or_ambiguous", "dynamic_candidate", "unsupported", "mixed_with_unresolved"}
BUILD_WEAK_STATUSES = {"conditional", "inactive", "mixed", "build_unknown"}

_SOURCE_REASON_MESSAGES = {
    "upstream_source_missing": "Some compact evidence is not backed by copied upstream source files; scope claims to the available snapshot evidence.",
    "no_upstream_metadata": "Some compact evidence has no upstream source metadata; it is compact-only evidence.",
    "upstream_metadata_not_source_path": "Some upstream references are metadata/sample references rather than source files.",
    "some_upstream_refs_skipped": "Some upstream references were skipped because they are not source-file evidence.",
    "upstream_refs_skipped": "The traceability report skipped upstream references for some evidence files.",
    "weak_anchor_match": "Some compact files are linked to upstream sources without strong anchor confirmation.",
    "source_coverage_not_mapped": "A coverage report exists, but the supporting fact paths could not be mapped to coverage entries.",
    "compact_source_missing": "A compact evidence file referenced by the coverage report is missing.",
    "compact_sha256_mismatch": "A compact evidence file hash does not match the manifest.",
    "no_compact_evidence_mapped": "The scenario could not be mapped to compact evidence files.",
}

_SEMANTIC_UNKNOWN_REASONS = {
    "ambiguous_symbol_resolution",
    "ambiguous_overload_resolution",
    "unresolved_member_receiver_type",
    "unresolved_call_target",
    "indirect_call_unresolved",
    "callback_relation_not_execution",
    "callback_target_unknown",
    "task_entry_execution_deferred",
    "scheduler_dependent_execution",
    "interrupt_mask_state_deferred",
    "port_layer_boundary",
    "assembly_boundary_unverified",
    "vector_table_unverified",
    "startup_file_missing",
    "port_stack_layout_target_specific",
    "virtual_dispatch_candidates",
    "unsupported_cpp_construct",
    "cross_tu_ambiguous_resolution",
    "mixed_execution_context",
}


def build_support_profile(
    repo: str | Path | None,
    facts: list[CodeFact],
    unknowns: list[UnknownFact] | None = None,
) -> SupportProfile:
    """Build a normalized evidence quality profile for a fact bundle.

    The profile intentionally does not make the normal no-snapshot case weak just
    because source coverage is not tracked. If a coverage report is present, its
    compact-vs-upstream status becomes a first-class quality input.
    """
    unknowns = list(unknowns or [])
    source_status, source_reasons = _source_coverage_status(repo, facts)
    semantic_status, semantic_reasons = _semantic_resolution_status(facts, unknowns)
    build_status, build_reasons = _build_status(facts, unknowns)
    target_profile = _target_profile_status(facts)
    execution_context, execution_contexts, execution_reasons = _execution_context_status(facts)

    unknown_reasons = _dedupe([*source_reasons, *semantic_reasons, *build_reasons, *execution_reasons, *[u.unknown_type for u in unknowns]])
    support_level = _support_level(
        facts=facts,
        source_coverage_status=source_status,
        semantic_resolution_status=semantic_status,
        build_status=build_status,
        unknown_reasons=unknown_reasons,
    )
    constraints = constraints_from_unknowns([*_unknown_facts_from_reasons(unknown_reasons, facts), *unknowns])
    return SupportProfile(
        support_level=support_level,
        source_coverage_status=source_status,
        semantic_resolution_status=semantic_status,
        build_status=build_status,
        target_profile=target_profile,
        execution_context=execution_context,
        execution_contexts=execution_contexts,
        unknown_reasons=unknown_reasons,
        response_constraints=_dedupe(constraints),
    )


def quality_unknowns(profile: SupportProfile, existing_unknowns: Iterable[UnknownFact] | None = None, facts: list[CodeFact] | None = None) -> list[UnknownFact]:
    existing_types = {unknown.unknown_type for unknown in existing_unknowns or []}
    return [unknown for unknown in _unknown_facts_from_reasons(profile.unknown_reasons, facts or []) if unknown.unknown_type not in existing_types]


def apply_quality_gate_to_verdict(repo: str | Path, verdict: Any) -> Any:
    """Attach quality metadata and downgrade unsafe strong claims when needed."""
    from repoanalyzer.evidence.claims import ClaimVerdict

    quality_facts = list(verdict.supporting_facts or verdict.contradicting_facts or [])
    quality_facts = [fact for fact in quality_facts if isinstance(fact, CodeFact)]
    profile = build_support_profile(repo, quality_facts, [u for u in verdict.unknowns if isinstance(u, UnknownFact)])
    profile = _adjust_profile_for_claim_semantics(verdict, profile)
    extra_unknowns = quality_unknowns(profile, verdict.unknowns, quality_facts)
    constraints = _dedupe([*list(verdict.response_constraints), *profile.response_constraints])

    new_verdict = verdict.verdict
    reason_code = verdict.reason_code
    message = verdict.message

    if verdict.verdict == "supported" and profile.support_level == "weak":
        new_verdict = "conditional"
        reason_code = f"{verdict.reason_code}_with_weak_evidence_quality"
        message = verdict.message + " Evidence quality is weak; qualify this claim."
        constraints.append("Qualify this claim because supporting evidence is weak or not fully upstream/build/semantic verified.")
    elif verdict.verdict == "contradicted" and _contradiction_needs_more_evidence(profile):
        new_verdict = "unknown"
        reason_code = "contradiction_not_safe_with_weak_evidence_quality"
        message = verdict.message + " Evidence quality is not strong enough to use absence/resolved-outgoing evidence as a contradiction."
        constraints.append("Do not present this as contradicted until source coverage and semantic/build evidence are strong enough for absence-style reasoning.")

    return ClaimVerdict(
        claim=verdict.claim,
        verdict=new_verdict,
        reason_code=reason_code,
        message=message,
        supporting_facts=verdict.supporting_facts,
        contradicting_facts=verdict.contradicting_facts,
        unknowns=[*list(verdict.unknowns), *extra_unknowns],
        response_constraints=_dedupe(constraints),
        support_level=profile.support_level,
        unknown_reasons=profile.unknown_reasons,
        quality_profile=profile,
    )



def _adjust_profile_for_claim_semantics(verdict: Any, profile: SupportProfile) -> SupportProfile:
    claim = getattr(verdict, "claim", None)
    if getattr(claim, "claim_type", None) == "file_active":
        requested = str(getattr(claim, "object", None) or getattr(claim, "payload", {}).get("status") or "active").lower()
        if requested in {"inactive", "false", "no"} and profile.build_status == "inactive":
            reasons = [reason for reason in profile.unknown_reasons if reason != "inactive_build_evidence"]
            return replace(profile, support_level="medium", unknown_reasons=reasons, response_constraints=constraints_from_unknowns(_unknown_facts_from_reasons(reasons, [])))
    return profile

def _contradiction_needs_more_evidence(profile: SupportProfile) -> bool:
    if profile.source_coverage_status in {"partially_supported", "upstream_missing", "compact_only", "unknown"}:
        return True
    if profile.semantic_resolution_status in {"unresolved", "candidate_or_ambiguous", "dynamic_candidate", "unsupported", "mixed_with_unresolved"}:
        return True
    if profile.build_status in {"conditional", "mixed", "build_unknown"}:
        return True
    return False


def _support_level(
    *,
    facts: list[CodeFact],
    source_coverage_status: str,
    semantic_resolution_status: str,
    build_status: str,
    unknown_reasons: list[str],
) -> str:
    if not facts:
        return "unknown"
    if build_status in BUILD_WEAK_STATUSES:
        return "weak"
    if semantic_resolution_status in SEMANTIC_WEAK_STATUSES:
        return "weak"
    if source_coverage_status in SOURCE_COVERAGE_WEAK_STATUSES:
        return "weak"
    if any(reason in _SEMANTIC_UNKNOWN_REASONS for reason in unknown_reasons):
        return "weak"
    if source_coverage_status == "not_tracked" or semantic_resolution_status == "not_tracked":
        return "medium"
    return "strong"




def _target_profile_status(facts: list[CodeFact]) -> str:
    names: list[str] = []
    for fact in facts:
        payload = fact.payload or {}
        value = payload.get("target_profile") or payload.get("target_profile_name")
        if isinstance(value, str) and value:
            names.append(value)
        context = payload.get("tu_context")
        if isinstance(context, dict):
            value = context.get("target_profile")
            if isinstance(value, str) and value:
                names.append(value)
    names = _dedupe(names)
    if not names:
        return "not_tracked"
    if len(names) == 1:
        return names[0]
    return "mixed"

def _build_status(facts: list[CodeFact], unknowns: list[UnknownFact]) -> tuple[str, list[str]]:
    if not facts:
        return "build_unknown", []
    statuses = {str(fact.payload.get("build_status") or "active") for fact in facts}
    reasons = [u.unknown_type for u in unknowns if u.unknown_type in {"conditional_build_evidence", "source_without_compile_commands", "header_unattributed_evidence", "unresolved_include_evidence", "unsupported_preprocessor_expression", "index_freshness"}]
    if statuses == {"active"}:
        return "active", _dedupe(reasons)
    if statuses == {"inactive"}:
        return "inactive", _dedupe([*reasons, "inactive_build_evidence"])
    if "conditional" in statuses:
        return "conditional", _dedupe([*reasons, "conditional_build_evidence"])
    if len(statuses) > 1:
        return "mixed", _dedupe([*reasons, "mixed_build_evidence"])
    return "build_unknown", _dedupe([*reasons, "build_status_unknown"])


def _semantic_resolution_status(facts: list[CodeFact], unknowns: list[UnknownFact]) -> tuple[str, list[str]]:
    if not facts:
        return "unknown", []
    reasons = [u.unknown_type for u in unknowns if u.unknown_type in _SEMANTIC_UNKNOWN_REASONS]
    statuses: list[str] = []
    for fact in facts:
        payload = fact.payload or {}
        unknown_type = payload.get("unknown_type")
        if isinstance(unknown_type, str) and unknown_type in _SEMANTIC_UNKNOWN_REASONS:
            reasons.append(unknown_type)
        status = payload.get("resolution_status") or payload.get("call_resolution_status") or payload.get("callback_resolution_status")
        if isinstance(status, str):
            statuses.append(status)
        call_kind = fact.call_kind or payload.get("call_kind") or payload.get("dispatch_kind")
        if call_kind in {"function_pointer", "virtual_candidate", "callback_candidate", "indirect"}:
            statuses.append("candidate_set")
        if fact.fact_type == "relation" and fact.predicate in {"registers_callback", "stores_callback"}:
            reasons.append("callback_relation_not_execution")
        if fact.fact_type == "relation" and fact.predicate == "invokes_callback":
            reasons.append("callback_target_unknown")
        if fact.fact_type == "relation" and fact.predicate in {"stores_task_entry", "initializes_stack_with_task_entry", "task_entry_dataflows_to"}:
            reasons.append("task_entry_execution_deferred")
            if fact.predicate == "task_entry_dataflows_to":
                reasons.append("scheduler_dependent_execution")
    normalized = {_normalize_resolution_status(status) for status in statuses if status}
    if any(item in {"unresolved"} for item in normalized):
        return "unresolved", _dedupe(reasons)
    if any(item in {"candidate_or_ambiguous"} for item in normalized):
        return "candidate_or_ambiguous", _dedupe(reasons)
    if any(item == "unsupported" for item in normalized):
        return "unsupported", _dedupe(reasons)
    if normalized and normalized <= {"resolved", "semantic_relation"}:
        return "resolved", _dedupe(reasons)
    if not normalized:
        # Syntactic facts such as direct regex call edges are still evidence, but
        # semantic precision is not explicitly tracked.
        return "not_tracked", _dedupe(reasons)
    if "resolved" in normalized and any(item not in {"resolved", "semantic_relation"} for item in normalized):
        return "mixed_with_unresolved", _dedupe(reasons)
    return "not_tracked", _dedupe(reasons)


def _normalize_resolution_status(status: str) -> str:
    if status in {"resolved", "resolved_candidate"}:
        return "resolved"
    if status in {"semantic_relation"}:
        return "semantic_relation"
    if status in {"candidate_set", "ambiguous"}:
        return "candidate_or_ambiguous"
    if status in {"unresolved", "unknown"}:
        return "unresolved"
    if status in {"unsupported"}:
        return "unsupported"
    return status



def _execution_context_status(facts: list[CodeFact]) -> tuple[str, list[str], list[str]]:
    """Summarize ISR/task execution-context annotations carried by evidence facts."""
    contexts: list[str] = []
    for fact in facts:
        payload = fact.payload or {}
        for key in (
            "execution_context",
            "caller_execution_context",
            "callee_execution_context",
            "creator_execution_context",
            "storage_execution_context",
            "invocation_execution_context",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value in {"isr", "task"}:
                contexts.append(value)
        if fact.fact_type == "relation" and fact.predicate == "has_execution_context" and fact.object in {"isr", "task"}:
            contexts.append(str(fact.object))
    contexts = _dedupe(contexts)
    if not contexts:
        return "not_tracked", [], []
    if len(contexts) == 1:
        return contexts[0], contexts, []
    return "mixed", contexts, ["mixed_execution_context"]

def _source_coverage_status(repo: str | Path | None, facts: list[CodeFact]) -> tuple[str, list[str]]:
    if not facts:
        return "unknown", []
    report = _load_coverage_report(repo)
    if report is None:
        return "not_tracked", []
    mapped_statuses: list[str] = []
    reasons: list[str] = []
    for fact in facts:
        entries = _coverage_entries_for_path(report, fact.path)
        for entry in entries:
            status = str(entry.get("support_status") or "unknown")
            if status != "not_applicable":
                mapped_statuses.append(status)
            reasons.extend(str(reason) for reason in entry.get("unknown_reasons") or [])
    if not mapped_statuses:
        return "not_tracked", ["source_coverage_not_mapped"]
    statuses = set(mapped_statuses)
    if "unknown" in statuses:
        status = "unknown"
    elif "upstream_missing" in statuses:
        status = "upstream_missing"
    elif "partially_supported" in statuses:
        status = "partially_supported"
    elif "compact_only" in statuses:
        status = "compact_only"
    elif statuses == {"upstream_supported"}:
        status = "upstream_supported"
    elif "upstream_supported" in statuses:
        status = "partially_supported"
    else:
        status = "unknown"
    return status, _dedupe(reasons)


def _load_coverage_report(repo: str | Path | None) -> dict[str, Any] | None:
    if repo is None:
        return None
    root = Path(repo).expanduser().resolve()
    candidates = [
        root / ".repoanalyzer-coverage-gap-report.json",
        root / ".repoanalyzer-index" / "coverage-gap-report.json",
        root / ".repoanalyzer-index" / "coverage_gap_report.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _coverage_entries_for_path(report: dict[str, Any], path: str) -> list[dict[str, Any]]:
    normalized = _norm_path(path)
    matched: list[dict[str, Any]] = []
    for entry in report.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        for compact in entry.get("compact_evidence") or []:
            if not isinstance(compact, dict):
                continue
            compact_path = _norm_path(str(compact.get("compact_path") or ""))
            if not compact_path:
                continue
            if normalized == compact_path or normalized.endswith("/" + compact_path) or compact_path.endswith("/" + normalized):
                matched.append(entry)
                break
    return matched


def _unknown_facts_from_reasons(reasons: Iterable[str], facts: list[CodeFact]) -> list[UnknownFact]:
    affects = _fact_affects(facts)
    out: list[UnknownFact] = []
    for reason in _dedupe([str(r) for r in reasons if r]):
        message = _SOURCE_REASON_MESSAGES.get(reason)
        if not message:
            continue
        severity = "high" if reason in {"compact_sha256_mismatch", "compact_source_missing"} else "medium"
        out.append(UnknownFact(reason, message, severity=severity, affects=affects))
    return out


def _fact_affects(facts: list[CodeFact]) -> list[str]:
    affects: list[str] = []
    for fact in facts:
        label = None
        if fact.caller and fact.callee:
            label = f"{fact.caller}->{fact.callee}"
        elif fact.subject and fact.object:
            label = f"{fact.subject}->{fact.object}"
        elif fact.qualified_name:
            label = fact.qualified_name
        elif fact.symbol:
            label = fact.symbol
        else:
            label = fact.path
        if label and label not in affects:
            affects.append(label)
    return affects[:20]


def _norm_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
