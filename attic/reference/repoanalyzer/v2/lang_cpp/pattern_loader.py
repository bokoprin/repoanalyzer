from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class PatternPack:
    name: str
    base_name: str
    callback_registration_terms: tuple[str, ...]
    callback_invocation_terms: tuple[str, ...]
    function_pointer_assignment_terms: tuple[str, ...]
    function_pointer_indirect_terms: tuple[str, ...]
    override_terms: tuple[str, ...]
    task_terms: tuple[str, ...]
    queue_terms: tuple[str, ...]
    event_terms: tuple[str, ...]
    timer_terms: tuple[str, ...]
    isr_terms: tuple[str, ...]
    state_terms: tuple[str, ...]
    path_weights: dict[str, float]
    noisy_paths: tuple[str, ...]
    override_paths: tuple[str, ...] = ()


def load_pattern_pack(
    name: str,
    *,
    repo_path: Path | None = None,
    override_file: Path | None = None,
) -> PatternPack:
    if override_file is None and repo_path is None:
        return _load_pattern_pack_cached(name)
    return _load_pattern_pack_uncached(name, repo_path=repo_path, override_file=override_file)


@lru_cache(maxsize=8)
def _load_pattern_pack_cached(name: str) -> PatternPack:
    return _load_pattern_pack_uncached(name, repo_path=None, override_file=None)


def _load_pattern_pack_uncached(
    name: str, *, repo_path: Path | None, override_file: Path | None
) -> PatternPack:
    normalized = (name or "generic_cpp").strip().lower() or "generic_cpp"
    patterns_dir = Path(__file__).with_name("patterns")
    candidate = patterns_dir / f"{normalized}.yaml"
    if not candidate.exists():
        normalized = "generic_cpp"
        candidate = patterns_dir / "generic_cpp.yaml"
    payload = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    applied_overrides: list[str] = []
    for extra in _resolve_override_candidates(repo_path=repo_path, override_file=override_file):
        try:
            override_payload = yaml.safe_load(extra.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(override_payload, dict):
            continue
        payload = _merge_payload(payload, override_payload)
        applied_overrides.append(str(extra))
    return PatternPack(
        name=normalized,
        base_name=normalized,
        callback_registration_terms=_tuple(payload, "callback_registration_terms"),
        callback_invocation_terms=_tuple(payload, "callback_invocation_terms"),
        function_pointer_assignment_terms=_tuple(payload, "function_pointer_assignment_terms"),
        function_pointer_indirect_terms=_tuple(payload, "function_pointer_indirect_terms"),
        override_terms=_tuple(payload, "override_terms"),
        task_terms=_tuple(payload, "task_terms"),
        queue_terms=_tuple(payload, "queue_terms"),
        event_terms=_tuple(payload, "event_terms"),
        timer_terms=_tuple(payload, "timer_terms"),
        isr_terms=_tuple(payload, "isr_terms"),
        state_terms=_tuple(payload, "state_terms"),
        path_weights={
            str(key).strip().lower(): float(value)
            for key, value in dict(payload.get("path_weights") or {}).items()
            if str(key).strip()
        },
        noisy_paths=_tuple(payload, "noisy_paths"),
        override_paths=tuple(applied_overrides),
    )


def _tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = payload.get(key) or []
    return tuple(str(item).strip().lower() for item in raw if str(item).strip())


def _resolve_override_candidates(
    *, repo_path: Path | None, override_file: Path | None
) -> list[Path]:
    candidates: list[Path] = []
    if override_file is not None:
        path = override_file.resolve()
        if path.exists():
            candidates.append(path)
        return candidates
    if repo_path is None:
        return candidates
    roots = [
        repo_path / ".repoanalyzer" / "v2_pattern_overrides.yaml",
        repo_path / ".repoanalyzer" / "pattern_pack_overrides.yaml",
        repo_path / "repoanalyzer.v2_patterns.yaml",
    ]
    for item in roots:
        if item.exists():
            candidates.append(item.resolve())
    return candidates


def _merge_payload(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    list_keys = {
        "callback_registration_terms",
        "callback_invocation_terms",
        "function_pointer_assignment_terms",
        "function_pointer_indirect_terms",
        "override_terms",
        "task_terms",
        "queue_terms",
        "event_terms",
        "timer_terms",
        "isr_terms",
        "state_terms",
        "noisy_paths",
    }
    for key in list_keys:
        merged: list[str] = []
        for value in list(base.get(key) or []) + list(override.get(key) or []):
            token = str(value).strip()
            if token and token not in merged:
                merged.append(token)
        if merged:
            out[key] = merged
    base_weights = dict(base.get("path_weights") or {})
    override_weights = dict(override.get("path_weights") or {})
    if base_weights or override_weights:
        out["path_weights"] = {**base_weights, **override_weights}
    return out
