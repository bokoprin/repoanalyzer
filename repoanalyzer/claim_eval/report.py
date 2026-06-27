from __future__ import annotations

import json
from repoanalyzer.claim_eval.runner import ClaimEvalResult


def render_json(result: ClaimEvalResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def render_text(result: ClaimEvalResult) -> str:
    lines = [f"Claim eval: {result.passed}/{result.total} passed"]
    for case in result.cases:
        mark = "PASS" if case["ok"] else "FAIL"
        verdict = case.get("verdict", {})
        lines.append(f"- {mark} {case['id']} ({verdict.get('verdict')}:{verdict.get('reason_code')})")
        for failure in case["failures"]:
            lines.append(f"  - {failure}")
    return "\n".join(lines)
