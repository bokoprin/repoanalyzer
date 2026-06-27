from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repoanalyzer.config import load_config
from repoanalyzer.core.paths import index_db_path
from repoanalyzer.core.source_kinds import CPP_HEADER_EXTENSIONS, CPP_RESOURCE_EXTENSIONS, CPP_SOURCE_EXTENSIONS
from repoanalyzer.core.target_selection import filter_active_files
from repoanalyzer.store.sqlite import SQLiteStore, file_sha256_from_text


@dataclass(frozen=True)
class FileStatus:
    path: str
    status: str
    reason: str
    indexed_sha256: str | None = None
    current_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True)
class RepoIndexStatus:
    repo: str
    db_path: str
    status: str
    indexed_files: int
    current_files: int
    stale: list[FileStatus] = field(default_factory=list)
    missing: list[FileStatus] = field(default_factory=list)
    new: list[FileStatus] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.status == "clean"

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "db_path": self.db_path,
            "status": self.status,
            "clean": self.clean,
            "indexed_files": self.indexed_files,
            "current_files": self.current_files,
            "stale": [item.to_dict() for item in self.stale],
            "missing": [item.to_dict() for item in self.missing],
            "new": [item.to_dict() for item in self.new],
            "metadata": self.metadata,
        }


def repo_index_status(repo: str | Path, *, config_path: str | Path | None = None) -> RepoIndexStatus:
    root = Path(repo).expanduser().resolve()
    db = index_db_path(root)
    if not db.exists():
        return RepoIndexStatus(
            repo=str(root),
            db_path=str(db),
            status="missing_index",
            indexed_files=0,
            current_files=0,
            metadata={},
        )

    store = SQLiteStore(db)
    metadata = store.all_metadata()
    config = load_config(config_path)
    exclude_patterns = list(config.index.exclude_patterns)
    compile_commands = config.cpp.effective_compile_commands
    include_dirs = list(config.cpp.effective_include_dirs)
    target_profile = config.cpp.target_profile.to_dict()
    if config_path is None:
        exclude_patterns = list(metadata.get("exclude_patterns") or [])
        target_profile = dict(metadata.get("target_profile") or target_profile or {})
        compile_commands = metadata.get("compile_commands") or target_profile.get("compile_commands") or compile_commands
        include_dirs = list(target_profile.get("include_dirs") or include_dirs)
        if isinstance(compile_commands, str):
            try:
                compile_commands = Path(compile_commands).relative_to(root).as_posix()
            except ValueError:
                compile_commands = str(compile_commands)

    indexed = {entry.path: entry for entry in store.file_index_entries()}
    current_files = _current_indexable_files(
        root,
        exclude_patterns=exclude_patterns,
        compile_commands=compile_commands,
        include_dirs=include_dirs,
        target_profile=target_profile,
    )
    current = {source.path: source for source in current_files}

    stale: list[FileStatus] = []
    missing: list[FileStatus] = []
    new: list[FileStatus] = []

    for path, entry in indexed.items():
        source = current.get(path)
        if source is None:
            missing.append(FileStatus(path=path, status="missing", reason="indexed_file_not_found_or_excluded", indexed_sha256=entry.sha256))
            continue
        current_sha = file_sha256_from_text(source.text)
        if current_sha != entry.sha256:
            stale.append(
                FileStatus(
                    path=path,
                    status="stale",
                    reason="sha256_changed",
                    indexed_sha256=entry.sha256,
                    current_sha256=current_sha,
                )
            )

    for path, source in current.items():
        if path not in indexed:
            new.append(
                FileStatus(
                    path=path,
                    status="new",
                    reason="current_file_not_indexed",
                    current_sha256=file_sha256_from_text(source.text),
                )
            )

    status = "clean" if not stale and not missing and not new else "dirty"
    metadata.setdefault("exclude_patterns", exclude_patterns)
    return RepoIndexStatus(
        repo=str(root),
        db_path=str(db),
        status=status,
        indexed_files=len(indexed),
        current_files=len(current),
        stale=stale,
        missing=missing,
        new=new,
        metadata=metadata,
    )


def _current_indexable_files(
    repo: Path,
    *,
    exclude_patterns: list[str] | None = None,
    compile_commands: str | None = None,
    include_dirs: list[str] | None = None,
    target_profile: dict[str, Any] | None = None,
):
    # Import lazily to avoid a package initialization cycle when store modules
    # are tested without importing the C++ ingest pipeline first.
    from repoanalyzer.cpp.build_context import load_build_context
    from repoanalyzer.cpp.scanner import iter_cpp_files

    build_context = load_build_context(
        repo,
        compile_commands,
        configured_include_dirs=include_dirs or [],
        target_profile=target_profile or {},
    )
    files = iter_cpp_files(repo, exclude_patterns=exclude_patterns)
    return _filter_files_for_status(files, build_context.source_files, target_profile or build_context.target_profile)


def _filter_files_for_status(files, source_files: list[str], target_profile: dict[str, Any] | None = None):
    return filter_active_files(files, source_files, target_profile)


def source_kind_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in CPP_SOURCE_EXTENSIONS:
        return "source"
    if suffix in CPP_HEADER_EXTENSIONS:
        return "header"
    if suffix in CPP_RESOURCE_EXTENSIONS:
        return "resource"
    return "unknown"
