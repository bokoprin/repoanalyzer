from __future__ import annotations

import json

from .models import RealRepoEvalReport


def render_json(report: RealRepoEvalReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def render_text(report: RealRepoEvalReport) -> str:
    lines = [
        f"Real repo eval: {'PASS' if report.ok else 'FAIL'} {report.case_id}",
        f"status: {report.status}",
        f"duration_ms: {report.duration_ms}",
    ]
    if report.failure_categories:
        lines.append(f"failure_categories: {report.failure_categories}")
    for failure in report.failures:
        lines.append(f"- {failure}")
    for scenario in report.scenarios:
        prefix = "PASS" if scenario.ok else "FAIL"
        lines.append(f"- {prefix} {scenario.id} ({scenario.kind}) {scenario.duration_ms}ms")
        for failure in scenario.failures:
            lines.append(f"    {failure}")
    return "\n".join(lines)
