from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_ui_resource"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_ui_resource_command_binding_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    result = ingest_repo(repo)
    assert result.files == 2

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.predicate == "binds_menu_item_to_command"
        and fact.object == "F_SEARCH_NEXT"
        and fact.payload.get("relation_kind") == "menu_resource_binding"
        for fact in relations
    )
    assert any(
        fact.predicate == "binds_accelerator_to_command"
        and fact.object == "F_SEARCH_NEXT"
        and fact.payload.get("accelerator_key") == "VK_F3"
        for fact in relations
    )
    assert any(
        fact.subject == "toolbar_slot_225"
        and fact.predicate == "binds_toolbar_button_to_command"
        and fact.object == "F_SEARCH_NEXT"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CKeyBind::CreateAccerelator"
        and fact.predicate == "creates_accelerator_table"
        and fact.object == "CreateAcceleratorTable"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CKeyBind::GetFuncCode"
        and fact.predicate == "translates_accelerator_to_command"
        and fact.object == "EFunctionCode"
        for fact in relations
    )


def test_ui_resource_command_binding_question_returns_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "リソースID / accelerator / menu / toolbar から command ID への対応はどう行われる？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "menu_resource_to_command_trace"
        and "F_SEARCH_NEXT" in fact.route
        and "sakura::CViewCommander::Command_SEARCH_NEXT" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "accelerator_to_command_trace"
        and "F_SEARCH_NEXT" in fact.route
        and "sakura::CViewCommander::Command_SEARCH_NEXT" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.payload.get("route_kind") == "toolbar_to_command_trace"
        and fact.route[:2] == ["toolbar_slot_225", "F_SEARCH_NEXT"]
        for fact in bundle.facts
    ), payload


def test_sakura_ui_resource_command_binding_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
