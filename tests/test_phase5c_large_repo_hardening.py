from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.mcp.tools import tool_find_callers_page, tool_query_diagnostics
from repoanalyzer.query import find_callers
from repoanalyzer.query.pages import find_callers_page
from repoanalyzer.store.diagnostics import query_diagnostics


def _write_many_callers_repo(root: Path, *, callers: int = 12) -> None:
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    lines = ["void target() {}"]
    for index in range(callers):
        lines.append(f"void caller_{index:02d}() {{ target(); }}")
    (src / "main.cpp").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_phase5c_page_helpers_apply_pagination_after_symbol_filtering(tmp_path: Path) -> None:
    _write_many_callers_repo(tmp_path, callers=12)
    ingest_repo(tmp_path, reset=True)

    all_callers = find_callers(tmp_path, "target")
    page1 = find_callers_page(tmp_path, "target", limit=5, offset=0)
    page2 = find_callers_page(tmp_path, "target", limit=5, offset=5)

    assert len(all_callers) == 12
    assert page1.total == 12
    assert page1.next_offset == 5
    assert page1.has_more is True
    assert [fact.caller for fact in page1.items] == [fact.caller for fact in all_callers[:5]]
    assert [fact.caller for fact in page2.items] == [fact.caller for fact in all_callers[5:10]]
    assert any("larger than this page" in warning for warning in page1.warnings)


def test_phase5c_mcp_paginated_tool_returns_page_metadata(tmp_path: Path) -> None:
    _write_many_callers_repo(tmp_path, callers=7)
    ingest_repo(tmp_path, reset=True)

    payload = tool_find_callers_page(str(tmp_path), "target", limit=3, offset=3)

    assert payload["page"]["total"] == 7
    assert payload["page"]["offset"] == 3
    assert payload["page"]["limit"] == 3
    assert payload["page"]["next_offset"] == 6
    assert len(payload["items"]) == 3


def test_phase5c_query_diagnostics_reports_roles_and_warnings(tmp_path: Path) -> None:
    _write_many_callers_repo(tmp_path, callers=2)
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    (vendor / "third_party.cpp").write_text("void vendored() {}\n", encoding="utf-8")
    ingest_repo(tmp_path, reset=True)

    diagnostics = query_diagnostics(tmp_path).to_dict()

    assert diagnostics["fact_type_counts"]["symbol"] >= 3
    assert diagnostics["file_role_counts"]["project"] == 1
    assert diagnostics["file_role_counts"]["vendor"] == 1
    assert any("non-project file roles" in warning for warning in diagnostics["warnings"])

    mcp_payload = tool_query_diagnostics(str(tmp_path))
    assert mcp_payload["schema_version"] == "query_diagnostics.v1"
    assert mcp_payload["indexed_files"] == 2


def test_phase5c_claim_verification_is_downgraded_when_index_is_dirty(tmp_path: Path) -> None:
    _write_many_callers_repo(tmp_path, callers=1)
    ingest_repo(tmp_path, reset=True)

    clean = verify_claim(tmp_path, Claim("calls", subject="caller_00", object="target"))
    assert clean.verdict in {"supported", "conditional"}
    assert not any(unknown.unknown_type == "index_freshness" for unknown in clean.unknowns)

    (tmp_path / "src" / "main.cpp").write_text("void target() {}\nvoid caller_00() {}\n", encoding="utf-8")
    stale = verify_claim(tmp_path, Claim("calls", subject="caller_00", object="target"))

    assert stale.verdict in {"conditional", "unknown"}
    assert any(unknown.unknown_type == "index_freshness" for unknown in stale.unknowns)
    assert any("Re-run ingest" in constraint for constraint in stale.response_constraints)


def test_phase5c_cli_query_diagnostics_smoke(tmp_path: Path) -> None:
    _write_many_callers_repo(tmp_path, callers=1)
    ingest_repo(tmp_path, reset=True)

    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "query-diagnostics", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "query_diagnostics.v1"
    assert payload["indexed_files"] == 1
