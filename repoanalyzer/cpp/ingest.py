from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from repoanalyzer.config import load_config
from repoanalyzer.core.paths import index_db_path
from repoanalyzer.core.models import CodeFact
from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.store.status import source_kind_for_path
from repoanalyzer.core.source_kinds import CPP_HEADER_EXTENSIONS, CPP_SOURCE_EXTENSIONS

from .build_context import load_build_context
from .build_guards import extract_build_guards
from .build_provenance import build_guard_chain_payload, build_guard_summary
from .calls import extract_calls
from .includes import extract_includes
from .macro_eval import macro_map, parse_macro_definition
from .preprocessor_model import ConditionalGuard, LineBuildStatus, PreprocessorModel, analyze_preprocessor
from .references import extract_references
from .scanner import iter_cpp_files
from .semantic import analyze_cpp_semantics
from .cross_tu import apply_cross_tu_resolution
from .symbols import extract_symbols
from repoanalyzer.core.target_selection import decide_target_file, filter_active_files


@dataclass(frozen=True)
class IngestResult:
    repo: str
    db_path: str
    files: int
    facts: int
    mode: str = "full"
    status: str = "indexed"
    message: str | None = None
    full_reingest_required: bool = False
    changed_files: list[str] | None = None
    missing_files: list[str] | None = None
    new_files: list[str] | None = None


def ingest_repo(
    repo: str | Path,
    *,
    config_path: str | Path | None = None,
    reset: bool = True,
    incremental: bool = False,
) -> IngestResult:
    root = Path(repo).expanduser().resolve()
    config = load_config(config_path)
    store = SQLiteStore(index_db_path(root))
    if incremental:
        return _incremental_ingest_repo(root, config_path=config_path)
    store.init(reset=reset)
    if reset:
        store.clear()

    started_at = _utc_now()
    build_context = load_build_context(
        root,
        config.cpp.effective_compile_commands,
        configured_include_dirs=config.cpp.effective_include_dirs,
        target_profile=config.cpp.target_profile,
    )
    build_signature = _build_context_signature(root, config_path, config, build_context)
    candidate_files = iter_cpp_files(root, exclude_patterns=config.index.exclude_patterns)
    files = _filter_files_for_build_context(
        candidate_files,
        build_context.source_files,
        build_context.target_profile,
    )
    all_facts: list[CodeFact] = []
    all_facts.extend(_target_file_selection_facts(candidate_files, build_context))
    for source_file in files:
        store.upsert_file(
            source_file.path,
            source_file.text,
            language="cpp",
            absolute_path=source_file.absolute_path,
            source_kind=source_kind_for_path(source_file.path),
        )
        all_facts.extend(_extract_source_file_with_context(root, source_file, build_context, config.cpp.effective_macros))
    all_facts.extend(_target_profile_facts(root, config_path, build_context, config.cpp.effective_macros))
    all_facts = apply_cross_tu_resolution(all_facts)
    store.insert_facts(all_facts)
    finished_at = _utc_now()
    store.set_metadata_many(
        {
            "repo_root": str(root),
            "db_path": str(index_db_path(root)),
            "config_path": str(Path(config_path).expanduser().resolve()) if config_path is not None else None,
            "compile_commands": str(build_context.compile_commands_path) if build_context.compile_commands_path else None,
            "ingest_mode": "full_reset" if reset else "append",
            "ingest_started_at": started_at,
            "ingest_finished_at": finished_at,
            "indexed_file_count": len(files),
            "fact_count": len(all_facts),
            "exclude_patterns": list(config.index.exclude_patterns),
            "target_profile": build_context.target_profile,
            "build_context_signature": build_signature,
        }
    )
    return IngestResult(str(root), str(index_db_path(root)), len(files), len(all_facts), mode="full", status="indexed")



