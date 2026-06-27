from __future__ import annotations

from pathlib import Path

INDEX_DIR_NAME = ".repoanalyzer-index"
INDEX_DB_NAME = "index.sqlite3"


def index_dir(repo: str | Path) -> Path:
    return Path(repo).expanduser().resolve() / INDEX_DIR_NAME


def index_db_path(repo: str | Path) -> Path:
    return index_dir(repo) / INDEX_DB_NAME
