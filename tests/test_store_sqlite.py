from pathlib import Path

from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.core.models import CodeFact


def test_sqlite_store_roundtrip(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "index.sqlite3")
    store.init(reset=True)
    store.upsert_file("src/a.cpp", "void f() {}")
    store.insert_facts([
        CodeFact(fact_type="call", path="src/a.cpp", start_line=1, end_line=1, caller="main", callee="f")
    ])
    facts = store.query_facts("fact_type='call' AND callee=?", ("f",))
    assert len(facts) == 1
    assert facts[0].caller == "main"
