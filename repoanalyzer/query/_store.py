from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.paths import index_db_path
from repoanalyzer.store.sqlite import SQLiteStore


def open_store(repo: str | Path) -> SQLiteStore:
    db = index_db_path(repo)
    if not db.exists():
        raise FileNotFoundError(f"Index not found: {db}. Run `repoanalyzer ingest <repo>` first.")
    return SQLiteStore(db)
