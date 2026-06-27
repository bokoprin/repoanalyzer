from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.query import find_callers, find_definitions
from repoanalyzer.store.status import repo_index_status
from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.core.paths import index_db_path


def _write_repo(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "device.cpp").write_text("void target() {}\n", encoding="utf-8")
    (root / "src" / "main.cpp").write_text("void caller() { target(); }\n", encoding="utf-8")


def test_phase5b_incremental_reindexes_changed_source_without_duplicates(tmp_path: Path) -> None:
    _write_repo(tmp_path)
    full = ingest_repo(tmp_path, reset=True)
    assert full.status == "indexed"
    assert [fact.caller for fact in find_callers(tmp_path, "target")] == ["caller"]

    (tmp_path / "src" / "main.cpp").write_text(
        "void caller() { target(); }\nvoid new_caller() { target(); }\n",
        encoding="utf-8",
    )
    dirty = repo_index_status(tmp_path)
    assert [item.path for item in dirty.stale] == ["src/main.cpp"]

    result = ingest_repo(tmp_path, reset=False, incremental=True)
    assert result.mode == "incremental"
    assert result.status == "indexed"
    assert result.changed_files == ["src/main.cpp"]
    assert result.full_reingest_required is False

    callers = find_callers(tmp_path, "target")
    assert [fact.caller for fact in callers] == ["caller", "new_caller"]
    assert repo_index_status(tmp_path).status == "clean"

    # Running again is a no-op and does not duplicate facts.
    noop = ingest_repo(tmp_path, reset=False, incremental=True)
    assert noop.status == "clean"
    callers_after_noop = find_callers(tmp_path, "target")
    assert [fact.caller for fact in callers_after_noop] == ["caller", "new_caller"]


def test_phase5b_incremental_removes_deleted_source_facts(tmp_path: Path) -> None:
    _write_repo(tmp_path)
    ingest_repo(tmp_path, reset=True)
    assert find_definitions(tmp_path, "caller")

    (tmp_path / "src" / "main.cpp").unlink()
    result = ingest_repo(tmp_path, reset=False, incremental=True)

    assert result.status == "indexed"
    assert result.missing_files == ["src/main.cpp"]
    assert find_definitions(tmp_path, "caller") == []
    assert find_callers(tmp_path, "target") == []
    assert repo_index_status(tmp_path).status == "clean"


def test_phase5b_incremental_requires_full_reingest_for_header_change(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "include").mkdir(parents=True)
    (tmp_path / "include" / "device.h").write_text("void target();\n", encoding="utf-8")
    (tmp_path / "src" / "device.cpp").write_text('#include "device.h"\nvoid target() {}\n', encoding="utf-8")
    ingest_repo(tmp_path, reset=True)

    (tmp_path / "include" / "device.h").write_text("void target();\nvoid new_header_decl();\n", encoding="utf-8")
    before_facts = len(SQLiteStore(index_db_path(tmp_path)).all_facts())
    result = ingest_repo(tmp_path, reset=False, incremental=True)

    assert result.status == "full_reingest_required"
    assert result.full_reingest_required is True
    assert "header changes" in (result.message or "")
    assert len(SQLiteStore(index_db_path(tmp_path)).all_facts()) == before_facts
    assert repo_index_status(tmp_path).status == "dirty"


def test_phase5b_incremental_requires_full_reingest_for_compile_commands_change(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.cpp").write_text("void main_entry() {}\n", encoding="utf-8")
    compile_commands = tmp_path / "compile_commands.json"
    compile_commands.write_text(
        json.dumps([
            {"directory": str(tmp_path), "command": "g++ -c src/main.cpp", "file": "src/main.cpp"}
        ]),
        encoding="utf-8",
    )
    config = tmp_path / "repoanalyzer.yml"
    config.write_text("cpp:\n  compile_commands: compile_commands.json\n", encoding="utf-8")

    ingest_repo(tmp_path, config_path=config, reset=True)
    compile_commands.write_text(
        json.dumps([
            {"directory": str(tmp_path), "command": "g++ -DCHANGED=1 -c src/main.cpp", "file": "src/main.cpp"}
        ]),
        encoding="utf-8",
    )

    result = ingest_repo(tmp_path, config_path=config, reset=False, incremental=True)
    assert result.status == "full_reingest_required"
    assert result.full_reingest_required is True
    assert "build context" in (result.message or "")


def test_phase5b_cli_incremental_smoke(tmp_path: Path) -> None:
    _write_repo(tmp_path)
    ingest_repo(tmp_path, reset=True)
    (tmp_path / "src" / "main.cpp").write_text(
        "void caller() { target(); }\nvoid cli_new_caller() { target(); }\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "ingest", str(tmp_path), "--incremental"],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    payload = json.loads(proc.stdout)
    assert payload["mode"] == "incremental"
    assert payload["status"] == "indexed"
    assert payload["changed_files"] == ["src/main.cpp"]
    assert [fact.caller for fact in find_callers(tmp_path, "target")] == ["caller", "cli_new_caller"]
