from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repoanalyzer.snapshot.traceability import (
    TraceabilityEntry,
    UpstreamTraceRef,
    generate_traceability_report,
)


@dataclass(frozen=True)
class CompactEvidenceRef:
    compact_path: str
    traceability_status: str
    compact_exists: bool
    compact_sha256_matches_manifest: bool | None
    matched_anchors: list[str] = field(default_factory=list)
    missing_anchors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compact_path": self.compact_path,
            "traceability_status": self.traceability_status,
            "compact_exists": self.compact_exists,
            "compact_sha256_matches_manifest": self.compact_sha256_matches_manifest,
            "matched_anchors": self.matched_anchors,
            "missing_anchors": self.missing_anchors,
        }


@dataclass(frozen=True)
class UpstreamEvidenceRef:
    repository: str
    ref: str | None
    upstream_path: str
    copied_path: str | None
    exists: bool
    sha256: str | None = None
    skipped_reason: str | None = None
    compact_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_trace_ref(cls, ref: UpstreamTraceRef, *, compact_paths: list[str]) -> "UpstreamEvidenceRef":
        return cls(
            repository=ref.repository,
            ref=ref.ref,
            upstream_path=ref.upstream_path,
            copied_path=ref.copied_path,
            exists=ref.exists,
            sha256=ref.sha256,
            skipped_reason=ref.skipped_reason,
            compact_paths=compact_paths,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "ref": self.ref,
            "upstream_path": self.upstream_path,
            "copied_path": self.copied_path,
            "exists": self.exists,
            "sha256": self.sha256,
            "skipped_reason": self.skipped_reason,
            "compact_paths": self.compact_paths,
        }


