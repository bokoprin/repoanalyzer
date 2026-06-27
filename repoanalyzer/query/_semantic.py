from __future__ import annotations

from repoanalyzer.core.models import CodeFact


def name_matches(fact_name: str | None, query: str, *, qualified: str | None = None, subject: str | None = None) -> bool:
    if not query:
        return False
    values = [v for v in [fact_name, qualified, subject] if v]
    for value in values:
        if value == query:
            return True
        if value.endswith("::" + query):
            return True
        if "(" in value and value.split("(", 1)[0] == query:
            return True
        if "(" in value and value.split("(", 1)[0].endswith("::" + query):
            return True
    return False


def call_endpoint_matches(fact: CodeFact, query: str, endpoint: str) -> bool:
    if endpoint == "callee":
        values = [fact.callee, fact.payload.get("callee_qualified_name"), fact.object]
        values.extend(fact.payload.get("candidate_qualified_names") or [])
    else:
        values = [fact.caller, fact.payload.get("caller_qualified_name"), fact.subject]
    return any(name_matches(str(v) if v is not None else None, query) for v in values)
