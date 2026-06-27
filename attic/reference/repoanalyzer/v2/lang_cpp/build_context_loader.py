from __future__ import annotations

import json
import os
import re
import shlex
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from repoanalyzer.v2.core.models import BuildContext

_DEFINE_RE = re.compile(r"^-D([A-Za-z_][A-Za-z0-9_]*)(?:=(.+))?$")
_HEADER_DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.+))?$")
_MACRO_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FEATURE_PREFIXES = ("ENABLE_", "USE_", "WITH_", "CONFIG_")
_TARGET_KEYS = ("target", "board", "platform", "arch")
_VARIANT_KEYS = ("variant", "build_type", "profile", "flavor", "mode")
_DEFAULT_HEADERS = (
    "FreeRTOSConfig.h",
    "freertosconfig.h",
    "config.h",
    "build_config.h",
    "project_config.h",
    "autoconf.h",
    "pg_config.h",
    "opensslconf.h",
    "configuration.h",
)
_DEFAULT_PROFILE_FILES = (
    ".repoanalyzer/build_profiles.yaml",
    "repoanalyzer.build_profiles.yaml",
)
_DEFAULT_COMPILE_COMMANDS = ("compile_commands.json", "build/compile_commands.json")
_DEFAULT_CMAKE_CACHE = ("CMakeCache.txt", "build/CMakeCache.txt")
_DEFAULT_MSBUILD_PROJECT_PATTERNS = ("**/*.vcxproj", "**/*.props")
_DEFAULT_MAKEFILE_FILES = (
    "Makefile",
    "makefile",
    "GNUmakefile",
    "build/Makefile",
    "build/makefile",
    "Makefile.msc",
    "makefile.msc",
)
_DEFAULT_MAKEFILE_PATTERNS = ("**/*.mk", "**/*.mak", "**/Makefile.msc", "**/makefile.msc")
_DEFAULT_CONFIGURE_FILES = ("configure.ac", "configure.in", "Configure")
_HEADER_MACRO_LIMIT_PER_FILE = 256
_GLOBAL_COMPILE_MACRO_RATIO = 0.6
_GLOBAL_COMPILE_MACRO_MAX = 64
_GLOBAL_HEADER_MACRO_MAX = 48
_INCLUDE_GUARD_SUFFIXES = ("_H", "_H_", "_HPP", "_HPP_", "_HH", "_HH_")
_BUILD_CONTEXT_CACHE_MAX = 64
_BUILD_CONTEXT_CACHE: dict[tuple[Any, ...], BuildContextLoadResult] = {}
_HEADER_NAME_PRIORITY = {
    "freertosconfig.h": 0,
    "config.h": 1,
    "build_config.h": 2,
    "project_config.h": 3,
    "autoconf.h": 4,
    "pg_config.h": 5,
    "opensslconf.h": 6,
    "configuration.h": 7,
}


@dataclass(slots=True)
class BuildContextLoadResult:
    context: BuildContext
    sources: list[dict[str, Any]] = field(default_factory=list)
    scoped_entries: list[dict[str, Any]] = field(default_factory=list)
    profile_name: str = ""
    profile_file: str = ""
    ambiguous_notes: list[str] = field(default_factory=list)

    def to_trace_payload(self) -> dict[str, Any]:
        return {
            "summary": self.context.summary(),
            "defined_macros": sorted(self.context.defined_macros),
            "target": self.context.target,
            "variant": self.context.variant,
            "features": sorted(self.context.feature_flags),
            "source": self.context.source,
            "sources": list(self.context.sources),
            "overridden_by": list(self.context.overridden_by),
            "source_details": self.sources,
            "scoped_entries": self.scoped_entries,
            "profile_name": self.profile_name,
            "profile_file": self.profile_file,
            "ambiguous_notes": list(self.ambiguous_notes),
        }


