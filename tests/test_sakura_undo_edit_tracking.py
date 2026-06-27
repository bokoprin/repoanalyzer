from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_undo_edit"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_edit_and_undo_semantic_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.subject == "sakura::CViewCommander::Command_WCHAR"
        and fact.predicate == "performs_edit_operation"
        and fact.object == "sakura::CEditView::InsertData_CEditView"
        and fact.payload.get("operation_kind") == "insert_text"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CViewCommander::Command_UNDO"
        and fact.predicate == "consumes_undo_history"
        and fact.object == "sakura::COpeBuf::DoUndo"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CViewCommander::Command_REDO"
        and fact.predicate == "consumes_redo_history"
        and fact.object == "sakura::COpeBuf::DoRedo"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CViewCommander::Command_UNDO"
        and fact.predicate == "marks_undo_redo_execution"
        and fact.payload.get("operation_kind") == "enter_undo_redo_execution"
        for fact in relations
    )


def test_undo_edit_question_returns_command_edit_and_undo_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "Undo/Redo と編集操作はどう追跡される？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "F_WCHAR"
        and fact.payload.get("route_kind") == "edit_command_trace"
        and fact.route[:2] == ["F_WCHAR", "sakura::CViewCommander::Command_WCHAR"]
        and "sakura::CEditView::InsertData_CEditView" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "F_UNDO"
        and fact.payload.get("route_kind") == "undo_execution_trace"
        and "sakura::COpeBuf::DoUndo" in fact.route
        and "sakura::CEditView::ReplaceData_CEditView3" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "F_REDO"
        and fact.payload.get("route_kind") == "redo_execution_trace"
        and "sakura::COpeBuf::DoRedo" in fact.route
        and "sakura::CEditView::ReplaceData_CEditView3" in fact.route
        for fact in bundle.facts
    ), payload


def test_sakura_undo_edit_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
