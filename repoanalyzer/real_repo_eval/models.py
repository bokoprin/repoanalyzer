from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, asdict
from typing import Any


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return _to_dict(asdict(value))
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class IngestSpec:
    enabled: bool = True
    incremental: bool = False
    config: str | None = None


@dataclass(frozen=True)
class RealRepoScenario:
    id: str
    kind: str
    question: str | None = None
    mode: str | None = None
    text: str | None = None
    answer_text: str | None = None
    claim: dict[str, Any] | None = None
    expect: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RealRepoEvalCase:
    id: str
    description: str | None = None
    ingest: IngestSpec = field(default_factory=IngestSpec)
    budgets: dict[str, Any] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)
    scenarios: list[RealRepoScenario] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioResult:
    id: str
    kind: str
    ok: bool
    duration_ms: int
    failures: list[str] = field(default_factory=list)
    failure_categories: list[str] = field(default_factory=list)
    output: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "failures": list(self.failures),
            "failure_categories": list(self.failure_categories),
            "output": _to_dict(self.output),
        }


@dataclass(frozen=True)
class RealRepoEvalReport:
    repo: str
    case_id: str
    ok: bool
    status: str
    duration_ms: int
    ingest_result: Any | None = None
    repo_status: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    scenarios: list[ScenarioResult] = field(default_factory=list)
    failure_categories: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "real_repo_eval_report.v1",
            "repo": self.repo,
            "case_id": self.case_id,
            "ok": self.ok,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "ingest_result": _to_dict(self.ingest_result),
            "repo_status": self.repo_status,
            "diagnostics": self.diagnostics,
            "metrics": self.metrics,
            "scenarios": [scenario.to_dict() for scenario in self.scenarios],
            "failure_categories": dict(self.failure_categories),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }
