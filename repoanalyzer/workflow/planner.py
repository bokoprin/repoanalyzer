from __future__ import annotations

import re

from repoanalyzer.evidence.claim_extraction import extract_claims
from .models import AnswerPlan, WorkflowStep


def plan_question(question: str) -> AnswerPlan:
    extraction = extract_claims(question)
    claims = list(extraction.extracted_claims)
    intent = _intent(question, has_claims=bool(claims))
    steps: list[WorkflowStep] = []
    tools: list[str] = []
    warnings: list[str] = [str(w.get("message") or w.get("warning_type")) for w in extraction.warnings]

    steps.append(WorkflowStep("preflight", "Check index freshness and diagnostics before repository reasoning.", "preflight"))
    tools.append("preflight")

    if claims:
        steps.append(
            WorkflowStep(
                "extract_claims",
                "Use deterministic claim extraction before verifying the answer or question claims.",
                "extract_claims",
                inputs={"claim_count": len(claims)},
            )
        )
        steps.append(WorkflowStep("verify_claims", "Verify extracted claims before allowing the final answer.", "verify_claims"))
        tools.extend(["extract_claims", "verify_claims"])
    else:
        steps.append(WorkflowStep("collect_evidence", "Collect evidence for the inferred repository question.", "collect_evidence", inputs={"mode": intent}))
        tools.append("collect_evidence")

    if intent in {"callers", "callees", "call_path"}:
        page_tool = "find_callers_page" if intent == "callers" else "find_callees_page" if intent == "callees" else "collect_evidence"
        steps.append(
            WorkflowStep(
                "page_results",
                "Use paginated tools for potentially large call graph result sets and follow next_offset if has_more is true.",
                page_tool,
            )
        )
        if page_tool not in tools:
            tools.append(page_tool)

    steps.append(WorkflowStep("answer_contract", "Convert verification results into a safe answer contract before sending text.", "answer_contract"))
    tools.append("answer_contract")

    return AnswerPlan(
        question=question,
        interpreted_intent=intent,
        steps=steps,
        required_tools=_dedupe(tools),
        extracted_claims=claims,
        warnings=[w for w in warnings if w],
    )


def _intent(question: str, *, has_claims: bool) -> str:
    q = question.lower()
    if has_claims:
        return "claim_verification"
    if "path" in q or "call path" in q or "reaches" in q or "到達" in question:
        return "call_path"
    if "caller" in q or "called from" in q or "呼ばれる" in question:
        return "callers"
    if "callee" in q or re.search(r"\bcalls?\b", q) or "呼ぶ" in question:
        return "callees"
    if "definition" in q or "定義" in question:
        return "definition"
    return "evidence"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