def _incremental_ingest_repo(root: Path, *, config_path: str | Path | None = None) -> IngestResult:
    config = load_config(config_path)
    store = SQLiteStore(index_db_path(root))
    store.init(reset=False)
    started_at = _utc_now()
    build_context = load_build_context(
        root,
        config.cpp.effective_compile_commands,
        configured_include_dirs=config.cpp.effective_include_dirs,
        target_profile=config.cpp.target_profile,
    )
    current_signature = _build_context_signature(root, config_path, config, build_context)
    previous_signature = store.get_metadata("build_context_signature")
    if previous_signature and previous_signature != current_signature:
        return IngestResult(
            str(root),
            str(index_db_path(root)),
            0,
            0,
            mode="incremental",
            status="full_reingest_required",
            message="build context or index configuration changed; run full ingest",
            full_reingest_required=True,
        )
    if previous_signature is None:
        return IngestResult(
            str(root),
            str(index_db_path(root)),
            0,
            0,
            mode="incremental",
            status="full_reingest_required",
            message="index does not contain a build_context_signature; run full ingest once before incremental ingest",
            full_reingest_required=True,
        )

    current_files = _filter_files_for_build_context(
        iter_cpp_files(root, exclude_patterns=config.index.exclude_patterns), build_context.source_files, build_context.target_profile
    )
    current_by_path = {source_file.path: source_file for source_file in current_files}
    indexed_entries = {entry.path: entry for entry in store.file_index_entries()}

    changed = sorted(
        path for path, entry in indexed_entries.items()
        if path in current_by_path and _sha256_text(current_by_path[path].text) != entry.sha256
    )
    missing = sorted(path for path in indexed_entries if path not in current_by_path)
    new = sorted(path for path in current_by_path if path not in indexed_entries)

    touched = sorted(set(changed) | set(missing) | set(new))
    if not touched:
        facts = store.all_facts()
        store.set_metadata_many(
            {
                "ingest_mode": "incremental_noop",
                "last_incremental_started_at": started_at,
                "last_incremental_finished_at": _utc_now(),
                "last_incremental_status": "clean",
            }
        )
        return IngestResult(
            str(root),
            str(index_db_path(root)),
            0,
            len(facts),
            mode="incremental",
            status="clean",
            message="index is already clean",
            changed_files=[],
            missing_files=[],
            new_files=[],
        )

    unsafe = _unsafe_incremental_reasons(touched)
    if unsafe:
        return IngestResult(
            str(root),
            str(index_db_path(root)),
            0,
            len(store.all_facts()),
            mode="incremental",
            status="full_reingest_required",
            message="; ".join(unsafe),
            full_reingest_required=True,
            changed_files=changed,
            missing_files=missing,
            new_files=new,
        )

    affected_sources = sorted(path for path in set(changed) | set(missing) | set(new) if Path(path).suffix.lower() in CPP_SOURCE_EXTENSIONS)
    keep_facts = [fact for fact in store.all_facts() if not _fact_depends_on_sources(fact, affected_sources)]
    refreshed_facts: list[CodeFact] = []
    for path in sorted(set(changed) | set(new)):
        source_file = current_by_path[path]
        store.upsert_file(
            source_file.path,
            source_file.text,
            language="cpp",
            absolute_path=source_file.absolute_path,
            source_kind=source_kind_for_path(source_file.path),
        )
        refreshed_facts.extend(_extract_source_file_with_context(root, source_file, build_context, config.cpp.effective_macros))

    store.delete_paths(missing)
    combined_facts = apply_cross_tu_resolution(keep_facts + refreshed_facts)
    store.replace_all_facts(combined_facts)
    store.set_metadata_many(
        {
            "ingest_mode": "incremental_safe",
            "last_incremental_started_at": started_at,
            "last_incremental_finished_at": _utc_now(),
            "last_incremental_status": "indexed",
            "last_incremental_changed_files": changed,
            "last_incremental_missing_files": missing,
            "last_incremental_new_files": new,
            "indexed_file_count": len(store.file_index_entries()),
            "fact_count": len(combined_facts),
            "build_context_signature": current_signature,
        }
    )
    return IngestResult(
        str(root),
        str(index_db_path(root)),
        len(set(changed) | set(new)),
        len(combined_facts),
        mode="incremental",
        status="indexed",
        changed_files=changed,
        missing_files=missing,
        new_files=new,
    )


