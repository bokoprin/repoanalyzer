from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._store import open_store

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_sakura_config_profile"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_config_profile_semantic_relations_are_extracted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    relations = open_store(repo).query_facts(active_fact_where("fact_type='relation'"))

    assert any(
        fact.subject == "sakura::CShareData_IO::LoadShareData"
        and fact.predicate == "runs_profile_io"
        and fact.object == "sakura::CShareData_IO::ShareData_IO_2"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CShareData_IO::ShareData_IO_2"
        and fact.predicate == "reads_profile"
        and fact.object == "sakura::CDataProfile::ReadProfile"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CShareData_IO::ShareData_IO_2"
        and fact.predicate == "writes_profile"
        and fact.object == "sakura::CDataProfile::WriteProfile"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CShareData_IO::ShareData_IO_2"
        and fact.predicate == "loads_config_section"
        and fact.object == "sakura::CShareData_IO::ShareData_IO_Common"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CShareData_IO::ShareData_IO_2"
        and fact.predicate == "accesses_common_setting"
        and fact.object == "sakura::DLLSHAREDATA::m_Common"
        for fact in relations
    )
    assert any(
        fact.subject == "sakura::CShareData_IO::ShareData_IO_Mru"
        and fact.predicate == "maps_profile_key"
        and fact.object == "sakura::CDataProfile::IOProfileData"
        for fact in relations
    )


def test_config_profile_question_returns_load_save_and_section_traces(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    bundle = collect_evidence(repo, "設定読み書き / CShareData / CommonSetting / profile / ini系はどう行われる？")
    payload = bundle.to_dict()

    assert bundle.answerability == "answerable"
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CShareData_IO::ShareData_IO_2"
        and fact.payload.get("route_kind") == "profile_core_io_trace"
        and "sakura::CDataProfile::ReadProfile" in fact.route
        and "sakura::CShareData_IO::ShareData_IO_Common" in fact.route
        and "sakura::CDataProfile::WriteProfile" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CShareData_IO::ShareData_IO_Mru"
        and fact.payload.get("route_kind") == "mru_section_profile_mapping_trace"
        and "sakura::GetDllShareData" in fact.route
        and "sakura::CDataProfile::IOProfileData" in fact.route
        for fact in bundle.facts
    ), payload
    assert any(
        fact.fact_type == "call_path"
        and fact.subject == "sakura::CShareData_IO::LoadShareData"
        and fact.payload.get("route_kind") == "load_share_data_trace"
        for fact in bundle.facts
    ), payload


def test_sakura_config_profile_fixture_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    ingest_repo(repo)

    result = run_eval(repo, repo / "cases.yaml")

    assert result.failed == 0, result.to_dict()
