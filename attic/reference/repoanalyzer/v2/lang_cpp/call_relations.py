from __future__ import annotations

import re
from pathlib import Path

from repoanalyzer.v2.core.models import EntityCandidate
from repoanalyzer.v2.index.reader import V2IndexReader
from repoanalyzer.v2.lang_cpp.pattern_loader import PatternPack
from repoanalyzer.v2.lang_cpp.utils import is_cpp_path, is_noisy_cpp_path

_FP_ASSIGN_RE = re.compile(
    r"(?P<lhs>[A-Za-z_][A-Za-z0-9_:>\-.]*)\s*=\s*&?(?P<target>[A-Za-z_][A-Za-z0-9_:]*)"
)
_INDIRECT_CALL_RE = re.compile(
    r"(\(\*\s*[A-Za-z_][A-Za-z0-9_]*\s*\)\s*\()"
    r"|([A-Za-z_][A-Za-z0-9_]*\s*->\s*\()"
)


def find_override_candidates(
    *,
    reader: V2IndexReader,
    repo_path: Path,
    anchors: list[str],
    pattern_pack: PatternPack,
    slot: str,
    limit: int = 16,
) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    seen: set[tuple[str, int]] = set()
    for anchor in anchors:
        short = anchor.split("::")[-1]
        for row in reader.find_symbol_definitions(short, limit=limit * 2):
            path = str(row["path"]).replace("\\", "/")
            if not is_cpp_path(path) or is_noisy_cpp_path(path):
                continue
            line = int(row["start_line"])
            if (path, line) in seen:
                continue
            seen.add((path, line))
            excerpt = _read_excerpt(repo_path, path, line).lower()
            reasons: list[str] = []
            score = 0.38
            matched_rule = ""
            if any(term in excerpt for term in pattern_pack.override_terms):
                score += 0.22
                reasons.append("override_keyword")
                matched_rule = next(
                    (term for term in pattern_pack.override_terms if term in excerpt), ""
                )
            if "virtual" in excerpt:
                score += 0.12
                reasons.append("virtual_keyword")
            if anchor != short and short == str(row["name"]):
                score += 0.08
                reasons.append("short_name_match")
            if score < 0.45:
                continue
            candidates.append(
                EntityCandidate(
                    slot=slot,
                    entity_type="override_call",
                    source="source_scan",
                    path=path,
                    start_line=line,
                    end_line=int(row["end_line"]),
                    focus_line=line,
                    score=score,
                    confidence=min(score, 0.82),
                    reasons=reasons or ["override_candidate"],
                    symbol=str(row["name"]),
                    kind="override_call",
                        payload={
                            "relation_kind": "override_call",
                            "context": excerpt,
                            "pattern_pack": pattern_pack.name,
                            "matched_rule": matched_rule or "override",
                            "path_score_components": {
                                "base_relation_weight": pattern_pack.path_weights.get(
                                    "override_call", 0.56
                                )
                            },
                        },
                    )
                )
    return _dedupe(candidates)


def find_callback_candidates(
    *,
    repo_path: Path,
    files: list[str],
    symbols: list[str],
    pattern_pack: PatternPack,
    slot: str,
    limit: int = 20,
) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    needle_symbols = {symbol.split("::")[-1] for symbol in symbols if symbol}
    for path in files:
        if not is_cpp_path(path) or is_noisy_cpp_path(path):
            continue
        for line_no, text in _iter_lines(repo_path, path):
            lowered = text.lower()
            if not any(symbol in text for symbol in needle_symbols):
                continue
            matched_term = next(
                (
                    term
                    for term in [
                        *pattern_pack.callback_registration_terms,
                        *pattern_pack.callback_invocation_terms,
                    ]
                    if term in lowered
                ),
                "",
            )
            if matched_term:
                target = next((symbol for symbol in needle_symbols if symbol in text), "")
                kind = (
                    "callback_registration"
                    if any(term in lowered for term in pattern_pack.callback_registration_terms)
                    else "callback_invoke"
                )
                candidates.append(
                    EntityCandidate(
                        slot=slot,
                        entity_type=kind,
                        source="source_scan",
                        path=path,
                        start_line=line_no,
                        end_line=line_no,
                        focus_line=line_no,
                        score=0.56 if kind == "callback_registration" else 0.52,
                        confidence=0.56 if kind == "callback_registration" else 0.52,
                        reasons=[kind],
                        symbol=target,
                        kind=kind,
                        payload={
                            "relation_kind": kind,
                            "context": text.strip(),
                            "unknown_reason": (
                                "callback_registered_but_target_unknown"
                                if kind == "callback_registration"
                                else ""
                            ),
                            "pattern_pack": pattern_pack.name,
                            "matched_rule": matched_term,
                            "path_score_components": {
                                "base_relation_weight": pattern_pack.path_weights.get(
                                    kind, 0.52
                                )
                            },
                        },
                    )
                )
            if len(candidates) >= limit:
                return _dedupe(candidates)[:limit]
    return _dedupe(candidates)[:limit]


