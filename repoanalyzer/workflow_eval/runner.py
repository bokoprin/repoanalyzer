from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repoanalyzer.workflow.session import workflow_run
from .cases import load_workflow_cases
from .matchers import evaluate_trace


@dataclass(frozen=True)
class WorkflowEvalResult:
    total: int
    passed: int
    failed: int
    cases: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "passed": self.passed, "failed": self.failed, "cases": self.cases}


def run_workflow_eval(repo: str | Path, case_file: str | Path) -> WorkflowEvalResult:
    cases = load_workflow_cases(case_file)
    results: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        trace = workflow_run(repo, case.question, answer_text=case.answer_text)
        judged = evaluate_trace(trace, case.expected)
        if judged["ok"]:
            passed += 1
        results.append({"id": case.id, "ok": judged["ok"], "failures": judged["failures"], "trace": trace.to_dict()})
    return WorkflowEvalResult(total=len(cases), passed=passed, failed=len(cases) - passed, cases=results)