def _extract_source_file_with_context(root: Path, source_file, build_context, configured_macros: list[str]) -> list[CodeFact]:
    text = source_file.text
    macros = _macros_for_source(source_file.path, build_context, configured_macros)
    macro_defs = macro_map(macros)
    preprocessor = analyze_preprocessor(text, macro_defs)
    facts = _extract_file_facts(source_file.path, text, macro_defs, preprocessor)
    facts.extend(_build_config_macro_facts(source_file.path, macros, build_context, configured_macros))
    facts = _attach_include_resolution(facts, source_file.path, build_context)
    facts.extend(_header_visibility_facts(source_file.path, build_context))
    facts.extend(_project_direct_header_facts(root, source_file.path, build_context, configured_macros))
    return _attach_translation_unit_context(facts, source_file.path, build_context, configured_macros)


def _fact_depends_on_sources(fact: CodeFact, sources: list[str]) -> bool:
    if not sources:
        return False
    source_set = set(sources)
    if fact.path in source_set:
        return True
    context = fact.payload.get("tu_context") if isinstance(fact.payload, dict) else None
    if isinstance(context, dict) and context.get("source") in source_set:
        return True
    projected = fact.payload.get("projected_from") if isinstance(fact.payload, dict) else None
    if isinstance(projected, dict) and projected.get("source") in source_set:
        return True
    return False


def _unsafe_incremental_reasons(paths: list[str]) -> list[str]:
    unsafe: list[str] = []
    headers = [path for path in paths if Path(path).suffix.lower() in CPP_HEADER_EXTENSIONS]
    if headers:
        unsafe.append("header changes affect multiple translation units; run full ingest: " + ", ".join(headers))
    non_cpp = [path for path in paths if Path(path).suffix.lower() not in (CPP_HEADER_EXTENSIONS | CPP_SOURCE_EXTENSIONS)]
    if non_cpp:
        unsafe.append("non C/C++ indexed file changed; run full ingest: " + ", ".join(non_cpp))
    return unsafe


def _build_context_signature(root: Path, config_path: str | Path | None, config, build_context) -> dict[str, Any]:
    compile_commands_path = build_context.compile_commands_path
    return {
        "config_path": str(Path(config_path).expanduser().resolve()) if config_path is not None else None,
        "config_sha256": _file_sha256(Path(config_path).expanduser().resolve()) if config_path is not None else None,
        "compile_commands": str(compile_commands_path) if compile_commands_path else None,
        "compile_commands_sha256": _file_sha256(compile_commands_path) if compile_commands_path else None,
        "configured_macros": sorted(set(config.cpp.effective_macros)),
        "include_dirs": sorted(set(config.cpp.effective_include_dirs)),
        "target_profile": build_context.target_profile,
        "exclude_patterns": list(config.index.exclude_patterns),
        "source_files": list(build_context.source_files),
    }


def _file_sha256(path: Path | str | None) -> str | None:
    if path is None:
        return None
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()

def _extract_file_facts(
    path: str,
    text: str,
    macro_defs: dict[str, str | None],
    preprocessor: PreprocessorModel,
) -> list[CodeFact]:
    facts: list[CodeFact] = []
    facts.extend(extract_includes(path, text))
    facts.extend(extract_build_guards(path, text, macro_defs))
    semantic_facts = analyze_cpp_semantics(path, text)
    if semantic_facts:
        facts.extend(semantic_facts)
    else:
        facts.extend(extract_symbols(path, text))
        facts.extend(extract_references(path, text))
        facts.extend(extract_calls(path, text))
    return _mark_build_status(facts, preprocessor, macro_defs)


