from __future__ import annotations

import json
from repoanalyzer.workflow_eval.runner import WorkflowEvalResult


def render_json(result: WorkflowEvalResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)


def render_text(result: WorkflowEvalResult) -> str:
    lines = [f"Workflow eval: {result.passed}/{result.total} passed"]
    for case in result.cases:
        mark = "PASS" if case["ok"] else "FAIL"
        trace = case.get("trace", {})
        lines.append(f"- {mark} {case['id']} ({trace.get('status')})")
        for failure in case["failures"]:
            lines.append(f"  - {failure}")
    return "\n".join(lines)