@dataclass(frozen=True)
class CoverageGapEntry:
    scenario_id: str
    scenario_kind: str
    question: str | None = None
    mode: str | None = None
    support_status: str = "unknown"
    compact_evidence: list[CompactEvidenceRef] = field(default_factory=list)
    upstream_present: list[UpstreamEvidenceRef] = field(default_factory=list)
    upstream_missing: list[UpstreamEvidenceRef] = field(default_factory=list)
    upstream_skipped: list[UpstreamEvidenceRef] = field(default_factory=list)
    recommended_additions: list[str] = field(default_factory=list)
    unknown_reasons: list[str] = field(default_factory=list)
    selectors: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_kind": self.scenario_kind,
            "question": self.question,
            "mode": self.mode,
            "support_status": self.support_status,
            "compact_evidence": [item.to_dict() for item in self.compact_evidence],
            "upstream_evidence": {
                "present": [item.to_dict() for item in self.upstream_present],
                "missing": [item.to_dict() for item in self.upstream_missing],
                "skipped": [item.to_dict() for item in self.upstream_skipped],
            },
            "recommended_additions": self.recommended_additions,
            "unknown_reasons": self.unknown_reasons,
            "selectors": self.selectors,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class SnapshotCoverageGapReport:
    schema_version: str = "snapshot_coverage_gap_report.v1"
    ok: bool = True
    snapshot_id: str | None = None
    manifest: str = ""
    snapshot_root: str = ""
    cases: str = ""
    upstream_output_root: str = "upstream_sources"
    entries: list[CoverageGapEntry] = field(default_factory=list)
    traceability_errors: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "snapshot_id": self.snapshot_id,
            "manifest": self.manifest,
            "snapshot_root": self.snapshot_root,
            "cases": self.cases,
            "upstream_output_root": self.upstream_output_root,
            "metrics": _build_coverage_metrics(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
            "traceability_errors": self.traceability_errors,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def generate_coverage_gap_report(
    manifest_path: str | Path,
    snapshot_root: str | Path,
    cases_path: str | Path,
    *,
    upstream_output_root: str = "upstream_sources",
    write_report: bool = True,
    report_name: str = ".repoanalyzer-coverage-gap-report.json",
) -> SnapshotCoverageGapReport:
    """Report trace/scenario-level upstream evidence coverage gaps.

    The existing traceability report answers a file-level question: whether each
    compact slice can be linked to copied upstream source evidence. This report
    lifts that information to real-repo-eval scenario/trace granularity so an
    LLM workflow can distinguish:

    - compact-only evidence,
    - upstream evidence present,
    - missing upstream source files,
    - non-source/metadata references that cannot be validated as source, and
    - scenarios that cannot be mapped to compact files yet.

    Missing upstream files are gaps, not report-generation failures. Integrity
    errors such as missing compact files or compact hash mismatches remain errors
    because the compact evidence itself is no longer trustworthy.
    """
    manifest = Path(manifest_path).expanduser().resolve()
    snapshot = Path(snapshot_root).expanduser().resolve()
    cases = Path(cases_path).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []

    if not cases.exists():
        return SnapshotCoverageGapReport(
            ok=False,
            manifest=str(manifest),
            snapshot_root=str(snapshot),
            cases=str(cases),
            upstream_output_root=upstream_output_root,
            errors=[f"cases file not found: {cases}"],
        )

    traceability = generate_traceability_report(
        manifest,
        snapshot,
        upstream_output_root=upstream_output_root,
        write_report=False,
    )
    trace_payload = traceability.to_dict()
    if not traceability.ok:
        errors.extend(traceability.errors)
    warnings.extend(traceability.warnings)

    try:
        raw_cases = yaml.safe_load(cases.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return SnapshotCoverageGapReport(
            ok=False,
            snapshot_id=traceability.snapshot_id,
            manifest=str(manifest),
            snapshot_root=str(snapshot),
            cases=str(cases),
            upstream_output_root=upstream_output_root,
            traceability_errors=traceability.errors,
            errors=[*errors, f"failed to read cases: {exc}"],
            warnings=sorted(set(warnings)),
        )

    scenarios = _load_scenarios(raw_cases)
    manifest_entries = {entry.compact_path: entry for entry in traceability.entries}
    snapshot_texts = _read_compact_texts(snapshot, traceability.entries)
    entries = [
        _build_coverage_entry(scenario, manifest_entries, snapshot_texts)
        for scenario in scenarios
    ]

    for entry in entries:
        if entry.support_status == "unknown":
            warnings.append(f"scenario {entry.scenario_id} could not be mapped to compact evidence")

    report = SnapshotCoverageGapReport(
        ok=not errors,
        snapshot_id=traceability.snapshot_id or str(raw_cases.get("id") or cases.stem),
        manifest=str(manifest),
        snapshot_root=str(snapshot),
        cases=str(cases),
        upstream_output_root=upstream_output_root,
        entries=entries,
        traceability_errors=traceability.errors,
        errors=errors,
        warnings=sorted(set(warnings)),
    )
    if write_report:
        try:
            report_path = snapshot / report_name
            report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:  # pragma: no cover - defensive path
            report = SnapshotCoverageGapReport(
                ok=False,
                snapshot_id=report.snapshot_id,
                manifest=report.manifest,
                snapshot_root=report.snapshot_root,
                cases=report.cases,
                upstream_output_root=report.upstream_output_root,
                entries=report.entries,
                traceability_errors=report.traceability_errors,
                errors=[*report.errors, f"failed to write coverage gap report: {exc}"],
                warnings=report.warnings,
            )
    return report


def _load_scenarios(raw_cases: Any) -> list[dict[str, Any]]:
    if isinstance(raw_cases, list):
        return [dict(item, id=str(item.get("id") or f"scenario_{index + 1}")) for index, item in enumerate(raw_cases) if isinstance(item, dict)]
    if not isinstance(raw_cases, dict):
        return []
    scenarios = raw_cases.get("scenarios") or []
    loaded: list[dict[str, Any]] = []
    for index, item in enumerate(scenarios):
        if not isinstance(item, dict):
            continue
        loaded.append(dict(item, id=str(item.get("id") or f"scenario_{index + 1}")))
    return loaded


def _read_compact_texts(snapshot: Path, entries: list[TraceabilityEntry]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for entry in entries:
        if not _is_trace_source_path(entry.compact_path):
            continue
        if not entry.compact_exists:
            texts[entry.compact_path] = ""
            continue
        path = snapshot / entry.compact_path
        try:
            texts[entry.compact_path] = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            texts[entry.compact_path] = ""
    return texts


def _build_coverage_entry(
    scenario: dict[str, Any],
    manifest_entries: dict[str, TraceabilityEntry],
    snapshot_texts: dict[str, str],
) -> CoverageGapEntry:
    scenario_id = str(scenario.get("id") or "scenario")
    scenario_kind = str(scenario.get("kind") or "unknown")
    if scenario_kind in {"query_diagnostics", "repo_status"}:
        return CoverageGapEntry(
            scenario_id=scenario_id,
            scenario_kind=scenario_kind,
            question=scenario.get("question"),
            mode=scenario.get("mode"),
            support_status="not_applicable",
            unknown_reasons=["non_trace_scenario"],
            selectors={},
            notes=["Scenario checks repository/index health rather than a source trace."],
        )
    selectors = _extract_scenario_selectors(scenario)
    compact_paths = _select_compact_paths(scenario_id, selectors, snapshot_texts)
    compact_entries = [manifest_entries[path] for path in compact_paths if path in manifest_entries]

    compact_evidence = [
        CompactEvidenceRef(
            compact_path=entry.compact_path,
            traceability_status=entry.traceability_status,
            compact_exists=entry.compact_exists,
            compact_sha256_matches_manifest=entry.compact_sha256_matches_manifest,
            matched_anchors=entry.matched_anchors,
            missing_anchors=entry.missing_anchors,
        )
        for entry in compact_entries
    ]

    upstream_by_key: dict[tuple[str, str | None, str, str | None, str | None], list[str]] = {}
    upstream_ref_by_key: dict[tuple[str, str | None, str, str | None, str | None], UpstreamTraceRef] = {}
    for entry in compact_entries:
        for ref in entry.upstream_refs:
            key = (ref.repository, ref.ref, ref.upstream_path, ref.copied_path, ref.skipped_reason)
            upstream_ref_by_key[key] = ref
            upstream_by_key.setdefault(key, []).append(entry.compact_path)

    present: list[UpstreamEvidenceRef] = []
    missing: list[UpstreamEvidenceRef] = []
    skipped: list[UpstreamEvidenceRef] = []
    for key in sorted(upstream_ref_by_key, key=lambda item: (item[0], item[2], item[3] or "", item[4] or "")):
        ref = upstream_ref_by_key[key]
        compact_ref_paths = sorted(set(upstream_by_key[key]))
        evidence_ref = UpstreamEvidenceRef.from_trace_ref(ref, compact_paths=compact_ref_paths)
        if ref.skipped_reason is not None:
            skipped.append(evidence_ref)
        elif ref.exists:
            present.append(evidence_ref)
        else:
            missing.append(evidence_ref)

    unknown_reasons: list[str] = []
    notes: list[str] = []
    recommended = sorted({ref.upstream_path for ref in missing if ref.upstream_path})

    if not compact_entries:
        support_status = "unknown"
        unknown_reasons.append("no_compact_evidence_mapped")
        notes.append("No compact snapshot file matched this scenario's route/symbol selectors.")
    elif any(not item.compact_exists for item in compact_entries):
        support_status = "unknown"
        unknown_reasons.append("compact_source_missing")
    elif any(item.compact_sha256_matches_manifest is False for item in compact_entries):
        support_status = "unknown"
        unknown_reasons.append("compact_sha256_mismatch")
    elif not any(entry.upstream_refs for entry in compact_entries):
        support_status = "compact_only"
        unknown_reasons.append("no_upstream_metadata")
    elif missing and present:
        support_status = "partially_supported"
        unknown_reasons.append("upstream_source_missing")
    elif missing and not present:
        support_status = "upstream_missing"
        unknown_reasons.append("upstream_source_missing")
    elif skipped and not present:
        support_status = "compact_only"
        unknown_reasons.append("upstream_metadata_not_source_path")
    elif skipped and present:
        support_status = "partially_supported"
        unknown_reasons.append("some_upstream_refs_skipped")
    elif present:
        support_status = "upstream_supported"
    else:
        support_status = "unknown"
        unknown_reasons.append("no_upstream_source_refs")

    for item in compact_entries:
        if item.traceability_status == "manifest_linked":
            unknown_reasons.append("weak_anchor_match")
        elif item.traceability_status == "upstream_refs_skipped":
            unknown_reasons.append("upstream_refs_skipped")
        elif item.traceability_status == "no_upstream_metadata":
            unknown_reasons.append("no_upstream_metadata")

    return CoverageGapEntry(
        scenario_id=scenario_id,
        scenario_kind=scenario_kind,
        question=scenario.get("question"),
        mode=scenario.get("mode"),
        support_status=support_status,
        compact_evidence=compact_evidence,
        upstream_present=present,
        upstream_missing=missing,
        upstream_skipped=skipped,
        recommended_additions=recommended,
        unknown_reasons=sorted(set(unknown_reasons)),
        selectors=selectors,
        notes=notes,
    )


def _extract_scenario_selectors(scenario: dict[str, Any]) -> dict[str, list[str]]:
    expect = scenario.get("expect") or {}
    route_kinds: list[str] = []
    symbols: list[str] = []
    literal_terms: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            payload = value.get("payload_contains")
            if isinstance(payload, dict):
                route_kind = payload.get("route_kind")
                if isinstance(route_kind, str):
                    route_kinds.append(route_kind)
                for payload_value in payload.values():
                    if isinstance(payload_value, str):
                        literal_terms.append(payload_value)
            for key in ("subject", "object", "caller", "callee", "predicate", "claim_type", "fact_type"):
                item = value.get(key)
                if isinstance(item, str):
                    if _looks_like_symbolish(item):
                        symbols.append(item)
                    else:
                        literal_terms.append(item)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            if _looks_like_symbolish(value):
                symbols.append(value)

    walk(expect)
    for key in ("question", "text", "mode"):
        value = scenario.get(key)
        if isinstance(value, str):
            literal_terms.extend(_text_terms(value))
            symbols.extend(_symbol_terms(value))

    token_terms: list[str] = []
    for symbol in symbols:
        token_terms.extend(_symbol_variants(symbol))
    for route_kind in route_kinds:
        token_terms.extend(_route_variants(route_kind))

    return {
        "route_kinds": _unique(route_kinds),
        "symbols": _unique(symbols),
        "tokens": _unique([*token_terms, *literal_terms]),
    }


def _select_compact_paths(scenario_id: str, selectors: dict[str, list[str]], snapshot_texts: dict[str, str]) -> list[str]:
    if not snapshot_texts:
        return []
    scores: dict[str, int] = {}
    route_kinds = selectors.get("route_kinds") or []
    symbols = selectors.get("symbols") or []
    tokens = selectors.get("tokens") or []
    scenario_tokens = _scenario_id_tokens(scenario_id)
    module_hints = _scenario_module_hints(scenario_id)

    for path, text in snapshot_texts.items():
        lower_text = text.lower()
        lower_path = path.lower()
        score = 0
        for route_kind in route_kinds:
            if route_kind and route_kind in text:
                score += 15
            for variant in _route_variants(route_kind):
                if variant and (variant.lower() in lower_path or variant.lower() in lower_text):
                    score += 5
        for symbol in symbols:
            variants = _symbol_variants(symbol)
            if symbol in text:
                score += 8
            if any(variant and variant in text for variant in variants):
                score += 3
        for token in tokens:
            token = token.strip()
            if len(token) < 3:
                continue
            token_lower = token.lower()
            if token_lower in lower_path:
                score += 4
            if token_lower in lower_text:
                score += 1
        for module in module_hints:
            if f"modules/{module}/" in lower_path:
                score += 30
        for token in scenario_tokens:
            if token in lower_path:
                score += 6
        if score:
            scores[path] = score

    if scores:
        best = max(scores.values())
        threshold = max(8, int(best * 0.6))
        return sorted(path for path, score in scores.items() if score >= threshold)

    # Last-resort convention: scenario ids often start with the module/trace name.
    return sorted(path for path in snapshot_texts if any(token in path.lower() for token in scenario_tokens))



def _is_trace_source_path(path: str) -> bool:
    lowered = path.lower()
    if lowered.startswith("upstream_sources/"):
        return False
    return lowered.endswith((".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".rc", ".ipp"))


def _scenario_module_hints(scenario_id: str) -> list[str]:
    lowered = scenario_id.lower()
    hints: list[str] = []
    mapping = {
        "search_command": "search_command",
        "search_claim": "search_command",
        "grep_receiver": "grep_chain",
        "grep_chain": "grep_chain",
        "grep_replace": "grep_replace",
        "undo_redo": "undo_edit",
        "undo_edit": "undo_edit",
        "file_loading": "file_loading",
        "encoding": "file_loading",
        "config_profile": "config_profile",
        "profile_io": "config_profile",
        "windows_message": "windows_message",
        "dialog": "windows_message",
        "ui_resource": "ui_resource",
        "resource_command": "ui_resource",
        "extension_execution": "extension_execution",
        "macro_command": "extension_execution",
        "plugin_hook": "extension_execution",
        "external_command": "extension_execution",
    }
    for needle, module in mapping.items():
        if needle in lowered:
            hints.append(module)
    return _unique(hints)

def _build_coverage_metrics(entries: list[CoverageGapEntry]) -> dict[str, int]:
    counts: dict[str, int] = {
        "scenario_count": len(entries),
        "compact_evidence_files": len({item.compact_path for entry in entries for item in entry.compact_evidence}),
        "upstream_present_refs": sum(len(entry.upstream_present) for entry in entries),
        "upstream_missing_refs": sum(len(entry.upstream_missing) for entry in entries),
        "upstream_skipped_refs": sum(len(entry.upstream_skipped) for entry in entries),
        "recommended_addition_count": len({item for entry in entries for item in entry.recommended_additions}),
    }
    for status in ["upstream_supported", "partially_supported", "compact_only", "upstream_missing", "unknown", "not_applicable"]:
        counts[f"{status}_scenarios"] = sum(1 for entry in entries if entry.support_status == status)
    return counts


def _text_terms(text: str) -> list[str]:
    terms = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    return [term for term in terms if term not in _BORING_SELECTOR_TERMS]


def _symbol_terms(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)+", text)


def _looks_like_symbolish(value: str) -> bool:
    return "::" in value or re.match(r"^[A-Z][A-Za-z0-9_]*$", value) is not None or re.match(r"^[A-Z_][A-Z0-9_]{2,}$", value) is not None


def _symbol_variants(symbol: str) -> list[str]:
    normalized = symbol.strip()
    if not normalized:
        return []
    parts = [part for part in normalized.split("::") if part]
    variants = [normalized]
    variants.extend(parts)
    if len(parts) >= 2:
        variants.append("::".join(parts[-2:]))
    return _unique(variants)


def _route_variants(route_kind: str) -> list[str]:
    if not route_kind:
        return []
    tokens = [token for token in re.split(r"[_\W]+", route_kind.lower()) if len(token) >= 3]
    variants = [route_kind, route_kind.replace("_trace", ""), *tokens]
    # Trace names often include generic words; leave specific words first but keep
    # module path matching useful for fixture snapshots.
    return _unique([item for item in variants if item and item not in _BORING_SELECTOR_TERMS])


def _scenario_id_tokens(scenario_id: str) -> list[str]:
    tokens = [token for token in re.split(r"[_\W]+", scenario_id.lower()) if len(token) >= 3]
    return [token for token in tokens if token not in _BORING_SELECTOR_TERMS]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item is None:
            continue
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_BORING_SELECTOR_TERMS = {
    "trace",
    "command",
    "execution",
    "question",
    "class",
    "fact",
    "type",
    "calls",
    "called",
    "caller",
    "callee",
    "path",
    "route",
    "kind",
    "supported",
    "relation",
    "payload",
    "contains",
    "answerable",
    "where",
    "from",
    "does",
    "how",
    "text",
    "mode",
    "search",
    "profile",
    "dialog",
    "message",
    "resource",
    "external",
    "macro",
    "plugin",
    "file",
    "encoding",
    "undo",
    "redo",
    "grep",
    "replace",
}
