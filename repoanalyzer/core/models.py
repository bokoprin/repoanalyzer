from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FactKind(str, Enum):
    SYMBOL = "symbol"
    REFERENCE = "reference"
    CALL = "call"
    CALL_PATH = "call_path"
    INCLUDE = "include"
    BUILD_GUARD = "build_guard"


@dataclass(frozen=True)
class SupportProfile:
    support_level: str = "unknown"
    source_coverage_status: str = "not_tracked"
    semantic_resolution_status: str = "not_tracked"
    build_status: str = "build_unknown"
    target_profile: str = "not_tracked"
    execution_context: str = "not_tracked"
    execution_contexts: list[str] = field(default_factory=list)
    unknown_reasons: list[str] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass(frozen=True)
class SourceSpan:
    path: str
    start_line: int
    end_line: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodeFact:
    fact_type: str
    path: str
    start_line: int
    end_line: int
    confidence: str = Confidence.MEDIUM.value
    source: str = "regex_cpp_minimal"
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    symbol: str | None = None
    qualified_name: str | None = None
    kind: str | None = None
    caller: str | None = None
    callee: str | None = None
    call_kind: str | None = None
    route: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def span(self) -> SourceSpan:
        return SourceSpan(self.path, self.start_line, self.end_line)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass(frozen=True)
class UnknownFact:
    unknown_type: str
    message: str
    severity: str = "medium"
    affects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass
class EvidenceBundle:
    question: str
    interpreted_intent: str
    answerability: str
    facts: list[CodeFact] = field(default_factory=list)
    unknowns: list[UnknownFact] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)
    support_level: str = "unknown"
    unknown_reasons: list[str] = field(default_factory=list)
    quality_profile: SupportProfile | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": "evidence_bundle.v1",
            "question": self.question,
            "interpreted_intent": self.interpreted_intent,
            "answerability": self.answerability,
            "facts": [fact.to_dict() for fact in self.facts],
            "unknowns": [unknown.to_dict() for unknown in self.unknowns],
            "response_constraints": list(self.response_constraints),
            "support_level": self.support_level,
            "unknown_reasons": list(self.unknown_reasons),
            "quality_profile": self.quality_profile.to_dict() if self.quality_profile else None,
        }
        return {k: v for k, v in data.items() if v not in (None, [], {})}


def normalize_repo_path(repo: str | Path) -> Path:
    return Path(repo).expanduser().resolve()
