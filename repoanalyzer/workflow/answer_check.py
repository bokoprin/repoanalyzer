from __future__ import annotations

from pathlib import Path

from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence.answer_constraints import answer_constraints_from_verdicts
from repoanalyzer.evidence.claims import ClaimEvidenceBundle
from .models import AnswerVerificationReport
from .policy import evaluate_answer_policy, policy_actions


def verify_answer(repo: str | Path, text: str, question: str | None = None) -> AnswerVerificationReport:
    bundle = verify_claim_text(repo, text)
    safety_level = _safety_level(bundle)
    build_summary = answer_constraints_from_verdicts(bundle.verdicts)
    constraints = _dedupe([*_constraints(bundle), *build_summary.response_constraints])
    policy_violations = evaluate_answer_policy(text, safety_level=safety_level, overall_verdict=bundle.overall_verdict)
    required_actions = _required_actions(bundle, safety_level) + policy_actions(policy_violations)
    warnings = [str(w.get("message") or w.get("warning_type")) for w in bundle.extraction_warnings]
    if not bundle.verdicts:
        warnings.append("No supported deterministic claim patterns were extracted; verify the answer manually or provide structured claims.")
    return AnswerVerificationReport(
        text=text,
        question=question,
        claim_bundle=bundle,
        safety_level=safety_level,
        overall_verdict=bundle.overall_verdict,
        required_actions=required_actions,
        response_constraints=constraints,
        answer_obligations=build_summary.answer_obligations,
        build_context=build_summary.build_context.to_dict(),
        warnings=[w for w in warnings if w],
        policy_violations=policy_violations,
    )


def _safety_level(bundle: ClaimEvidenceBundle) -> str:
    verdict = bundle.overall_verdict
    if not bundle.verdicts:
        return "needs_more_evidence"
    if verdict == "contradicted":
        return "unsafe"
    if verdict == "unknown":
        return "needs_more_evidence"
    if verdict == "conditional":
        return "must_qualify"
    if verdict == "supported":
        return "safe"
    return "needs_more_evidence"


def _constraints(bundle: ClaimEvidenceBundle) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for verdict in bundle.verdicts:
        for constraint in verdict.response_constraints:
            if constraint not in seen:
                seen.add(constraint)
                out.append(constraint)
    return out


def _required_actions(bundle: ClaimEvidenceBundle, safety_level: str) -> list[str]:
    actions: list[str] = []
    if safety_level == "unsafe":
        actions.append("revise_or_remove_contradicted_claims")
    if safety_level == "must_qualify":
        actions.append("qualify_conditional_claims")
    if safety_level == "needs_more_evidence":
        actions.append("collect_more_evidence_or_reduce_claims")
    if any(any(getattr(unknown, "unknown_type", "") == "index_freshness" for unknown in verdict.unknowns) for verdict in bundle.verdicts):
        actions.append("rerun_ingest")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
