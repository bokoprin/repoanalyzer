from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from repoanalyzer.core.source_kinds import CPP_EXTENSIONS


@dataclass(frozen=True)
class SourceFile:
    path: str
    absolute_path: Path
    text: str


def iter_cpp_files(repo: str | Path, exclude_patterns: list[str] | None = None) -> list[SourceFile]:
    root = Path(repo).expanduser().resolve()
    patterns = list(exclude_patterns or [])
    files: list[SourceFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if ".repoanalyzer-index" in path.parts:
            continue
        if path.suffix.lower() not in CPP_EXTENSIONS:
            continue
        rel = path.relative_to(root).as_posix()
        if _is_excluded(rel, patterns):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        files.append(SourceFile(rel, path, text))
    return files


def _is_excluded(rel_path: str, patterns: list[str]) -> bool:
    for raw_pattern in patterns:
        pattern = raw_pattern.strip().replace("\\", "/")
        if not pattern:
            continue
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if pattern.endswith("/**") and rel_path.startswith(pattern[:-3].rstrip("/") + "/"):
            return True
        if "/" not in pattern and pattern in rel_path.split("/"):
            return True
    return False
