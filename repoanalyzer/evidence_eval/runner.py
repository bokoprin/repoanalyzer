from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repoanalyzer.evidence.collect import collect_evidence
from .cases import load_cases
from .matchers import evaluate_bundle


@dataclass(frozen=True)
class EvalResult:
    total: int
    passed: int
    failed: int
    cases: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "cases": self.cases,
        }


def run_eval(repo: str | Path, case_file: str | Path) -> EvalResult:
    cases = load_cases(case_file)
    results: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        bundle = collect_evidence(repo, case.question, mode=case.mode)
        judged = evaluate_bundle(bundle, case.expected, case.required_unknowns, case.answerability)
        if judged["ok"]:
            passed += 1
        results.append(
            {
                "id": case.id,
                "ok": judged["ok"],
                "failures": judged["failures"],
                "bundle": bundle.to_dict(),
            }
        )
    return EvalResult(total=len(cases), passed=passed, failed=len(cases) - passed, cases=results)
