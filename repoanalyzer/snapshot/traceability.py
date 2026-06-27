from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repoanalyzer.snapshot.generator import (
    _looks_like_source_path,
    _parse_upstream_paths,
    _safe_join,
    _safe_repo_slug,
    _sha256_file,
    _upstream_destination,
)


@dataclass(frozen=True)
class UpstreamTraceRef:
    repository: str
    ref: str | None
    upstream_path: str
    copied_path: str | None
    exists: bool
    sha256: str | None = None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "ref": self.ref,
            "upstream_path": self.upstream_path,
            "copied_path": self.copied_path,
            "exists": self.exists,
            "sha256": self.sha256,
            "skipped_reason": self.skipped_reason,
        }


@dataclass(frozen=True)
class TraceabilityEntry:
    source_index: int
    compact_path: str
    compact_exists: bool
    compact_sha256: str | None
    manifest_sha256: str | None
    compact_sha256_matches_manifest: bool | None
    upstream_refs: list[UpstreamTraceRef] = field(default_factory=list)
    anchors_checked: list[str] = field(default_factory=list)
    matched_anchors: list[str] = field(default_factory=list)
    missing_anchors: list[str] = field(default_factory=list)
    traceability_status: str = "unknown"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_index": self.source_index,
            "compact_path": self.compact_path,
            "compact_exists": self.compact_exists,
            "compact_sha256": self.compact_sha256,
            "manifest_sha256": self.manifest_sha256,
            "compact_sha256_matches_manifest": self.compact_sha256_matches_manifest,
            "upstream_refs": [ref.to_dict() for ref in self.upstream_refs],
            "anchors_checked": self.anchors_checked,
            "matched_anchors": self.matched_anchors,
            "missing_anchors": self.missing_anchors,
            "traceability_status": self.traceability_status,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SnapshotTraceabilityReport:
    schema_version: str = "snapshot_traceability_report.v1"
    ok: bool = True
    snapshot_id: str | None = None
    manifest: str = ""
    snapshot_root: str = ""
    upstream_output_root: str = "upstream_sources"
    entries: list[TraceabilityEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        entries = [entry.to_dict() for entry in self.entries]
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "snapshot_id": self.snapshot_id,
            "manifest": self.manifest,
            "snapshot_root": self.snapshot_root,
            "upstream_output_root": self.upstream_output_root,
            "metrics": _build_metrics(self.entries),
            "entries": entries,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def generate_traceability_report(
    manifest_path: str | Path,
    snapshot_root: str | Path,
    *,
    upstream_output_root: str = "upstream_sources",
    write_report: bool = True,
    report_name: str = ".repoanalyzer-traceability-report.json",
) -> SnapshotTraceabilityReport:
    """Validate compact snapshot files against their upstream source evidence.

    This report is intentionally evidence-oriented rather than byte-for-byte
    equivalence-oriented. Compact slices are small source-derived fixtures, so a
    valid relationship is: the compact destination exists and matches its local
    manifest hash; each source-like upstream path has been copied under
    `upstream_sources`; and at least some strong lexical anchors from the compact
    slice can be found in the upstream evidence file(s).
    """
    manifest = Path(manifest_path).expanduser().resolve()
    snapshot = Path(snapshot_root).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not manifest.exists():
        return SnapshotTraceabilityReport(ok=False, manifest=str(manifest), snapshot_root=str(snapshot), upstream_output_root=upstream_output_root, errors=[f"manifest not found: {manifest}"])
    if not snapshot.exists():
        return SnapshotTraceabilityReport(ok=False, manifest=str(manifest), snapshot_root=str(snapshot), upstream_output_root=upstream_output_root, errors=[f"snapshot root not found: {snapshot}"])

    try:
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return SnapshotTraceabilityReport(ok=False, manifest=str(manifest), snapshot_root=str(snapshot), upstream_output_root=upstream_output_root, errors=[f"failed to read manifest: {exc}"])

    if str(raw.get("schema_version") or "") != "snapshot_manifest.v1":
        errors.append(f"unsupported manifest schema_version: {raw.get('schema_version')!r}")

    snapshot_id = str(raw.get("snapshot_id") or raw.get("id") or manifest.stem)
    entries: list[TraceabilityEntry] = []
    sources = raw.get("sources") or []
    if not isinstance(sources, list):
        return SnapshotTraceabilityReport(ok=False, snapshot_id=snapshot_id, manifest=str(manifest), snapshot_root=str(snapshot), upstream_output_root=upstream_output_root, errors=["manifest sources must be a list"])

    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        entries.append(_build_entry(index, item, snapshot, upstream_output_root, warnings))

    for entry in entries:
        if not entry.compact_exists:
            errors.append(f"compact destination missing: {entry.compact_path}")
        if entry.compact_sha256_matches_manifest is False:
            errors.append(f"compact sha256 mismatch: {entry.compact_path}")
        for ref in entry.upstream_refs:
            if ref.skipped_reason is None and not ref.exists:
                warnings.append(f"upstream evidence missing for {entry.compact_path}: {ref.upstream_path}")

    ok = not errors
    report = SnapshotTraceabilityReport(
        ok=ok,
        snapshot_id=snapshot_id,
        manifest=str(manifest),
        snapshot_root=str(snapshot),
        upstream_output_root=upstream_output_root,
        entries=entries,
        errors=errors,
        warnings=sorted(set(warnings)),
    )
    if write_report:
        report_path = snapshot / report_name
        report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _build_entry(index: int, item: dict[str, Any], snapshot: Path, upstream_output_root: str, warnings: list[str]) -> TraceabilityEntry:
    compact_rel = str(item.get("destination") or item.get("dest") or item.get("path") or item.get("source") or f"sources[{index}]")
    notes: list[str] = []
    try:
        compact_path = _safe_join(snapshot, compact_rel)
    except ValueError:
        compact_path = snapshot / "__invalid_compact_path__"
        notes.append("invalid compact destination path")
    compact_exists = compact_path.exists() and compact_path.is_file()
    manifest_sha = str(item.get("sha256")) if item.get("sha256") else None
    compact_sha = _sha256_file(compact_path) if compact_exists else None
    sha_match: bool | None = None
    if manifest_sha and compact_sha:
        sha_match = compact_sha.lower() == manifest_sha.lower()

    upstream_refs = _build_upstream_refs(index, item, snapshot, upstream_output_root)
    compact_text = _read_text(compact_path) if compact_exists else ""
    upstream_text = "\n".join(_read_text(snapshot / ref.copied_path) for ref in upstream_refs if ref.copied_path and ref.exists)
    anchors = _extract_traceability_anchors(compact_text)
    matched = [anchor for anchor in anchors if anchor in upstream_text]
    missing = [anchor for anchor in anchors if anchor not in upstream_text]

    if not upstream_refs:
        status = "no_upstream_metadata"
    elif all(ref.skipped_reason is not None for ref in upstream_refs):
        status = "upstream_refs_skipped"
    elif not any(ref.exists for ref in upstream_refs):
        status = "upstream_missing"
    elif anchors and len(matched) >= min(3, len(anchors)):
        status = "content_anchored"
    elif any(ref.exists for ref in upstream_refs):
        status = "manifest_linked"
        if anchors:
            notes.append("upstream evidence exists but fewer than 3 compact anchors were found")
    else:
        status = "unknown"

    return TraceabilityEntry(
        source_index=index,
        compact_path=compact_rel,
        compact_exists=compact_exists,
        compact_sha256=compact_sha,
        manifest_sha256=manifest_sha,
        compact_sha256_matches_manifest=sha_match,
        upstream_refs=upstream_refs,
        anchors_checked=anchors,
        matched_anchors=matched,
        missing_anchors=missing,
        traceability_status=status,
        notes=notes,
    )


def _build_upstream_refs(index: int, item: dict[str, Any], snapshot: Path, upstream_output_root: str) -> list[UpstreamTraceRef]:
    upstream = item.get("upstream")
    if not isinstance(upstream, dict):
        return []
    repository = str(upstream.get("repository") or upstream.get("repo") or "").strip()
    if not repository:
        return [UpstreamTraceRef(repository="", ref=None, upstream_path="", copied_path=None, exists=False, skipped_reason="missing_repository")]
    ref = str(upstream.get("ref")) if upstream.get("ref") else None
    paths = _parse_upstream_paths(upstream)
    if not paths:
        return [UpstreamTraceRef(repository=repository, ref=ref, upstream_path="", copied_path=None, exists=False, skipped_reason="no_upstream_paths")]
    repo_slug = _safe_repo_slug(repository)
    refs: list[UpstreamTraceRef] = []
    for path_index, upstream_path in enumerate(paths):
        if not _looks_like_source_path(upstream_path):
            refs.append(UpstreamTraceRef(repository=repository, ref=ref, upstream_path=upstream_path, copied_path=None, exists=False, skipped_reason="not_source_path"))
            continue
        override_dest = _upstream_destination(upstream, upstream_path, path_index)
        copied_rel = override_dest or f"{upstream_output_root}/{repo_slug}/{upstream_path}"
        try:
            copied_path = _safe_join(snapshot, copied_rel)
        except ValueError:
            refs.append(UpstreamTraceRef(repository=repository, ref=ref, upstream_path=upstream_path, copied_path=None, exists=False, skipped_reason="invalid_copied_path"))
            continue
        exists = copied_path.exists() and copied_path.is_file()
        refs.append(UpstreamTraceRef(repository=repository, ref=ref, upstream_path=upstream_path, copied_path=copied_rel, exists=exists, sha256=_sha256_file(copied_path) if exists else None))
    return refs


def _extract_traceability_anchors(text: str, *, limit: int = 40) -> list[str]:
    raw = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text)
    scored: dict[str, int] = {}
    for token in raw:
        if token in _BORING_TOKENS:
            continue
        if token.startswith("__"):
            continue
        score = 1
        if token.startswith(("C", "F_", "WM_", "IDC_", "IDD_", "IDR_", "PP_", "CODE_", "OPE_")):
            score += 5
        if "::" in token:
            score += 3
        if any(ch.isupper() for ch in token[1:]):
            score += 2
        if len(token) > 18:
            score += 1
        scored[token] = max(scored.get(token, 0), score)
    ordered = sorted(scored, key=lambda tok: (-scored[tok], tok))
    return ordered[:limit]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _build_metrics(entries: list[TraceabilityEntry]) -> dict[str, int]:
    return {
        "entry_count": len(entries),
        "compact_files_checked": sum(1 for entry in entries if entry.compact_exists),
        "compact_sha_matches": sum(1 for entry in entries if entry.compact_sha256_matches_manifest is True),
        "entries_with_upstream_metadata": sum(1 for entry in entries if entry.upstream_refs),
        "upstream_refs_checked": sum(1 for entry in entries for ref in entry.upstream_refs if ref.skipped_reason is None),
        "upstream_refs_existing": sum(1 for entry in entries for ref in entry.upstream_refs if ref.exists),
        "upstream_refs_skipped": sum(1 for entry in entries for ref in entry.upstream_refs if ref.skipped_reason is not None),
        "content_anchored_entries": sum(1 for entry in entries if entry.traceability_status == "content_anchored"),
        "manifest_linked_entries": sum(1 for entry in entries if entry.traceability_status == "manifest_linked"),
        "missing_upstream_entries": sum(1 for entry in entries if entry.traceability_status == "upstream_missing"),
        "no_upstream_metadata_entries": sum(1 for entry in entries if entry.traceability_status == "no_upstream_metadata"),
    }


_BORING_TOKENS = {
    "namespace",
    "class",
    "struct",
    "public",
    "private",
    "protected",
    "return",
    "void",
    "bool",
    "true",
    "false",
    "nullptr",
    "const",
    "static",
    "include",
    "using",
    "enum",
    "int",
    "long",
    "short",
    "char",
    "wchar_t",
    "auto",
    "for",
    "if",
    "else",
    "while",
    "switch",
    "case",
    "break",
    "continue",
    "new",
    "delete",
    "std",
    "string",
    "wstring",
    "vector",
    "size_t",
    "required",
    "source",
    "destination",
}
