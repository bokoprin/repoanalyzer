from __future__ import annotations

import shutil
from pathlib import Path
from typer.testing import CliRunner

from repoanalyzer.cli import app
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_sakura_cross_trace_snapshot"
CASE_FILE = FIXTURE / "phase7_sakura_cross_trace_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_sakura_cross_trace_real_repo_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = repo / CASE_FILE.name

    report = run_real_repo_eval(repo, case_file)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["metrics"]["indexed_files"] >= 17
    assert payload["metrics"]["total_facts"] >= 1000
    assert payload["metrics"]["scenario_count"] == 12
    assert payload["metrics"]["passed_scenarios"] == 12
    assert payload["metrics"]["failed_scenarios"] == 0


def test_phase7_sakura_cross_trace_questions_are_all_answerable(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    run_real_repo_eval(repo, repo / CASE_FILE.name)

    questions_and_routes = {
        "検索はどう実行される？": "command_execution_trace",
        "Undo/Redo と編集操作はどう追跡される？": "undo_execution_trace",
        "ファイル読み込み・文字コード判定はどう行われる？": "file_open_encoding_trace",
        "設定読み書き / CShareData / CommonSetting / profile / ini系はどう行われる？": "profile_core_io_trace",
        "Windows message / dialog callback はどう行われる？": "dialog_creation_callback_trace",
        "リソースID / accelerator / menu / toolbar から command ID への対応はどう行われる？": "menu_resource_to_command_trace",
        "プラグイン / マクロ / 外部コマンド実行経路はどう行われる？": "extension_execution",
    }
    for question, expected in questions_and_routes.items():
        bundle = collect_evidence(repo, question)
        assert bundle.answerability == "answerable", bundle.to_dict()
        if expected == "extension_execution":
            route_kinds = {fact.payload.get("route_kind") for fact in bundle.facts if fact.fact_type == "call_path"}
            assert {"macro_command_execution_trace", "plugin_hook_invocation_trace", "external_command_launch_trace"} <= route_kinds
        else:
            assert any(
                fact.fact_type == "call_path" and fact.payload.get("route_kind") == expected
                for fact in bundle.facts
            ), bundle.to_dict()


def test_phase7_sakura_cross_trace_cli_and_diagnostics(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["real-repo-eval", str(repo), str(repo / CASE_FILE.name), "--output", "json"])

    assert result.exit_code == 0, result.output
    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] >= 17
    assert diagnostics["total_facts"] >= 1000
    assert diagnostics["warnings"] == []
