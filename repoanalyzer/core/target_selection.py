from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from repoanalyzer.core.source_kinds import CPP_SOURCE_EXTENSIONS


@dataclass(frozen=True)
class TargetFileDecision:
    path: str
    status: str
    reasons: list[str] = field(default_factory=list)
    matched_prefixes: list[str] = field(default_factory=list)
    active_port: str | None = None
    heap: str | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"

    def to_payload(self, target_profile: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = target_profile or {}
        payload: dict[str, Any] = {
            "selection_status": self.status,
            "selection_reasons": list(self.reasons),
            "matched_prefixes": list(self.matched_prefixes),
            "target_profile": profile.get("name"),
            "active_port": self.active_port or profile.get("active_port"),
            "heap": self.heap or profile.get("heap"),
            "build_status": self.status,
            "build_status_precision": "target_profile_file_selection",
            "target_profile_file_selection": True,
        }
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


def filter_active_files(files: Iterable[Any], source_files: list[str], target_profile: dict[str, Any] | None = None) -> list[Any]:
    allowed_sources = set(source_files)
    return [source_file for source_file in files if decide_target_file(source_file.path, allowed_sources, target_profile).active]


def decide_target_file(path: str, source_files: set[str] | list[str] | None = None, target_profile: dict[str, Any] | None = None) -> TargetFileDecision:
    profile = target_profile or {}
    normalized_path = _normalize_path(path)
    allowed_sources = set(source_files or [])
    active_prefixes = [_normalize_prefix(value) for value in profile.get("active_path_prefixes") or []]
    inactive_prefixes = [_normalize_prefix(value) for value in profile.get("inactive_path_prefixes") or []]
    active_prefixes = [value for value in active_prefixes if value]
    inactive_prefixes = [value for value in inactive_prefixes if value]
    active_port = _normalize_prefix(profile.get("active_port")) or None
    heap = _normalize_heap(profile.get("heap"))

    reasons: list[str] = []
    matched_prefixes: list[str] = []

    explicit_inactive = [prefix for prefix in inactive_prefixes if _path_matches_prefix(normalized_path, prefix)]
    if explicit_inactive:
        return TargetFileDecision(
            normalized_path,
            "inactive",
            ["inactive_path_prefix"],
            explicit_inactive,
            active_port=active_port,
            heap=heap,
        )

    if active_prefixes:
        matched_active = [prefix for prefix in active_prefixes if _path_matches_prefix(normalized_path, prefix)]
        if not matched_active:
            return TargetFileDecision(
                normalized_path,
                "inactive",
                ["not_in_active_path_prefixes"],
                [],
                active_port=active_port,
                heap=heap,
            )
        reasons.append("active_path_prefix")
        matched_prefixes.extend(matched_active)

    if active_port and _is_portable_port_path(normalized_path):
        if _path_matches_prefix(normalized_path, active_port):
            reasons.append("active_port")
            matched_prefixes.append(active_port)
        else:
            return TargetFileDecision(
                normalized_path,
                "inactive",
                ["non_selected_port"],
                matched_prefixes,
                active_port=active_port,
                heap=heap,
            )

    if _is_heap_file(normalized_path):
        if heap is None:
            reasons.append("heap_unconstrained")
        elif _heap_file_matches(normalized_path, heap):
            reasons.append("selected_heap")
            matched_prefixes.append(_heap_path(heap))
        else:
            return TargetFileDecision(
                normalized_path,
                "inactive",
                ["non_selected_heap"],
                matched_prefixes,
                active_port=active_port,
                heap=heap,
            )

    if allowed_sources and Path(normalized_path).suffix.lower() in CPP_SOURCE_EXTENSIONS and normalized_path not in allowed_sources:
        return TargetFileDecision(
            normalized_path,
            "inactive",
            ["not_in_compile_commands"],
            matched_prefixes,
            active_port=active_port,
            heap=heap,
        )

    if not reasons:
        if allowed_sources and normalized_path in allowed_sources:
            reasons.append("compile_commands_entry")
        else:
            reasons.append("default_active")

    return TargetFileDecision(
        normalized_path,
        "active",
        _dedupe(reasons),
        _dedupe(matched_prefixes),
        active_port=active_port,
        heap=heap,
    )


def _normalize_path(value: Any) -> str:
    return str(value).strip().replace("\\", "/").strip("/")


def _normalize_prefix(value: Any) -> str:
    if value is None:
        return ""
    return _normalize_path(value)


def _normalize_heap(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\\", "/")
    if not text:
        return None
    name = Path(text).name
    if name.endswith(".c"):
        name = name[:-2]
    return name or None


def _heap_path(heap: str) -> str:
    if "/" in heap:
        return heap
    return f"portable/MemMang/{heap}.c"


def _path_matches_prefix(path: str, prefix: str) -> bool:
    normalized = path.strip("/")
    prefix = prefix.strip("/")
    return bool(prefix) and (normalized == prefix or normalized.startswith(prefix.rstrip("/") + "/"))


def _is_portable_port_path(path: str) -> bool:
    portable_prefix = _portable_prefix(path)
    if portable_prefix is None:
        return False
    if path.startswith("portable/MemMang/"):
        return False
    parts = path.split("/")
    return len(parts) >= len(portable_prefix.split("/")) + 1


def _portable_prefix(path: str) -> str | None:
    if path.startswith("portable/"):
        return "portable"
    if path.startswith("src/portable/"):
        return "src/portable"
    return None


def _is_heap_file(path: str) -> bool:
    name = Path(path).name
    return path.startswith("portable/MemMang/") and name.startswith("heap_") and name.endswith(".c")


def _heap_file_matches(path: str, heap: str) -> bool:
    return Path(path).stem == heap or _normalize_path(path) == _normalize_path(_heap_path(heap))


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
