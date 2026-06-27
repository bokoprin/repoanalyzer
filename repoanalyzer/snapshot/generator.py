from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SnapshotGenerationReport:
    schema_version: str = "snapshot_generation_report.v1"
    ok: bool = True
    snapshot_id: str | None = None
    manifest: str = ""
    output: str = ""
    source_mode: str = "local"
    source_count: int = 0
    copied_files: list[str] = field(default_factory=list)
    upstream_copied_files: list[str] = field(default_factory=list)
    generated_files: list[str] = field(default_factory=list)
    skipped_optional_sources: list[str] = field(default_factory=list)
    skipped_upstream_sources: list[str] = field(default_factory=list)
    checkout_roots: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "snapshot_id": self.snapshot_id,
            "manifest": self.manifest,
            "output": self.output,
            "source_mode": self.source_mode,
            "source_count": self.source_count,
            "copied_files": self.copied_files,
            "upstream_copied_files": self.upstream_copied_files,
            "generated_files": self.generated_files,
            "skipped_optional_sources": self.skipped_optional_sources,
            "skipped_upstream_sources": self.skipped_upstream_sources,
            "checkout_roots": self.checkout_roots,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def generate_snapshot(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    clean: bool = True,
    source_mode: str = "local",
    checkout_roots: dict[str, str | Path] | str | Path | None = None,
    upstream_output_root: str = "upstream_sources",
) -> SnapshotGenerationReport:
    """Generate a compact validation snapshot from a source-fetch manifest.

    `source_mode` controls where copied source files come from:

    - `local` copies each manifest entry's `source` from `source_root` to
      `destination`. This is the historical, network-free compact snapshot mode.
    - `upstream` copies files named in `upstream.path` / `upstream.paths` from a
      local repository checkout passed via `checkout_roots`. Upstream files are
      placed under `upstream_output_root/<repository>/<path>` unless an
      `upstream.destination` is supplied.
    - `both` performs both operations. This is useful for audit snapshots that
      keep compact slices and their upstream source evidence side by side.

    The generator never performs network access. It only copies from local
    files or local checkouts so tests and local LLM workflows remain reproducible.
    """
    normalized_mode = str(source_mode or "local").lower()
    if normalized_mode not in {"local", "upstream", "both"}:
        return SnapshotGenerationReport(ok=False, source_mode=normalized_mode, manifest=str(manifest_path), output=str(output_dir), errors=[f"unsupported source_mode: {source_mode!r}"])

    manifest = Path(manifest_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    copied: list[str] = []
    upstream_copied: list[str] = []
    generated: list[str] = []
    skipped: list[str] = []
    skipped_upstream: list[str] = []

    if not manifest.exists():
        return SnapshotGenerationReport(ok=False, source_mode=normalized_mode, manifest=str(manifest), output=str(output), errors=[f"manifest not found: {manifest}"])

    try:
        raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return SnapshotGenerationReport(ok=False, source_mode=normalized_mode, manifest=str(manifest), output=str(output), errors=[f"failed to read manifest: {exc}"])

    schema = str(raw.get("schema_version") or "")
    if schema != "snapshot_manifest.v1":
        errors.append(f"unsupported manifest schema_version: {schema!r}")

    snapshot_id = str(raw.get("snapshot_id") or raw.get("id") or manifest.stem)
    source_root = _resolve_source_root(manifest, raw.get("source_root", "."))
    sources = list(raw.get("sources") or [])
    checkout_root_map = _normalize_checkout_roots(checkout_roots, raw.get("checkout_roots"), manifest)

    if normalized_mode in {"upstream", "both"} and not checkout_root_map:
        errors.append("source_mode requires at least one checkout root for upstream copying")

    if clean and output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        if normalized_mode in {"local", "both"}:
            _copy_local_source(index, item, source_root, output, copied, skipped, errors)
        if normalized_mode in {"upstream", "both"}:
            _copy_upstream_sources(index, item, checkout_root_map, output, upstream_output_root, upstream_copied, skipped_upstream, warnings, errors)

    compile_commands = raw.get("compile_commands") or raw.get("generated", {}).get("compile_commands")
    if compile_commands:
        cc_output = str(compile_commands.get("output") or "compile_commands.json")
        try:
            dest = _safe_join(output, cc_output)
        except ValueError as exc:
            errors.append(f"compile_commands output is invalid: {exc}")
        else:
            entries = compile_commands.get("entries") or []
            if not isinstance(entries, list):
                errors.append("compile_commands.entries must be a list")
            else:
                try:
                    normalized_entries = [_normalize_compile_command_entry(entry, output) for entry in entries]
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(json.dumps(normalized_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    generated.append(_rel_to(output, dest))

    readme = raw.get("readme") or raw.get("generated", {}).get("readme")
    if readme:
        readme_output = str(readme.get("output") or "README.md")
        try:
            dest = _safe_join(output, readme_output)
        except ValueError as exc:
            errors.append(f"readme output is invalid: {exc}")
        else:
            content = str(readme.get("content") or "")
            if normalized_mode in {"upstream", "both"}:
                content += (
                    "\n\nGenerated with upstream checkout copy mode. "
                    "Upstream evidence files are copied under `"
                    + upstream_output_root
                    + "` unless entries override the destination.\n"
                )
            if not content.endswith("\n"):
                content += "\n"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            generated.append(_rel_to(output, dest))

    manifest_copy = raw.get("write_manifest_copy", True)
    if manifest_copy:
        try:
            dest = _safe_join(output, ".repoanalyzer-source-fetch-manifest.yaml")
            shutil.copyfile(manifest, dest)
            generated.append(_rel_to(output, dest))
        except Exception as exc:  # pragma: no cover - defensive path
            warnings.append(f"failed to write manifest copy: {exc}")

    ok = not errors
    report = SnapshotGenerationReport(
        ok=ok,
        snapshot_id=snapshot_id,
        manifest=str(manifest),
        output=str(output),
        source_mode=normalized_mode,
        source_count=len(sources),
        copied_files=sorted(set(copied)),
        upstream_copied_files=sorted(set(upstream_copied)),
        generated_files=sorted(set(generated)),
        skipped_optional_sources=sorted(set(skipped)),
        skipped_upstream_sources=sorted(set(skipped_upstream)),
        checkout_roots={repo: str(path) for repo, path in sorted(checkout_root_map.items())},
        errors=errors,
        warnings=warnings,
    )
    report_path = output / ".repoanalyzer-snapshot-report.json"
    try:
        report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive path
        report_errors = [*report.errors, f"failed to write generation report: {exc}"]
        report = SnapshotGenerationReport(
            ok=False,
            snapshot_id=report.snapshot_id,
            manifest=report.manifest,
            output=report.output,
            source_mode=report.source_mode,
            source_count=report.source_count,
            copied_files=report.copied_files,
            upstream_copied_files=report.upstream_copied_files,
            generated_files=report.generated_files,
            skipped_optional_sources=report.skipped_optional_sources,
            skipped_upstream_sources=report.skipped_upstream_sources,
            checkout_roots=report.checkout_roots,
            errors=report_errors,
            warnings=report.warnings,
        )
    return report


def _copy_local_source(index: int, item: dict[str, Any], source_root: Path, output: Path, copied: list[str], skipped: list[str], errors: list[str]) -> None:
    dest_raw = item.get("destination") or item.get("dest") or item.get("path")
    source_raw = item.get("source") or item.get("local_path")
    if not dest_raw:
        errors.append(f"sources[{index}] is missing destination")
        return
    required = bool(item.get("required", True))
    try:
        dest = _safe_join(output, str(dest_raw))
    except ValueError as exc:
        errors.append(f"sources[{index}] invalid destination: {exc}")
        return
    if not source_raw:
        if required:
            errors.append(f"sources[{index}] {dest_raw}: missing source")
        else:
            skipped.append(str(dest_raw))
        return
    source = Path(str(source_raw))
    if not source.is_absolute():
        source = (source_root / source).resolve()
    if not source.exists():
        msg = f"source not found: {source}"
        if required:
            errors.append(msg)
        else:
            skipped.append(str(dest_raw))
        return
    if not source.is_file():
        errors.append(f"source is not a file: {source}")
        return
    expected_sha = item.get("sha256")
    if expected_sha:
        actual_sha = _sha256_file(source)
        if actual_sha.lower() != str(expected_sha).lower():
            errors.append(f"sha256 mismatch for {source}: expected {expected_sha}, got {actual_sha}")
            return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    copied.append(_rel_to(output, dest))


def _copy_upstream_sources(
    index: int,
    item: dict[str, Any],
    checkout_roots: dict[str, Path],
    output: Path,
    upstream_output_root: str,
    upstream_copied: list[str],
    skipped_upstream: list[str],
    warnings: list[str],
    errors: list[str],
) -> None:
    upstream = item.get("upstream")
    if not isinstance(upstream, dict):
        skipped_upstream.append(f"sources[{index}]:missing_upstream")
        return
    repository = str(upstream.get("repository") or upstream.get("repo") or "").strip()
    if not repository:
        skipped_upstream.append(f"sources[{index}]:missing_repository")
        return
    root = checkout_roots.get(repository) or (next(iter(checkout_roots.values())) if len(checkout_roots) == 1 else None)
    if root is None:
        errors.append(f"sources[{index}] no checkout root for repository {repository}")
        return
    paths = _parse_upstream_paths(upstream)
    if not paths:
        skipped_upstream.append(f"sources[{index}]:no_upstream_paths")
        return
    required = bool(upstream.get("required", False))
    repo_slug = _safe_repo_slug(repository)
    for path_index, upstream_path in enumerate(paths):
        if not _looks_like_source_path(upstream_path):
            skipped_upstream.append(f"sources[{index}]:{upstream_path}")
            continue
        try:
            source = _safe_join(root, upstream_path)
        except ValueError as exc:
            errors.append(f"sources[{index}] invalid upstream path {upstream_path!r}: {exc}")
            continue
        if not source.exists():
            msg = f"upstream source not found: {source}"
            if required:
                errors.append(msg)
            else:
                warnings.append(msg)
                skipped_upstream.append(f"sources[{index}]:{upstream_path}")
            continue
        if not source.is_file():
            errors.append(f"upstream source is not a file: {source}")
            continue
        expected_sha = upstream.get("sha256")
        per_path_sha = None
        if isinstance(expected_sha, dict):
            per_path_sha = expected_sha.get(upstream_path)
        elif isinstance(expected_sha, list):
            per_path_sha = expected_sha[path_index] if path_index < len(expected_sha) else None
        elif expected_sha and len(paths) == 1:
            per_path_sha = expected_sha
        if per_path_sha:
            actual_sha = _sha256_file(source)
            if actual_sha.lower() != str(per_path_sha).lower():
                errors.append(f"upstream sha256 mismatch for {source}: expected {per_path_sha}, got {actual_sha}")
                continue
        override_destination = _upstream_destination(upstream, upstream_path, path_index)
        dest_rel = override_destination or f"{upstream_output_root}/{repo_slug}/{upstream_path}"
        try:
            dest = _safe_join(output, dest_rel)
        except ValueError as exc:
            errors.append(f"sources[{index}] invalid upstream destination: {exc}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        upstream_copied.append(_rel_to(output, dest))


def _resolve_source_root(manifest: Path, source_root_raw: Any) -> Path:
    root = Path(str(source_root_raw))
    if root.is_absolute():
        return root.resolve()
    return (manifest.parent / root).resolve()


def _normalize_checkout_roots(
    explicit: dict[str, str | Path] | str | Path | None,
    manifest_roots: Any,
    manifest: Path,
) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    if isinstance(manifest_roots, dict):
        for repo, raw_path in manifest_roots.items():
            roots[str(repo)] = _resolve_path_against_manifest(manifest, raw_path)
    if explicit is None:
        return roots
    if isinstance(explicit, dict):
        for repo, raw_path in explicit.items():
            roots[str(repo)] = Path(raw_path).expanduser().resolve()
        return roots
    roots["*"] = Path(explicit).expanduser().resolve()
    return roots


def _resolve_path_against_manifest(manifest: Path, raw_path: Any) -> Path:
    path = Path(str(raw_path)).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (manifest.parent / path).resolve()


def _parse_upstream_paths(upstream: dict[str, Any]) -> list[str]:
    raw_paths = upstream.get("path") or upstream.get("paths")
    if raw_paths is None:
        return []
    if isinstance(raw_paths, str):
        parts = [part.strip() for part in raw_paths.split("+")]
    elif isinstance(raw_paths, list):
        parts = []
        for raw in raw_paths:
            if isinstance(raw, dict):
                value = raw.get("path") or raw.get("source")
            else:
                value = raw
            if value is not None:
                parts.append(str(value).strip())
    else:
        return []
    return [part for part in parts if part]


def _upstream_destination(upstream: dict[str, Any], upstream_path: str, path_index: int) -> str | None:
    raw = upstream.get("destination") or upstream.get("dest")
    if raw is None:
        destinations = upstream.get("destinations")
        if isinstance(destinations, dict):
            value = destinations.get(upstream_path)
            return str(value) if value is not None else None
        if isinstance(destinations, list) and path_index < len(destinations):
            value = destinations[path_index]
            return str(value) if value is not None else None
        return None
    if isinstance(raw, dict):
        value = raw.get(upstream_path)
        return str(value) if value is not None else None
    if isinstance(raw, list):
        if path_index < len(raw):
            value = raw[path_index]
            return str(value) if value is not None else None
        return None
    if path_index == 0:
        return str(raw)
    return None


def _looks_like_source_path(path: str) -> bool:
    suffix = Path(path).suffix.lower()
    return "/" in path and suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".rc", ".rc2"}


def _safe_repo_slug(repository: str) -> str:
    return repository.replace(":", "_").replace("/", "__").replace("\\", "__")


def _safe_join(root: Path, rel: str) -> Path:
    path = Path(rel)
    if path.is_absolute():
        raise ValueError(f"absolute paths are not allowed: {rel}")
    if any(part == ".." for part in path.parts):
        raise ValueError(f"parent traversal is not allowed: {rel}")
    return (root / path).resolve()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_compile_command_entry(entry: Any, output: Path) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("compile_commands entries must be objects")
    normalized = dict(entry)
    if "directory" not in normalized:
        normalized["directory"] = str(output)
    elif normalized["directory"] in (".", "${SNAPSHOT_ROOT}"):
        normalized["directory"] = str(output)
    if "file" in normalized and not Path(str(normalized["file"])).is_absolute():
        normalized["file"] = str(output / str(normalized["file"]))
    return normalized


def _rel_to(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
