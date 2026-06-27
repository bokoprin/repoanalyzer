from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.models import CodeFact
from ._store import open_store
from ._active import active_fact_where
from ._semantic import call_endpoint_matches


def find_callers(repo: str | Path, symbol: str, *, limit: int | None = None, offset: int = 0) -> list[CodeFact]:
    store = open_store(repo)
    facts = store.query_facts(active_fact_where("fact_type='call'"))
    matched = [fact for fact in facts if call_endpoint_matches(fact, symbol, "callee")]
    return _slice(matched, limit=limit, offset=offset)


def _slice(facts: list[CodeFact], *, limit: int | None, offset: int) -> list[CodeFact]:
    if offset < 0:
        raise ValueError("offset must be non-negative")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    if limit is None:
        return facts[offset:]
    return facts[offset: offset + limit]
