from __future__ import annotations

import json
from dataclasses import dataclass

from repoanalyzer.ingest.index_store import IndexStore


@dataclass(slots=True)
class V2IndexReader:
    store: IndexStore

    def find_symbol_definitions(self, anchor: str, limit: int = 30) -> list[dict[str, object]]:
        rows = self.store.connection.execute(
            """
            SELECT path, name, kind, start_line, end_line, signature
            FROM symbols
            WHERE name = ?
               OR name LIKE ?
               OR name LIKE ?
            ORDER BY CASE WHEN name = ? THEN 0 ELSE 1 END, path, start_line
            LIMIT ?
            """,
            (anchor, f"{anchor}%", f"%::{anchor}", anchor, max(limit, 1)),
        ).fetchall()
        return [dict(row) for row in rows]

    def find_symbol_aliases(self, anchor: str, limit: int = 50) -> list[dict[str, object]]:
        rows = self.store.connection.execute(
            """
            SELECT path, raw_name, normalized_name, scope, line
            FROM symbol_aliases
            WHERE raw_name = ?
               OR normalized_name = ?
               OR raw_name LIKE ?
               OR normalized_name LIKE ?
            ORDER BY CASE WHEN raw_name = ? OR normalized_name = ? THEN 0 ELSE 1 END, path, line
            LIMIT ?
            """,
            (
                anchor,
                anchor.lower(),
                f"{anchor}%",
                f"{anchor.lower()}%",
                anchor,
                anchor.lower(),
                max(limit, 1),
            ),
        ).fetchall()
        return [dict(row) for row in rows]

    def find_symbol_usages(self, anchor: str, limit: int = 40) -> list[dict[str, object]]:
        refs = self.store.find_symbol_references_fuzzy(anchor, limit=max(limit, 1))
        rows = [
            {"path": path, "line": line, "context": context, "kind": "reference"}
            for path, line, context in refs
        ]
        call_refs = self.store.find_call_references(anchor, limit=max(limit, 1))
        rows.extend(
            {
                "path": path,
                "line": line,
                "context": f"{caller} -> {callee}",
                "kind": kind,
            }
            for path, line, caller, callee, kind in call_refs
        )
        return rows[: max(limit, 1)]

    def find_setting_relations(
        self, aliases: list[str], relation_kind: str, limit: int = 50
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, int, str]] = set()
        for alias in aliases:
            cursor = self.store.connection.execute(
                """
                SELECT
                  path, config_key_or_type, relation_kind, line,
                  symbol_name, confidence, context
                FROM v2_config_relations
                WHERE relation_kind = ?
                  AND (
                    lower(config_key_or_type) LIKE ?
                    OR lower(symbol_name) LIKE ?
                    OR lower(context) LIKE ?
                  )
                ORDER BY confidence DESC, path, line
                LIMIT ?
                """,
                (
                    relation_kind,
                    f"%{alias.lower()}%",
                    f"%{alias.lower()}%",
                    f"%{alias.lower()}%",
                    max(limit, 1),
                ),
            )
            for row in cursor.fetchall():
                payload = dict(row)
                key = (str(payload["path"]), int(payload["line"]), str(payload["relation_kind"]))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(payload)
        return rows[: max(limit, 1)]

    def find_field_accesses(
        self, aliases: list[str], access_kinds: tuple[str, ...], limit: int = 50
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        seen: set[tuple[str, int, str]] = set()
        encoded_kinds = json.dumps(list(access_kinds))
        for alias in aliases:
            cursor = self.store.connection.execute(
                """
                SELECT path, field_name, owner_type, line, access_kind, symbol_name, context
                FROM v2_field_accesses
                WHERE access_kind IN (
                  SELECT value FROM json_each(?)
                )
                  AND (
                    lower(field_name) LIKE ?
                    OR lower(owner_type) LIKE ?
                    OR lower(symbol_name) LIKE ?
                    OR lower(context) LIKE ?
                  )
                ORDER BY path, line
                LIMIT ?
                """,
                (
                    encoded_kinds,
                    f"%{alias.lower()}%",
                    f"%{alias.lower()}%",
                    f"%{alias.lower()}%",
                    f"%{alias.lower()}%",
                    max(limit, 1),
                ),
            )
            for row in cursor.fetchall():
                payload = dict(row)
                key = (str(payload["path"]), int(payload["line"]), str(payload["access_kind"]))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(payload)
        return rows[: max(limit, 1)]

    def find_callers(self, symbol: str, limit: int = 30) -> list[dict[str, object]]:
        rows = self.store.find_call_references(symbol, limit=max(limit, 1))
        return [
            {"path": path, "line": line, "caller": caller, "callee": callee, "kind": kind}
            for path, line, caller, callee, kind in rows
        ]

    def find_callees(self, symbol: str, limit: int = 30) -> list[dict[str, object]]:
        cursor = self.store.connection.execute(
            """
            SELECT path, caller, callee, line, kind
            FROM call_edges
            WHERE caller = ?
               OR caller LIKE ?
            ORDER BY path, line
            LIMIT ?
            """,
            (symbol, f"%::{symbol}", max(limit, 1)),
        )
        return [dict(row) for row in cursor.fetchall()]

    def snippet_span(self, entity_type: str, entity_key: str) -> dict[str, object] | None:
        row = self.store.connection.execute(
            """
            SELECT path, start_line, end_line, focus_line
            FROM v2_snippet_spans
            WHERE entity_type = ? AND entity_key = ?
            """,
            (entity_type, entity_key),
        ).fetchone()
        if row is None:
            return None
        return dict(row)