def _project_direct_header_facts(root: Path, source_path: str, build_context, configured_macros: list[str]) -> list[CodeFact]:
    if Path(source_path).suffix.lower() not in CPP_SOURCE_EXTENSIONS:
        return []
    headers = build_context.included_headers_by_source.get(source_path, [])
    if not headers:
        return []

    macros = _macros_for_source(source_path, build_context, configured_macros)
    macro_defs = macro_map(macros)
    projected: list[CodeFact] = []
    for header in headers:
        header_path = root / header
        if not header_path.exists() or not header_path.is_file():
            continue
        try:
            text = header_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = header_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        preprocessor = analyze_preprocessor(text, macro_defs)
        header_facts = _extract_file_facts(header, text, macro_defs, preprocessor)
        context = _header_projection_context(source_path, header, build_context, configured_macros)
        for fact in header_facts:
            payload = dict(fact.payload)
            payload["projected_from"] = {"path": header, "start_line": fact.start_line, "end_line": fact.end_line}
            payload["projection_kind"] = "direct_include_header"
            payload["tu_context"] = context
            projected.append(replace(fact, payload=payload))
    return projected


def _macros_for_source(path: str, build_context, configured_macros: list[str]) -> list[str]:
    if Path(path).suffix.lower() in CPP_SOURCE_EXTENSIONS and path in build_context.macros_by_source:
        base_macros = list(build_context.macros_by_source[path])
    else:
        base_macros = list(build_context.macros)
    return _merge_macros_with_precedence(base_macros, configured_macros)


def _merge_macros_with_precedence(base_macros: list[str], override_macros: list[str]) -> list[str]:
    """Merge macro definitions by name while preserving target-profile overrides.

    compile_commands/header macros form the translation-unit baseline.  Explicit
    repoanalyzer.yml macros are treated as a target-profile overlay and override
    duplicate names deterministically instead of relying on sorted(set(...)).
    """
    values: dict[str, str] = {}
    order: list[str] = []
    for raw in [*base_macros, *override_macros]:
        definition = parse_macro_definition(raw)
        if definition is None:
            continue
        if definition.name not in values:
            order.append(definition.name)
        values[definition.name] = _macro_definition_to_raw(definition)
    return [values[name] for name in sorted(order)]




def _macro_definition_to_raw(definition) -> str:
    if definition.value is None or definition.value == "":
        return definition.name
    return f"{definition.name}={definition.value}"

def _macro_value_from_raw(raw: str) -> str | None:
    definition = parse_macro_definition(raw)
    if definition is None:
        return None
    return definition.value if definition.value is not None else "1"


def _build_config_macro_facts(path: str, macros: list[str], build_context, configured_macros: list[str]) -> list[CodeFact]:
    origins = _macro_origins(
        build_context.command_macros_by_source.get(path, []) if Path(path).suffix.lower() in CPP_SOURCE_EXTENSIONS else build_context.macros,
        build_context.header_macros_by_source.get(path, []),
        configured_macros,
    )
    facts: list[CodeFact] = []
    seen: set[str] = set()
    for raw in macros:
        definition = parse_macro_definition(raw)
        if definition is None or definition.name in seen:
            continue
        seen.add(definition.name)
        value = definition.value if definition.value is not None else "1"
        facts.append(
            CodeFact(
                fact_type="build_config",
                path=path,
                start_line=1,
                end_line=1,
                subject=definition.name,
                predicate="macro_value",
                object=value,
                confidence="high",
                source="build_context_macro_profile",
                payload={
                    "macro_name": definition.name,
                    "macro_value": value,
                    "macro_origins": origins.get(definition.name, []),
                    "build_status": "active",
                    "build_status_precision": "target_profile_macro",
                    "build_profile_source": "compile_commands_or_repoanalyzer_config",
                    "target_profile": (build_context.target_profile or {}).get("name"),
                },
            )
        )
    return facts




