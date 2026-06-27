from __future__ import annotations

from pathlib import Path

from repoanalyzer.v2.core.models import EntityCandidate
from repoanalyzer.v2.lang_cpp.pattern_loader import PatternPack
from repoanalyzer.v2.lang_cpp.utils import is_cpp_path, is_noisy_cpp_path


def find_execution_context_candidates(
    *,
    repo_path: Path,
    files: list[str],
    symbols: list[str],
    pattern_pack: PatternPack,
    slot: str = "path",
    limit: int = 24,
) -> list[EntityCandidate]:
    candidates: list[EntityCandidate] = []
    needle_symbols = {symbol.split("::")[-1] for symbol in symbols if symbol}
    all_terms = (
        *pattern_pack.task_terms,
        *pattern_pack.queue_terms,
        *pattern_pack.event_terms,
        *pattern_pack.timer_terms,
        *pattern_pack.isr_terms,
        *pattern_pack.state_terms,
        "dispatch",
        "handler",
        "switch",
    )
    for path in files:
        if not is_cpp_path(path) or is_noisy_cpp_path(path):
            continue
        file_path = repo_path / Path(path)
        if not file_path.exists():
            continue
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        file_contains_symbol = not needle_symbols or any(
            symbol in line for symbol in needle_symbols for line in lines
        )
        if not file_contains_symbol:
            continue
        for index, text in enumerate(lines, start=1):
            lowered = text.lower()
            if needle_symbols and not any(symbol in text for symbol in needle_symbols):
                if not any(term in lowered for term in all_terms):
                    continue
            relation_kind = ""
            score = 0.0
            matched_rule = ""
            if any(term in lowered for term in pattern_pack.task_terms):
                relation_kind = "task_handoff"
                score = pattern_pack.path_weights.get("task_handoff", 0.55)
                matched_rule = next(
                    (term for term in pattern_pack.task_terms if term in lowered), ""
                )
            elif any(term in lowered for term in pattern_pack.queue_terms):
                relation_kind = "queue_handoff"
                score = pattern_pack.path_weights.get("queue_handoff", 0.52)
                matched_rule = next(
                    (term for term in pattern_pack.queue_terms if term in lowered), ""
                )
            elif any(term in lowered for term in pattern_pack.event_terms):
                relation_kind = "event_handoff"
                score = pattern_pack.path_weights.get("event_handoff", 0.5)
                matched_rule = next(
                    (term for term in pattern_pack.event_terms if term in lowered), ""
                )
            elif any(term in lowered for term in pattern_pack.timer_terms):
                relation_kind = "timer_handoff"
                score = pattern_pack.path_weights.get("timer_handoff", 0.47)
                matched_rule = next(
                    (term for term in pattern_pack.timer_terms if term in lowered), ""
                )
            elif any(term in lowered for term in pattern_pack.isr_terms):
                relation_kind = "isr_handoff"
                score = pattern_pack.path_weights.get("isr_handoff", 0.47)
                matched_rule = next(
                    (term for term in pattern_pack.isr_terms if term in lowered), ""
                )
            elif any(term in lowered for term in pattern_pack.state_terms):
                relation_kind = "state_transition"
                score = pattern_pack.path_weights.get("state_transition", 0.49)
                matched_rule = next(
                    (term for term in pattern_pack.state_terms if term in lowered), ""
                )
            elif "dispatch" in lowered and ("handler" in lowered or "table" in lowered):
                relation_kind = "dispatch_handoff"
                score = pattern_pack.path_weights.get("dispatch_handoff", 0.46)
                matched_rule = "dispatch_handler_pattern"
            elif "dispatch_table" in lowered or ("handler_map" in lowered):
                relation_kind = "dispatch_handoff"
                score = pattern_pack.path_weights.get("dispatch_handoff", 0.5)
                matched_rule = "dispatch_table_pattern"
            elif "switch" in lowered and any(
                token in lowered for token in ("state", "event", "msg")
            ):
                relation_kind = "state_transition"
                score = pattern_pack.path_weights.get("state_transition", 0.49)
                matched_rule = "switch_state_pattern"
            elif "next_state" in lowered or "set_state(" in lowered:
                relation_kind = "state_transition"
                score = pattern_pack.path_weights.get("state_transition", 0.53)
                matched_rule = "state_transition_helper"
            if not relation_kind:
                continue
            unknown_reason = ""
            if relation_kind == "dispatch_handoff":
                unknown_reason = "unresolved_dispatch_target"
            elif relation_kind == "state_transition" and "next" in lowered and "state" in lowered:
                unknown_reason = "unresolved_state_transition"
            candidates.append(
                EntityCandidate(
                    slot=slot,
                    entity_type=relation_kind,
                    source="source_scan",
                    path=path,
                    start_line=index,
                    end_line=index,
                    focus_line=index,
                    score=score,
                    confidence=score,
                    reasons=[relation_kind],
                    symbol=next((symbol for symbol in needle_symbols if symbol in text), ""),
                    kind=relation_kind,
                    payload={
                        "relation_kind": relation_kind,
                        "context": text.strip(),
                        "pattern_pack": pattern_pack.name,
                        "matched_rule": matched_rule or relation_kind,
                        "unknown_reason": unknown_reason,
                        "path_score_components": {"base_relation_weight": score},
                    },
                )
            )
            if len(candidates) >= limit:
                return _dedupe(candidates)[:limit]
    return _dedupe(candidates)[:limit]


def _dedupe(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    best: dict[tuple[str, int, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.path, candidate.start_line, candidate.entity_type)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: item.score, reverse=True)
