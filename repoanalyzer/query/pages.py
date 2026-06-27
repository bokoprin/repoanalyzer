from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.models import CodeFact
from .callers import find_callers
from .callees import find_callees
from .definitions import find_definitions
from .references import find_references
from .pagination import Page, page_from_query


def find_definitions_page(repo: str | Path, symbol: str, *, limit: int | None = None, offset: int = 0) -> Page[CodeFact]:
    return page_from_query(find_definitions, repo, symbol, limit=limit, offset=offset)


def find_references_page(repo: str | Path, symbol: str, *, limit: int | None = None, offset: int = 0) -> Page[CodeFact]:
    return page_from_query(find_references, repo, symbol, limit=limit, offset=offset)


def find_callers_page(repo: str | Path, symbol: str, *, limit: int | None = None, offset: int = 0) -> Page[CodeFact]:
    return page_from_query(find_callers, repo, symbol, limit=limit, offset=offset)


def find_callees_page(repo: str | Path, symbol: str, *, limit: int | None = None, offset: int = 0) -> Page[CodeFact]:
    return page_from_query(find_callees, repo, symbol, limit=limit, offset=offset)