def _target_profile_facts(root: Path, config_path: str | Path | None, build_context, configured_macros: list[str]) -> list[CodeFact]:
    profile = dict(build_context.target_profile or {})
    effective_macros = _merge_macros_with_precedence(list(build_context.macros), configured_macros)
    macro_values = {
        definition.name: (definition.value if definition.value is not None else "1")
        for raw in effective_macros
        if (definition := parse_macro_definition(raw)) is not None
    }
    if not profile and not build_context.compile_commands_path and not effective_macros and not build_context.include_dirs:
        return []

    name = str(profile.get("name") or "default")
    source_path = _target_profile_source_path(root, config_path)
    standard_profile_keys = {
        "name",
        "compile_commands",
        "include_dirs",
        "macros",
        "config_headers",
        "active_path_prefixes",
        "inactive_path_prefixes",
        "active_port",
        "heap",
    }
    profile_attributes = {
        key: value
        for key, value in profile.items()
        if key not in standard_profile_keys and value not in (None, [], {})
    }
    base_payload = {
        "target_profile_name": name,
        "compile_commands": str(build_context.compile_commands_path) if build_context.compile_commands_path else profile.get("compile_commands"),
        "include_dirs": list(build_context.include_dirs),
        "macros": effective_macros,
        "macro_values": macro_values,
        "config_headers": list(profile.get("config_headers") or []),
        "active_path_prefixes": list(profile.get("active_path_prefixes") or []),
        "inactive_path_prefixes": list(profile.get("inactive_path_prefixes") or []),
        "active_port": profile.get("active_port"),
        "heap": profile.get("heap"),
        "attributes": profile_attributes,
        "build_status": "active",
        "build_status_precision": "target_profile",
        "target_profile_first_class": True,
    }
    base_payload = {key: value for key, value in base_payload.items() if value not in (None, [], {})}
    facts: list[CodeFact] = [
        CodeFact(
            fact_type="target_profile",
            path=source_path,
            start_line=1,
            end_line=1,
            subject=name,
            predicate="selected_profile",
            object="active",
            confidence="high",
            source="repoanalyzer_target_profile",
            payload=base_payload,
        )
    ]

    def add_attribute(subject: str, obj: Any, predicate: str = "target_attribute") -> None:
        if obj in (None, "", [], {}):
            return
        if isinstance(obj, list):
            values = obj
        else:
            values = [obj]
        for value in values:
            if value in (None, ""):
                continue
            payload = dict(base_payload)
            payload["attribute"] = subject
            facts.append(
                CodeFact(
                    fact_type="target_profile",
                    path=source_path,
                    start_line=1,
                    end_line=1,
                    subject=subject,
                    predicate=predicate,
                    object=str(value),
                    confidence="high",
                    source="repoanalyzer_target_profile",
                    payload=payload,
                )
            )

    add_attribute("compile_commands", build_context.compile_commands_path)
    add_attribute("include_dir", list(build_context.include_dirs), "target_artifact")
    add_attribute("config_header", list(profile.get("config_headers") or []), "target_artifact")
    add_attribute("active_path_prefix", list(profile.get("active_path_prefixes") or []), "target_file_selection")
    add_attribute("inactive_path_prefix", list(profile.get("inactive_path_prefixes") or []), "target_file_selection")
    add_attribute("active_port", profile.get("active_port"))
    add_attribute("heap", profile.get("heap"))
    for attribute_name, attribute_value in sorted(profile_attributes.items()):
        add_attribute(str(attribute_name), attribute_value)
    for mode, macro_name in (("dynamic", "configSUPPORT_DYNAMIC_ALLOCATION"), ("static", "configSUPPORT_STATIC_ALLOCATION")):
        value = str(macro_values.get(macro_name, "")).strip()
        if value in {"0", "1"}:
            enabled = value == "1"
            setting = "enabled" if enabled else "disabled"
            payload = {
                **base_payload,
                "allocation_mode": mode,
                "allocation_setting": setting,
                "macro_name": macro_name,
                "macro_value": value,
                "allocation_profile_first_class": True,
            }
            facts.append(
                CodeFact(
                    fact_type="target_profile",
                    path=source_path,
                    start_line=1,
                    end_line=1,
                    subject=f"{mode}_allocation",
                    predicate="allocation_setting",
                    object=setting,
                    confidence="high",
                    source="repoanalyzer_target_profile",
                    payload=payload,
                )
            )
    for macro_name, value in sorted(macro_values.items()):
        facts.append(
            CodeFact(
                fact_type="target_profile",
                path=source_path,
                start_line=1,
                end_line=1,
                subject=macro_name,
                predicate="macro_value",
                object=str(value),
                confidence="high",
                source="repoanalyzer_target_profile",
                payload={**base_payload, "macro_name": macro_name, "macro_value": str(value)},
            )
        )
    return facts


