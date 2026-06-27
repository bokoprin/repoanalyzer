from __future__ import annotations

from repoanalyzer.core.models import CodeFact
from .symbols import extract_references_and_calls


def extract_references(path: str, text: str) -> list[CodeFact]:
    return [fact for fact in extract_references_and_calls(path, text) if fact.fact_type == "reference"]
