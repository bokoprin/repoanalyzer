from __future__ import annotations

from repoanalyzer.core.models import CodeFact, UnknownFact


def assess_answerability(facts: list[CodeFact], unknowns: list[UnknownFact]) -> str:
    if facts and not unknowns:
        return "answerable"
    if facts:
        return "partial"
    return "insufficient_evidence"
