from __future__ import annotations

from pathlib import Path


def read_file_range(repo: str | Path, path: str, start_line: int, end_line: int) -> dict:
    root = Path(repo).expanduser().resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError("path escapes repository root")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, start_line)
    end = min(len(lines), end_line)
    selected = lines[start - 1 : end]
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "text": "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start)),
    }
