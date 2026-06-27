from __future__ import annotations

from repoanalyzer.v2.core.models import EntityCandidate, EvidencePlan
from repoanalyzer.v2.index.reader import V2IndexReader
from repoanalyzer.v2.lang_cpp.call_relations import (
    find_callback_candidates,
    find_function_pointer_candidates,
    find_override_candidates,
)
from repoanalyzer.v2.lang_cpp.pattern_loader import PatternPack
from repoanalyzer.v2.lang_cpp.utils import is_cpp_path, is_noisy_cpp_path


class CppSymbolRetriever:
    _META_ANCHORS = {
        "lookup_symbols",
        "lookupsymbol",
        "symbol",
        "symbols",
    }
    def __init__(
        self,
        reader: V2IndexReader,
        repo_path,
        pattern_pack: PatternPack,
        exclusion_paths: tuple[str, ...],
        exclusion_patterns: tuple[str, ...],
    ) -> None:
        self.reader = reader
        self.repo_path = repo_path
        self.pattern_pack = pattern_pack
        self.exclusion_paths = tuple(item.lower() for item in exclusion_paths)
        self.exclusion_patterns = tuple(item.lower() for item in exclusion_patterns)

    def retrieve(self, plan: EvidencePlan) -> dict[str, list[EntityCandidate]]:
        slots = {"definition": [], "support": [], "usage": []}
        normalized_anchors = [anchor.lower() for anchor in plan.anchors if anchor.strip()]
        for anchor in plan.anchors:
            definition_rows = self.reader.find_symbol_definitions(anchor, limit=24)
            for row in definition_rows:
                path = str(row["path"]).replace("\\", "/")
                if not is_cpp_path(path):
                    continue
                name = str(row["name"])
                qualified_name = str(row.get("qualified_name") or "")
                score = self._definition_score(
                    anchor=anchor,
                    name=name,
                    qualified_name=qualified_name,
                    path=path,
                    kind=str(row["kind"]),
                )
                if score <= 0.0:
                    continue
                slots["definition"].append(
                    EntityCandidate(
                        slot="definition",
                        entity_type="symbol_definition",
                        source="symbols",
                        path=path,
                        start_line=int(row["start_line"]),
                        end_line=int(row["end_line"]),
                        focus_line=int(row["start_line"]),
                        score=score,
                        confidence=min(max(score, 0.0), 1.0),
                        reasons=self._definition_reasons(anchor=anchor, name=name, path=path),
                        symbol=name,
                        kind=str(row["kind"]),
                        payload={
                            "signature": str(row["signature"]),
                            "match_anchor": anchor,
                            "evidence_role": "exact_definition",
                        },
                    )
                )
                if path.endswith((".h", ".hpp", ".hh", ".hxx")):
                    slots["support"].append(
                        EntityCandidate(
                            slot="support",
                            entity_type="symbol_declaration",
                            source="symbols",
                            path=path,
                            start_line=int(row["start_line"]),
                            end_line=int(row["end_line"]),
                            focus_line=int(row["start_line"]),
                            score=max(0.45, score - 0.22),
                            confidence=min(max(score - 0.18, 0.4), 0.9),
                            reasons=["declaration_support"],
                            symbol=name,
                            kind="declaration",
                            payload={
                                "signature": str(row["signature"]),
                                "match_anchor": anchor,
                                "relation_kind": "declaration_support",
                                "evidence_role": "declaration",
                            },
                        )
                    )
            slots["support"].extend(
                self._header_impl_pair_support(anchor=anchor, definition_rows=definition_rows)
            )
            for row in self.reader.find_symbol_aliases(anchor, limit=16):
                path = str(row["path"]).replace("\\", "/")
                if not is_cpp_path(path):
                    continue
                raw_name = str(row["raw_name"])
                score = 0.64 if raw_name == anchor else 0.48
                if self._is_excluded(path=path, value=raw_name):
                    score -= 0.55
                if not self._is_symbol_anchor_relevant(raw_name, normalized_anchors):
                    score -= 0.2
                if score <= 0.0:
                    continue
                slots["support"].append(
                    EntityCandidate(
                        slot="support",
                        entity_type="symbol_alias",
                        source="symbol_aliases",
                        path=path,
                        start_line=int(row["line"]),
                        end_line=int(row["line"]),
                        focus_line=int(row["line"]),
                        score=score,
                        confidence=min(score, 1.0),
                        reasons=["alias_match", "supporting_context"],
                        symbol=raw_name,
                        kind="alias",
                        payload={
                            "scope": str(row.get("scope") or ""),
                            "evidence_role": "supporting_context",
                        },
                    )
                )
            for row in self.reader.find_symbol_usages(anchor, limit=24):
                path = str(row["path"]).replace("\\", "/")
                if not is_cpp_path(path):
                    continue
                score = 0.54
                context = str(row.get("context", ""))
                short_anchor = anchor.split("::")[-1]
                if short_anchor and short_anchor in context:
                    score += 0.12
                if self._is_excluded(path=path, value=str(row.get("context", ""))):
                    score -= 0.35
                if score <= 0.0:
                    continue
                slots["usage"].append(
                    EntityCandidate(
                        slot="usage",
                        entity_type="symbol_usage",
                        source="symbol_refs",
                        path=path,
                        start_line=int(row["line"]),
                        end_line=int(row["line"]),
                        focus_line=int(row["line"]),
                        score=score,
                        confidence=min(score, 1.0),
                        reasons=["usage_reference"],
                        symbol=anchor,
                        kind=str(row.get("kind", "reference")),
                        payload={
                            "context": context,
                            "evidence_role": "reference_or_usage",
                        },
                    )
                )
        files = self.reader.store.list_files(limit=20000)
        slots["support"].extend(
            find_override_candidates(
                reader=self.reader,
                repo_path=self.repo_path,
                anchors=plan.anchors,
                pattern_pack=self.pattern_pack,
                slot="support",
                limit=12,
            )
        )
        slots["support"].extend(
            find_callback_candidates(
                repo_path=self.repo_path,
                files=files,
                symbols=plan.anchors,
                pattern_pack=self.pattern_pack,
                slot="support",
                limit=12,
            )
        )
        slots["usage"].extend(
            find_function_pointer_candidates(
                repo_path=self.repo_path,
                files=files,
                symbols=plan.anchors,
                pattern_pack=self.pattern_pack,
                slot="usage",
                limit=12,
            )
        )
        slots["support"] = [
            item
            for item in slots["support"]
            if self._is_relevant_support_candidate(item, normalized_anchors)
        ]
        slots["usage"] = [
            item
            for item in slots["usage"]
            if self._is_relevant_usage_candidate(item, normalized_anchors)
        ]
        return {key: _dedupe_and_rank(value) for key, value in slots.items()}

    def _definition_score(
        self,
        *,
        anchor: str,
        name: str,
        qualified_name: str,
        path: str,
        kind: str,
    ) -> float:
        score = 0.0
        if anchor == qualified_name:
            score += 1.0
        elif anchor == name:
            score += 0.95
        elif anchor.split("::")[-1] == name:
            score += 0.86
        elif anchor.lower() == name.lower():
            score += 0.82
        elif anchor.lower() in name.lower():
            score += 0.64
        if kind in {"function", "method", "class", "type", "struct"}:
            score += 0.08
        if path.endswith((".h", ".hpp", ".hh", ".hxx", ".c", ".cc", ".cpp", ".cxx")):
            score += 0.05
        if self._is_excluded(path=path, value=name):
            score -= 0.8
        if score < 0.68:
            return 0.0
        return score

    def _header_impl_pair_support(
        self,
        *,
        anchor: str,
        definition_rows: list[dict[str, object]],
    ) -> list[EntityCandidate]:
        by_name: dict[str, list[dict[str, object]]] = {}
        for row in definition_rows:
            name = str(row.get("name") or "")
            if not name:
                continue
            by_name.setdefault(name, []).append(row)
        out: list[EntityCandidate] = []
        for name, rows in by_name.items():
            has_header = any(
                str(item.get("path") or "").endswith((".h", ".hpp", ".hh", ".hxx"))
                for item in rows
            )
            has_impl = any(
                str(item.get("path") or "").endswith((".c", ".cc", ".cpp", ".cxx"))
                for item in rows
            )
            if not (has_header and has_impl):
                continue
            for row in rows:
                path = str(row.get("path") or "").replace("\\", "/")
                if self._is_excluded(path=path, value=name):
                    continue
                line = int(row.get("start_line") or 1)
                out.append(
                    EntityCandidate(
                        slot="support",
                        entity_type="symbol_pair_support",
                        source="symbols",
                        path=path,
                        start_line=line,
                        end_line=int(row.get("end_line") or line),
                        focus_line=line,
                        score=0.63 if anchor.split("::")[-1] == name else 0.56,
                        confidence=0.66,
                        reasons=["header_impl_pair"],
                        symbol=name,
                        kind="support_pair",
                        payload={
                            "relation_kind": "header_impl_pair",
                            "match_anchor": anchor,
                        },
                    )
                )
        return out[:16]

    def _definition_reasons(self, *, anchor: str, name: str, path: str) -> list[str]:
        reasons: list[str] = []
        if anchor == name:
            reasons.append("exact_symbol_match")
        elif anchor.split("::")[-1] == name:
            reasons.append("qualified_symbol_match")
        else:
            reasons.append("alias_or_partial_match")
        reasons.append("cpp_code_path")
        if self._is_excluded(path=path, value=name):
            reasons.append("suppressed_noise_path")
        return reasons

    def _is_symbol_anchor_relevant(self, value: str, anchors: list[str]) -> bool:
        lowered = value.lower()
        compact = lowered.replace("_", "").replace("::", "")
        for anchor in anchors:
            if anchor in lowered:
                return True
            if anchor.replace("_", "").replace("::", "") in compact:
                return True
            if anchor.split("::")[-1] == lowered:
                return True
        return False

    def _is_relevant_support_candidate(
        self, candidate: EntityCandidate, anchors: list[str]
    ) -> bool:
        if self._is_excluded(path=candidate.path, value=candidate.symbol):
            return False
        relation_kind = str(candidate.payload.get("relation_kind") or candidate.entity_type)
        if relation_kind in {"override_call", "callback_registration", "callback_invoke"}:
            if candidate.score < 0.5:
                return False
        if candidate.entity_type == "symbol_alias" and candidate.score < 0.52:
            return False
        joined = " ".join(
            [
                candidate.symbol.lower(),
                str(candidate.payload.get("context") or "").lower(),
                str(candidate.payload.get("scope") or "").lower(),
            ]
        )
        if self._is_meta_anchor_only(anchors):
            return True
        return self._is_symbol_anchor_relevant(joined, anchors)

    def _is_relevant_usage_candidate(
        self, candidate: EntityCandidate, anchors: list[str]
    ) -> bool:
        if self._is_excluded(path=candidate.path, value=candidate.symbol):
            return False
        context = str(candidate.payload.get("context") or "").lower()
        if candidate.entity_type == "function_pointer_call" and "(*" not in context:
            if candidate.score < 0.5:
                return False
        if self._is_meta_anchor_only(anchors):
            return True
        joined = " ".join([candidate.symbol.lower(), context])
        return self._is_symbol_anchor_relevant(joined, anchors)

    def _is_meta_anchor_only(self, anchors: list[str]) -> bool:
        normalized = [anchor.strip().lower() for anchor in anchors if anchor.strip()]
        if not normalized:
            return False
        return all(anchor in self._META_ANCHORS for anchor in normalized)

    def _is_excluded(self, *, path: str, value: str) -> bool:
        lowered_path = path.lower()
        lowered_value = value.lower()
        return (
            is_noisy_cpp_path(path)
            or any(token in lowered_path for token in self.exclusion_paths)
            or any(token in lowered_value for token in self.exclusion_patterns)
        )


def _dedupe_and_rank(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    best: dict[tuple[str, int, int, str, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.path,
            candidate.start_line,
            candidate.end_line,
            candidate.slot,
            candidate.entity_type,
        )
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: item.score, reverse=True)