def build_context_from_sources(
    *,
    repo_path: Path,
    cli_macros: list[str] | tuple[str, ...],
    macro_file: Path | None,
    target: str | None,
    variant: str | None,
    features: list[str] | tuple[str, ...],
    profile_name: str | None = None,
    auto_build_context: bool = False,
) -> BuildContextLoadResult:
    repo_root = repo_path.resolve()
    cache_key: tuple[Any, ...] | None = None
    cache_enabled_env = os.getenv("REPOANALYZER_ENABLE_BUILD_CONTEXT_CACHE", "0")
    cache_disabled_env = os.getenv("REPOANALYZER_DISABLE_BUILD_CONTEXT_CACHE", "0")
    cache_enabled = (
        auto_build_context
        and cache_enabled_env in {"1", "true", "TRUE"}
        and cache_disabled_env not in {"1", "true", "TRUE"}
    )
    if cache_enabled:
        cache_key = (
            str(repo_root),
            tuple(sorted(str(item).strip().upper() for item in cli_macros if str(item).strip())),
            str(macro_file.resolve()) if macro_file is not None else "",
            (target or "").strip(),
            (variant or "").strip(),
            tuple(sorted(str(item).strip().upper() for item in features if str(item).strip())),
            (profile_name or "").strip(),
            True,
        )
        cached = _BUILD_CONTEXT_CACHE.get(cache_key)
        if cached is not None:
            return _clone_build_context_load_result(cached)

    macro_set: set[str] = set()
    feature_set: set[str] = set()
    compiler_flags: list[str] = []
    source_details: list[dict[str, Any]] = []
    scoped_entries: list[dict[str, Any]] = []
    source_order: list[str] = []
    overrides: list[str] = []
    derived_targets: list[str] = []
    derived_variants: list[str] = []
    ambiguous: list[str] = []

    def add_source(name: str, *, meta: dict[str, Any] | None = None) -> None:
        if name not in source_order:
            source_order.append(name)
        payload = {"source": name}
        if meta:
            payload.update(meta)
        source_details.append(payload)

    def add_scoped_entry(
        *,
        source_type: str,
        confidence: float,
        scope_type: str,
        scope_target: str,
        macros: set[str] | list[str],
        features: set[str] | list[str] | None = None,
        compiler: list[str] | tuple[str, ...] | None = None,
        include_dirs: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        macro_values = sorted({item for item in macros if item})
        feature_values = sorted({item for item in (features or []) if item})
        compiler_values = [item for item in (compiler or []) if item]
        include_values = [
            str(item).replace("\\", "/") for item in (include_dirs or []) if str(item)
        ]
        if not macro_values and not feature_values and not compiler_values:
            return
        scoped_entries.append(
            {
                "source_type": source_type,
                "confidence": round(float(confidence), 3),
                "scope_type": scope_type,
                "scope_target": scope_target,
                "macros": macro_values,
                "features": feature_values,
                "compiler_flags": compiler_values,
                "include_dirs": include_values,
            }
        )

    if auto_build_context:
        cc_entries, cc_source = _load_compile_commands(repo_root)
        if cc_entries:
            (
                macros,
                flags,
                inferred_target,
                inferred_variant,
                scoped_compile,
            ) = _extract_from_compile_commands(
                cc_entries,
                repo_root=repo_root,
            )
            macro_set.update(macros)
            compiler_flags.extend(flags)
            add_scoped_entry(
                source_type="compile_commands",
                confidence=0.95,
                scope_type="global",
                scope_target="*",
                macros=macros,
                compiler=flags,
            )
            for entry in scoped_compile:
                scope_target = str(entry.get("file") or "")
                add_scoped_entry(
                    source_type="compile_commands",
                    confidence=0.97,
                    scope_type="translation_unit",
                    scope_target=scope_target,
                    macros=set(entry.get("macros") or []),
                    compiler=list(entry.get("compiler_flags") or []),
                    include_dirs=list(entry.get("include_dirs") or []),
                )
                module_target = str(entry.get("module") or "")
                if module_target:
                    add_scoped_entry(
                        source_type="compile_commands",
                        confidence=0.82,
                        scope_type="module",
                        scope_target=module_target,
                        macros=set(entry.get("macros") or []),
                        compiler=list(entry.get("compiler_flags") or []),
                        include_dirs=list(entry.get("include_dirs") or []),
                    )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "compile_commands",
                meta={
                    "path": cc_source,
                    "entries": len(cc_entries),
                    "global_macros": len(macros),
                    "scoped_entries": len(scoped_compile),
                    "confidence": 0.97,
                },
            )

        cmake_data = _load_cmake_cache(repo_root)
        if cmake_data:
            macros, flags, inferred_target, inferred_variant = _extract_from_cmake_cache(cmake_data)
            selected_macros = _select_global_aux_macros(macros)
            macro_set.update(selected_macros)
            feature_set.update(flags)
            add_scoped_entry(
                source_type="cmake_cache",
                confidence=0.7,
                scope_type="target_variant",
                scope_target=_build_target_variant_scope(inferred_target, inferred_variant),
                macros=macros,
                features=flags,
            )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "cmake_cache",
                meta={
                    "entries": len(cmake_data),
                    "macros": len(macros),
                    "global_macros": len(selected_macros),
                },
            )

        cmake_lists = _load_cmake_lists(repo_root)
        if cmake_lists:
            (
                macros,
                flags,
                inferred_target,
                inferred_variant,
            ) = _extract_from_cmake_lists(cmake_lists)
            selected_macros = _select_global_aux_macros(macros)
            macro_set.update(selected_macros)
            feature_set.update(flags)
            add_scoped_entry(
                source_type="cmake_lists",
                confidence=0.62,
                scope_type="target_variant",
                scope_target=_build_target_variant_scope(inferred_target, inferred_variant),
                macros=macros,
                features=flags,
            )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "cmake_lists",
                meta={
                    "files": len(cmake_lists),
                    "macros": len(macros),
                    "global_macros": len(selected_macros),
                },
            )

        msbuild_projects = _load_msbuild_projects(repo_root)
        if msbuild_projects:
            (
                macros,
                inferred_target,
                inferred_variant,
                scoped_projects,
            ) = _extract_from_msbuild_projects(
                msbuild_projects,
                repo_root=repo_root,
            )
            selected_macros = _select_global_aux_macros(macros)
            macro_set.update(selected_macros)
            include_dir_count = 0
            for scoped in scoped_projects:
                include_dirs = list(scoped.get("include_dirs") or [])
                include_dir_count += len(include_dirs)
                scope_target = str(scoped.get("scope_target") or "")
                add_scoped_entry(
                    source_type="msbuild_project",
                    confidence=0.66,
                    scope_type=str(scoped.get("scope_type") or "module"),
                    scope_target=scope_target,
                    macros=set(scoped.get("macros") or []),
                    include_dirs=include_dirs,
                )
                module_target = str(scoped.get("module") or "")
                if module_target and module_target != scope_target:
                    add_scoped_entry(
                        source_type="msbuild_project",
                        confidence=0.62,
                        scope_type="module",
                        scope_target=module_target,
                        macros=set(scoped.get("macros") or []),
                        include_dirs=include_dirs,
                    )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "msbuild_project",
                meta={
                    "files": len(msbuild_projects),
                    "macros": len(macros),
                    "global_macros": len(selected_macros),
                    "include_dirs": include_dir_count,
                },
            )

        makefiles = _load_makefiles(repo_root)
        if makefiles:
            (
                macros,
                features,
                inferred_target,
                inferred_variant,
                scoped_makefiles,
            ) = _extract_from_makefiles(makefiles)
            selected_macros = _select_global_aux_macros(macros)
            macro_set.update(selected_macros)
            feature_set.update(features)
            for scoped in scoped_makefiles:
                add_scoped_entry(
                    source_type="makefile",
                    confidence=0.61,
                    scope_type=str(scoped.get("scope_type") or "path_prefix"),
                    scope_target=str(scoped.get("scope_target") or ""),
                    macros=set(scoped.get("macros") or []),
                    features=set(scoped.get("features") or []),
                    include_dirs=list(scoped.get("include_dirs") or []),
                )
            add_scoped_entry(
                source_type="makefile",
                confidence=0.6,
                scope_type="target_variant",
                scope_target=_build_target_variant_scope(inferred_target, inferred_variant),
                macros=macros,
                features=features,
            )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "makefile",
                meta={
                    "files": len(makefiles),
                    "macros": len(macros),
                    "global_macros": len(selected_macros),
                    "scoped_entries": len(scoped_makefiles),
                },
            )

        configure_scripts = _load_configure_scripts(repo_root)
        if configure_scripts:
            (
                macros,
                features,
                inferred_target,
                inferred_variant,
                scoped_configure,
            ) = _extract_from_configure_scripts(configure_scripts)
            selected_macros = _select_global_aux_macros(macros)
            macro_set.update(selected_macros)
            feature_set.update(features)
            for scoped in scoped_configure:
                add_scoped_entry(
                    source_type="configure_script",
                    confidence=0.57,
                    scope_type="path_prefix",
                    scope_target=str(scoped.get("scope_target") or ""),
                    macros=set(scoped.get("macros") or []),
                    features=set(scoped.get("features") or []),
                )
            add_scoped_entry(
                source_type="configure_script",
                confidence=0.54,
                scope_type="target_variant",
                scope_target=_build_target_variant_scope(inferred_target, inferred_variant),
                macros=macros,
                features=features,
            )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "configure_script",
                meta={
                    "files": len(configure_scripts),
                    "macros": len(macros),
                    "global_macros": len(selected_macros),
                    "features": len(features),
                    "scoped_entries": len(scoped_configure),
                },
            )

        header_hits = _scan_config_headers(repo_root)
        if header_hits:
            (
                macros,
                inferred_target,
                inferred_variant,
                scoped_headers,
            ) = _extract_from_headers(header_hits)
            selected_global_header_macros = _select_global_header_macros(macros)
            macro_set.update(selected_global_header_macros)
            pruned_total = 0
            for scoped in scoped_headers:
                pruned_total += int(scoped.get("pruned_macros") or 0)
                add_scoped_entry(
                    source_type="config_header",
                    confidence=0.58,
                    scope_type=str(scoped.get("scope_type") or "path_prefix"),
                    scope_target=str(scoped.get("scope_target") or ""),
                    macros=set(scoped.get("macros") or []),
                )
            if inferred_target:
                derived_targets.append(inferred_target)
            if inferred_variant:
                derived_variants.append(inferred_variant)
            add_source(
                "config_header",
                meta={
                    "files": len(header_hits),
                    "macros": len(macros),
                    "global_macros": len(selected_global_header_macros),
                    "guard_like_macros_ignored": max(
                        0, len(macros) - len(selected_global_header_macros)
                    ),
                    "pruned_macros": pruned_total,
                    "confidence": 0.58,
                },
            )

        env_macros = _split_terms(os.getenv("REPOANALYZER_BUILD_MACROS", ""))
        env_features = _split_terms(os.getenv("REPOANALYZER_BUILD_FEATURES", ""))
        env_target = (os.getenv("REPOANALYZER_BUILD_TARGET") or "").strip()
        env_variant = (os.getenv("REPOANALYZER_BUILD_VARIANT") or "").strip()
        if env_macros or env_features or env_target or env_variant:
            macro_set.update(_normalize_macros(env_macros))
            feature_set.update(_normalize_terms(env_features))
            add_scoped_entry(
                source_type="env",
                confidence=0.6,
                scope_type="global",
                scope_target="*",
                macros=_normalize_macros(env_macros),
                features=_normalize_terms(env_features),
            )
            if env_target:
                derived_targets.append(env_target)
            if env_variant:
                derived_variants.append(env_variant)
            add_source(
                "env",
                meta={
                    "macros": len(env_macros),
                    "features": len(env_features),
                    "target": env_target,
                    "variant": env_variant,
                },
            )

        profile = _load_profile(repo_root, profile_name or "")
        if profile is not None:
            profile_macros = _normalize_macros(_iter_values(profile.get("macros")))
            profile_features = _normalize_terms(_iter_values(profile.get("features")))
            macro_set.update(profile_macros)
            feature_set.update(profile_features)
            add_scoped_entry(
                source_type="profile",
                confidence=0.65,
                scope_type="global",
                scope_target="*",
                macros=profile_macros,
                features=profile_features,
            )
            if profile.get("target"):
                derived_targets.append(str(profile["target"]).strip())
            if profile.get("variant"):
                derived_variants.append(str(profile["variant"]).strip())
            compiler_flags.extend(
                [value for value in _iter_values(profile.get("compiler_flags")) if value]
            )
            add_source(
                "profile",
                meta={
                    "name": str(profile.get("_profile_name") or ""),
                    "file": str(profile.get("_profile_file") or ""),
                    "macros": len(profile_macros),
                    "features": len(profile_features),
                },
            )

    if macro_file is not None and macro_file.exists():
        file_macros = _load_macro_file(macro_file)
        if file_macros:
            macro_set.update(_normalize_macros(file_macros))
            overrides.append("macro_file")
            add_scoped_entry(
                source_type="macro_file",
                confidence=0.98,
                scope_type="global",
                scope_target="*",
                macros=_normalize_macros(file_macros),
            )
            add_source("macro_file", meta={"path": str(macro_file), "macros": len(file_macros)})

    cli_macros_norm = _normalize_macros(list(cli_macros))
    if cli_macros_norm:
        macro_set.update(cli_macros_norm)
        overrides.append("cli_macro")
        add_scoped_entry(
            source_type="cli_macro",
            confidence=1.0,
            scope_type="global",
            scope_target="*",
            macros=cli_macros_norm,
        )
        add_source("cli_macro", meta={"macros": len(cli_macros_norm)})

    feature_norm = _normalize_terms(list(features))
    if feature_norm:
        feature_set.update(feature_norm)
        overrides.append("cli_feature")
        add_scoped_entry(
            source_type="cli_feature",
            confidence=1.0,
            scope_type="global",
            scope_target="*",
            macros=set(),
            features=feature_norm,
        )
        add_source("cli_feature", meta={"features": len(feature_norm)})

    selected_target = (target or "").strip() or ""
    if selected_target:
        overrides.append("cli_target")
        add_source("cli_target", meta={"target": selected_target})
    else:
        selected_target = _pick_single_or_none(derived_targets, ambiguous, "target")

    selected_variant = (variant or "").strip() or ""
    if selected_variant:
        overrides.append("cli_variant")
        add_source("cli_variant", meta={"variant": selected_variant})
    else:
        selected_variant = _pick_single_or_none(derived_variants, ambiguous, "variant")

    inferred_features = {macro for macro in macro_set if macro.startswith(_FEATURE_PREFIXES)}
    feature_set.update(inferred_features)

    source_label = "merged" if source_order else "unspecified"
    profile_file = ""
    resolved_profile_name = ""
    for item in source_details:
        if str(item.get("source")) == "profile":
            resolved_profile_name = str(item.get("name") or "")
            profile_file = str(item.get("file") or "")
            break
    context = BuildContext(
        defined_macros=frozenset(sorted(macro_set)),
        target=selected_target or None,
        variant=selected_variant or None,
        feature_flags=frozenset(sorted(feature_set)),
        compiler_flags=tuple(dict.fromkeys(flag for flag in compiler_flags if flag)),
        source=source_label,
        sources=tuple(source_order),
        overridden_by=tuple(overrides),
    )
    if context.is_empty():
        context = BuildContext()
    result = BuildContextLoadResult(
        context=context,
        sources=source_details,
        scoped_entries=scoped_entries,
        profile_name=resolved_profile_name,
        profile_file=profile_file,
        ambiguous_notes=ambiguous,
    )
    if cache_enabled and cache_key is not None:
        _BUILD_CONTEXT_CACHE[cache_key] = _clone_build_context_load_result(result)
        if len(_BUILD_CONTEXT_CACHE) > _BUILD_CONTEXT_CACHE_MAX:
            oldest = next(iter(_BUILD_CONTEXT_CACHE))
            if oldest != cache_key:
                _BUILD_CONTEXT_CACHE.pop(oldest, None)
    return result


