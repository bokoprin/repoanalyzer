from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repoanalyzer.core.paths import index_dir

LOG_NAME = "workflow_sessions.jsonl"


@dataclass(frozen=True)
class WorkflowSessionRecord:
    session_id: str
    created_at: str
    label: str | None
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "workflow_session_record.v1",
            "session_id": self.session_id,
            "created_at": self.created_at,
            "label": self.label,
            "trace": self.trace,
        }


def append_workflow_session(repo: str | Path, trace: Any, label: str | None = None) -> WorkflowSessionRecord:
    root = Path(repo).expanduser().resolve()
    trace_payload = trace.to_dict() if hasattr(trace, "to_dict") else dict(trace)
    created_at = datetime.now(timezone.utc).isoformat()
    session_id = f"wf-{created_at.replace(':', '').replace('+', 'Z')}-{abs(hash(json.dumps(trace_payload, sort_keys=True, default=str))) % 1000000:06d}"
    record = WorkflowSessionRecord(session_id=session_id, created_at=created_at, label=label, trace=trace_payload)
    target = index_dir(root) / LOG_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
    return record


def read_workflow_sessions(repo: str | Path, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    target = index_dir(Path(repo).expanduser().resolve()) / LOG_NAME
    records: list[dict[str, Any]] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
    total = len(records)
    records = list(reversed(records))
    page = records[offset:offset + limit]
    next_offset = offset + limit if offset + limit < total else None
    return {
        "schema_version": "workflow_session_history.v1",
        "total": total,
        "limit": limit,
        "offset": offset,
        "next_offset": next_offset,
        "has_more": next_offset is not None,
        "sessions": page,
    }
