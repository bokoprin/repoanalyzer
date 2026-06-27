from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


@dataclass
class TargetProfileConfig:
    """First-class target-build profile used by C/C++ ingest.

    The profile is intentionally small and serializable.  It lets a fixture or a
    real embedded project say which compile database, config headers, macros,
    and source-tree slices define the target under analysis instead of leaving
    those as scattered top-level options.
    """

    name: str | None = None
    compile_commands: str | None = None
    include_dirs: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    config_headers: list[str] = field(default_factory=list)
    active_path_prefixes: list[str] = field(default_factory=list)
    inactive_path_prefixes: list[str] = field(default_factory=list)
    active_port: str | None = None
    heap: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        attributes = dict(data.pop("attributes", {}) or {})
        data = {key: value for key, value in data.items() if value not in (None, [], {})}
        for key, value in attributes.items():
            if key not in data and value not in (None, [], {}):
                data[key] = value
        return data


@dataclass
class CppConfig:
    include_dirs: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    compile_commands: str | None = None
    obey_gitignore: bool = True
    target_profile: TargetProfileConfig = field(default_factory=TargetProfileConfig)

    @property
    def effective_compile_commands(self) -> str | None:
        return self.target_profile.compile_commands or self.compile_commands

    @property
    def effective_include_dirs(self) -> list[str]:
        return _dedupe([*self.include_dirs, *self.target_profile.include_dirs])

    @property
    def effective_macros(self) -> list[str]:
        return _dedupe([*self.macros, *self.target_profile.macros])


@dataclass
class IndexConfig:
    dir_name: str = ".repoanalyzer-index"
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class RepoAnalyzerConfig:
    index: IndexConfig = field(default_factory=IndexConfig)
    cpp: CppConfig = field(default_factory=CppConfig)


def load_config(path: str | Path | None = None) -> RepoAnalyzerConfig:
    if path is None:
        return RepoAnalyzerConfig()
    p = Path(path)
    if not p.exists():
        return RepoAnalyzerConfig()
    raw: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    idx = raw.get("index", {}) or {}
    cpp = raw.get("cpp", {}) or {}
    target_profile = _load_target_profile(cpp.get("target_profile") or {})
    return RepoAnalyzerConfig(
        index=IndexConfig(
            dir_name=str(idx.get("dir_name", ".repoanalyzer-index")),
            exclude_patterns=list(idx.get("exclude_patterns", []) or []),
        ),
        cpp=CppConfig(
            include_dirs=list(cpp.get("include_dirs", []) or []),
            macros=list(cpp.get("macros", []) or []),
            compile_commands=cpp.get("compile_commands"),
            obey_gitignore=bool(cpp.get("obey_gitignore", True)),
            target_profile=target_profile,
        ),
    )


def _load_target_profile(raw: Any) -> TargetProfileConfig:
    if not isinstance(raw, dict):
        return TargetProfileConfig()
    known_keys = {
        "name",
        "compile_commands",
        "include_dirs",
        "macros",
        "config_headers",
        "config_header",
        "active_path_prefixes",
        "active_paths",
        "inactive_path_prefixes",
        "inactive_paths",
        "active_port",
        "heap",
        "attributes",
    }
    attributes = dict(raw.get("attributes") or {}) if isinstance(raw.get("attributes"), dict) else {}
    for key, value in raw.items():
        if key not in known_keys and value not in (None, [], {}):
            attributes[str(key)] = value
    return TargetProfileConfig(
        name=_optional_str(raw.get("name")),
        compile_commands=_optional_str(raw.get("compile_commands")),
        include_dirs=list(raw.get("include_dirs", []) or []),
        macros=list(raw.get("macros", []) or []),
        config_headers=list(raw.get("config_headers", raw.get("config_header", [])) or []),
        active_path_prefixes=list(raw.get("active_path_prefixes", raw.get("active_paths", [])) or []),
        inactive_path_prefixes=list(raw.get("inactive_path_prefixes", raw.get("inactive_paths", [])) or []),
        active_port=_optional_str(raw.get("active_port")),
        heap=_optional_str(raw.get("heap")),
        attributes=attributes,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
