from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._store import open_store
from repoanalyzer.query._active import active_fact_where

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_command_dispatch"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_sakura_command_switch_dispatch_relation_is_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation' AND predicate='dispatches_to'"))

    assert any(
        fact.subject == "F_SEARCH_NEXT"
        and fact.object == "sakura::CViewCommander::Command_SEARCH_NEXT"
        and fact.payload.get("relation_kind") == "command_dispatch"
        and fact.payload.get("edge_status") == "conditional_dispatch"
        and fact.payload.get("resolution_status") == "resolved"
        for fact in relations
    )


def test_search_execution_question_returns_command_to_search_core_trace(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "検索はどう実行される？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "relation"
        and fact.subject == "F_SEARCH_NEXT"
        and fact.object == "sakura::CViewCommander::Command_SEARCH_NEXT"
        for fact in bundle.facts
    )
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "F_SEARCH_NEXT"
        and fact.payload.get("route_kind") == "command_execution_trace"
        and fact.route[:2] == ["F_SEARCH_NEXT", "sakura::CViewCommander::Command_SEARCH_NEXT"]
        and "sakura::CSearchAgent::SearchString" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call"
        and fact.caller == "sakura::CSearchAgent::SearchWord"
        and fact.callee == "sakura::CSearchAgent::SearchStringWord"
        for fact in bundle.facts
    )


def test_sakura_command_dispatch_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
