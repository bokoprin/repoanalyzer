from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repoanalyzer.evidence.verify import verify_claim
from .cases import load_claim_cases
from .matchers import evaluate_verdict


@dataclass(frozen=True)
class ClaimEvalResult:
    total: int
    passed: int
    failed: int
    cases: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "passed": self.passed, "failed": self.failed, "cases": self.cases}


def run_claim_eval(repo: str | Path, case_file: str | Path) -> ClaimEvalResult:
    cases = load_claim_cases(case_file)
    results: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        verdict = verify_claim(repo, case.claim)
        judged = evaluate_verdict(verdict, case.verdict, case.reason_code, case.expected)
        if judged["ok"]:
            passed += 1
        results.append({"id": case.id, "ok": judged["ok"], "failures": judged["failures"], "verdict": verdict.to_dict()})
    return ClaimEvalResult(total=len(cases), passed=passed, failed=len(cases) - passed, cases=results)
