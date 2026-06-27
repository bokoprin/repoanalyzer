from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from repoanalyzer.models import ChunkLocation as ChunkLocationModel
from repoanalyzer.models import (
    ChunkRecord,
    DependencyRecord,
    RetrievedChunk,
    ScannedFile,
    SummaryRecord,
    SymbolRecord,
    SymbolReferenceRecord,
)
from repoanalyzer.search.tokenizer import tokenize_code_query

SCHEMA_VERSION = "2"


class IndexStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._transaction_depth = 0
        self._apply_pragmas()
        self._ensure_runtime_indexes()

    def _apply_pragmas(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        cursor.execute("PRAGMA temp_store = MEMORY;")
        cursor.execute("PRAGMA foreign_keys = ON;")

    def _ensure_runtime_indexes(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='symbol_refs'")
        if cursor.fetchone() is None:
            return
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_symbol_refs_name
            ON symbol_refs(name)
            """
        )
        self.connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        is_outer = self._transaction_depth == 0
        if is_outer and not self.connection.in_transaction:
            self.connection.execute("BEGIN")
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            if is_outer and self.connection.in_transaction:
                self.connection.rollback()
            raise
        else:
            if is_outer and self.connection.in_transaction:
                self.connection.commit()
        finally:
            self._transaction_depth = max(self._transaction_depth - 1, 0)

    def _maybe_commit(self, commit: bool) -> None:
        if commit and self._transaction_depth == 0 and self.connection.in_transaction:
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def init_schema(self) -> None:
        cursor = self.connection.cursor()
        cursor.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                language TEXT,
                size_bytes INTEGER NOT NULL,
                line_count INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts
            USING fts5(path, symbol, content);

            CREATE TABLE IF NOT EXISTS embeddings (
                chunk_id INTEGER PRIMARY KEY,
                model TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS embeddings_v2 (
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                chunk_id INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY(model, model_version, chunk_id),
                FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS embedding_subchunks (
                id INTEGER PRIMARY KEY,
                parent_chunk_id INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                subchunk_index INTEGER NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                focus_line INTEGER NOT NULL,
                token_estimate INTEGER NOT NULL,
                source_kind TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                UNIQUE(parent_chunk_id, subchunk_index),
                FOREIGN KEY(parent_chunk_id) REFERENCES chunks(id) ON DELETE CASCADE,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS embedding_subchunk_vectors_v2 (
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                subchunk_id INTEGER NOT NULL,
                vector_json TEXT NOT NULL,
                PRIMARY KEY(model, model_version, subchunk_id),
                FOREIGN KEY(subchunk_id) REFERENCES embedding_subchunks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS query_embedding_cache (
                model TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(model, query_hash)
            );

            CREATE TABLE IF NOT EXISTS retrieval_events (
                id INTEGER PRIMARY KEY,
                ts TEXT NOT NULL,
                query_hash TEXT NOT NULL,
                stage TEXT NOT NULL,
                k INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                hit_count INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS symbols (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                signature TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS symbol_refs (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                line INTEGER NOT NULL,
                context TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS symbol_aliases (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                raw_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                line INTEGER NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS dependencies (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                line INTEGER NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS call_edges (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                caller TEXT NOT NULL,
                callee TEXT NOT NULL,
                line INTEGER NOT NULL,
                kind TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS graph_precompute (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                target TEXT NOT NULL,
                kind TEXT NOT NULL,
                line INTEGER NOT NULL,
                weight REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY,
                level TEXT NOT NULL,
                path TEXT NOT NULL,
                parent_path TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(level, path)
            );

            CREATE TABLE IF NOT EXISTS v2_file_roles (
                file_id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                role TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS v2_field_accesses (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                field_name TEXT NOT NULL,
                owner_type TEXT NOT NULL,
                line INTEGER NOT NULL,
                access_kind TEXT NOT NULL,
                symbol_name TEXT NOT NULL,
                context TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS v2_config_relations (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                config_key_or_type TEXT NOT NULL,
                relation_kind TEXT NOT NULL,
                line INTEGER NOT NULL,
                symbol_name TEXT NOT NULL,
                confidence REAL NOT NULL,
                context TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS v2_snippet_spans (
                id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                focus_line INTEGER NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_symbol_refs_name
            ON symbol_refs(name);

            CREATE INDEX IF NOT EXISTS idx_embedding_subchunks_parent
            ON embedding_subchunks(parent_chunk_id);

            CREATE INDEX IF NOT EXISTS idx_embedding_subchunks_file
            ON embedding_subchunks(file_id);

            CREATE INDEX IF NOT EXISTS idx_embedding_subchunks_path
            ON embedding_subchunks(path);
            """
        )
        self.connection.commit()

    def ensure_schema_version(self, expected_version: str = SCHEMA_VERSION) -> None:
        current = self.load_meta("schema_version")
        if current is None:
            self.save_meta("schema_version", expected_version)
            return
        if current == expected_version:
            return
        msg = (
            "schema version mismatch: "
            f"current={current}, expected={expected_version}. "
            "run ingest with --force to rebuild the index."
        )
        raise RuntimeError(msg)

    def set_schema_version(self, version: str = SCHEMA_VERSION, commit: bool = True) -> None:
        self.save_meta("schema_version", version, commit=commit)

    def clear_all(self, commit: bool = True) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM chunk_fts")
        cursor.execute("DELETE FROM chunks")
        cursor.execute("DELETE FROM files")
        cursor.execute("DELETE FROM embeddings")
        cursor.execute("DELETE FROM embeddings_v2")
        cursor.execute("DELETE FROM embedding_subchunk_vectors_v2")
        cursor.execute("DELETE FROM embedding_subchunks")
        cursor.execute("DELETE FROM symbols")
        cursor.execute("DELETE FROM symbol_refs")
        cursor.execute("DELETE FROM symbol_aliases")
        cursor.execute("DELETE FROM dependencies")
        cursor.execute("DELETE FROM call_edges")
        cursor.execute("DELETE FROM graph_precompute")
        cursor.execute("DELETE FROM summaries")
        cursor.execute("DELETE FROM v2_file_roles")
        cursor.execute("DELETE FROM v2_field_accesses")
        cursor.execute("DELETE FROM v2_config_relations")
        cursor.execute("DELETE FROM v2_snippet_spans")
        cursor.execute("DELETE FROM query_embedding_cache")
        cursor.execute("DELETE FROM retrieval_events")
        cursor.execute("DELETE FROM meta")
        self._maybe_commit(commit)

    def upsert_file(self, scanned_file: ScannedFile, commit: bool = True) -> int:
        now = datetime.now(UTC).isoformat()
        cursor = self.connection.cursor()
        cursor.execute(
            """
            INSERT INTO files(path, language, size_bytes, line_count, sha256, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
              language=excluded.language,
              size_bytes=excluded.size_bytes,
              line_count=excluded.line_count,
              sha256=excluded.sha256,
              updated_at=excluded.updated_at
            """,
            (
                scanned_file.relative_path,
                scanned_file.language,
                scanned_file.size_bytes,
                scanned_file.line_count,
                scanned_file.sha256,
                now,
            ),
        )
        cursor.execute("SELECT id FROM files WHERE path = ?", (scanned_file.relative_path,))
        row = cursor.fetchone()
        if row is None:
            msg = f"failed to load file row for {scanned_file.relative_path}"
            raise RuntimeError(msg)
        file_id = int(row["id"])
        self._maybe_commit(commit)
        return file_id

    def replace_chunks_for_file(
        self,
        file_id: int,
        path: str,
        chunks: list[ChunkRecord],
        commit: bool = True,
    ) -> list[int]:
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,))
        existing_ids = [int(row["id"]) for row in cursor.fetchall()]
        for chunk_id in existing_ids:
            cursor.execute("DELETE FROM chunk_fts WHERE rowid = ?", (chunk_id,))
        cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

        inserted_rowids: list[int] = []
        for chunk in chunks:
            cursor.execute(
                """
                INSERT INTO chunks(
                  file_id, path, start_line, end_line, symbol, content, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    chunk.start_line,
                    chunk.end_line,
                    chunk.symbol,
                    chunk.content,
                    chunk.content_hash,
                ),
            )
            rowid = cursor.lastrowid
            if rowid is None:
                msg = f"failed to insert chunk for {path}"
                raise RuntimeError(msg)
            cursor.execute(
                """
                INSERT INTO chunk_fts(rowid, path, symbol, content)
                VALUES (?, ?, ?, ?)
                """,
                (rowid, path, chunk.symbol, chunk.content),
            )
            inserted_rowids.append(int(rowid))
        self._maybe_commit(commit)
        return inserted_rowids

    def save_meta(self, key: str, value: str, commit: bool = True) -> None:
        self.connection.execute(
            """
            INSERT INTO meta(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        self._maybe_commit(commit)

    def load_meta(self, key: str) -> str | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row is None:
            return None
        return str(row["value"])

    def load_ltr_weights(self, default: list[float] | None = None) -> list[float]:
        fallback = default or [1.0, 0.3, 0.1]
        raw = self.load_meta("ltr_weights_json")
        if raw is None:
            return fallback
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return fallback
        if not isinstance(payload, list):
            return fallback
        values: list[float] = []
        for item in payload[:3]:
            try:
                values.append(float(item))
            except (TypeError, ValueError):
                continue
        if len(values) != 3:
            return fallback
        return values

    def save_ltr_weights(self, weights: list[float], commit: bool = True) -> None:
        normalized = [float(value) for value in weights[:3]]
        if len(normalized) < 3:
            normalized.extend([0.0] * (3 - len(normalized)))
        self.save_meta("ltr_weights_json", json.dumps(normalized), commit=commit)

    def log_retrieval_event(
        self,
        query_hash: str,
        stage: str,
        k: int,
        latency_ms: float,
        hit_count: int,
        payload: dict[str, object] | None = None,
        commit: bool = True,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        self.connection.execute(
            """
            INSERT INTO retrieval_events(
              ts, query_hash, stage, k, latency_ms, hit_count, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now, query_hash, stage, k, float(latency_ms), int(hit_count), payload_json),
        )
        self._maybe_commit(commit)

    def list_retrieval_events(
        self,
        stage: str | None = None,
        limit: int = 200,
    ) -> list[tuple[str, str, str, int, float, int]]:
        cursor = self.connection.cursor()
        if stage:
            cursor.execute(
                """
                SELECT ts, query_hash, stage, k, latency_ms, hit_count
                FROM retrieval_events
                WHERE stage = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (stage, limit),
            )
        else:
            cursor.execute(
                """
                SELECT ts, query_hash, stage, k, latency_ms, hit_count
                FROM retrieval_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [
            (
                str(row["ts"]),
                str(row["query_hash"]),
                str(row["stage"]),
                int(row["k"]),
                float(row["latency_ms"]),
                int(row["hit_count"]),
            )
            for row in cursor.fetchall()
        ]

    def delete_file_by_path(self, path: str, commit: bool = True) -> None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM files WHERE path = ?", (path,))
        row = cursor.fetchone()
        if row is None:
            return
        file_id = int(row["id"])
        cursor.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,))
        chunk_ids = [int(chunk_row["id"]) for chunk_row in cursor.fetchall()]
        for chunk_id in chunk_ids:
            cursor.execute("DELETE FROM chunk_fts WHERE rowid = ?", (chunk_id,))
            cursor.execute("DELETE FROM embeddings WHERE chunk_id = ?", (chunk_id,))
            cursor.execute("DELETE FROM embeddings_v2 WHERE chunk_id = ?", (chunk_id,))
        cursor.execute("DELETE FROM graph_precompute WHERE path = ? OR target = ?", (path, path))
        cursor.execute("DELETE FROM v2_file_roles WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_field_accesses WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_config_relations WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_snippet_spans WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
        self._maybe_commit(commit)

    def save_manifest(self, payload: dict[str, object], commit: bool = True) -> None:
        self.save_meta(
            "manifest_json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            commit=commit,
        )

    def fetch_manifest_records(self) -> list[tuple[str, str, int, int]]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT path, language, size_bytes, line_count
            FROM files
            ORDER BY path
            """,
        )
        return [
            (
                str(row["path"]),
                str(row["language"] or "unknown"),
                int(row["size_bytes"]),
                int(row["line_count"]),
            )
            for row in cursor.fetchall()
        ]

    def fetch_file_hashes(self) -> dict[str, str]:
        cursor = self.connection.cursor()
        cursor.execute("SELECT path, sha256 FROM files")
        rows = cursor.fetchall()
        return {str(row["path"]): str(row["sha256"]) for row in rows}

    def fetch_file_summary_inputs(self) -> list[dict[str, object]]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT
              files.path AS path,
              files.language AS language,
              files.line_count AS line_count,
              files.size_bytes AS size_bytes,
              (
                SELECT COUNT(*)
                FROM symbols
                WHERE symbols.file_id = files.id
              ) AS symbol_count,
              (
                SELECT COUNT(*)
                FROM dependencies
                WHERE dependencies.file_id = files.id
              ) AS dependency_count,
              (
                SELECT COUNT(*)
                FROM chunks
                WHERE chunks.file_id = files.id
              ) AS chunk_count
            FROM files
            ORDER BY files.path
            """,
        )
        rows = cursor.fetchall()
        return [
            {
                "path": str(row["path"]),
                "language": str(row["language"] or "unknown"),
                "line_count": int(row["line_count"]),
                "size_bytes": int(row["size_bytes"]),
                "symbol_count": int(row["symbol_count"] or 0),
                "dependency_count": int(row["dependency_count"] or 0),
                "chunk_count": int(row["chunk_count"] or 0),
            }
            for row in rows
        ]

    def replace_symbols_for_file(
        self,
        file_id: int,
        path: str,
        symbols: list[SymbolRecord],
        references: list[SymbolReferenceRecord],
        commit: bool = True,
    ) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM symbol_refs WHERE file_id = ?", (file_id,))

        for symbol in symbols:
            cursor.execute(
                """
                INSERT INTO symbols(file_id, path, name, kind, start_line, end_line, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    symbol.name,
                    symbol.kind,
                    symbol.start_line,
                    symbol.end_line,
                    symbol.signature,
                ),
            )
        for ref in references:
            cursor.execute(
                """
                INSERT INTO symbol_refs(file_id, path, name, line, context)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    ref.name,
                    ref.line,
                    ref.context,
                ),
            )
        self._maybe_commit(commit)

    def replace_symbol_aliases_for_file(
        self,
        file_id: int,
        path: str,
        aliases: list[tuple[str, str, str, int]],
        commit: bool = True,
    ) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM symbol_aliases WHERE file_id = ?", (file_id,))
        for raw_name, normalized_name, scope, line in aliases:
            cursor.execute(
                """
                INSERT INTO symbol_aliases(
                  file_id, path, raw_name, normalized_name, scope, line
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    raw_name,
                    normalized_name,
                    scope,
                    line,
                ),
            )
        self._maybe_commit(commit)

    def list_symbol_aliases(self, limit: int = 200) -> list[tuple[str, str, str, str, int]]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT path, raw_name, normalized_name, scope, line
            FROM symbol_aliases
            ORDER BY path, line, raw_name
            LIMIT ?
            """,
            (limit,),
        )
        return [
            (
                str(row["path"]),
                str(row["raw_name"]),
                str(row["normalized_name"]),
                str(row["scope"]),
                int(row["line"]),
            )
            for row in cursor.fetchall()
        ]

    def find_symbols(
        self,
        name: str | None = None,
        limit: int = 50,
    ) -> list[tuple[str, str, str, int, int, str]]:
        cursor = self.connection.cursor()
        if name:
            cursor.execute(
                """
                SELECT path, name, kind, start_line, end_line, signature
                FROM symbols
                WHERE name LIKE ?
                ORDER BY path, start_line
                LIMIT ?
                """,
                (f"{name}%", limit),
            )
        else:
            cursor.execute(
                """
                SELECT path, name, kind, start_line, end_line, signature
                FROM symbols
                ORDER BY path, start_line
                LIMIT ?
                """,
                (limit,),
            )
        return [
            (
                str(row["path"]),
                str(row["name"]),
                str(row["kind"]),
                int(row["start_line"]),
                int(row["end_line"]),
                str(row["signature"]),
            )
            for row in cursor.fetchall()
        ]

    def find_symbol_references(
        self,
        name: str,
        limit: int = 50,
    ) -> list[tuple[str, int, str]]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT path, line, context
            FROM symbol_refs
            WHERE name = ?
            ORDER BY path, line
            LIMIT ?
            """,
            (name, limit),
        )
        return [
            (str(row["path"]), int(row["line"]), str(row["context"])) for row in cursor.fetchall()
        ]

    def find_symbol_references_fuzzy(
        self,
        name: str,
        limit: int = 50,
    ) -> list[tuple[str, int, str]]:
        normalized_limit = max(int(limit), 1)
        short_name = name.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT path, line, context
            FROM symbol_refs
            WHERE name = ?
               OR name = ?
               OR name LIKE ?
               OR name LIKE ?
            ORDER BY path, line
            LIMIT ?
            """,
            (
                name,
                short_name,
                f"%::{short_name}",
                f"%.{short_name}",
                normalized_limit * 3,
            ),
        )
        rows = [
            (str(row["path"]), int(row["line"]), str(row["context"])) for row in cursor.fetchall()
        ]
        deduped: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int, str]] = set()
        for row in rows:
            if row in seen:
                continue
            seen.add(row)
            deduped.append(row)
            if len(deduped) >= normalized_limit:
                break
        return deduped

    def replace_dependencies_for_file(
        self,
        file_id: int,
        path: str,
        dependencies: list[DependencyRecord],
        commit: bool = True,
    ) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM dependencies WHERE file_id = ?", (file_id,))
        for dep in dependencies:
            cursor.execute(
                """
                INSERT INTO dependencies(file_id, path, target, kind, line)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    dep.target,
                    dep.kind,
                    dep.line,
                ),
            )
        self._maybe_commit(commit)

    def replace_v2_metadata_for_file(
        self,
        *,
        file_id: int,
        path: str,
        role: str,
        field_accesses: list[dict[str, object]],
        config_relations: list[dict[str, object]],
        snippet_spans: list[dict[str, object]],
        commit: bool = True,
    ) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM v2_file_roles WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_field_accesses WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_config_relations WHERE file_id = ?", (file_id,))
        cursor.execute("DELETE FROM v2_snippet_spans WHERE file_id = ?", (file_id,))
        cursor.execute(
            """
            INSERT INTO v2_file_roles(file_id, path, role)
            VALUES (?, ?, ?)
            """,
            (file_id, path, role),
        )
        for row in field_accesses:
            cursor.execute(
                """
                INSERT INTO v2_field_accesses(
                  file_id, path, field_name, owner_type, line, access_kind, symbol_name, context
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    str(row.get("field_name", "")),
                    str(row.get("owner_type", "")),
                    int(row.get("line", 0) or 0),
                    str(row.get("access_kind", "")),
                    str(row.get("symbol_name", "")),
                    str(row.get("context", "")),
                ),
            )
        for row in config_relations:
            cursor.execute(
                """
                INSERT INTO v2_config_relations(
                  file_id, path, config_key_or_type, relation_kind,
                  line, symbol_name, confidence, context
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    str(row.get("config_key_or_type", "")),
                    str(row.get("relation_kind", "")),
                    int(row.get("line", 0) or 0),
                    str(row.get("symbol_name", "")),
                    float(row.get("confidence", 0.0) or 0.0),
                    str(row.get("context", "")),
                ),
            )
        for row in snippet_spans:
            cursor.execute(
                """
                INSERT INTO v2_snippet_spans(
                  file_id, path, entity_type, entity_key, start_line, end_line, focus_line
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    path,
                    str(row.get("entity_type", "")),
                    str(row.get("entity_key", "")),
                    int(row.get("start_line", 0) or 0),
                    int(row.get("end_line", 0) or 0),
                    int(row.get("focus_line", 0) or 0),
                ),
            )
        self._maybe_commit(commit)

    def replace_call_edges_for_file(
        self,
        file_id: int,
        path: str,
        edges: list[tuple[str, str, int, str]],
        commit: bool = True,
    ) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM call_edges WHERE file_id = ?", (file_id,))
        for caller, callee, line, kind in edges:
            cursor.execute(
                """
                INSERT INTO call_edges(file_id, path, caller, callee, line, kind)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (file_id, path, caller, callee, line, kind),
            )
        self._maybe_commit(commit)

    def list_call_edges(
        self,
        from_prefix: str | None = None,
        limit: int = 200,
    ) -> list[tuple[str, str, str, int, str]]:
        cursor = self.connection.cursor()
        if from_prefix:
            normalized = from_prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                """
                SELECT path, caller, callee, line, kind
                FROM call_edges
                WHERE path LIKE ?
                ORDER BY path, line
                LIMIT ?
                """,
                (f"{normalized}%", limit),
            )
        else:
            cursor.execute(
                """
                SELECT path, caller, callee, line, kind
                FROM call_edges
                ORDER BY path, line
                LIMIT ?
                """,
                (limit,),
            )
        return [
            (
                str(row["path"]),
                str(row["caller"]),
                str(row["callee"]),
                int(row["line"]),
                str(row["kind"]),
            )
            for row in cursor.fetchall()
        ]

    def find_call_references(
        self,
        callee_name: str,
        limit: int = 50,
    ) -> list[tuple[str, int, str, str, str]]:
        normalized_limit = max(int(limit), 1)
        short_name = callee_name.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT path, line, caller, callee, kind
            FROM call_edges
            WHERE callee = ?
               OR callee = ?
               OR callee LIKE ?
               OR callee LIKE ?
            ORDER BY path, line
            LIMIT ?
            """,
            (
                callee_name,
                short_name,
                f"%::{short_name}",
                f"%.{short_name}",
                normalized_limit * 4,
            ),
        )
        rows = [
            (
                str(row["path"]),
                int(row["line"]),
                str(row["caller"]),
                str(row["callee"]),
                str(row["kind"]),
            )
            for row in cursor.fetchall()
        ]
        deduped: list[tuple[str, int, str, str, str]] = []
        seen: set[tuple[str, int, str, str, str]] = set()
        for row in rows:
            if row in seen:
                continue
            seen.add(row)
            deduped.append(row)
            if len(deduped) >= normalized_limit:
                break
        return deduped

    def rebuild_graph_precompute(self, commit: bool = True) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM graph_precompute")
        cursor.execute(
            """
            INSERT INTO graph_precompute(path, target, kind, line, weight)
            SELECT path, target, kind, line, 1.0
            FROM dependencies
            """
        )
        cursor.execute(
            """
            INSERT INTO graph_precompute(path, target, kind, line, weight)
            SELECT path, callee, kind, line, 0.7
            FROM call_edges
            """
        )
        cursor.execute(
            """
            INSERT INTO graph_precompute(path, target, kind, line, weight)
            SELECT
              call_edges.path,
              symbol_aliases.path AS target,
              'call-resolved',
              call_edges.line,
              0.85
            FROM call_edges
            JOIN symbol_aliases ON symbol_aliases.raw_name = call_edges.callee
            """
        )
        self._maybe_commit(commit)

    def list_graph_neighbors(
        self,
        paths: list[str],
        limit: int = 500,
    ) -> list[tuple[str, str, str, int]]:
        if not paths or limit <= 0:
            return []
        cursor = self.connection.cursor()
        collected: list[tuple[str, str, str, int]] = []
        for path in paths:
            if len(collected) >= limit:
                break
            cursor.execute(
                """
                SELECT path, target, kind, line
                FROM graph_precompute
                WHERE path = ?
                ORDER BY weight DESC, line ASC
                LIMIT ?
                """,
                (path, limit),
            )
            for row in cursor.fetchall():
                collected.append(
                    (
                        str(row["path"]),
                        str(row["target"]),
                        str(row["kind"]),
                        int(row["line"]),
                    )
                )
                if len(collected) >= limit:
                    break
        return collected

    def list_dependencies(
        self,
        from_prefix: str | None = None,
        limit: int = 200,
    ) -> list[tuple[str, str, str, int]]:
        cursor = self.connection.cursor()
        if from_prefix:
            normalized = from_prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                """
                SELECT path, target, kind, line
                FROM dependencies
                WHERE path LIKE ?
                ORDER BY path, line
                LIMIT ?
                """,
                (f"{normalized}%", limit),
            )
        else:
            cursor.execute(
                """
                SELECT path, target, kind, line
                FROM dependencies
                ORDER BY path, line
                LIMIT ?
                """,
                (limit,),
            )
        return [
            (
                str(row["path"]),
                str(row["target"]),
                str(row["kind"]),
                int(row["line"]),
            )
            for row in cursor.fetchall()
        ]

    def replace_all_summaries(self, summaries: list[SummaryRecord], commit: bool = True) -> None:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM summaries")
        now = datetime.now(UTC).isoformat()
        for record in summaries:
            cursor.execute(
                """
                INSERT INTO summaries(level, path, parent_path, summary, details_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.level,
                    record.path,
                    record.parent_path,
                    record.summary,
                    json.dumps(record.details, ensure_ascii=False),
                    now,
                ),
            )
        self._maybe_commit(commit)

    def get_summary(self, level: str, path: str) -> SummaryRecord | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT level, path, parent_path, summary, details_json
            FROM summaries
            WHERE level = ? AND path = ?
            """,
            (level, path),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return SummaryRecord(
            level=str(row["level"]),
            path=str(row["path"]),
            parent_path=str(row["parent_path"]),
            summary=str(row["summary"]),
            details=_safe_json_object(str(row["details_json"])),
        )

    def list_summaries(
        self,
        level: str,
        parent_prefix: str | None = None,
        limit: int = 50,
    ) -> list[SummaryRecord]:
        cursor = self.connection.cursor()
        if parent_prefix is None:
            cursor.execute(
                """
                SELECT level, path, parent_path, summary, details_json
                FROM summaries
                WHERE level = ?
                ORDER BY path
                LIMIT ?
                """,
                (level, limit),
            )
        else:
            normalized = parent_prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                """
                SELECT level, path, parent_path, summary, details_json
                FROM summaries
                WHERE level = ? AND parent_path LIKE ?
                ORDER BY path
                LIMIT ?
                """,
                (level, f"{normalized}%", limit),
            )
        rows = cursor.fetchall()
        return [
            SummaryRecord(
                level=str(row["level"]),
                path=str(row["path"]),
                parent_path=str(row["parent_path"]),
                summary=str(row["summary"]),
                details=_safe_json_object(str(row["details_json"])),
            )
            for row in rows
        ]

    def load_manifest(self) -> dict[str, object] | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT value FROM meta WHERE key = 'manifest_json'")
        row = cursor.fetchone()
        if row is None:
            return None
        return json.loads(str(row["value"]))

    def fetch_chunk_by_id(self, chunk_id: int) -> RetrievedChunk | None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT id, path, start_line, end_line, content
            FROM chunks
            WHERE id = ?
            """,
            (chunk_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        location = ChunkLocationModel(
            path=str(row["path"]),
            start_line=int(row["start_line"]),
            end_line=int(row["end_line"]),
        )
        return RetrievedChunk(location=location, content=str(row["content"]), score=0.0)

    def fetch_chunks_by_ids(self, chunk_ids: list[int]) -> list[RetrievedChunk]:
        if not chunk_ids:
            return []
        cursor = self.connection.cursor()
        unique_ids = list(dict.fromkeys(chunk_ids))
        by_id: dict[int, RetrievedChunk] = {}
        try:
            cursor.execute(
                """
                SELECT id, path, start_line, end_line, content
                FROM chunks
                WHERE id IN (
                  SELECT CAST(value AS INTEGER)
                  FROM json_each(?)
                )
                """,
                (json.dumps(unique_ids),),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
            for chunk_id in unique_ids:
                cursor.execute(
                    """
                    SELECT id, path, start_line, end_line, content
                    FROM chunks
                    WHERE id = ?
                    """,
                    (chunk_id,),
                )
                row = cursor.fetchone()
                if row is not None:
                    rows.append(row)
        for row in rows:
            row_id = int(row["id"])
            by_id[row_id] = RetrievedChunk(
                location=ChunkLocationModel(
                    path=str(row["path"]),
                    start_line=int(row["start_line"]),
                    end_line=int(row["end_line"]),
                ),
                content=str(row["content"]),
                score=0.0,
            )
        return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]

    def fetch_chunks_by_paths(
        self,
        paths: list[str],
        limit_per_path: int = 1,
        total_limit: int = 50,
    ) -> list[RetrievedChunk]:
        if not paths or total_limit <= 0:
            return []
        cursor = self.connection.cursor()
        fetched: list[RetrievedChunk] = []
        seen: set[tuple[str, int, int]] = set()
        per_path_limit = max(limit_per_path, 1)
        for path in paths:
            if len(fetched) >= total_limit:
                break
            cursor.execute(
                """
                SELECT path, start_line, end_line, content
                FROM chunks
                WHERE path = ?
                ORDER BY start_line
                LIMIT ?
                """,
                (path, per_path_limit),
            )
            for row in cursor.fetchall():
                key = (str(row["path"]), int(row["start_line"]), int(row["end_line"]))
                if key in seen:
                    continue
                seen.add(key)
                fetched.append(
                    RetrievedChunk(
                        location=ChunkLocationModel(
                            path=key[0],
                            start_line=key[1],
                            end_line=key[2],
                        ),
                        content=str(row["content"]),
                        score=0.0,
                    )
                )
                if len(fetched) >= total_limit:
                    break
        return fetched

    def fetch_adjacent_chunks(
        self,
        path: str,
        start_line: int,
        end_line: int,
        before: int = 1,
        after: int = 1,
    ) -> list[RetrievedChunk]:
        cursor = self.connection.cursor()
        results: list[RetrievedChunk] = []
        if before > 0:
            cursor.execute(
                """
                SELECT path, start_line, end_line, content
                FROM chunks
                WHERE path = ? AND end_line < ?
                ORDER BY end_line DESC
                LIMIT ?
                """,
                (path, start_line, before),
            )
            previous = list(cursor.fetchall())
            previous.reverse()
            for row in previous:
                results.append(
                    RetrievedChunk(
                        location=ChunkLocationModel(
                            path=str(row["path"]),
                            start_line=int(row["start_line"]),
                            end_line=int(row["end_line"]),
                        ),
                        content=str(row["content"]),
                        score=0.0,
                    )
                )
        if after > 0:
            cursor.execute(
                """
                SELECT path, start_line, end_line, content
                FROM chunks
                WHERE path = ? AND start_line > ?
                ORDER BY start_line ASC
                LIMIT ?
                """,
                (path, end_line, after),
            )
            for row in cursor.fetchall():
                results.append(
                    RetrievedChunk(
                        location=ChunkLocationModel(
                            path=str(row["path"]),
                            start_line=int(row["start_line"]),
                            end_line=int(row["end_line"]),
                        ),
                        content=str(row["content"]),
                        score=0.0,
                    )
                )
        return results

    def list_symbol_names_for_paths(self, paths: list[str], limit: int = 200) -> list[str]:
        if not paths:
            return []
        cursor = self.connection.cursor()
        collected: list[str] = []
        seen: set[str] = set()
        for path in paths:
            if len(collected) >= limit:
                break
            cursor.execute(
                """
                SELECT DISTINCT name
                FROM symbols
                WHERE path = ?
                ORDER BY name
                LIMIT ?
                """,
                (path, limit),
            )
            for row in cursor.fetchall():
                name = str(row["name"])
                if name in seen:
                    continue
                seen.add(name)
                collected.append(name)
                if len(collected) >= limit:
                    break
        return collected

    def find_reference_paths_for_name(self, name: str, limit: int = 200) -> list[str]:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            SELECT DISTINCT path
            FROM symbol_refs
            WHERE name = ?
            ORDER BY path
            LIMIT ?
            """,
            (name, limit),
        )
        return [str(row["path"]) for row in cursor.fetchall()]

    def list_dependencies_for_paths(
        self,
        paths: list[str],
        limit: int = 500,
    ) -> list[tuple[str, str, str, int]]:
        if not paths:
            return []
        cursor = self.connection.cursor()
        collected: list[tuple[str, str, str, int]] = []
        for path in paths:
            if len(collected) >= limit:
                break
            cursor.execute(
                """
                SELECT path, target, kind, line
                FROM dependencies
                WHERE path = ?
                ORDER BY line
                LIMIT ?
                """,
                (path, limit),
            )
            for row in cursor.fetchall():
                collected.append(
                    (
                        str(row["path"]),
                        str(row["target"]),
                        str(row["kind"]),
                        int(row["line"]),
                    )
                )
                if len(collected) >= limit:
                    break
        return collected

    def search_fts(
        self,
        question: str,
        limit: int,
        tokenizer_mode: str = "sudachi",
        fts_mode: str = "advanced",
    ) -> list[RetrievedChunk]:
        fts_query = _to_fts_query(
            question,
            tokenizer_mode=tokenizer_mode,
            fts_mode=fts_mode,
        )
        if not fts_query:
            return []

        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT
                  chunks.path AS path,
                  chunks.start_line AS start_line,
                  chunks.end_line AS end_line,
                  chunks.content AS content,
                  bm25(chunk_fts, 8.0, 4.0, 1.0) AS rank
                FROM chunk_fts
                JOIN chunks ON chunks.id = chunk_fts.rowid
                WHERE chunk_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (fts_query, limit),
            )
        except sqlite3.OperationalError:
            return []

        rows = cursor.fetchall()
        results: list[RetrievedChunk] = []
        for row in rows:
            location = ChunkLocationModel(
                path=str(row["path"]),
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
            )
            score = -float(row["rank"]) if row["rank"] is not None else 0.0
            results.append(
                RetrievedChunk(
                    location=location,
                    content=str(row["content"]),
                    score=score,
                )
            )
        return results

    def upsert_embeddings(
        self,
        vectors: list[tuple[int, list[float]]],
        model: str,
        model_version: str = "v1",
        commit: bool = True,
    ) -> None:
        if not vectors:
            return
        cursor = self.connection.cursor()
        cursor.executemany(
            """
            INSERT INTO embeddings(chunk_id, model, vector_json)
            VALUES (?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
              model=excluded.model,
              vector_json=excluded.vector_json
            """,
            [(chunk_id, model, json.dumps(vector)) for chunk_id, vector in vectors],
        )
        cursor.executemany(
            """
            INSERT INTO embeddings_v2(model, model_version, chunk_id, vector_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(model, model_version, chunk_id) DO UPDATE SET
              vector_json=excluded.vector_json
            """,
            [(model, model_version, chunk_id, json.dumps(vector)) for chunk_id, vector in vectors],
        )
        self._maybe_commit(commit)

    def replace_subchunks_for_parent(
        self,
        *,
        parent_chunk_id: int,
        file_id: int,
        path: str,
        model: str,
        model_version: str,
        subchunks: list[dict[str, object]],
        commit: bool = True,
    ) -> int:
        cursor = self.connection.cursor()
        cursor.execute(
            "DELETE FROM embedding_subchunks WHERE parent_chunk_id = ?",
            (parent_chunk_id,),
        )
        inserted = 0
        for row in subchunks:
            vector = row.get("vector")
            if not isinstance(vector, list) or not vector:
                continue
            cursor.execute(
                """
                INSERT INTO embedding_subchunks(
                  parent_chunk_id, file_id, path, subchunk_index,
                  start_line, end_line, focus_line, token_estimate,
                  source_kind, content, content_hash
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    parent_chunk_id,
                    file_id,
                    path,
                    int(row.get("subchunk_index", 0) or 0),
                    int(row.get("start_line", 0) or 0),
                    int(row.get("end_line", 0) or 0),
                    int(row.get("focus_line", 0) or 0),
                    int(row.get("token_estimate", 0) or 0),
                    str(row.get("source_kind", "")),
                    str(row.get("content", "")),
                    str(row.get("content_hash", "")),
                ),
            )
            subchunk_id = cursor.lastrowid
            if subchunk_id is None:
                continue
            cursor.execute(
                """
                INSERT INTO embedding_subchunk_vectors_v2(
                  model, model_version, subchunk_id, vector_json
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model, model_version, subchunk_id) DO UPDATE SET
                  vector_json=excluded.vector_json
                """,
                (
                    model,
                    model_version,
                    int(subchunk_id),
                    json.dumps([float(value) for value in vector]),
                ),
            )
            inserted += 1
        self._maybe_commit(commit)
        return inserted

    def load_embeddings(
        self,
        model: str,
        model_version: str = "v1",
        use_subchunks: bool = False,
    ) -> list[tuple[int, list[float]]]:
        cursor = self.connection.cursor()
        if use_subchunks:
            try:
                cursor.execute(
                    """
                    SELECT subchunk_id, vector_json
                    FROM embedding_subchunk_vectors_v2
                    WHERE model = ? AND model_version = ?
                    """,
                    (model, model_version),
                )
                rows = cursor.fetchall()
                if rows:
                    return [
                        (
                            int(row["subchunk_id"]),
                            [float(value) for value in json.loads(str(row["vector_json"]))],
                        )
                        for row in rows
                    ]
            except sqlite3.OperationalError:
                return []

        try:
            cursor.execute(
                """
                SELECT chunk_id, vector_json
                FROM embeddings_v2
                WHERE model = ? AND model_version = ?
                """,
                (model, model_version),
            )
            rows = cursor.fetchall()
            if rows:
                return [
                    (
                        int(row["chunk_id"]),
                        [float(value) for value in json.loads(str(row["vector_json"]))],
                    )
                    for row in rows
                ]
        except sqlite3.OperationalError:
            pass

        cursor.execute(
            """
            SELECT chunk_id, vector_json
            FROM embeddings
            WHERE model = ?
            """,
            (model,),
        )
        fallback_rows = cursor.fetchall()
        return [
            (int(row["chunk_id"]), [float(value) for value in json.loads(str(row["vector_json"]))])
            for row in fallback_rows
        ]

    def fetch_subchunk_rows_by_ids(
        self,
        subchunk_ids: list[int],
    ) -> list[dict[str, object]]:
        if not subchunk_ids:
            return []
        cursor = self.connection.cursor()
        unique_ids = list(dict.fromkeys(subchunk_ids))
        by_id: dict[int, dict[str, object]] = {}
        try:
            cursor.execute(
                """
                SELECT id, parent_chunk_id, path, start_line, end_line, focus_line,
                       subchunk_index, token_estimate, source_kind
                FROM embedding_subchunks
                WHERE id IN (
                  SELECT CAST(value AS INTEGER)
                  FROM json_each(?)
                )
                """,
                (json.dumps(unique_ids),),
            )
            rows = cursor.fetchall()
        except sqlite3.OperationalError:
            rows = []
        for row in rows:
            row_id = int(row["id"])
            by_id[row_id] = {
                "id": row_id,
                "parent_chunk_id": int(row["parent_chunk_id"]),
                "path": str(row["path"]),
                "start_line": int(row["start_line"]),
                "end_line": int(row["end_line"]),
                "focus_line": int(row["focus_line"]),
                "subchunk_index": int(row["subchunk_index"]),
                "token_estimate": int(row["token_estimate"]),
                "source_kind": str(row["source_kind"]),
            }
        return [by_id[subchunk_id] for subchunk_id in subchunk_ids if subchunk_id in by_id]

    def load_cached_query_embedding(
        self,
        model: str,
        query_hash: str,
        ttl_sec: int,
    ) -> list[float] | None:
        if ttl_sec <= 0:
            return None
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """
                SELECT vector_json, updated_at
                FROM query_embedding_cache
                WHERE model = ? AND query_hash = ?
                """,
                (model, query_hash),
            )
        except sqlite3.OperationalError:
            return None
        row = cursor.fetchone()
        if row is None:
            return None
        updated_at_raw = str(row["updated_at"])
        try:
            updated_at = datetime.fromisoformat(updated_at_raw)
        except ValueError:
            return None
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl_sec)
        if updated_at < cutoff:
            return None
        values = json.loads(str(row["vector_json"]))
        if not isinstance(values, list):
            return None
        return [float(value) for value in values]

    def upsert_query_embedding(
        self,
        model: str,
        query_hash: str,
        vector: list[float],
        commit: bool = True,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        try:
            self.connection.execute(
                """
                INSERT INTO query_embedding_cache(model, query_hash, vector_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(model, query_hash) DO UPDATE SET
                  vector_json=excluded.vector_json,
                  updated_at=excluded.updated_at
                """,
                (model, query_hash, json.dumps(vector), now),
            )
        except sqlite3.OperationalError:
            return
        self._maybe_commit(commit)

    def list_files(self, prefix: str | None = None, limit: int = 50) -> list[str]:
        cursor = self.connection.cursor()
        if prefix:
            normalized = prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                """
                SELECT path
                FROM files
                WHERE path LIKE ?
                ORDER BY path
                LIMIT ?
                """,
                (f"{normalized}%", limit),
            )
        else:
            cursor.execute(
                """
                SELECT path
                FROM files
                ORDER BY path
                LIMIT ?
                """,
                (limit,),
            )
        return [str(row["path"]) for row in cursor.fetchall()]

    def count_chunks(self, prefix: str | None = None) -> int:
        cursor = self.connection.cursor()
        if prefix:
            normalized = prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM chunks WHERE path LIKE ?",
                (f"{normalized}%",),
            )
        else:
            cursor.execute("SELECT COUNT(*) AS cnt FROM chunks")
        row = cursor.fetchone()
        if row is None:
            return 0
        return int(row["cnt"])

    def count_subchunks(self, prefix: str | None = None) -> int:
        cursor = self.connection.cursor()
        if prefix:
            normalized = prefix.rstrip("/").replace("\\", "/")
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM embedding_subchunks WHERE path LIKE ?",
                (f"{normalized}%",),
            )
        else:
            cursor.execute("SELECT COUNT(*) AS cnt FROM embedding_subchunks")
        row = cursor.fetchone()
        if row is None:
            return 0
        return int(row["cnt"])


