from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.query import find_callers, find_definitions
from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.store.status import repo_index_status
from repoanalyzer.core.paths import index_db_path


BASIC_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "basic_call"


def _write_basic_repo(root: Path) -> None:
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "main.cpp").write_text("void target() {}\nvoid caller() { target(); }\n", encoding="utf-8")


def test_phase5a_schema_metadata_file_index_and_status_transitions(tmp_path: Path) -> None:
    _write_basic_repo(tmp_path)
    result = ingest_repo(tmp_path, reset=True)
    assert result.files == 1

    store = SQLiteStore(index_db_path(tmp_path))
    metadata = store.all_metadata()
    assert metadata["schema_version"] >= 2
    assert metadata["repo_root"] == str(tmp_path.resolve())
    assert metadata["indexed_file_count"] == 1
    assert metadata["fact_count"] == result.facts

    entries = store.file_index_entries()
    assert len(entries) == 1
    assert entries[0].path == "src/main.cpp"
    assert entries[0].source_kind == "source"
    assert entries[0].sha256
    assert entries[0].mtime_ns > 0

    clean = repo_index_status(tmp_path)
    assert clean.status == "clean"
    assert clean.indexed_files == 1
    assert clean.current_files == 1

    (tmp_path / "src" / "main.cpp").write_text("void target() {}\nvoid caller() { target(); }\nvoid newer() {}\n", encoding="utf-8")
    stale = repo_index_status(tmp_path)
    assert stale.status == "dirty"
    assert [item.path for item in stale.stale] == ["src/main.cpp"]

    (tmp_path / "src" / "main.cpp").unlink()
    missing = repo_index_status(tmp_path)
    assert missing.status == "dirty"
    assert [item.path for item in missing.missing] == ["src/main.cpp"]

    (tmp_path / "src" / "extra.cpp").write_text("void extra() {}\n", encoding="utf-8")
    changed = repo_index_status(tmp_path)
    assert [item.path for item in changed.new] == ["src/extra.cpp"]


def test_phase5a_query_pagination_primitives() -> None:
    ingest_repo(BASIC_FIXTURE, reset=True)
    store = SQLiteStore(index_db_path(BASIC_FIXTURE))

    all_facts = store.query_facts("fact_type='symbol'")
    first_page = store.query_facts("fact_type='symbol'", limit=1, offset=0)
    second_page = store.query_facts("fact_type='symbol'", limit=1, offset=1)

    assert len(first_page) == 1
    assert len(second_page) == 1
    assert first_page[0].to_dict() != second_page[0].to_dict()
    assert [first_page[0].to_dict(), second_page[0].to_dict()] == [fact.to_dict() for fact in all_facts[:2]]


def test_phase5a_exclude_patterns_are_respected(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "vendor").mkdir()
    (tmp_path / "generated").mkdir()
    (tmp_path / "src" / "main.cpp").write_text("void kept() {}\n", encoding="utf-8")
    (tmp_path / "vendor" / "ignored.cpp").write_text("void ignored_vendor() {}\n", encoding="utf-8")
    (tmp_path / "generated" / "ignored.cpp").write_text("void ignored_generated() {}\n", encoding="utf-8")
    config = tmp_path / "repoanalyzer.yml"
    config.write_text(
        "index:\n  exclude_patterns:\n    - vendor/**\n    - generated/**\n",
        encoding="utf-8",
    )

    result = ingest_repo(tmp_path, config_path=config, reset=True)
    assert result.files == 1
    assert len(find_definitions(tmp_path, "kept")) == 1
    assert find_definitions(tmp_path, "ignored_vendor") == []
    assert find_definitions(tmp_path, "ignored_generated") == []

    status = repo_index_status(tmp_path)
    assert status.status == "clean"
    assert status.current_files == 1
    assert status.metadata["exclude_patterns"] == ["vendor/**", "generated/**"]


def test_phase5a_collect_evidence_reports_index_freshness_unknown(tmp_path: Path) -> None:
    _write_basic_repo(tmp_path)
    ingest_repo(tmp_path, reset=True)

    (tmp_path / "src" / "main.cpp").write_text("void target() {}\nvoid caller() { target(); }\nvoid changed() {}\n", encoding="utf-8")

    bundle = collect_evidence(tmp_path, "target はどこから呼ばれる？", mode="callers")
    assert any(unknown.unknown_type == "index_freshness" for unknown in bundle.unknowns)
    assert any("re-run ingest" in constraint for constraint in bundle.response_constraints)


def test_phase5a_cli_repo_status_smoke(tmp_path: Path) -> None:
    _write_basic_repo(tmp_path)
    ingest_repo(tmp_path, reset=True)
    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "repo-status", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    payload = json.loads(proc.stdout)
    assert payload["status"] == "clean"
    assert payload["indexed_files"] == 1
