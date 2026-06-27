from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repoanalyzer.core.paths import index_db_path
from repoanalyzer.core.path_roles import path_role
from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.store.status import repo_index_status


@dataclass(frozen=True)
class QueryDiagnostics:
    repo: str
    db_path: str
    total_facts: int
    fact_type_counts: dict[str, int]
    indexed_files: int
    file_role_counts: dict[str, int]
    largest_files: list[dict[str, Any]] = field(default_factory=list)
    status: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "query_diagnostics.v1",
            "repo": self.repo,
            "db_path": self.db_path,
            "total_facts": self.total_facts,
            "fact_type_counts": dict(self.fact_type_counts),
            "indexed_files": self.indexed_files,
            "file_role_counts": dict(self.file_role_counts),
            "largest_files": list(self.largest_files),
            "status": self.status,
            "warnings": list(self.warnings),
        }


def query_diagnostics(repo: str | Path) -> QueryDiagnostics:
    root = Path(repo).expanduser().resolve()
    db = index_db_path(root)
    store = SQLiteStore(db)
    facts = store.all_facts()
    entries = store.file_index_entries()
    status = repo_index_status(root).to_dict()
    fact_type_counts = Counter(fact.fact_type for fact in facts)
    file_role_counts = Counter(path_role(entry.path) for entry in entries)
    largest_files = [
        {
            "path": entry.path,
            "source_kind": entry.source_kind,
            "role": path_role(entry.path),
            "size_bytes": entry.size_bytes,
            "line_count": entry.line_count,
        }
        for entry in sorted(entries, key=lambda e: (e.size_bytes, e.line_count), reverse=True)[:10]
    ]
    warnings: list[str] = []
    if not status.get("clean", False):
        warnings.append("Index is not fresh; run full or safe incremental ingest before absence/completeness claims.")
    noisy_roles = {role: count for role, count in file_role_counts.items() if role in {"vendor", "generated", "test"} and count}
    if noisy_roles:
        warnings.append(f"Indexed non-project file roles detected: {noisy_roles}. Consider index.exclude_patterns if they are not analysis targets.")
    if len(facts) > 10000:
        warnings.append("Large fact table detected; use paginated query tools and avoid unbounded MCP responses.")
    return QueryDiagnostics(
        repo=str(root),
        db_path=str(db),
        total_facts=len(facts),
        fact_type_counts=dict(sorted(fact_type_counts.items())),
        indexed_files=len(entries),
        file_role_counts=dict(sorted(file_role_counts.items())),
        largest_files=largest_files,
        status=status,
        warnings=warnings,
    )
