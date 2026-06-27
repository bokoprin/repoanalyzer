from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import IngestSpec, RealRepoEvalCase, RealRepoScenario


def load_real_repo_case(path: str | Path) -> RealRepoEvalCase:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):
        raw = {"id": Path(path).stem, "scenarios": raw}
    ingest_raw = raw.get("ingest", {}) or {}
    scenarios: list[RealRepoScenario] = []
    for index, item in enumerate(raw.get("scenarios", []) or []):
        scenario_id = str(item.get("id") or f"scenario_{index + 1}")
        scenarios.append(
            RealRepoScenario(
                id=scenario_id,
                kind=str(item["kind"]),
                question=item.get("question"),
                mode=item.get("mode"),
                text=item.get("text"),
                answer_text=item.get("answer_text"),
                claim=item.get("claim"),
                expect=dict(item.get("expect") or {}),
            )
        )
    return RealRepoEvalCase(
        id=str(raw.get("id") or Path(path).stem),
        description=raw.get("description"),
        ingest=IngestSpec(
            enabled=bool(ingest_raw.get("enabled", True)),
            incremental=bool(ingest_raw.get("incremental", False)),
            config=ingest_raw.get("config"),
        ),
        budgets=dict(raw.get("budgets") or {}),
        expect=dict(raw.get("expect") or {}),
        scenarios=scenarios,
    )
