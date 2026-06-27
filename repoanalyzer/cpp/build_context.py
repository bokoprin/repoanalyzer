from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repoanalyzer.core.source_kinds import CPP_SOURCE_EXTENSIONS
from repoanalyzer.cpp.macro_eval import MacroDefinition, parse_hash_define


_LOCAL_INCLUDE_RE = re.compile(r'^\s*#\s*include\s+"(?P<target>[^"]+)"')
_IFNDEF_RE = re.compile(r"^\s*#\s*ifndef\s+(?P<name>[A-Za-z_]\w*)\b")
_DEFINE_NAME_RE = re.compile(r"^\s*#\s*define\s+(?P<name>[A-Za-z_]\w*)\b")
_HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx"}


@dataclass(frozen=True)
class BuildContext:
    compile_commands_path: str | None = None
    include_dirs: list[str] = field(default_factory=list)
    macros: list[str] = field(default_factory=list)
    entries: list[dict] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    command_macros_by_source: dict[str, list[str]] = field(default_factory=dict)
    macros_by_source: dict[str, list[str]] = field(default_factory=dict)
    header_macros_by_source: dict[str, list[str]] = field(default_factory=dict)
    included_headers_by_source: dict[str, list[str]] = field(default_factory=dict)
    include_resolution_by_source: dict[str, dict[str, str]] = field(default_factory=dict)
    target_profile: dict[str, Any] = field(default_factory=dict)


