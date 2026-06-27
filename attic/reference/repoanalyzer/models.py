from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChunkLocation:
    path: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class RetrievedChunk:
    location: ChunkLocation
    content: str
    score: float = 0.0


@dataclass(slots=True)
class ScannedFile:
    repo_root: Path
    relative_path: str
    absolute_path: Path
    language: str
    size_bytes: int
    line_count: int
    sha256: str
    text: str


@dataclass(slots=True)
class ChunkRecord:
    path: str
    start_line: int
    end_line: int
    symbol: str
    content: str
    content_hash: str


@dataclass(slots=True)
class SymbolRecord:
    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str


@dataclass(slots=True)
class SymbolReferenceRecord:
    path: str
    name: str
    line: int
    context: str


@dataclass(slots=True)
class DependencyRecord:
    path: str
    target: str
    kind: str
    line: int


@dataclass(slots=True)
class SummaryRecord:
    level: str
    path: str
    parent_path: str
    summary: str
    details: dict[str, Any]
