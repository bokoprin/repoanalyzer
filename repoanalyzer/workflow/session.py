from __future__ import annotations

from pathlib import Path

from .answer_check import verify_answer
from .contracts import contract_from_verification
from .models import WorkflowTrace, WorkflowStep
from .planner import plan_question
from .preflight import preflight
from .session_log import append_workflow_session


def workflow_run(repo: str | Path, question: str, answer_text: str | None = None, *, record: bool = False, label: str | None = None) -> WorkflowTrace:
    root = Path(repo).expanduser().resolve()
    report = preflight(root)
    plan = plan_question(question)
    steps = list(plan.steps)
    warnings = list(report.warnings) + list(plan.warnings)
    verification = None
    contract = None
    status = "planned"

    if answer_text is not None:
        verification = verify_answer(root, answer_text, question=question)
        contract = contract_from_verification(verification)
        status = _status_from_contract(contract.safety_level)
        steps.append(WorkflowStep("verify_answer", "Verify draft answer claims before sending.", "verify_answer"))
        steps.append(WorkflowStep("safe_answer_contract", "Apply safe answer contract to the draft answer.", "answer_contract"))
        warnings.extend(verification.warnings)
        warnings.extend(contract.warnings)
    elif report.safety_level == "blocked":
        status = "blocked"
    elif report.safety_level in {"degraded", "caution"}:
        status = "ready_with_caution"
    else:
        status = "ready"

    trace = WorkflowTrace(
        repo=str(root),
        question=question,
        status=status,
        preflight=report,
        plan=plan,
        answer_verification=verification,
        answer_contract=contract,
        steps=steps,
        warnings=_dedupe(warnings),
    )
    if record:
        append_workflow_session(root, trace, label=label)
    return trace


def _status_from_contract(safety_level: str) -> str:
    if safety_level == "unsafe":
        return "blocked"
    if safety_level == "needs_more_evidence":
        return "needs_more_evidence"
    if safety_level == "must_qualify":
        return "ready_with_qualifications"
    return "ready"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