def _clone_build_context_load_result(result: BuildContextLoadResult) -> BuildContextLoadResult:
    return BuildContextLoadResult(
        context=result.context,
        sources=deepcopy(result.sources),
        scoped_entries=deepcopy(result.scoped_entries),
        profile_name=str(result.profile_name),
        profile_file=str(result.profile_file),
        ambiguous_notes=list(result.ambiguous_notes),
    )


def _load_compile_commands(repo_root: Path) -> tuple[list[dict[str, Any]], str]:
    candidates: list[Path] = []
    for relative in _DEFAULT_COMPILE_COMMANDS:
        path = repo_root / relative
        if path.exists():
            candidates.append(path)
    if not candidates:
        matches = list(repo_root.glob("**/compile_commands.json"))
        candidates.extend(sorted(matches)[:3])
    best_entries: list[dict[str, Any]] = []
    best_score = -1
    best_path = ""
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            entries = [entry for entry in data if isinstance(entry, dict)]
            score = _compile_commands_quality(entries)
            if score <= best_score:
                continue
            best_score = score
            best_entries = entries
            best_path = _normalize_repo_relative_path(
                repo_root=repo_root,
                value=str(path),
                base_dir=repo_root,
            )
    return best_entries, best_path


def _extract_from_compile_commands(
    entries: list[dict[str, Any]],
    *,
    repo_root: Path,
) -> tuple[set[str], list[str], str, str, list[dict[str, Any]]]:
    flags: list[str] = []
    targets: list[str] = []
    variants: list[str] = []
    scoped: list[dict[str, Any]] = []
    macro_counter: Counter[str] = Counter()
    seen_files: set[str] = set()
    for entry in entries:
        command = str(entry.get("command") or "").strip()
        args = entry.get("arguments")
        directory_raw = str(entry.get("directory") or "").strip()
        directory_abs = _resolve_directory(repo_root=repo_root, directory=directory_raw)
        tokens: list[str] = []
        if isinstance(args, list):
            tokens = _expand_response_files(
                [str(item) for item in args],
                base_dir=directory_abs,
            )
        elif command:
            tokens = _tokenize_compile_command(command, base_dir=directory_abs)
        file_macros: set[str] = set()
        file_flags: list[str] = []
        include_dirs: list[str] = []
        pending_include = False
        pending_isystem = False
        pending_define = False
        for token in tokens:
            if pending_include:
                include_dirs.append(str(token).strip().replace("\\", "/"))
                pending_include = False
                continue
            if pending_isystem:
                include_dirs.append(str(token).strip().replace("\\", "/"))
                pending_isystem = False
                continue
            if pending_define:
                pending_define = False
                name, _, value = str(token).partition("=")
                if value.strip() in {"0", "FALSE", "false"}:
                    continue
                normalized = name.strip().upper()
                if _MACRO_NAME_RE.match(normalized):
                    file_macros.add(normalized)
                continue
            match = _DEFINE_RE.match(token.strip())
            if match:
                macro_name = match.group(1).upper()
                file_macros.add(macro_name)
                continue
            if token == "-I":  # nosec B105
                pending_include = True
                continue
            if token == "-isystem":  # nosec B105
                pending_isystem = True
                continue
            if token in {"-D", "/D"}:
                pending_define = True
                continue
            if token.startswith("-I") and len(token) > 2:
                include_dirs.append(token[2:].strip())
                continue
            if token.startswith("/I") and len(token) > 2:
                include_dirs.append(token[2:].strip())
                continue
            if token.startswith("-isystem") and len(token) > len("-isystem"):
                include_dirs.append(token[len("-isystem") :].strip())
                continue
            if token.startswith("/D") and len(token) > 2:
                name, _, value = token[2:].partition("=")
                if value.strip() in {"0", "FALSE", "false"}:
                    continue
                normalized = name.strip().upper()
                if _MACRO_NAME_RE.match(normalized):
                    file_macros.add(normalized)
                continue
            if token.startswith("-O") or token.startswith("-std=") or token.startswith("-f"):
                flags.append(token.strip())
                file_flags.append(token.strip())
        file_path = str(entry.get("file") or "")
        if file_path:
            normalized_file = _normalize_repo_relative_path(
                repo_root=repo_root,
                value=file_path,
                base_dir=directory_abs,
            )
            if normalized_file:
                seen_files.add(normalized_file)
            normalized_includes = [
                _normalize_repo_relative_path(
                    repo_root=repo_root,
                    value=include_dir,
                    base_dir=directory_abs,
                    keep_relative=True,
                )
                for include_dir in include_dirs
            ]
            normalized_includes = [item for item in normalized_includes if item]
            scoped.append(
                {
                    "file": normalized_file,
                    "module": _infer_module_from_path(normalized_file),
                    "directory": _normalize_repo_relative_path(
                        repo_root=repo_root,
                        value=str(directory_abs),
                        base_dir=repo_root,
                    ),
                    "macros": sorted(file_macros),
                    "compiler_flags": file_flags,
                    "include_dirs": _normalize_include_dirs(normalized_includes),
                }
            )
        for macro in file_macros:
            macro_counter[macro] += 1
        inferred = _infer_target_variant_from_text(f"{file_path} {directory_raw}")
        if inferred[0]:
            targets.append(inferred[0])
        if inferred[1]:
            variants.append(inferred[1])
    global_macros = _select_global_compile_macros(
        macro_counter=macro_counter,
        total_files=max(1, len(seen_files)),
    )
    return global_macros, flags, _pick_single(targets), _pick_single(variants), scoped


