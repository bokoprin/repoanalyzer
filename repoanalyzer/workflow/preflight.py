from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.paths import index_db_path
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.store.status import repo_index_status
from .models import AgentPreflightReport

_RECOMMENDED_TOOLS = [
    "repo_status",
    "query_diagnostics",
    "collect_evidence",
    "verify_text",
    "verify_claim",
    "find_definitions_page",
    "find_callers_page",
    "find_callees_page",
]


def preflight(repo: str | Path) -> AgentPreflightReport:
    root = Path(repo).expanduser().resolve()
    db_path = index_db_path(root)
    required_actions: list[str] = []
    warnings: list[str] = []
    status_dict: dict = {}
    diagnostics_dict: dict = {}

    if not db_path.exists():
        required_actions.append("run_ingest")
        warnings.append("Index database does not exist; run ingest before answering repository questions.")
        return AgentPreflightReport(
            repo=str(root),
            index_ready=False,
            status={"status": "missing", "clean": False, "db_path": str(db_path)},
            diagnostics={"warnings": ["index_missing"]},
            safety_level="blocked",
            required_actions=required_actions,
            warnings=warnings,
            recommended_tools=["ingest"],
        )

    try:
        status = repo_index_status(root)
        status_dict = status.to_dict()
        if not status.clean:
            required_actions.append("refresh_index")
            warnings.append("Index is dirty; avoid completeness, absence, or contradiction claims until ingest is rerun.")
    except Exception as exc:
        required_actions.append("repair_or_reingest")
        warnings.append(f"Could not compute repo status: {exc}")
        status_dict = {"status": "unknown", "clean": False, "error": str(exc)}

    try:
        diagnostics = query_diagnostics(root)
        diagnostics_dict = diagnostics.to_dict()
        warnings.extend(diagnostics.warnings)
    except Exception as exc:
        warnings.append(f"Could not compute query diagnostics: {exc}")
        diagnostics_dict = {"warnings": [str(exc)]}

    if required_actions:
        safety_level = "degraded"
    elif warnings:
        safety_level = "caution"
    else:
        safety_level = "ready"

    return AgentPreflightReport(
        repo=str(root),
        index_ready=True,
        status=status_dict,
        diagnostics=diagnostics_dict,
        safety_level=safety_level,
        required_actions=required_actions,
        warnings=_dedupe(warnings),
        recommended_tools=list(_RECOMMENDED_TOOLS),
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