def load_build_context(
    repo: str | Path,
    compile_commands: str | None = None,
    *,
    configured_include_dirs: list[str] | None = None,
    target_profile: Any | None = None,
) -> BuildContext:
    root = Path(repo).expanduser().resolve()
    if compile_commands:
        configured_path = Path(compile_commands).expanduser()
        path = configured_path if configured_path.is_absolute() else root / configured_path
        path = path.resolve(strict=False)
    else:
        path = root / "compile_commands.json"
    configured_include_dirs = list(configured_include_dirs or [])
    profile_payload = _target_profile_payload(target_profile, compile_commands)
    profile_config_headers = _resolve_profile_config_headers(root, profile_payload)
    if not path.exists():
        header_macros = _macros_from_header_files(root, profile_config_headers, [])
        return BuildContext(
            include_dirs=sorted(set(configured_include_dirs)),
            macros=header_macros,
            target_profile=profile_payload,
        )
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except Exception:
        entries = []
    include_dirs: list[str] = list(configured_include_dirs)
    macros: list[str] = []
    source_files: list[str] = []
    command_macros_by_source: dict[str, list[str]] = {}
    macros_by_source: dict[str, list[str]] = {}
    header_macros_by_source: dict[str, list[str]] = {}
    included_headers_by_source: dict[str, list[str]] = {}
    include_resolution_by_source: dict[str, dict[str, str]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        command = entry.get("command") or " ".join(entry.get("arguments") or [])
        parts = _split_command(str(command))
        entry_macros = _extract_macros(parts)
        entry_include_dirs = _extract_include_dirs(parts)
        effective_entry_include_dirs = [*configured_include_dirs, *entry_include_dirs]
        include_dirs.extend(effective_entry_include_dirs)
        macros.extend(entry_macros)

        source_file = _entry_source_file(root, path, entry)
        if source_file is None:
            continue

        source_files.append(source_file)
        command_macros_by_source[source_file] = sorted(set(entry_macros))
        source_abs = (root / source_file).resolve(strict=False)
        entry_base_dirs = _entry_base_dirs(root, path, entry)
        header_files, include_resolution = _entry_header_files(root, source_abs, entry_base_dirs, effective_entry_include_dirs, parts)
        for profile_header in profile_config_headers:
            if profile_header not in header_files:
                header_files.append(profile_header)
        header_macros = _macros_from_header_files(root, header_files, entry_macros)
        combined_macros = sorted(set(entry_macros + header_macros))
        macros_by_source[source_file] = combined_macros
        header_macros_by_source[source_file] = sorted(set(header_macros))
        included_headers_by_source[source_file] = sorted(
            {
                rel
                for header in header_files
                if (rel := _repo_relative_existing_file(root, header)) is not None
            }
        )
        include_resolution_by_source[source_file] = {
            target: rel
            for target, header in include_resolution.items()
            if (rel := _repo_relative_existing_file(root, header)) is not None
        }

    return BuildContext(
        str(path),
        sorted(set(include_dirs)),
        sorted(set(macros)),
        entries,
        sorted(set(source_files)),
        command_macros_by_source,
        macros_by_source,
        header_macros_by_source,
        included_headers_by_source,
        include_resolution_by_source,
        profile_payload,
    )



def _target_profile_payload(target_profile: Any | None, compile_commands: str | None) -> dict[str, Any]:
    if target_profile is None:
        return {}
    if hasattr(target_profile, "to_dict"):
        payload = dict(target_profile.to_dict())
    elif isinstance(target_profile, dict):
        payload = dict(target_profile)
    else:
        payload = {}
    if compile_commands and "compile_commands" not in payload:
        payload["compile_commands"] = compile_commands
    if payload:
        payload.setdefault("name", "default")
    return {key: value for key, value in payload.items() if value not in (None, [], {})}


def _resolve_profile_config_headers(root: Path, profile_payload: dict[str, Any]) -> list[Path]:
    headers: list[Path] = []
    for raw in profile_payload.get("config_headers") or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        path = Path(raw).expanduser()
        candidates = [path] if path.is_absolute() else [root / path]
        for candidate in candidates:
            resolved = _resolve_path(candidate)
            if resolved.exists() and resolved.is_file() and _repo_relative_existing_file(root, resolved) is not None:
                headers.append(resolved)
                break
    result: list[Path] = []
    seen: set[str] = set()
    for header in headers:
        key = str(header)
        if key not in seen:
            seen.add(key)
            result.append(header)
    return result

def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _extract_macros(parts: list[str]) -> list[str]:
    macros: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if part == "-D" and idx + 1 < len(parts):
            macros.append(parts[idx + 1])
            idx += 2
            continue
        if part.startswith("-D") and len(part) > 2:
            macros.append(part[2:])
        idx += 1
    return macros


def _extract_include_dirs(parts: list[str]) -> list[str]:
    include_dirs: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if part == "-I" and idx + 1 < len(parts):
            include_dirs.append(parts[idx + 1])
            idx += 2
            continue
        if part.startswith("-I") and len(part) > 2:
            include_dirs.append(part[2:])
        idx += 1
    return include_dirs


def _extract_forced_includes(parts: list[str]) -> list[str]:
    includes: list[str] = []
    idx = 0
    while idx < len(parts):
        part = parts[idx]
        if part == "-include" and idx + 1 < len(parts):
            includes.append(parts[idx + 1])
            idx += 2
            continue
        if part.startswith("-include") and len(part) > len("-include"):
            includes.append(part[len("-include") :])
        idx += 1
    return includes


def _entry_source_file(root: Path, compile_commands_path: Path, entry: dict[str, Any]) -> str | None:
    raw_file = entry.get("file")
    if not isinstance(raw_file, str) or not raw_file:
        return None

    candidates = _entry_file_candidates(root, compile_commands_path, entry, raw_file)
    for candidate in candidates:
        rel = _repo_relative_cpp_source(root, candidate)
        if rel is not None and candidate.exists():
            return rel
    for candidate in candidates:
        rel = _repo_relative_cpp_source(root, candidate)
        if rel is not None:
            return rel
    return None


def _entry_file_candidates(
    root: Path,
    compile_commands_path: Path,
    entry: dict[str, Any],
    raw_file: str,
) -> list[Path]:
    file_path = Path(raw_file).expanduser()
    if file_path.is_absolute():
        return [_resolve_path(file_path)]

    return [_resolve_path(directory / file_path) for directory in _entry_base_dirs(root, compile_commands_path, entry)]


def _entry_base_dirs(root: Path, compile_commands_path: Path, entry: dict[str, Any]) -> list[Path]:
    raw_directory = entry.get("directory")
    if isinstance(raw_directory, str) and raw_directory:
        directory_path = Path(raw_directory).expanduser()
        if directory_path.is_absolute():
            directories = [directory_path]
        else:
            directories = [root / directory_path, compile_commands_path.parent / directory_path]
    else:
        directories = [root, compile_commands_path.parent]

    result: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        resolved = _resolve_path(directory)
        key = str(resolved)
        if key not in seen:
            result.append(resolved)
            seen.add(key)
    return result


def _entry_header_files(
    root: Path,
    source_abs: Path,
    entry_base_dirs: list[Path],
    include_dirs: list[str],
    parts: list[str],
) -> tuple[list[Path], dict[str, Path]]:
    headers: list[Path] = []
    resolution: dict[str, Path] = {}
    for target in _extract_forced_includes(parts):
        header = _resolve_header(root, source_abs.parent, entry_base_dirs, include_dirs, target)
        if header is not None:
            headers.append(header)
            resolution[target] = header

    source_text = _read_text(source_abs)
    if source_text is not None:
        for target in _direct_local_include_targets(source_text):
            header = _resolve_header(root, source_abs.parent, entry_base_dirs, include_dirs, target)
            if header is not None:
                headers.append(header)
                resolution[target] = header

    result: list[Path] = []
    seen: set[str] = set()
    for header in headers:
        key = str(header)
        if key not in seen:
            result.append(header)
            seen.add(key)
    return result, resolution


def _direct_local_include_targets(text: str) -> list[str]:
    targets: list[str] = []
    for line in text.splitlines():
        m = _LOCAL_INCLUDE_RE.match(line)
        if m:
            targets.append(m.group("target"))
    return targets


def _resolve_header(
    root: Path,
    source_dir: Path,
    entry_base_dirs: list[Path],
    include_dirs: list[str],
    target: str,
) -> Path | None:
    target_path = Path(target).expanduser()
    candidates: list[Path]
    if target_path.is_absolute():
        candidates = [target_path]
    else:
        bases: list[Path] = [source_dir, *entry_base_dirs]
        for include_dir in include_dirs:
            include_path = Path(include_dir).expanduser()
            if include_path.is_absolute():
                bases.append(include_path)
            else:
                bases.extend([base / include_path for base in entry_base_dirs])
                bases.append(root / include_path)
        candidates = [base / target_path for base in bases]

    seen: set[str] = set()
    for candidate in candidates:
        resolved = _resolve_path(candidate)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if not resolved.exists() or not resolved.is_file():
            continue
        if resolved.suffix.lower() not in _HEADER_EXTENSIONS:
            continue
        if _repo_relative_existing_file(root, resolved) is None:
            continue
        return resolved
    return None


def _macros_from_header_files(root: Path, header_files: list[Path], base_macros: list[str]) -> list[str]:
    macros: list[str] = []
    visible = {definition.name for raw in base_macros if (definition := _parse_raw_macro(raw)) is not None}
    for header in header_files:
        text = _read_text(header)
        if text is None:
            continue
        for definition in _extract_header_definitions(text, visible):
            raw = _definition_to_raw(definition)
            macros.append(raw)
            visible.add(definition.name)
    return sorted(set(macros))


def _extract_header_definitions(text: str, initially_defined: set[str]) -> list[MacroDefinition]:
    include_guard = _detect_include_guard(text)
    defined = set(initially_defined)
    definitions: list[MacroDefinition] = []
    stack: list[str] = []

    for line in text.splitlines():
        status = _preprocessor_status(line, defined, include_guard)
        if status is not None:
            directive, value = status
            if directive in {"if", "ifdef", "ifndef"}:
                stack.append(value)
                continue
            if directive == "else":
                if stack:
                    stack[-1] = _invert_status(stack[-1])
                continue
            if directive == "endif":
                if stack:
                    stack.pop()
                continue

        if any(state != "active" for state in stack):
            continue

        definition = parse_hash_define(line)
        if definition is None:
            continue
        if definition.name == include_guard:
            # Do not leak include guard sentinels into the TU macro map; doing so
            # can make standalone header ingest think the header body is inactive.
            continue
        definitions.append(definition)
        defined.add(definition.name)
    return definitions


def _preprocessor_status(line: str, defined: set[str], include_guard: str | None) -> tuple[str, str] | None:
    stripped = line.strip()
    m_ifndef = _IFNDEF_RE.match(stripped)
    if m_ifndef:
        name = m_ifndef.group("name")
        if name == include_guard:
            return "ifndef", "active"
        return "ifndef", "inactive" if name in defined else "conditional"
    if stripped.startswith("#ifdef"):
        name = stripped[len("#ifdef") :].strip()
        return "ifdef", "active" if name in defined else "conditional"
    if stripped.startswith("#if"):
        expr = stripped[3:].strip()
        if expr in {"1", "(1)"}:
            return "if", "active"
        if expr in {"0", "(0)"}:
            return "if", "inactive"
        return "if", "conditional"
    if stripped.startswith("#else"):
        return "else", "else"
    if stripped.startswith("#endif"):
        return "endif", "endif"
    return None


def _invert_status(status: str) -> str:
    if status == "active":
        return "inactive"
    if status == "inactive":
        return "active"
    return "conditional"


def _detect_include_guard(text: str) -> str | None:
    lines = [line for line in text.splitlines() if line.strip()]
    for idx, line in enumerate(lines[:8]):
        m_ifndef = _IFNDEF_RE.match(line)
        if not m_ifndef:
            continue
        name = m_ifndef.group("name")
        for candidate in lines[idx + 1 : idx + 5]:
            m_define = _DEFINE_NAME_RE.match(candidate)
            if m_define and m_define.group("name") == name:
                return name
        return None
    return None


def _parse_raw_macro(raw: str) -> MacroDefinition | None:
    from repoanalyzer.cpp.macro_eval import parse_macro_definition

    return parse_macro_definition(raw)


def _definition_to_raw(definition: MacroDefinition) -> str:
    if definition.value is None or definition.value == "":
        return definition.name
    return f"{definition.name}={definition.value}"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _repo_relative_cpp_source(root: Path, path: Path) -> str | None:
    resolved = _resolve_path(path)
    if resolved.suffix.lower() not in CPP_SOURCE_EXTENSIONS:
        return None
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def _repo_relative_existing_file(root: Path, path: Path) -> str | None:
    resolved = _resolve_path(path)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)
