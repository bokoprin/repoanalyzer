from __future__ import annotations

import json
from repoanalyzer.evidence_eval.runner import EvalResult


def render_json(result: EvalResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def render_text(result: EvalResult) -> str:
    lines = [f"Evidence eval: {result.passed}/{result.total} passed"]
    for case in result.cases:
        mark = "PASS" if case["ok"] else "FAIL"
        lines.append(f"- {mark} {case['id']}")
        for failure in case["failures"]:
            lines.append(f"  - {failure}")
    return "\n".join(lines)