def _to_fts_query(
    question: str,
    tokenizer_mode: str = "sudachi",
    fts_mode: str = "advanced",
) -> str:
    if fts_mode.strip().lower() != "advanced":
        return _to_fts_query_basic(question, tokenizer_mode=tokenizer_mode)
    return _to_fts_query_advanced(question, tokenizer_mode=tokenizer_mode)


def _to_fts_query_basic(question: str, tokenizer_mode: str = "sudachi") -> str:
    terms = _tokenize_code_query(question, tokenizer_mode=tokenizer_mode)
    if not terms:
        return ""
    core = [term.replace('"', '""') for term in terms[:4]]
    optional = [term.replace('"', '""') for term in terms[4:12]]
    core_expr = " AND ".join(f'"{term}"' for term in core)
    if not optional:
        return core_expr
    optional_expr = " OR ".join(f'"{term}"' for term in optional)
    return f"({core_expr}) OR ({optional_expr})"


def _to_fts_query_advanced(question: str, tokenizer_mode: str = "sudachi") -> str:
    phrases = [value.strip() for value in _extract_quoted_phrases(question) if value.strip()]
    stripped_question = _strip_quoted_segments(question)
    terms = _tokenize_code_query(stripped_question, tokenizer_mode=tokenizer_mode)
    if not phrases and not terms:
        return ""

    filters: list[str] = []
    tokens: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered.startswith("path:") and len(term) > 5:
            filters.append(f'path : "{_escape_fts_term(term[5:])}"')
            continue
        if lowered.startswith("symbol:") and len(term) > 7:
            filters.append(f'symbol : "{_escape_fts_term(term[7:])}"')
            continue
        tokens.append(term)

    core = [_escape_fts_term(term) for term in [*phrases, *tokens][:4]]
    optional = [_escape_fts_term(term) for term in tokens[4:12]]
    segments: list[str] = []
    if core:
        segments.append(" AND ".join(f'"{term}"' for term in core))
        if len(core) > 1:
            segments.append(" OR ".join(f'"{term}"' for term in core))
    if len(core) >= 2:
        near_left = f'"{core[0]}"'
        near_right = f'"{core[1]}"'
        segments.append(f"NEAR({near_left} {near_right}, 8)")
    if optional:
        segments.append(" OR ".join(f'"{term}"' for term in optional))

    if not segments:
        return " AND ".join(filters)
    body = " OR ".join(f"({segment})" for segment in segments)
    if not filters:
        return body
    return " AND ".join([*filters, f"({body})"])


def _extract_quoted_phrases(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


def _strip_quoted_segments(text: str) -> str:
    return re.sub(r'"[^"]*"', " ", text)


def _escape_fts_term(term: str) -> str:
    return term.replace('"', '""')


def _tokenize_code_query(question: str, tokenizer_mode: str = "sudachi") -> list[str]:
    return tokenize_code_query(question, mode=tokenizer_mode)


def _safe_json_object(raw: str) -> dict[str, object]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}
