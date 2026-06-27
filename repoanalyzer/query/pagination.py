from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Generic, Iterable, TypeVar, Any

T = TypeVar("T")
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
    next_offset: int | None = None
    result_cap: int = MAX_PAGE_LIMIT
    warnings: list[str] = field(default_factory=list)

    @property
    def has_more(self) -> bool:
        return self.next_offset is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() if hasattr(item, "to_dict") else item for item in self.items],
            "page": {
                "total": self.total,
                "limit": self.limit,
                "offset": self.offset,
                "next_offset": self.next_offset,
                "has_more": self.has_more,
                "result_cap": self.result_cap,
                "warnings": list(self.warnings),
            },
        }


def normalize_page_params(limit: int | None = None, offset: int = 0, *, max_limit: int = MAX_PAGE_LIMIT) -> tuple[int, int, list[str]]:
    warnings: list[str] = []
    if offset < 0:
        raise ValueError("offset must be non-negative")
    requested = DEFAULT_PAGE_LIMIT if limit is None else limit
    if requested < 0:
        raise ValueError("limit must be non-negative")
    if requested > max_limit:
        warnings.append(f"Requested limit {requested} exceeds max_limit {max_limit}; capped to {max_limit}.")
        requested = max_limit
    return requested, offset, warnings


def paginate_items(items: Iterable[T], *, limit: int | None = None, offset: int = 0, max_limit: int = MAX_PAGE_LIMIT) -> Page[T]:
    normalized_limit, normalized_offset, warnings = normalize_page_params(limit, offset, max_limit=max_limit)
    materialized = list(items)
    total = len(materialized)
    page_items = materialized[normalized_offset: normalized_offset + normalized_limit]
    next_offset = normalized_offset + normalized_limit if normalized_offset + normalized_limit < total else None
    if total > normalized_limit:
        warnings.append("Result set is larger than this page; use next_offset to continue.")
    return Page(
        items=page_items,
        total=total,
        limit=normalized_limit,
        offset=normalized_offset,
        next_offset=next_offset,
        result_cap=max_limit,
        warnings=warnings,
    )


def page_from_query(query: Callable[..., list[T]], *args: Any, limit: int | None = None, offset: int = 0, max_limit: int = MAX_PAGE_LIMIT, **kwargs: Any) -> Page[T]:
    # Query helpers return fully filtered results when limit/offset are omitted;
    # pagination is then applied after semantic name matching so pages are stable.
    return paginate_items(query(*args, **kwargs), limit=limit, offset=offset, max_limit=max_limit)
