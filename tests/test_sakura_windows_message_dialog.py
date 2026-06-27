from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_windows_message"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_windows_message_dialog_semantic_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.subject == "sakura::CSearchDialog::OpenDialog"
        and fact.predicate == "creates_dialog"
        and fact.object == "sakura::DialogBoxParam"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CSearchDialog::OpenDialog"
        and fact.predicate == "registers_dialog_callback"
        and fact.object == "sakura::CSearchDialog::DlgProc"
        and fact.payload.get("unknown_type") == "dialog_callback_not_direct_call"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CSearchDialog::DlgProc"
        and fact.predicate == "handles_windows_message"
        and fact.object == "WM_COMMAND"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CSearchDialog::DlgProc"
        and fact.predicate == "handles_control_command"
        and fact.object == "IDC_BUTTON_FIND"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CSearchDialog::OnFindNext"
        and fact.predicate == "sends_windows_message"
        and fact.object == "WM_COMMAND"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CPropTypesColor::InitColorList"
        and fact.predicate == "registers_window_subclass_callback"
        and fact.object == "sakura::CPropTypesColor::ColorList_SubclassProc"
        for fact in relations
    )


def test_windows_message_dialog_question_returns_deterministic_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "Windows message / dialog callback はどう行われる？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CSearchDialog::OpenDialog"
        and fact.payload.get("route_kind") == "dialog_creation_callback_trace"
        and "sakura::DialogBoxParam" in fact.route
        and "sakura::CSearchDialog::DlgProc" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CSearchDialog::DlgProc"
        and fact.payload.get("route_kind") == "dialog_message_dispatch_trace"
        and "WM_COMMAND" in fact.route
        and "IDC_BUTTON_FIND" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CSearchDialog::OnFindNext"
        and fact.payload.get("route_kind") == "wm_command_bridge_trace"
        and "WM_COMMAND" in fact.route
        for fact in bundle.facts
    ), payload


def test_sakura_windows_message_dialog_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
