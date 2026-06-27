from __future__ import annotations

from collections import Counter

from repoanalyzer.v2.core.models import EntityCandidate, EvidencePlan
from repoanalyzer.v2.index.reader import V2IndexReader
from repoanalyzer.v2.lang_cpp.utils import is_cpp_path, normalize_setting_key, path_prior


class CppSettingRetriever:
    def __init__(
        self,
        reader: V2IndexReader,
        alias_patterns: tuple[str, ...],
        path_priors: dict[str, float],
        storage_terms: tuple[str, ...],
        read_terms: tuple[str, ...],
        apply_terms: tuple[str, ...],
    ) -> None:
        self.reader = reader
        self.alias_patterns = tuple(item.lower() for item in alias_patterns)
        self.storage_terms = tuple(item.lower() for item in storage_terms)
        self.read_terms = tuple(item.lower() for item in read_terms)
        self.apply_terms = tuple(item.lower() for item in apply_terms)
        self.promote = {
            key.lower(): float(value) for key, value in path_priors.items() if float(value) > 0
        }
        self.penalize = {
            key.lower(): float(value) for key, value in path_priors.items() if float(value) < 0
        }

    def retrieve(self, plan: EvidencePlan) -> dict[str, list[EntityCandidate]]:
        aliases = self._aliases(plan.anchors)
        storage = self._relation_candidates(
            aliases=aliases, relation_kind="storage", slot="storage"
        )
        read = self._relation_candidates(aliases=aliases, relation_kind="read", slot="read")
        apply = self._relation_candidates(aliases=aliases, relation_kind="apply", slot="apply")
        self._apply_same_object_bonus(storage, read, apply)
        return {
            "storage": _dedupe_and_rank(storage),
            "read": _dedupe_and_rank(read),
            "apply": _dedupe_and_rank(apply),
        }

    def _relation_candidates(
        self, *, aliases: list[str], relation_kind: str, slot: str
    ) -> list[EntityCandidate]:
        candidates: list[EntityCandidate] = []
        relation_rows = self.reader.find_setting_relations(
            aliases, relation_kind=relation_kind, limit=40
        )
        access_kinds = {
            "storage": ("declaration",),
            "read": ("read", "return"),
            "apply": ("apply", "write", "pass"),
        }[relation_kind]
        access_rows = self.reader.find_field_accesses(aliases, access_kinds=access_kinds, limit=40)
        for row in relation_rows:
            path = str(row["path"]).replace("\\", "/")
            if not is_cpp_path(path):
                continue
            object_key = normalize_setting_key(
                str(row.get("config_key_or_type") or ""),
                str(row.get("symbol_name") or ""),
            )
            score = 0.62 + float(row.get("confidence") or 0.0) * 0.22
            score += path_prior(path, promote=self.promote, penalize=self.penalize)
            score += self._anchor_bonus(str(row.get("config_key_or_type") or ""), aliases)
            candidates.append(
                EntityCandidate(
                    slot=slot,
                    entity_type="config_relation",
                    source="v2_config_relations",
                    path=path,
                    start_line=int(row["line"]),
                    end_line=int(row["line"]),
                    focus_line=int(row["line"]),
                    score=score,
                    confidence=min(max(score, 0.0), 1.0),
                    reasons=[f"{relation_kind}_relation", "config_relation"],
                    symbol=str(row.get("symbol_name") or ""),
                    kind=relation_kind,
                    payload={
                        "context": str(row.get("context") or ""),
                        "normalized_key": object_key,
                        "config_key_or_type": str(row.get("config_key_or_type") or ""),
                    },
                )
            )
        for row in access_rows:
            path = str(row["path"]).replace("\\", "/")
            if not is_cpp_path(path):
                continue
            field_name = str(row.get("field_name") or "")
            owner_type = str(row.get("owner_type") or "")
            symbol_name = str(row.get("symbol_name") or "")
            object_key = normalize_setting_key(owner_type, field_name, symbol_name)
            score = 0.55
            score += self._anchor_bonus(field_name, aliases)
            score += self._anchor_bonus(owner_type, aliases)
            score += path_prior(path, promote=self.promote, penalize=self.penalize)
            if field_name.lower().startswith(("m_", "s_")):
                score += 0.08
            candidates.append(
                EntityCandidate(
                    slot=slot,
                    entity_type="field_access",
                    source="v2_field_accesses",
                    path=path,
                    start_line=int(row["line"]),
                    end_line=int(row["line"]),
                    focus_line=int(row["line"]),
                    score=score,
                    confidence=min(max(score, 0.0), 1.0),
                    reasons=[f"{relation_kind}_field_access", "field_access_match"],
                    symbol=symbol_name,
                    kind=str(row.get("access_kind") or relation_kind),
                    payload={
                        "context": str(row.get("context") or ""),
                        "field_name": field_name,
                        "owner_type": owner_type,
                        "normalized_key": object_key,
                    },
                )
            )
        return candidates

    def _aliases(self, anchors: list[str]) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            lowered = anchor.lower()
            parts = {
                lowered,
                lowered.replace("::", ""),
                lowered.replace("_", ""),
                lowered.split("::")[-1],
            }
            for part in parts:
                if not part or part in seen:
                    continue
                seen.add(part)
                values.append(part)
        for pattern in self.alias_patterns:
            if pattern not in seen:
                seen.add(pattern)
                values.append(pattern)
        for special in ("commonsetting", "searchoption", "m_ssearchoption", "m_scursearchoption"):
            if special not in seen:
                seen.add(special)
                values.append(special)
        return values[:18]

    def _anchor_bonus(self, value: str, aliases: list[str]) -> float:
        lowered = value.lower()
        compact = lowered.replace("_", "")
        bonus = 0.0
        for alias in aliases:
            if alias in lowered:
                bonus = max(bonus, 0.18)
            elif alias.replace("_", "") in compact:
                bonus = max(bonus, 0.12)
        return bonus

    def _apply_same_object_bonus(
        self,
        storage: list[EntityCandidate],
        read: list[EntityCandidate],
        apply: list[EntityCandidate],
    ) -> None:
        counts = Counter(
            candidate.payload.get("normalized_key", "")
            for candidate in [*storage, *read, *apply]
            if candidate.payload.get("normalized_key")
        )
        for candidate in [*storage, *read, *apply]:
            key = str(candidate.payload.get("normalized_key") or "")
            if not key:
                continue
            count = counts.get(key, 0)
            if count >= 2:
                candidate.score += 0.12
                candidate.confidence = min(1.0, candidate.confidence + 0.08)
                candidate.reasons.append("same_object_bonus")


def _dedupe_and_rank(candidates: list[EntityCandidate]) -> list[EntityCandidate]:
    best: dict[tuple[str, int, int, str], EntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.path, candidate.start_line, candidate.end_line, candidate.slot)
        current = best.get(key)
        if current is None or candidate.score > current.score:
            best[key] = candidate
    return sorted(best.values(), key=lambda item: item.score, reverse=True)
