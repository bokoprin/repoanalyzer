ACTIVE_FACT_PREDICATE = "COALESCE(json_extract(payload_json, '$.build_status'), 'active') != 'inactive'"


def active_fact_where(where: str) -> str:
    return f"({where}) AND {ACTIVE_FACT_PREDICATE}"
