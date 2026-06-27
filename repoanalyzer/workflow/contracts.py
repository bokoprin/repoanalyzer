from __future__ import annotations

from .answer_check import verify_answer
from repoanalyzer.evidence.answer_constraints import answer_constraints_from_verdicts
from .models import AnswerVerificationReport, SafeAnswerContract


def build_answer_contract(repo: str, text: str, question: str | None = None) -> SafeAnswerContract:
    return contract_from_verification(verify_answer(repo, text, question=question))


def contract_from_verification(report: AnswerVerificationReport) -> SafeAnswerContract:
    allowed = []
    qualified = []
    unknown = []
    prohibited = []
    required_qualifications: list[str] = []
    warnings = list(report.warnings)
    policy_violations = list(report.policy_violations)
    build_summary = answer_constraints_from_verdicts(report.claim_bundle.verdicts)

    for verdict in report.claim_bundle.verdicts:
        item = verdict.claim.to_dict()
        if verdict.verdict == "supported":
            allowed.append(item)
        elif verdict.verdict == "conditional":
            qualified.append(item)
            required_qualifications.append(_qualification_for(verdict))
        elif verdict.verdict == "contradicted":
            prohibited.append(item)
        else:
            unknown.append(item)

    must_not_send = report.safety_level == "unsafe" or any(getattr(v, "severity", "") == "high" for v in policy_violations)
    can_answer = report.safety_level in {"safe", "must_qualify"}
    if not report.claim_bundle.verdicts:
        can_answer = False

    return SafeAnswerContract(
        safety_level=report.safety_level,
        can_answer=can_answer,
        must_not_send=must_not_send,
        allowed_claims=allowed,
        qualified_claims=qualified,
        unknown_claims=unknown,
        prohibited_claims=prohibited,
        required_qualifications=_dedupe([q for q in [*required_qualifications, *build_summary.required_qualifications] if q]),
        response_constraints=_dedupe([*list(report.response_constraints), *build_summary.response_constraints]),
        answer_obligations=build_summary.answer_obligations,
        build_context=build_summary.build_context.to_dict(),
        warnings=warnings,
        policy_violations=policy_violations,
    )


def _qualification_for(verdict) -> str:
    if verdict.unknowns:
        unknown_types = ", ".join(sorted({unknown.unknown_type for unknown in verdict.unknowns if hasattr(unknown, "unknown_type")}))
        if unknown_types:
            return f"Qualify claim {verdict.claim.to_dict()} because it depends on {unknown_types}."
    return f"Qualify claim {verdict.claim.to_dict()} because its verdict is conditional."


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
