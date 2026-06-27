from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_extension_execution"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_extension_execution_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    result = ingest_repo(repo)
    assert result.files == 1

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.subject == "sakura::CViewCommander::HandleCommand"
        and fact.predicate == "records_macro_command"
        and fact.object in {"CSMacroMgr::Append", "sakura::CSMacroMgr::Append"}
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CViewCommander::HandleCommand"
        and fact.predicate == "executes_macro"
        and fact.object in {"CSMacroMgr::Exec", "sakura::CSMacroMgr::Exec"}
        for fact in relations
    )
    assert any(
        fact.subject == "F_SEARCH_NEXT"
        and fact.predicate == "maps_macro_function"
        and fact.object == "SearchNext"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CJackManager::RegisterPlug"
        and fact.predicate == "registers_plugin_hook"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CJackManager::InvokePlugins"
        and fact.predicate == "invokes_plugin_hook"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CViewCommander::Command_EXECEXTCOMMAND"
        and fact.predicate == "launches_external_process"
        for fact in relations
    )


def test_extension_execution_question_returns_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "プラグイン / マクロ / 外部コマンド実行経路はどう行われる？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "macro_command_execution_trace"
        and any(step.endswith("CSMacroMgr::Exec") for step in fact.route)
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "plugin_hook_invocation_trace"
        and any(step.endswith("CPlug::Invoke") for step in fact.route)
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "external_command_launch_trace"
        and any(step.endswith("ShellExecuteW") or step.endswith("CreateProcessW") for step in fact.route)
        for fact in bundle.facts
    ), payload


def test_sakura_extension_execution_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