def _target_profile_source_path(root: Path, config_path: str | Path | None) -> str:
    if config_path is None:
        return ".repoanalyzer/target_profile"
    path = Path(config_path).expanduser()
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return str(path)

def _target_file_selection_facts(files, build_context) -> list[CodeFact]:
    profile = dict(build_context.target_profile or {})
    if not profile and not build_context.source_files:
        return []
    profile_name = str(profile.get("name") or "default")
    allowed_sources = set(build_context.source_files)
    facts: list[CodeFact] = []
    for source_file in files:
        decision = decide_target_file(source_file.path, allowed_sources, profile)
        predicate = "file_active" if decision.active else "file_inactive"
        payload = decision.to_payload(profile)
        payload.update({
            "target_profile_name": profile_name,
            "file_path": decision.path,
            "source_kind": source_kind_for_path(decision.path),
        })
        facts.append(
            CodeFact(
                fact_type="target_file",
                path=".repoanalyzer/target_file_selection",
                start_line=1,
                end_line=1,
                subject=decision.path,
                predicate=predicate,
                object=profile_name,
                confidence="high",
                source="target_profile_file_selection",
                payload=payload,
            )
        )
    return facts

def _filter_files_for_build_context(files, source_files: list[str], target_profile: dict[str, Any] | None = None) -> list:
    return filter_active_files(files, source_files, target_profile)


def _attach_translation_unit_context(
    facts: list[CodeFact],
    path: str,
    build_context,
    configured_macros: list[str],
) -> list[CodeFact]:
    marked: list[CodeFact] = []
    for fact in facts:
        payload = dict(fact.payload)
        if "tu_context" not in payload:
            payload["tu_context"] = _translation_unit_context(path, build_context, configured_macros)
        marked.append(replace(fact, payload=payload))
    return marked


def _translation_unit_context(path: str, build_context, configured_macros: list[str]) -> dict:
    suffix = Path(path).suffix.lower()
    has_compile_commands = bool(build_context.compile_commands_path)
    is_source = suffix in CPP_SOURCE_EXTENSIONS
    is_header = suffix in CPP_HEADER_EXTENSIONS

    command_macros = sorted(set(build_context.command_macros_by_source.get(path, [])))
    header_macros = sorted(set(build_context.header_macros_by_source.get(path, [])))
    effective_macros = _macros_for_source(path, build_context, configured_macros)
    macro_names = sorted(name for raw in effective_macros if (name := _macro_name_from_raw(raw)) is not None)
    macro_values = {name: value for raw in effective_macros if (name := _macro_name_from_raw(raw)) is not None and (value := _macro_value_from_raw(raw)) is not None}

    if is_source:
        kind = "translation_unit" if path in build_context.source_files else "source_without_compile_commands"
        precision = "translation_unit" if path in build_context.source_files else "source_file_scan"
    elif is_header:
        kind = "header_standalone"
        precision = "header_unattributed"
    else:
        kind = "unknown_cpp_file"
        precision = "unknown"

    target_profile = dict(build_context.target_profile or {})
    target_profile_name = target_profile.get("name") or ("default" if has_compile_commands or configured_macros else None)

    context = {
        "kind": kind,
        "source": path if is_source else None,
        "target_profile": target_profile_name,
        "target_profile_payload": target_profile,
        "compile_commands": has_compile_commands,
        "compile_commands_entry": path in build_context.source_files,
        "precision": precision,
        "macro_names": macro_names,
        "macro_values": macro_values,
        "command_macros": command_macros,
        "header_macros": header_macros,
        "macro_origins": _macro_origins(command_macros, header_macros, configured_macros),
        "configured_macros": sorted(set(configured_macros)),
        "included_headers": list(build_context.included_headers_by_source.get(path, [])),
    }
    return {key: value for key, value in context.items() if value not in (None, [], {})}


