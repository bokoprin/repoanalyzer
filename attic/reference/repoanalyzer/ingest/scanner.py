from __future__ import annotations

import io
import os
from collections import deque
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from fnmatch import fnmatch
from functools import partial
from hashlib import sha256
from pathlib import Path
from typing import Any

from repoanalyzer.models import ScannedFile

IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

TEXT_EXT_LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".rb": "ruby",
    ".php": "php",
    ".cs": "csharp",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".md": "markdown",
    ".txt": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "config",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".psd1": "powershell",
    ".sql": "sql",
    ".pl": "perl",
    ".pm": "perl",
    ".t": "perl",
}


ScanProgressCallback = Callable[[int, int], None]


def detect_language(path: Path) -> str:
    return TEXT_EXT_LANGUAGE_MAP.get(path.suffix.lower(), "unknown")


def is_likely_binary(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return True
    sample = data[:4096]
    if not sample:
        return False
    text_like = 0
    for byte in sample:
        if byte in {9, 10, 13}:
            text_like += 1
            continue
        if 32 <= byte <= 126:
            text_like += 1
            continue
        if 128 <= byte <= 255:
            text_like += 1
    non_text_ratio = 1.0 - (text_like / len(sample))
    return non_text_ratio > 0.30


def scan_repository(
    repo_path: Path,
    max_file_size_bytes: int = 2 * 1024 * 1024,
    workers: int | None = None,
    partial_large_file_enabled: bool = True,
    partial_large_file_bytes: int = 10 * 1024 * 1024,
    partial_large_file_sample_lines: int = 4000,
    encoding_detect: str = "charset-normalizer",
    obey_gitignore: bool = True,
    progress_callback: ScanProgressCallback | None = None,
) -> list[ScannedFile]:
    repo_root = repo_path.resolve()
    gitignore_patterns = _load_gitignore_patterns(repo_root) if obey_gitignore else []
    scanned = _scan_many_files(
        repo_root=repo_root,
        file_paths=_iter_repository_files(repo_root),
        max_file_size_bytes=max_file_size_bytes,
        workers=workers,
        partial_large_file_enabled=partial_large_file_enabled,
        partial_large_file_bytes=partial_large_file_bytes,
        partial_large_file_sample_lines=partial_large_file_sample_lines,
        encoding_detect=encoding_detect,
        gitignore_patterns=gitignore_patterns,
        progress_callback=progress_callback,
    )
    scanned.sort(key=lambda item: item.relative_path)
    return scanned


def scan_selected_files(
    repo_path: Path,
    relative_paths: list[str],
    max_file_size_bytes: int = 2 * 1024 * 1024,
    workers: int | None = None,
    partial_large_file_enabled: bool = True,
    partial_large_file_bytes: int = 10 * 1024 * 1024,
    partial_large_file_sample_lines: int = 4000,
    encoding_detect: str = "charset-normalizer",
    obey_gitignore: bool = True,
    progress_callback: ScanProgressCallback | None = None,
) -> list[ScannedFile]:
    repo_root = repo_path.resolve()
    gitignore_patterns = _load_gitignore_patterns(repo_root) if obey_gitignore else []
    file_paths = [repo_root / relative_path for relative_path in relative_paths]
    scanned = _scan_many_files(
        repo_root=repo_root,
        file_paths=file_paths,
        max_file_size_bytes=max_file_size_bytes,
        workers=workers,
        partial_large_file_enabled=partial_large_file_enabled,
        partial_large_file_bytes=partial_large_file_bytes,
        partial_large_file_sample_lines=partial_large_file_sample_lines,
        encoding_detect=encoding_detect,
        gitignore_patterns=gitignore_patterns,
        progress_callback=progress_callback,
    )
    scanned.sort(key=lambda item: item.relative_path)
    return scanned


def _scan_many_files(
    repo_root: Path,
    file_paths: Iterable[Path],
    max_file_size_bytes: int,
    workers: int | None,
    partial_large_file_enabled: bool,
    partial_large_file_bytes: int,
    partial_large_file_sample_lines: int,
    encoding_detect: str,
    gitignore_patterns: list[str],
    progress_callback: ScanProgressCallback | None,
) -> list[ScannedFile]:
    scanned: list[ScannedFile] = []
    file_path_list = list(file_paths)
    total_files = len(file_path_list)
    if progress_callback is not None:
        progress_callback(0, total_files)
    scanner = partial(
        _scan_single_file,
        repo_root=repo_root,
        max_file_size_bytes=max_file_size_bytes,
        partial_large_file_enabled=partial_large_file_enabled,
        partial_large_file_bytes=partial_large_file_bytes,
        partial_large_file_sample_lines=partial_large_file_sample_lines,
        encoding_detect=encoding_detect,
        gitignore_patterns=gitignore_patterns,
    )
    max_workers = _normalize_workers(workers)
    if max_workers <= 1:
        for index, file_path in enumerate(file_path_list, start=1):
            scanned_file = scanner(file_path=file_path)
            if scanned_file is not None:
                scanned.append(scanned_file)
            if progress_callback is not None:
                progress_callback(index, total_files)
        return scanned

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        def _scan_path(path: Path) -> ScannedFile | None:
            return scanner(file_path=path)

        completed = 0
        for scanned_file in executor.map(_scan_path, file_path_list, chunksize=64):
            if scanned_file is not None:
                scanned.append(scanned_file)
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, total_files)
    return scanned