def _compile_commands_quality(entries: list[dict[str, Any]]) -> int:
    if not entries:
        return 0
    file_count = 0
    macro_hits = 0
    include_hits = 0
    for entry in entries:
        if str(entry.get("file") or "").strip():
            file_count += 1
        command_text = str(entry.get("command") or "")
        args = entry.get("arguments")
        if "-D" in command_text:
            macro_hits += 1
        if "-I" in command_text or "-isystem" in command_text:
            include_hits += 1
        if isinstance(args, list):
            for token in args:
                raw = str(token)
                if raw.startswith("-D") or raw.startswith("/D") or raw in {"-D", "/D"}:
                    macro_hits += 1
                if raw.startswith("-I") or raw.startswith("/I") or raw == "-isystem":
                    include_hits += 1
    return (file_count * 10) + (macro_hits * 2) + include_hits


def _load_cmake_cache(repo_root: Path) -> list[str]:
    for relative in _DEFAULT_CMAKE_CACHE:
        path = repo_root / relative
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
    return []


def _extract_from_cmake_cache(lines: list[str]) -> tuple[set[str], set[str], str, str]:
    macros: set[str] = set()
    features: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith(("#", "//")) or ":" not in line or "=" not in line:
            continue
        left, value = line.split("=", 1)
        key, _, dtype = left.partition(":")
        key_norm = key.strip()
        value_norm = value.strip()
        type_norm = dtype.strip().upper()
        key_upper = key_norm.upper()
        if type_norm == "BOOL":
            bool_value = value_norm.upper() in {"ON", "TRUE", "1", "YES"}
            if bool_value:
                macros.add(key_upper)
            continue
        if key_upper.startswith(_FEATURE_PREFIXES):
            features.add(key_upper)
        lowered = key_norm.lower()
        if any(token in lowered for token in _TARGET_KEYS) and value_norm:
            targets.append(value_norm)
        if any(token in lowered for token in _VARIANT_KEYS) and value_norm:
            variants.append(value_norm)
    return macros, features, _pick_single(targets), _pick_single(variants)