def find_function_pointer_candidates(
    *,
    repo_path: Path,
    files: list[str],
    symbols: list[str],
    pattern_pack: PatternPack,
    slot: str,
    limit: int = 20,
) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    needle_symbols = {symbol.split("::")[-1] for symbol in symbols if symbol}
    for path in files:
        if not is_cpp_path(path) or is_noisy_cpp_path(path):
            continue
        for line_no, text in _iter_lines(repo_path, path):
            if _INDIRECT_CALL_RE.search(text):
                matched_term = next(
                    (term for term in pattern_pack.function_pointer_indirect_terms if term in text),
                    "indirect_call",
                )
                candidates.append(
                    EntityCandidate(
                        slot=slot,
                        entity_type="function_pointer_call",
                        source="source_scan",
                        path=path,
                        start_line=line_no,
                        end_line=line_no,
                        focus_line=line_no,
                        score=0.48,
                        confidence=0.48,
                        reasons=["indirect_call_pattern"],
                        symbol="",
                        kind="function_pointer_call",
                        payload={
                            "relation_kind": "function_pointer_call",
                            "context": text.strip(),
                            "unknown_reason": "unresolved_function_pointer_target",
                            "pattern_pack": pattern_pack.name,
                            "matched_rule": matched_term,
                            "path_score_components": {
                                "base_relation_weight": pattern_pack.path_weights.get(
                                    "function_pointer_call", 0.38
                                )
                            },
                        },
                    )
                )
            match = _FP_ASSIGN_RE.search(text)
            if match:
                target = match.group("target")
                if target in needle_symbols:
                    assignment_rule = next(
                        (
                            term
                            for term in pattern_pack.function_pointer_assignment_terms
                            if term and term in text
                        ),
                        "&assign",
                    )
                    candidates.append(
                        EntityCandidate(
                            slot=slot,
                            entity_type="function_pointer_assignment",
                            source="source_scan",
                            path=path,
                            start_line=line_no,
                            end_line=line_no,
                            focus_line=line_no,
                            score=0.54,
                            confidence=0.54,
                            reasons=["function_pointer_assignment"],
                            symbol=target,
                            kind="function_pointer_assignment",
                            payload={
                                "relation_kind": "function_pointer_assignment",
                                "context": text.strip(),
                                "pattern_pack": pattern_pack.name,
                                "matched_rule": assignment_rule,
                                "path_score_components": {
                                    "base_relation_weight": pattern_pack.path_weights.get(
                                        "function_pointer_assignment", 0.44
                                    )
                                },
                            },
                        )
                    )
            if len(candidates) >= limit:
                return _dedupe(candidates)[:limit]
    return _dedupe(candidates)[:limit]


def _iter_lines(repo_path: Path, path: str) -> list[tuple[int, str]]:
    file_path = repo_path / Path(path)
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    return [(index + 1, line) for index, line in enumerate(lines)]


def _read_excerpt(repo_path: Path, path: str, line: int, radius: int = 2) -> str:
    file_path = repo_path / Path(path)
    if not file_path.exists():
        return ""
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    start = max(line - radius, 1)
    end = min(line + radius, len(lines))
    return "\n".join(lines[start - 1 : end])


def _dedupe(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    best: dict[tuple[str, int, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.path, candidate.start_line, candidate.entity_type)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: item.score, reverse=True)
