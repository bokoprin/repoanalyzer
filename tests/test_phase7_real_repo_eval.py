from __future__ import annotations

import json
import shutil
from pathlib import Path
from typer.testing import CliRunner

from repoanalyzer.cli import app
from repoanalyzer.mcp.tools import tool_real_repo_eval
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval


FIXTURE = Path(__file__).parent / "fixtures_cpp" / "basic_call"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def _write_case(path: Path) -> Path:
    case_file = path / "real_repo_cases.yaml"
    case_file.write_text(
        """
id: phase7_basic_real_repo_validation
ingest:
  enabled: true
budgets:
  max_total_ms: 20000
  max_facts: 500
expect:
  ingest:
    status: indexed
    min_files: 3
    min_facts: 1
  repo_status:
    clean: true
  diagnostics:
    min_total_facts: 1
    min_indexed_files: 3
    max_warnings: 0
scenarios:
  - id: evidence_callers
    kind: collect_evidence
    question: init_device はどこから呼ばれる？
    mode: callers
    expect:
      answerability: answerable
      must_include:
        - fact_type: call
          caller: start_device
          callee: init_device
          path: src/device.cpp
  - id: claim_text_supported
    kind: verify_text
    text: start_device calls init_device
    expect:
      overall_verdict: supported
      verdicts_include:
        - claim_type: calls
          subject: start_device
          object: init_device
          verdict: supported
  - id: workflow_supported
    kind: workflow_run
    question: Does start_device call init_device?
    answer_text: start_device calls init_device
    expect:
      status: ready
      safety_level: safe
      overall_verdict: supported
  - id: diagnostics_smoke
    kind: query_diagnostics
    expect:
      min_total_facts: 1
      max_warnings: 0
  - id: status_smoke
    kind: repo_status
    expect:
      clean: true
""".strip(),
        encoding="utf-8",
    )
    return case_file


def test_real_repo_eval_runs_ingest_diagnostics_and_scenarios(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = _write_case(tmp_path)

    report = run_real_repo_eval(repo, case_file)

    assert report.ok
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["metrics"]["indexed_files"] == 3
    assert payload["diagnostics"]["total_facts"] >= 1
    assert {scenario["id"] for scenario in payload["scenarios"]} == {
        "evidence_callers",
        "claim_text_supported",
        "workflow_supported",
        "diagnostics_smoke",
        "status_smoke",
    }


def test_real_repo_eval_reports_failure_categories(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = tmp_path / "failing_cases.yaml"
    case_file.write_text(
        """
id: phase7_failure_classification
ingest:
  enabled: true
scenarios:
  - id: claim_wrong_expectation
    kind: verify_text
    text: start_device calls missing_target
    expect:
      overall_verdict: supported
""".strip(),
        encoding="utf-8",
    )

    report = run_real_repo_eval(repo, case_file)

    assert not report.ok
    assert report.failure_categories.get("claim_mismatch") == 1
    assert report.scenarios[0].failure_categories == ["claim_mismatch"]


def test_real_repo_eval_cli_and_mcp_tool(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = _write_case(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["real-repo-eval", str(repo), str(case_file), "--output", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True

    mcp_payload = tool_real_repo_eval(str(repo), str(case_file))
    assert mcp_payload["schema_version"] == "real_repo_eval_report.v1"
    assert mcp_payload["ok"] is True