def _scan_config_headers(repo_root: Path) -> list[tuple[str, list[str]]]:
    candidates: list[Path] = []
    for name in _DEFAULT_HEADERS:
        direct = repo_root / name
        if direct.exists():
            candidates.append(direct)
    if not candidates:
        for pattern in (
            "**/config*.h",
            "**/*build*config*.h",
            "**/*project*config*.h",
            "**/FreeRTOSConfig.h",
            "**/freertosconfig.h",
            "**/pg_config*.h",
            "**/*openssl*conf*.h",
            "**/configuration*.h",
        ):
            candidates.extend(repo_root.glob(pattern))
    candidates = sorted(candidates, key=lambda path: _header_candidate_sort_key(repo_root, path))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        text_path = str(path).replace("\\", "/")
        if text_path in seen:
            continue
        seen.add(text_path)
        unique.append(path)
        if len(unique) >= 8:
            break
    results: list[tuple[str, list[str]]] = []
    for path in unique:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        results.append((rel, lines))
    return results


def _header_candidate_sort_key(repo_root: Path, path: Path) -> tuple[int, int, int, str]:
    name = path.name.lower()
    priority = _HEADER_NAME_PRIORITY.get(name, 99)
    rel = _normalize_repo_relative_path(
        repo_root=repo_root,
        value=str(path),
        base_dir=repo_root,
    )
    lowered = rel.lower()
    freertos_boost = 0 if "freertos" in lowered else 1
    depth = rel.count("/")
    return priority, freertos_boost, depth, lowered


def _extract_from_headers(
    header_hits: list[tuple[str, list[str]]],
) -> tuple[set[str], str, str, list[dict[str, Any]]]:
    macros: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    scoped_entries: list[dict[str, Any]] = []
    for rel_path, lines in header_hits:
        file_include_guard_like = 0
        inferred = _infer_target_variant_from_text(rel_path)
        if inferred[0]:
            targets.append(inferred[0])
        if inferred[1]:
            variants.append(inferred[1])
        per_file_macros: set[str] = set()
        for line in lines:
            match = _HEADER_DEFINE_RE.match(line)
            if not match:
                continue
            name = match.group(1).strip().upper()
            value = (match.group(2) or "").strip()
            if not _MACRO_NAME_RE.match(name):
                continue
            if _is_probable_include_guard(name):
                file_include_guard_like += 1
                continue
            if value in {"0", "FALSE", "false"}:
                continue
            macros.add(name)
            per_file_macros.add(name)
            text_for_infer = f"{name} {value}"
            inferred_from_define = _infer_target_variant_from_text(text_for_infer)
            if inferred_from_define[0]:
                targets.append(inferred_from_define[0])
            if inferred_from_define[1]:
                variants.append(inferred_from_define[1])
        prefix = rel_path.rsplit("/", 1)[0] + "/" if "/" in rel_path else ""
        selected_macros = sorted(per_file_macros)
        pruned_macros = 0
        if len(selected_macros) > _HEADER_MACRO_LIMIT_PER_FILE:
            selected_macros, pruned_macros = _prune_header_macros(selected_macros)
        scoped_entries.append(
            {
                "scope_type": "path_prefix",
                "scope_target": prefix or rel_path,
                "macros": selected_macros,
                "pruned_macros": pruned_macros,
                "include_guard_like": file_include_guard_like,
            }
        )
        module = _infer_module_from_path(rel_path)
        if module:
            scoped_entries.append(
                {
                    "scope_type": "module",
                    "scope_target": module,
                    "macros": selected_macros,
                    "pruned_macros": pruned_macros,
                    "include_guard_like": file_include_guard_like,
                }
            )
    return macros, _pick_single(targets), _pick_single(variants), scoped_entries


