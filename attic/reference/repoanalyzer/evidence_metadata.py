from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

CONFIG_SUFFIXES = {
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
}
GENERATED_MARKERS = {
    "generated",
    "build",
    "dist",
    ".repoanalyzer-index",
}


def normalize_repo_path(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").lstrip("./")


def classify_source_kind(path: str | None) -> str:
    """Classify evidence source so LLM clients do not mix tests/docs/runtime code."""
    normalized = normalize_repo_path(path)
    if not normalized:
        return "unknown"
    parts = [part.lower() for part in PurePosixPath(normalized).parts]
    suffix = PurePosixPath(normalized).suffix.lower()
    if any(part in {"tests", "test"} for part in parts) or normalized.lower().startswith("tests/"):
        return "test"
    if any(part in {"docs", "doc"} for part in parts) or normalized.lower().startswith("docs/"):
        return "docs"
    if any(part in {"evalution", "evaluation", "eval"} for part in parts):
        return "eval"
    if any(part in GENERATED_MARKERS for part in parts):
        return "generated"
    if suffix in CONFIG_SUFFIXES:
        return "config"
    return "production"


def infer_evidence_kind(item: dict[str, Any], *, default: str = "reference") -> str:
    """Infer a stable evidence kind from existing payload fields."""
    kind = str(item.get("evidence_kind") or item.get("kind") or "").lower()
    reference_kind = str(item.get("reference_kind") or "").lower()
    if item.get("caller") and item.get("callee"):
        return "static_call_reference" if default == "reference" else "call_edge"
    if reference_kind:
        if reference_kind in {"call", "call_reference"}:
            return "static_call_reference"
        return reference_kind
    if kind in {"function", "class", "method", "struct", "enum", "typedef", "macro", "variable"}:
        return "definition"
    if kind in {"call", "python-call", "cpp-call"}:
        return "call_edge"
    if item.get("target"):
        return "dependency_edge"
    if item.get("snippet") is not None:
        return "context_chunk"
    return default


def default_confidence(*, source_kind: str, evidence_kind: str) -> float:
    base = 0.85
    if source_kind == "production":
        base += 0.05
    elif source_kind in {"test", "docs", "eval"}:
        base -= 0.1
    elif source_kind in {"generated", "unknown"}:
        base -= 0.2
    if evidence_kind in {"mcp_tool_registration", "cli_entrypoint", "definition", "call_edge"}:
        base += 0.05
    elif evidence_kind in {"static_call_reference", "reference", "context_chunk"}:
        base -= 0.05
    return round(max(0.0, min(base, 0.99)), 2)


def enrich_evidence_item(
    item: dict[str, Any],
    *,
    evidence_kind: str | None = None,
    confidence: float | None = None,
    consumer_hint: str | None = None,
) -> dict[str, Any]:
    enriched = dict(item)
    source_kind = str(enriched.get("source_kind") or classify_source_kind(str(enriched.get("path") or "")))
    inferred_kind = evidence_kind or str(enriched.get("evidence_kind") or infer_evidence_kind(enriched))
    enriched.setdefault("source_kind", source_kind)
    enriched.setdefault("evidence_kind", inferred_kind)
    enriched.setdefault("confidence", confidence if confidence is not None else default_confidence(source_kind=source_kind, evidence_kind=inferred_kind))
    if consumer_hint is not None:
        enriched.setdefault("consumer_hint", consumer_hint)
    return enriched


def enrich_evidence_items(
    items: list[dict[str, Any]],
    *,
    evidence_kind: str | None = None,
    consumer_hint: str | None = None,
) -> list[dict[str, Any]]:
    return [enrich_evidence_item(item, evidence_kind=evidence_kind, consumer_hint=consumer_hint) for item in items]