def _normalize_workers(workers: int | None) -> int:
    if workers is None:
        return 1
    if workers <= 0:
        return 1
    return workers


def _scan_single_file(
    repo_root: Path,
    file_path: Path,
    max_file_size_bytes: int,
    partial_large_file_enabled: bool,
    partial_large_file_bytes: int,
    partial_large_file_sample_lines: int,
    encoding_detect: str,
    gitignore_patterns: list[str],
) -> ScannedFile | None:
    if not file_path.exists() or file_path.is_dir():
        return None
    if any(part in IGNORED_DIR_NAMES for part in file_path.parts):
        return None
    relative_path = file_path.relative_to(repo_root).as_posix()
    if _is_ignored_by_gitignore(relative_path, gitignore_patterns):
        return None

    size_bytes = file_path.stat().st_size
    if size_bytes > max_file_size_bytes and (
        not partial_large_file_enabled or size_bytes > partial_large_file_bytes
    ):
        return None

    data = file_path.read_bytes()
    if is_likely_binary(data):
        return None

    decoded = _decode_bytes(data, encoding_detect=encoding_detect)
    line_count = _count_lines_from_bytes(data)
    if size_bytes > max_file_size_bytes and partial_large_file_enabled:
        text = _sample_large_text_streaming(decoded, sample_lines=partial_large_file_sample_lines)
    else:
        text = decoded
    return ScannedFile(
        repo_root=repo_root,
        relative_path=relative_path,
        absolute_path=file_path,
        language=detect_language(file_path),
        size_bytes=size_bytes,
        line_count=line_count,
        sha256=sha256(data).hexdigest(),
        text=text,
    )


def _sample_large_text_streaming(text: str, sample_lines: int) -> str:
    head_count = max(sample_lines // 2, 1)
    tail_count = max(sample_lines - head_count, 1)
    if sample_lines <= 0:
        return ""
    head: list[str] = []
    tail: deque[str] = deque(maxlen=tail_count)
    total_lines = 0
    for raw_line in io.StringIO(text):
        line = raw_line.rstrip("\r\n")
        total_lines += 1
        if len(head) < head_count:
            head.append(line)
            continue
        tail.append(line)
    if total_lines <= sample_lines:
        return "\n".join([*head, *list(tail)])
    omitted = max(total_lines - len(head) - len(tail), 0)
    marker = f"... [truncated {omitted} lines] ..."
    sampled = [*head, marker, *list(tail)]
    return "\n".join(sampled)


def _count_lines_from_bytes(data: bytes) -> int:
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def _iter_repository_files(repo_root: Path) -> Iterable[Path]:
    for current_root, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIR_NAMES]
        root_path = Path(current_root)
        for name in filenames:
            yield root_path / name


def _load_gitignore_patterns(repo_root: Path) -> list[str]:
    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        return []
    patterns: list[str] = []
    for raw_line in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _is_ignored_by_gitignore(relative_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return False
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        normalized = pattern[1:] if negated else pattern
        normalized = normalized.lstrip("/")
        if not normalized:
            continue
        matched = False
        if normalized.endswith("/"):
            matched = relative_path.startswith(normalized.rstrip("/") + "/")
        elif fnmatch(relative_path, normalized):
            matched = True
        elif fnmatch(relative_path, f"**/{normalized}"):
            matched = True
        if matched:
            ignored = not negated
    return ignored


def _decode_bytes(data: bytes, encoding_detect: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if encoding_detect.strip().lower() == "charset-normalizer":
        charset_module: Any | None = None
        try:
            import charset_normalizer as charset_module  # type: ignore[import-not-found,import-untyped]
        except Exception:
            charset_module = None
        if charset_module is not None:
            try:
                best = charset_module.from_bytes(data).best()
            except Exception:
                best = None
            if best is not None:
                try:
                    return str(best)
                except Exception:
                    return data.decode("utf-8", errors="ignore")
    return data.decode("utf-8", errors="ignore")