def _prune_header_macros(values: list[str]) -> tuple[list[str], int]:
    prioritized = [
        item
        for item in values
        if item.startswith(_FEATURE_PREFIXES) or "TARGET" in item or "BOARD" in item
    ]
    if len(prioritized) >= _HEADER_MACRO_LIMIT_PER_FILE:
        selected = prioritized[:_HEADER_MACRO_LIMIT_PER_FILE]
    else:
        remaining = [item for item in values if item not in set(prioritized)]
        cap = max(0, _HEADER_MACRO_LIMIT_PER_FILE - len(prioritized))
        selected = prioritized + remaining[:cap]
    return selected, max(0, len(values) - len(selected))


def _load_profile(repo_root: Path, profile_name: str) -> dict[str, Any] | None:
    if not profile_name:
        return None
    for rel in _DEFAULT_PROFILE_FILES:
        path = repo_root / rel
        if not path.exists():
            continue
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(payload, dict):
            continue
        raw_profiles = payload.get("profiles") if "profiles" in payload else payload
        if not isinstance(raw_profiles, dict):
            continue
        data = raw_profiles.get(profile_name)
        if not isinstance(data, dict):
            continue
        copied = dict(data)
        copied["_profile_name"] = profile_name
        copied["_profile_file"] = str(path)
        return copied
    return None


def _load_macro_file(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text) or []
        if isinstance(loaded, dict):
            raw = loaded.get("macros") or loaded.get("defined_macros") or []
        elif isinstance(loaded, (list, tuple, set)):
            raw = loaded
        else:
            raw = [loaded]
        return [str(item).strip() for item in raw if str(item).strip()]
    values: list[str] = []
    for line in text.splitlines():
        parts = [item.strip() for item in line.split(",")]
        values.extend(item for item in parts if item)
    return values


def _normalize_macros(values: list[str]) -> set[str]:
    macros: set[str] = set()
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        token = token.removeprefix("-D")
        if "=" in token:
            name, value = token.split("=", 1)
            name = name.strip()
            value = value.strip()
            if value in {"0", "FALSE", "false"}:
                continue
            token = name
        token = token.strip().upper()
        if _MACRO_NAME_RE.match(token):
            macros.add(token)
    return macros


def _normalize_terms(values: list[str]) -> set[str]:
    out: set[str] = set()
    for item in values:
        text = str(item).strip().upper()
        if text:
            out.add(text)
    return out


