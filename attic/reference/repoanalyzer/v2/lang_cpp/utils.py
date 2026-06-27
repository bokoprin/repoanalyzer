from __future__ import annotations

import re
from pathlib import Path

CPP_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")
NOISY_PATH_HINTS = ("externals/", "vendor/", "sample/", "tests/", "helper/", "docs/", "help/")


def is_cpp_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return lowered.endswith(CPP_EXTENSIONS)


def is_noisy_cpp_path(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return any(token in lowered for token in NOISY_PATH_HINTS) or any(
        token in lowered for token in ("gtest", "googletest", "ctags")
    )


def path_prior(path: str, *, promote: dict[str, float], penalize: dict[str, float]) -> float:
    lowered = path.lower().replace("\\", "/")
    score = 0.0
    for token, bonus in promote.items():
        if token in lowered:
            score += float(bonus)
    for token, penalty in penalize.items():
        if token in lowered:
            score += float(penalty)
    return score


def normalize_setting_key(*parts: str) -> str:
    tokens: list[str] = []
    for part in parts:
        lowered = part.strip().lower()
        if not lowered:
            continue
        lowered = lowered.replace("::", "_")
        lowered = re.sub(r"^[ms]_", "", lowered)
        lowered = lowered.replace("_", "")
        tokens.append(lowered)
    joined = ":".join(token for token in tokens if token)
    return joined or ""


def read_excerpt(repo_path: Path, path: str, line: int, *, radius: int = 2) -> str:
    file_path = repo_path / Path(path)
    if not file_path.exists():
        return ""
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return ""
    start = max(line - radius, 1)
    end = min(line + radius, len(lines))
    return "\n".join(lines[start - 1 : end])
