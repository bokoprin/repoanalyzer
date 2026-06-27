from __future__ import annotations

from pathlib import Path

from repoanalyzer.v2.core.models import EntityCandidate, EvidencePlan
from repoanalyzer.v2.index.reader import V2IndexReader
from repoanalyzer.v2.lang_cpp.call_relations import (
    find_callback_candidates,
    find_function_pointer_candidates,
    find_override_candidates,
)
from repoanalyzer.v2.lang_cpp.execution_context import find_execution_context_candidates
from repoanalyzer.v2.lang_cpp.pattern_loader import PatternPack
from repoanalyzer.v2.lang_cpp.utils import is_cpp_path, read_excerpt


class CppFlowExplorer:
    def __init__(
        self,
        reader: V2IndexReader,
        repo_path: Path,
        effect_terms: tuple[str, ...],
        pattern_pack: PatternPack,
    ) -> None:
        self.reader = reader
        self.repo_path = repo_path
        self.effect_terms = tuple(item.lower() for item in effect_terms)
        self.pattern_pack = pattern_pack

    def retrieve(self, plan: EvidencePlan) -> dict[str, list[EntityCandidate]]:
        entry: list[EntityCandidate] = []
        path: list[EntityCandidate] = []
        effect: list[EntityCandidate] = []
        gaps: list[EntityCandidate] = []
        discovered_symbols: list[str] = []
        for anchor in plan.anchors:
            definitions = self.reader.find_symbol_definitions(anchor, limit=10)
            for row in definitions:
                file_path = str(row["path"]).replace("\\", "/")
                if not is_cpp_path(file_path):
                    continue
                name = str(row["name"])
                discovered_symbols.append(name)
                entry.append(
                    EntityCandidate(
                        slot="entry",
                        entity_type="symbol_definition",
                        source="symbols",
                        path=file_path,
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        focus_line=int(row["start_line"]),
                        score=0.86 if name == anchor or anchor.endswith(name) else 0.7,
                        confidence=0.86,
                        reasons=["flow_entry_definition"],
                        symbol=name,
                        kind=str(row["kind"]),
                        payload={
                            "call_path": [name],
                            "relation_kind": "entry_definition",
                            "pattern_pack": self.pattern_pack.name,
                            "path_score_components": {"base_relation_weight": 0.86},
                            "edge_reasons": ["entry_definition"],
                        },
                    )
                )
                callees = self.reader.find_callees(name, limit=8)
                for callee in callees:
                    cpath = str(callee["path"]).replace("\\", "/")
                    if not is_cpp_path(cpath):
                        continue
                    caller = str(callee["caller"])
                    target = str(callee["callee"])
                    line = int(callee["line"])
                    score = 0.68 if caller == name else 0.58
                    path.append(
                        EntityCandidate(
                            slot="path",
                            entity_type="direct_call",
                            source="call_edges",
                            path=cpath,
                            start_line=line,
                            end_line=line,
                            focus_line=line,
                            score=score,
                            confidence=min(score, 1.0),
                            reasons=["call_edge_path"],
                            symbol=target,
                            kind=str(callee.get("kind") or "call"),
                            payload={
                                "call_path": [caller, target],
                                "relation_kind": "direct_call",
                                "pattern_pack": self.pattern_pack.name,
                                "matched_rule": "call_edge",
                                "path_score_components": {
                                    "base_relation_weight": self.pattern_pack.path_weights.get(
                                        "direct_call", score
                                    ),
                                    "directness_bonus": 0.1,
                                    "same_path_continuity_bonus": 0.06,
                                },
                                "edge_reasons": ["direct_call", "call_edge_path"],
                            },
                        )
                    )
                    excerpt = read_excerpt(self.repo_path, cpath, line, radius=2).lower()
                    if any(term in target.lower() or term in excerpt for term in self.effect_terms):
                        effect.append(
                            EntityCandidate(
                                slot="effect",
                                entity_type="call_edge",
                                source="call_edges",
                                path=cpath,
                                start_line=line,
                                end_line=line,
                                focus_line=line,
                                score=0.72,
                                confidence=0.72,
                                reasons=["effect_term_match"],
                                symbol=target,
                                kind=str(callee.get("kind") or "call"),
                                payload={
                                    "call_path": [caller, target],
                                    "context": excerpt,
                                    "relation_kind": "direct_call",
                                    "pattern_pack": self.pattern_pack.name,
                                    "path_score_components": {
                                        "base_relation_weight": self.pattern_pack.path_weights.get(
                                            "direct_call", 0.72
                                        )
                                    },
                                    "edge_reasons": ["effect_term_match"],
                                },
                            )
                        )
                    if any(
                        token in excerpt
                        for token in ("callback", "function pointer", "queue", "event", "dispatch")
                    ):
                        unknown_reason = _classify_gap_reason(excerpt)
                        gaps.append(
                            EntityCandidate(
                                slot="unknown_gap",
                                entity_type="flow_gap",
                                source="call_edges",
                                path=cpath,
                                start_line=line,
                                end_line=line,
                                focus_line=line,
                                score=0.45,
                                confidence=0.45,
                                reasons=["indirect_gap"],
                                symbol=target,
                                kind="gap",
                                payload={
                                    "context": excerpt,
                                    "unknown_reason": unknown_reason,
                                    "relation_kind": "flow_gap",
                                    "pattern_pack": self.pattern_pack.name,
                                    "edge_reasons": ["indirect_gap"],
                                },
                            )
                        )
        if not effect and path:
            effect = path[:2]
        if not gaps and path:
            gaps.append(
                EntityCandidate(
                    slot="unknown_gap",
                    entity_type="flow_gap",
                    source="call_edges",
                    path=path[0].path,
                    start_line=path[0].start_line,
                    end_line=path[0].end_line,
                    focus_line=path[0].focus_line,
                    score=0.3,
                    confidence=0.3,
                    reasons=["unknown_gap_fallback"],
                    symbol=path[0].symbol,
                    kind="gap",
                    payload={
                        "context": "indirect or unconfirmed downstream flow",
                        "unknown_reason": "handoff_beyond_known_relation",
                        "relation_kind": "flow_gap",
                        "pattern_pack": self.pattern_pack.name,
                        "edge_reasons": ["unknown_gap_fallback"],
                    },
                )
            )
        files = self.reader.store.list_files(limit=20000)
        symbols = [*plan.anchors, *discovered_symbols]
        path.extend(
            find_override_candidates(
                reader=self.reader,
                repo_path=self.repo_path,
                anchors=symbols,
                pattern_pack=self.pattern_pack,
                slot="path",
                limit=10,
            )
        )
        path.extend(
            find_callback_candidates(
                repo_path=self.repo_path,
                files=files,
                symbols=symbols,
                pattern_pack=self.pattern_pack,
                slot="path",
                limit=10,
            )
        )
        fp_candidates = find_function_pointer_candidates(
            repo_path=self.repo_path,
            files=files,
            symbols=symbols,
            pattern_pack=self.pattern_pack,
            slot="path",
            limit=10,
        )
        path.extend(fp_candidates)
        gaps.extend(
            [
                EntityCandidate(
                    slot="unknown_gap",
                    entity_type="flow_gap",
                    source=item.source,
                    path=item.path,
                    start_line=item.start_line,
                    end_line=item.end_line,
                    focus_line=item.focus_line,
                    score=max(0.25, item.score - 0.05),
                    confidence=max(0.25, item.confidence - 0.05),
                    reasons=["unresolved_function_pointer_target"],
                    symbol=item.symbol,
                    kind="gap",
                    payload={
                        "context": str(item.payload.get("context") or ""),
                        "unknown_reason": "unresolved_function_pointer_target",
                        "relation_kind": "flow_gap",
                        "pattern_pack": self.pattern_pack.name,
                        "edge_reasons": ["unresolved_function_pointer_target"],
                    },
                )
                for item in fp_candidates
                if item.entity_type == "function_pointer_call"
            ]
        )
        path.extend(
            find_execution_context_candidates(
                repo_path=self.repo_path,
                files=files,
                symbols=symbols,
                pattern_pack=self.pattern_pack,
                slot="path",
                limit=16,
            )
        )
        for item in path:
            relation_kind = str(item.payload.get("relation_kind") or item.entity_type)
            unknown_reason = str(item.payload.get("unknown_reason") or "")
            if relation_kind in {"dispatch_handoff", "state_transition"} and unknown_reason:
                gaps.append(
                    EntityCandidate(
                        slot="unknown_gap",
                        entity_type="flow_gap",
                        source=item.source,
                        path=item.path,
                        start_line=item.start_line,
                        end_line=item.end_line,
                        focus_line=item.focus_line,
                        score=max(0.25, item.score - 0.08),
                        confidence=max(0.25, item.confidence - 0.08),
                        reasons=[unknown_reason],
                        symbol=item.symbol,
                        kind="gap",
                        payload={
                            "context": str(item.payload.get("context") or ""),
                            "unknown_reason": unknown_reason,
                            "relation_kind": "flow_gap",
                            "pattern_pack": self.pattern_pack.name,
                            "edge_reasons": [unknown_reason],
                        },
                    )
                )
        return {
            "entry": _dedupe_and_rank(entry),
            "path": _dedupe_and_rank(path),
            "effect": _dedupe_and_rank(effect),
            "unknown_gap": _dedupe_and_rank(gaps),
        }


def _dedupe_and_rank(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    best: dict[tuple[str, int, int, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.path, candidate.start_line, candidate.end_line, candidate.slot)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: item.score, reverse=True)


def _classify_gap_reason(excerpt: str) -> str:
    lowered = excerpt.lower()
    if "function pointer" in lowered or "(*" in lowered:
        return "unresolved_function_pointer_target"
    if "callback" in lowered and "register" in lowered:
        return "callback_registered_but_target_unknown"
    if "dispatch" in lowered or "handler" in lowered:
        return "unresolved_dispatch_target"
    if "state" in lowered and ("switch" in lowered or "next" in lowered):
        return "unresolved_state_transition"
    return "handoff_beyond_known_relation"