def _iter_values(value: object) -> list[str]:
    if isinstance(value, str):
        return _split_terms(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _split_terms(text: str) -> list[str]:
    values: list[str] = []
    for line in str(text).splitlines():
        for part in line.split(","):
            token = part.strip()
            if token:
                values.append(token)
    return values


def _pick_single(values: list[str]) -> str:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    unique = sorted(dict.fromkeys(normalized))
    if len(unique) == 1:
        return unique[0]
    return ""


def _pick_single_or_none(values: list[str], ambiguous: list[str], label: str) -> str:
    normalized = [str(value).strip() for value in values if str(value).strip()]
    unique = sorted(dict.fromkeys(normalized))
    if len(unique) <= 1:
        return unique[0] if unique else ""
    ambiguous.append(f"{label}_ambiguous:" + ",".join(unique[:5]))
    return ""


def _infer_target_variant_from_text(text: str) -> tuple[str, str]:
    lowered = str(text).lower()
    target = ""
    variant = ""
    for pattern in (r"(?:target|board|platform)[_:=\-]([a-z0-9_]+)", r"/boards?/([a-z0-9_]+)"):
        match = re.search(pattern, lowered)
        if match:
            target = match.group(1)
            break
    for pattern in (
        r"(?:variant|profile|build[_\-]?type)[_:=\-]([a-z0-9_]+)",
        r"/(debug|release|relwithdebinfo|minsizerel)/",
    ):
        match = re.search(pattern, lowered)
        if match:
            variant = match.group(1)
            break
    return target, variant


def _infer_module_from_path(path: str) -> str:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    if len(parts) <= 1:
        return ""
    if parts[0].lower() in {"src", "source", "include"} and len(parts) >= 2:
        return parts[1].lower()
    return parts[0].lower()


def _build_target_variant_scope(target: str, variant: str) -> str:
    parts: list[str] = []
    if str(target).strip():
        parts.append(f"target={str(target).strip().lower()}")
    if str(variant).strip():
        parts.append(f"variant={str(variant).strip().lower()}")
    return ",".join(parts) if parts else "*"


def _normalize_include_dirs(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value).strip().replace("\\", "/")
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _tokenize_compile_command(command: str, *, base_dir: Path) -> list[str]:
    try:
        tokens = shlex.split(command, posix=False)
    except ValueError:
        tokens = command.split()
    return _expand_response_files(tokens, base_dir=base_dir)


def _expand_response_files(tokens: list[str], *, base_dir: Path) -> list[str]:
    expanded: list[str] = []
    for token in tokens:
        text = str(token).strip()
        if not text.startswith("@"):
            expanded.append(text)
            continue
        rsp_path = Path(text[1:])
        if not rsp_path.is_absolute():
            rsp_path = (base_dir / rsp_path)
        try:
            raw = rsp_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            expanded.append(text)
            continue
        try:
            rsp_tokens = shlex.split(raw, posix=False)
        except ValueError:
            rsp_tokens = raw.split()
        expanded.extend(item for item in rsp_tokens if str(item).strip())
    return expanded


def _resolve_directory(*, repo_root: Path, directory: str) -> Path:
    raw = str(directory).strip()
    if not raw:
        return repo_root
    path = Path(raw)
    if path.is_absolute():
        return path
    return (repo_root / path).resolve()


def _normalize_repo_relative_path(
    *,
    repo_root: Path,
    value: str,
    base_dir: Path,
    keep_relative: bool = False,
) -> str:
    text = str(value).strip()
    if not text:
        return ""
    path = Path(text)
    if keep_relative and not path.is_absolute():
        return str(path).replace("\\", "/")
    if not path.is_absolute():
        path = (base_dir / path)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        rel = resolved.relative_to(repo_root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def _select_global_compile_macros(*, macro_counter: Counter[str], total_files: int) -> set[str]:
    if total_files <= 0:
        return set()
    selected: list[str] = []
    for macro, count in sorted(macro_counter.items(), key=lambda item: (-item[1], item[0])):
        if count / total_files >= _GLOBAL_COMPILE_MACRO_RATIO:
            selected.append(macro)
            if len(selected) >= _GLOBAL_COMPILE_MACRO_MAX:
                break
    return set(selected)


def _select_global_header_macros(values: set[str]) -> set[str]:
    prioritized = [
        item
        for item in sorted(values)
        if not _is_probable_include_guard(item)
        and (
            item.startswith(_FEATURE_PREFIXES)
            or "TARGET" in item
            or "BOARD" in item
            or "PLATFORM" in item
            or "VARIANT" in item
        )
    ]
    return set(prioritized[:_GLOBAL_HEADER_MACRO_MAX])


def _select_global_aux_macros(values: set[str]) -> set[str]:
    prioritized = [
        item
        for item in sorted(values)
        if not _is_probable_include_guard(item)
        and (
            item.startswith(_FEATURE_PREFIXES)
            or "TARGET" in item
            or "BOARD" in item
            or "PLATFORM" in item
            or "VARIANT" in item
        )
    ]
    return set(prioritized[:_GLOBAL_HEADER_MACRO_MAX])


def _is_probable_include_guard(name: str) -> bool:
    upper = str(name).strip().upper()
    if not upper:
        return False
    if upper.endswith(_INCLUDE_GUARD_SUFFIXES):
        return True
    return upper.startswith("__") and upper.endswith("__")


def _load_cmake_lists(repo_root: Path) -> list[tuple[str, list[str]]]:
    candidates = [repo_root / "CMakeLists.txt"]
    candidates.extend(sorted(repo_root.glob("**/CMakeLists.txt"))[:6])
    seen: set[str] = set()
    loaded: list[tuple[str, list[str]]] = []
    for path in candidates:
        if not path.exists():
            continue
        key = str(path.resolve()).replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = _normalize_repo_relative_path(
            repo_root=repo_root,
            value=str(path),
            base_dir=repo_root,
        )
        loaded.append((rel, lines))
        if len(loaded) >= 6:
            break
    return loaded


def _extract_from_cmake_lists(
    cmake_files: list[tuple[str, list[str]]],
) -> tuple[set[str], set[str], str, str]:
    macros: set[str] = set()
    features: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    define_re = re.compile(r"-D([A-Za-z_][A-Za-z0-9_]*)(?:=([^)\\s]+))?")
    for rel_path, lines in cmake_files:
        inferred = _infer_target_variant_from_text(rel_path)
        if inferred[0]:
            targets.append(inferred[0])
        if inferred[1]:
            variants.append(inferred[1])
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for match in define_re.finditer(line):
                name = match.group(1).upper()
                value = (match.group(2) or "").strip()
                if value in {"0", "FALSE", "false"}:
                    continue
                if _MACRO_NAME_RE.match(name):
                    macros.add(name)
                    if name.startswith(_FEATURE_PREFIXES):
                        features.add(name)
            inferred = _infer_target_variant_from_text(line)
            if inferred[0]:
                targets.append(inferred[0])
            if inferred[1]:
                variants.append(inferred[1])
    return macros, features, _pick_single(targets), _pick_single(variants)


def _load_makefiles(repo_root: Path) -> list[tuple[str, list[str]]]:
    candidates: list[Path] = []
    for relative in _DEFAULT_MAKEFILE_FILES:
        path = repo_root / relative
        if path.exists():
            candidates.append(path)
    if not candidates:
        for pattern in _DEFAULT_MAKEFILE_PATTERNS:
            candidates.extend(repo_root.glob(pattern))
    seen: set[str] = set()
    loaded: list[tuple[str, list[str]]] = []
    for path in sorted(candidates)[:10]:
        key = str(path.resolve()).replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = _normalize_repo_relative_path(
            repo_root=repo_root,
            value=str(path),
            base_dir=repo_root,
        )
        loaded.append((rel, lines))
        if len(loaded) >= 6:
            break
    return loaded


def _load_configure_scripts(repo_root: Path) -> list[tuple[str, list[str]]]:
    candidates: list[Path] = []
    for relative in _DEFAULT_CONFIGURE_FILES:
        path = repo_root / relative
        if path.exists():
            candidates.append(path)
    if not candidates:
        for pattern in ("**/configure.ac", "**/configure.in", "**/Configure"):
            candidates.extend(repo_root.glob(pattern))
    seen: set[str] = set()
    loaded: list[tuple[str, list[str]]] = []
    for path in sorted(candidates)[:6]:
        key = str(path.resolve()).replace("\\", "/")
        if key in seen:
            continue
        seen.add(key)
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = _normalize_repo_relative_path(
            repo_root=repo_root,
            value=str(path),
            base_dir=repo_root,
        )
        loaded.append((rel, lines))
    return loaded


def _load_msbuild_projects(repo_root: Path) -> list[tuple[str, list[str]]]:
    candidates: list[Path] = []
    for pattern in _DEFAULT_MSBUILD_PROJECT_PATTERNS:
        candidates.extend(repo_root.glob(pattern))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        text_path = str(path.resolve()).replace("\\", "/")
        if text_path in seen:
            continue
        seen.add(text_path)
        unique.append(path)
        if len(unique) >= 8:
            break
    loaded: list[tuple[str, list[str]]] = []
    for path in unique:
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        rel = _normalize_repo_relative_path(
            repo_root=repo_root,
            value=str(path),
            base_dir=repo_root,
        )
        loaded.append((rel, lines))
    return loaded


def _extract_from_msbuild_projects(
    project_files: list[tuple[str, list[str]]],
    *,
    repo_root: Path,
) -> tuple[set[str], str, str, list[dict[str, Any]]]:
    macros: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    scoped_entries: list[dict[str, Any]] = []
    preprocess_re = re.compile(
        r"<PreprocessorDefinitions>(.*?)</PreprocessorDefinitions>",
        re.IGNORECASE,
    )
    include_re = re.compile(
        r"<AdditionalIncludeDirectories>(.*?)</AdditionalIncludeDirectories>",
        re.IGNORECASE,
    )
    for rel_path, lines in project_files:
        text = "\n".join(lines)
        inferred = _infer_target_variant_from_text(rel_path)
        if inferred[0]:
            targets.append(inferred[0])
        if inferred[1]:
            variants.append(inferred[1])
        per_file_macros: set[str] = set()
        per_file_includes: list[str] = []
        for match in preprocess_re.finditer(text):
            chunk = str(match.group(1) or "")
            for token in re.split(r"[;,]", chunk):
                item = token.strip()
                if not item or item.startswith("%("):
                    continue
                normalized_macros = _normalize_macros([item])
                if normalized_macros:
                    per_file_macros.update(normalized_macros)
                    macros.update(normalized_macros)
                    inferred_define = _infer_target_variant_from_text(item)
                    if inferred_define[0]:
                        targets.append(inferred_define[0])
                    if inferred_define[1]:
                        variants.append(inferred_define[1])
        for match in include_re.finditer(text):
            chunk = str(match.group(1) or "")
            for token in chunk.split(";"):
                item = token.strip()
                if not item or item.startswith("%("):
                    continue
                normalized = _normalize_repo_relative_path(
                    repo_root=repo_root,
                    value=item,
                    base_dir=repo_root / Path(rel_path).parent,
                    keep_relative=True,
                )
                if normalized:
                    per_file_includes.append(normalized)
        include_dirs = _normalize_include_dirs(per_file_includes)
        scope_target = str(Path(rel_path).parent).replace("\\", "/")
        module = _infer_module_from_path(rel_path)
        scoped_entries.append(
            {
                "scope_type": "path_prefix",
                "scope_target": scope_target or rel_path,
                "module": module,
                "macros": sorted(per_file_macros),
                "include_dirs": include_dirs,
            }
        )
    return macros, _pick_single(targets), _pick_single(variants), scoped_entries


def _extract_from_makefiles(
    makefiles: list[tuple[str, list[str]]],
) -> tuple[set[str], set[str], str, str, list[dict[str, Any]]]:
    macros: set[str] = set()
    features: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    scoped_entries: list[dict[str, Any]] = []
    define_re = re.compile(r"(?:^|\s)-D([A-Za-z_][A-Za-z0-9_]*)(?:=([^\s]+))?")
    include_re = re.compile(r"(?:^|\s)-I([^\s]+)")
    for rel_path, lines in makefiles:
        inferred_from_path = _infer_target_variant_from_text(rel_path)
        if inferred_from_path[0]:
            targets.append(inferred_from_path[0])
        if inferred_from_path[1]:
            variants.append(inferred_from_path[1])
        file_macros: set[str] = set()
        file_features: set[str] = set()
        include_dirs: list[str] = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for match in define_re.finditer(line):
                name = match.group(1).upper()
                value = (match.group(2) or "").strip()
                if value in {"0", "FALSE", "false"}:
                    continue
                if _MACRO_NAME_RE.match(name):
                    macros.add(name)
                    file_macros.add(name)
                    if name.startswith(_FEATURE_PREFIXES):
                        features.add(name)
                        file_features.add(name)
            for match in include_re.finditer(line):
                include_dirs.append(match.group(1).strip())
            inferred = _infer_target_variant_from_text(line)
            if inferred[0]:
                targets.append(inferred[0])
            if inferred[1]:
                variants.append(inferred[1])
        scope_target = str(Path(rel_path).parent).replace("\\", "/")
        scoped_entries.append(
            {
                "scope_type": "path_prefix",
                "scope_target": scope_target or rel_path,
                "macros": sorted(file_macros),
                "features": sorted(file_features),
                "include_dirs": _normalize_include_dirs(include_dirs),
            }
        )
    return macros, features, _pick_single(targets), _pick_single(variants), scoped_entries


def _extract_from_configure_scripts(
    configure_files: list[tuple[str, list[str]]],
) -> tuple[set[str], set[str], str, str, list[dict[str, Any]]]:
    macros: set[str] = set()
    features: set[str] = set()
    targets: list[str] = []
    variants: list[str] = []
    scoped_entries: list[dict[str, Any]] = []
    ac_define_re = re.compile(r"AC_DEFINE\(\s*\[?([A-Za-z_][A-Za-z0-9_]*)\]?(?:\s*,\s*([^\)]*))?")
    openssl_no_re = re.compile(r"\b(OPENSSL_NO_[A-Za-z0-9_]+)\b")
    option_re = re.compile(r"--(enable|disable|with|without)-([a-z0-9_\-]+)", re.IGNORECASE)
    for rel_path, lines in configure_files:
        inferred_from_path = _infer_target_variant_from_text(rel_path)
        if inferred_from_path[0]:
            targets.append(inferred_from_path[0])
        if inferred_from_path[1]:
            variants.append(inferred_from_path[1])
        file_macros: set[str] = set()
        file_features: set[str] = set()
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for match in ac_define_re.finditer(line):
                name = str(match.group(1) or "").strip().upper()
                raw_value = str(match.group(2) or "").strip().strip("[]")
                if not _MACRO_NAME_RE.match(name):
                    continue
                if raw_value in {"0", "FALSE", "false"}:
                    continue
                macros.add(name)
                file_macros.add(name)
                if name.startswith(_FEATURE_PREFIXES):
                    features.add(name)
                    file_features.add(name)
            for match in openssl_no_re.finditer(line):
                name = str(match.group(1) or "").strip().upper()
                if not _MACRO_NAME_RE.match(name):
                    continue
                macros.add(name)
                file_macros.add(name)
            for match in option_re.finditer(line):
                kind = str(match.group(1) or "").strip().upper()
                option = str(match.group(2) or "").strip().upper().replace("-", "_")
                if not option:
                    continue
                feature_name = f"{kind}_{option}"
                if _MACRO_NAME_RE.match(feature_name):
                    features.add(feature_name)
                    file_features.add(feature_name)
            inferred = _infer_target_variant_from_text(line)
            if inferred[0]:
                targets.append(inferred[0])
            if inferred[1]:
                variants.append(inferred[1])
        scope_target = str(Path(rel_path).parent).replace("\\", "/")
        scoped_entries.append(
            {
                "scope_target": scope_target or rel_path,
                "macros": sorted(file_macros),
                "features": sorted(file_features),
            }
        )
    return macros, features, _pick_single(targets), _pick_single(variants), scoped_entries
