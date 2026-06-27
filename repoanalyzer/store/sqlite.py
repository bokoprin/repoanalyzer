from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from repoanalyzer.core.models import CodeFact
from repoanalyzer.core.source_kinds import CPP_HEADER_EXTENSIONS, CPP_SOURCE_EXTENSIONS
from repoanalyzer import __version__
from .schema import SCHEMA_SQL, SCHEMA_VERSION


@dataclass(frozen=True)
class FileIndexEntry:
    path: str
    language: str
    source_kind: str
    size_bytes: int
    sha256: str
    line_count: int
    mtime_ns: int
    indexed_at: str
    status: str


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = self.connect()
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init(self, reset: bool = False) -> None:
        if reset and self.db_path.exists():
            self.db_path.unlink()
        with self.connection() as con:
            con.executescript(SCHEMA_SQL)
            con.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, name)
                VALUES(?, ?)
                """,
                (SCHEMA_VERSION, f"schema_v{SCHEMA_VERSION}"),
            )
            con.execute(
                """
                INSERT INTO index_metadata(key, value_json)
                VALUES('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (json.dumps(SCHEMA_VERSION),),
            )
            con.execute(
                """
                INSERT INTO index_metadata(key, value_json)
                VALUES('tool_version', ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (json.dumps(__version__),),
            )

    def clear(self) -> None:
        with self.connection() as con:
            con.execute("DELETE FROM facts")
            con.execute("DELETE FROM files")
            con.execute("DELETE FROM file_index")

    def upsert_file(
        self,
        path: str,
        text: str,
        language: str = "cpp",
        *,
        absolute_path: str | Path | None = None,
        source_kind: str | None = None,
    ) -> None:
        digest = file_sha256_from_text(text)
        size = len(text.encode("utf-8", errors="replace"))
        line_count = len(text.splitlines())
        mtime_ns = _mtime_ns(absolute_path)
        kind = source_kind or _source_kind(path)
        with self.connection() as con:
            con.execute(
                """
                INSERT INTO files(path, language, size_bytes, sha256, line_count)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  language=excluded.language,
                  size_bytes=excluded.size_bytes,
                  sha256=excluded.sha256,
                  line_count=excluded.line_count
                """,
                (path, language, size, digest, line_count),
            )
            con.execute(
                """
                INSERT INTO file_index(path, language, source_kind, size_bytes, sha256, line_count, mtime_ns, status)
                VALUES(?, ?, ?, ?, ?, ?, ?, 'indexed')
                ON CONFLICT(path) DO UPDATE SET
                  language=excluded.language,
                  source_kind=excluded.source_kind,
                  size_bytes=excluded.size_bytes,
                  sha256=excluded.sha256,
                  line_count=excluded.line_count,
                  mtime_ns=excluded.mtime_ns,
                  indexed_at=CURRENT_TIMESTAMP,
                  status='indexed'
                """,
                (path, language, kind, size, digest, line_count, mtime_ns),
            )

    def set_metadata(self, key: str, value: Any) -> None:
        with self.connection() as con:
            con.execute(
                """
                INSERT INTO index_metadata(key, value_json)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )

    def set_metadata_many(self, values: dict[str, Any]) -> None:
        if not values:
            return
        with self.connection() as con:
            con.executemany(
                """
                INSERT INTO index_metadata(key, value_json)
                VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json=excluded.value_json,
                  updated_at=CURRENT_TIMESTAMP
                """,
                [(key, json.dumps(value, ensure_ascii=False, sort_keys=True)) for key, value in values.items()],
            )

    def get_metadata(self, key: str) -> Any | None:
        with self.connection() as con:
            row = con.execute("SELECT value_json FROM index_metadata WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def all_metadata(self) -> dict[str, Any]:
        with self.connection() as con:
            rows = con.execute("SELECT key, value_json FROM index_metadata ORDER BY key").fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    def file_index_entries(self) -> list[FileIndexEntry]:
        with self.connection() as con:
            rows = con.execute("SELECT * FROM file_index ORDER BY path").fetchall()
        return [
            FileIndexEntry(
                path=row["path"],
                language=row["language"],
                source_kind=row["source_kind"],
                size_bytes=int(row["size_bytes"]),
                sha256=row["sha256"],
                line_count=int(row["line_count"]),
                mtime_ns=int(row["mtime_ns"]),
                indexed_at=row["indexed_at"],
                status=row["status"],
            )
            for row in rows
        ]


    def delete_paths(self, paths: Iterable[str]) -> None:
        path_list = list(paths)
        if not path_list:
            return
        placeholders = ",".join("?" for _ in path_list)
        with self.connection() as con:
            con.execute(f"DELETE FROM facts WHERE path IN ({placeholders})", tuple(path_list))
            con.execute(f"DELETE FROM files WHERE path IN ({placeholders})", tuple(path_list))
            con.execute(f"DELETE FROM file_index WHERE path IN ({placeholders})", tuple(path_list))

    def replace_all_facts(self, facts: Iterable[CodeFact]) -> None:
        rows = []
        for fact in facts:
            rows.append(
                (
                    fact.fact_type,
                    fact.path,
                    fact.start_line,
                    fact.end_line,
                    fact.subject,
                    fact.predicate,
                    fact.object,
                    fact.symbol,
                    fact.qualified_name,
                    fact.kind,
                    fact.caller,
                    fact.callee,
                    fact.call_kind,
                    json.dumps(fact.route, ensure_ascii=False),
                    fact.confidence,
                    fact.source,
                    json.dumps(fact.payload, ensure_ascii=False),
                )
            )
        with self.connection() as con:
            con.execute("DELETE FROM facts")
            if rows:
                con.executemany(
                    """
                    INSERT INTO facts(
                      fact_type, path, start_line, end_line, subject, predicate, object,
                      symbol, qualified_name, kind, caller, callee, call_kind, route_json,
                      confidence, source, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )

    def insert_facts(self, facts: Iterable[CodeFact]) -> None:
        rows = []
        for fact in facts:
            rows.append(
                (
                    fact.fact_type,
                    fact.path,
                    fact.start_line,
                    fact.end_line,
                    fact.subject,
                    fact.predicate,
                    fact.object,
                    fact.symbol,
                    fact.qualified_name,
                    fact.kind,
                    fact.caller,
                    fact.callee,
                    fact.call_kind,
                    json.dumps(fact.route, ensure_ascii=False),
                    fact.confidence,
                    fact.source,
                    json.dumps(fact.payload, ensure_ascii=False),
                )
            )
        if not rows:
            return
        with self.connection() as con:
            con.executemany(
                """
                INSERT INTO facts(
                  fact_type, path, start_line, end_line, subject, predicate, object,
                  symbol, qualified_name, kind, caller, callee, call_kind, route_json,
                  confidence, source, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def query_facts(
        self,
        where: str = "1=1",
        params: tuple = (),
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[CodeFact]:
        sql = f"SELECT * FROM facts WHERE {where} ORDER BY path, start_line, fact_id"
        query_params: tuple = params
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            if offset < 0:
                raise ValueError("offset must be non-negative")
            sql += " LIMIT ? OFFSET ?"
            query_params = params + (limit, offset)
        elif offset:
            if offset < 0:
                raise ValueError("offset must be non-negative")
            sql += " LIMIT -1 OFFSET ?"
            query_params = params + (offset,)
        with self.connection() as con:
            rows = con.execute(sql, query_params).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def all_facts(self, *, limit: int | None = None, offset: int = 0) -> list[CodeFact]:
        return self.query_facts(limit=limit, offset=offset)

    def get_file_text(self, repo: str | Path, path: str) -> str:
        file_path = Path(repo).expanduser().resolve() / path
        return file_path.read_text(encoding="utf-8", errors="replace")

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> CodeFact:
        return CodeFact(
            fact_type=row["fact_type"],
            path=row["path"],
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            symbol=row["symbol"],
            qualified_name=row["qualified_name"],
            kind=row["kind"],
            caller=row["caller"],
            callee=row["callee"],
            call_kind=row["call_kind"],
            route=json.loads(row["route_json"] or "[]"),
            confidence=row["confidence"],
            source=row["source"],
            payload=json.loads(row["payload_json"] or "{}"),
        )


def file_sha256_from_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _mtime_ns(path: str | Path | None) -> int:
    if path is None:
        return 0
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return 0


def _source_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in CPP_SOURCE_EXTENSIONS:
        return "source"
    if suffix in CPP_HEADER_EXTENSIONS:
        return "header"
    return "unknown"