def _header_projection_context(source_path: str, header: str, build_context, configured_macros: list[str]) -> dict:
    source_context = dict(_translation_unit_context(source_path, build_context, configured_macros))
    source_context.update(
        {
            "kind": "header_projected_into_tu",
            "source": source_path,
            "header": header,
            "compile_commands_entry": source_path in build_context.source_files,
            "precision": "translation_unit_projected_header",
        }
    )
    return source_context


def _macro_origins(command_macros: list[str], header_macros: list[str], configured_macros: list[str]) -> dict[str, list[str]]:
    origins: dict[str, list[str]] = {}
    for origin, macros in [
        ("command", command_macros),
        ("header", header_macros),
        ("configured", configured_macros),
    ]:
        for raw in macros:
            name = _macro_name_from_raw(raw)
            if name is None:
                continue
            origins.setdefault(name, [])
            if origin not in origins[name]:
                origins[name].append(origin)
    return origins


def _macro_name_from_raw(raw: str) -> str | None:
    text = raw.strip()
    if text.startswith("-D"):
        text = text[2:].strip()
    if not text:
        return None
    name = text.split("=", 1)[0].strip()
    return name or None


def _attach_include_resolution(facts: list[CodeFact], path: str, build_context) -> list[CodeFact]:
    resolution = build_context.include_resolution_by_source.get(path, {})
    marked: list[CodeFact] = []
    for fact in facts:
        if fact.fact_type != "include" or fact.predicate != "includes":
            marked.append(fact)
            continue
        target = fact.payload.get("target") or fact.object
        payload = dict(fact.payload)
        if isinstance(target, str) and target in resolution:
            payload.update(
                {
                    "resolved_path": resolution[target],
                    "resolution_status": "resolved",
                    "resolution_scope": "compile_commands_include_path",
                }
            )
        else:
            payload.update({"resolution_status": "unresolved"})
        marked.append(replace(fact, payload=payload))
    return marked


def _header_visibility_facts(path: str, build_context) -> list[CodeFact]:
    if Path(path).suffix.lower() not in CPP_SOURCE_EXTENSIONS:
        return []
    facts: list[CodeFact] = []
    for header in build_context.included_headers_by_source.get(path, []):
        facts.append(
            CodeFact(
                fact_type="include",
                path=path,
                start_line=1,
                end_line=1,
                subject=path,
                predicate="header_visible_in_tu",
                object=header,
                confidence="medium",
                source="compile_commands_context",
                payload={
                    "build_status": "active",
                    "build_status_precision": "translation_unit",
                    "include_relation": "header_visible_in_tu",
                    "resolved_path": header,
                },
            )
        )
    return facts


