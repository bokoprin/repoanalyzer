from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_file_loading"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_file_loading_encoding_semantic_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.subject == "sakura::CFileLoad::FileOpen"
        and fact.predicate == "opens_file"
        and fact.object == "sakura::CreateFile"
        and fact.payload.get("operation_kind") == "win32_create_file"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CFileLoad::FileOpen"
        and fact.predicate == "detects_character_encoding"
        and fact.object == "sakura::CCodeMediator::CheckKanjiCode"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CFileLoad::FileOpen"
        and fact.predicate == "creates_encoding_converter"
        and fact.object == "sakura::CCodeFactory::CreateCodeBase"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CFileLoad::ReadLine_core"
        and fact.predicate == "converts_file_to_internal_encoding"
        and fact.object == "sakura::CIoBridge::FileToImpl"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CCodeMediator::CheckKanjiCode"
        and fact.predicate == "uses_encoding_detector"
        and fact.object == "sakura::CharsetDetector::Detect"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CFileLoad::FileOpen"
        and fact.predicate == "tracks_bom_status"
        and fact.payload.get("operation_kind") == "bom_detected"
        for fact in relations
    )


def test_file_loading_question_returns_open_detection_and_conversion_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "ファイル読み込み・文字コード判定はどう行われる？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CFileLoad::FileOpen"
        and fact.payload.get("route_kind") == "file_open_encoding_trace"
        and "sakura::CCodeMediator::CheckKanjiCode" in fact.route
        and "sakura::CCodeFactory::CreateCodeBase" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CFileLoad::ReadLine_core"
        and fact.payload.get("route_kind") == "line_read_conversion_trace"
        and "sakura::CFileLoad::GetNextLineCharCode" in fact.route
        and "sakura::CIoBridge::FileToImpl" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CCodeMediator::CheckKanjiCode"
        and fact.payload.get("route_kind") == "encoding_detector_trace"
        and "sakura::CharsetDetector::Detect" in fact.route
        and "sakura::CESI::CheckKanjiCode" in fact.route
        for fact in bundle.facts
    ), payload


def test_sakura_file_loading_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