def _mark_build_status(
    facts: list[CodeFact],
    preprocessor: PreprocessorModel,
    macro_defs: dict[str, str | None],
) -> list[CodeFact]:
    marked: list[CodeFact] = []
    for fact in facts:
        if fact.fact_type == "build_guard":
            marked.append(_mark_build_guard_status(fact))
            continue

        status = _fact_line_status(fact, preprocessor)
        payload = dict(fact.payload)
        _attach_build_provenance(payload, status, macro_defs, fact_build_status=status.status)
        if status.status == "inactive":
            payload.update(
                {
                    "build_status": "inactive",
                    "build_status_precision": "line_preprocessor_model",
                    "inactive_reason": status.inactive_reason or "preprocessor_condition",
                    "inactive_expression": status.inactive_expression or "unknown",
                }
            )
            marked.append(replace(fact, confidence="low", payload=payload))
        elif status.status == "conditional":
            guards = list(status.guard_stack)
            payload.update(
                {
                    "build_status": "conditional",
                    "build_status_precision": "line_preprocessor_model",
                    "conditional_reason": "unresolved_preprocessor_guard",
                    "guard_expressions": [guard.expression for guard in guards],
                    "guard_directives": [guard.directive for guard in guards],
                    "guard_lines": [guard.line for guard in guards],
                    "guard_stack": [guard.to_dict() for guard in guards],
                }
            )
            evaluation_reasons = sorted({guard.evaluation_reason for guard in guards if guard.evaluation_reason})
            unsupported_kinds = sorted({guard.unsupported_kind for guard in guards if guard.unsupported_kind})
            unresolved_symbols = sorted({symbol for guard in guards for symbol in guard.unresolved_symbols})
            if evaluation_reasons:
                payload["guard_evaluation_reasons"] = evaluation_reasons
            if unsupported_kinds:
                payload["unsupported_preprocessor_kinds"] = unsupported_kinds
            if unresolved_symbols:
                payload["unresolved_guard_symbols"] = unresolved_symbols
            marked.append(replace(fact, confidence="medium", payload=payload))
        else:
            payload.update(
                {
                    "build_status": "active",
                    "build_status_precision": "line_preprocessor_model",
                }
            )
            marked.append(replace(fact, payload=payload))
    return marked


def _attach_build_provenance(payload: dict, status: LineBuildStatus, macro_defs: dict[str, str | None], *, fact_build_status: str) -> None:
    if not status.guard_stack:
        return
    chain = build_guard_chain_payload(status.guard_stack, macro_defs, fact_build_status=fact_build_status)
    if not chain:
        return
    payload["build_guard_chain"] = chain
    payload.update(build_guard_summary(chain))


def _mark_build_guard_status(fact: CodeFact) -> CodeFact:
    payload = dict(fact.payload)
    status = payload.get("effective_status") or payload.get("status") or "active"
    if status not in {"active", "inactive", "conditional"}:
        status = "conditional" if status == "unclosed" else "active"
    payload.setdefault("build_status", status)
    payload.setdefault("build_status_precision", "preprocessor_branch" if payload.get("kind") == "guard_branch" else "preprocessor_guard_block")
    return replace(fact, payload=payload)


def _fact_line_status(fact: CodeFact, preprocessor: PreprocessorModel) -> LineBuildStatus:
    lines = [fact.start_line] if fact.fact_type == "symbol" else range(fact.start_line, fact.end_line + 1)
    statuses = [preprocessor.line_status.get(line, LineBuildStatus(line=line, status="active")) for line in lines]
    inactive = [status for status in statuses if status.status == "inactive"]
    if inactive:
        return inactive[0]
    conditional = [status for status in statuses if status.status == "conditional"]
    if conditional:
        guards: list[ConditionalGuard] = []
        seen: set[tuple[str, str, int]] = set()
        for status in conditional:
            for guard in status.guard_stack:
                key = (guard.directive, guard.expression, guard.line)
                if key not in seen:
                    guards.append(guard)
                    seen.add(key)
        return LineBuildStatus(line=fact.start_line, status="conditional", guard_stack=tuple(guards))
    active_guards: list[ConditionalGuard] = []
    seen: set[tuple[str, str, int]] = set()
    for status in statuses:
        for guard in status.guard_stack:
            key = (guard.directive, guard.expression, guard.line)
            if key not in seen:
                active_guards.append(guard)
                seen.add(key)
    return LineBuildStatus(line=fact.start_line, status="active", guard_stack=tuple(active_guards))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
