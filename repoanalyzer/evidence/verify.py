from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Iterable

from repoanalyzer.core.models import CodeFact, UnknownFact
from repoanalyzer.evidence.claims import Claim, ClaimEvidenceBundle, ClaimVerdict
from repoanalyzer.evidence.claim_reasoning import constraints_for_facts, fact_build_status, has_conditional_evidence, unknowns_for_facts, verdict_for_positive_support
from repoanalyzer.evidence.quality_gate import apply_quality_gate_to_verdict
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._semantic import call_endpoint_matches, name_matches
from repoanalyzer.query._store import open_store
from repoanalyzer.query.definitions import find_definitions
from repoanalyzer.store.status import repo_index_status


def verify_claim(repo: str | Path, claim: Claim | dict) -> ClaimVerdict:
    normalized = claim if isinstance(claim, Claim) else Claim.from_dict(claim)
    verdict = _verify_claim_without_freshness(repo, normalized)
    verdict = _apply_index_freshness(repo, verdict)
    return apply_quality_gate_to_verdict(repo, verdict)


def _verify_claim_without_freshness(repo: str | Path, normalized: Claim) -> ClaimVerdict:
    if normalized.payload.get("polarity") == "negative":
        return _verify_negative_claim(repo, normalized)
    if normalized.claim_type == "definition_exists":
        return _verify_definition_exists(repo, normalized)
    if normalized.claim_type == "calls":
        return _verify_calls(repo, normalized)
    if normalized.claim_type == "reaches":
        return _verify_reaches(repo, normalized)
    if normalized.claim_type == "includes":
        return _verify_includes(repo, normalized)
    if normalized.claim_type == "build_active":
        return _verify_build_active(repo, normalized)
    if normalized.claim_type == "build_config":
        return _verify_build_config(repo, normalized)
    if normalized.claim_type == "allocation_profile":
        return _verify_allocation_profile(repo, normalized)
    if normalized.claim_type == "callback_registers":
        return _verify_callback_registers(repo, normalized)
    if normalized.claim_type == "stores_callback":
        return _verify_callback_relation(repo, normalized, predicate="stores_callback")
    if normalized.claim_type == "invokes_callback":
        return _verify_callback_relation(repo, normalized, predicate="invokes_callback")
    if normalized.claim_type == "callback_dataflow":
        return _verify_callback_dataflow(repo, normalized)
    if normalized.claim_type == "task_entry_dataflow":
        return _verify_task_entry_dataflow(repo, normalized)
    if normalized.claim_type == "scheduler_semantic":
        return _verify_scheduler_semantic(repo, normalized)
    if normalized.claim_type == "task_state_transition":
        return _verify_task_state_transition(repo, normalized)
    if normalized.claim_type == "kernel_object_semantic":
        return _verify_kernel_object_semantic(repo, normalized)
    if normalized.claim_type == "hook_assert_trace_semantic":
        return _verify_hook_assert_trace_semantic(repo, normalized)
    if normalized.claim_type == "heap_allocator_semantic":
        return _verify_heap_allocator_semantic(repo, normalized)
    if normalized.claim_type == "port_advanced_semantic":
        return _verify_port_advanced_semantic(repo, normalized)
    if normalized.claim_type == "port_boundary":
        return _verify_port_boundary(repo, normalized)
    if normalized.claim_type == "execution_context":
        return _verify_execution_context(repo, normalized)
    if normalized.claim_type == "target_profile":
        return _verify_target_profile(repo, normalized)
    if normalized.claim_type == "file_active":
        return _verify_file_active(repo, normalized)
    if normalized.claim_type == "usb_descriptor_semantic":
        return _verify_usb_descriptor_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_callback_semantic":
        return _verify_tinyusb_callback_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_driver_dispatch_semantic":
        return _verify_tinyusb_driver_dispatch_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_device_runtime_semantic":
        return _verify_tinyusb_device_runtime_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_host_runtime_semantic":
        return _verify_tinyusb_host_runtime_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_class_protocol_semantic":
        return _verify_tinyusb_class_protocol_semantic(repo, normalized)
    if normalized.claim_type == "tinyusb_typec_pd_semantic":
        return _verify_tinyusb_typec_pd_semantic(repo, normalized)
    return _unknown(normalized, "unsupported_claim_type", f"Unsupported claim type: {normalized.claim_type}")


def _apply_index_freshness(repo: str | Path, verdict: ClaimVerdict) -> ClaimVerdict:
    try:
        status = repo_index_status(repo)
    except Exception:
        return verdict
    if status.clean:
        return verdict
    unknown = UnknownFact(
        "index_freshness",
        "The repository has changed since ingest; claim verification may be stale.",
        severity="high",
        affects=[verdict.claim.claim_type],
    )
    constraints = list(verdict.response_constraints)
    constraints.append("Re-run ingest before using this claim verdict for completeness, absence, or contradiction claims.")
    reason = verdict.reason_code
    new_verdict = verdict.verdict
    message = verdict.message + " Index freshness is dirty."
    if verdict.verdict == "contradicted":
        new_verdict = "unknown"
        reason = "index_not_fresh_for_contradiction"
    elif verdict.verdict == "supported":
        new_verdict = "conditional"
        reason = "supported_but_index_not_fresh"
    return ClaimVerdict(
        claim=verdict.claim,
        verdict=new_verdict,
        reason_code=reason,
        message=message,
        supporting_facts=verdict.supporting_facts,
        contradicting_facts=verdict.contradicting_facts,
        unknowns=list(verdict.unknowns) + [unknown],
        response_constraints=constraints,
    )


def verify_claims(repo: str | Path, claims: Iterable[Claim | dict]) -> ClaimEvidenceBundle:
    return ClaimEvidenceBundle([verify_claim(repo, claim) for claim in claims])


def _verify_negative_claim(repo: str | Path, claim: Claim) -> ClaimVerdict:
    positive_payload = {k: v for k, v in claim.payload.items() if k != "polarity"}
    positive = Claim(claim.claim_type, subject=claim.subject, object=claim.object, payload=positive_payload)
    positive_verdict = _verify_claim_without_freshness(repo, positive)
    if positive_verdict.verdict == "supported":
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="negated_claim_refuted_by_supported_evidence",
            message="The negative claim is refuted by supported positive evidence.",
            contradicting_facts=positive_verdict.supporting_facts,
            unknowns=positive_verdict.unknowns,
            response_constraints=["Do not state this negative claim; supported evidence exists for the positive form."] + list(positive_verdict.response_constraints),
        )
    if positive_verdict.verdict == "contradicted":
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="negated_claim_supported_by_contradiction_of_positive",
            message="The negative claim is supported because the positive form was contradicted by resolved evidence.",
            supporting_facts=positive_verdict.contradicting_facts,
            response_constraints=["This support is scoped to the same evidence limits as the contradicted positive claim."] + list(positive_verdict.response_constraints),
        )
    if positive_verdict.verdict == "conditional":
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="negated_claim_depends_on_conditional_positive_evidence",
            message="The negative claim cannot be stated unconditionally because the positive form has conditional evidence.",
            supporting_facts=positive_verdict.supporting_facts,
            unknowns=positive_verdict.unknowns,
            response_constraints=["Qualify the negative claim; positive evidence is conditional rather than absent."] + list(positive_verdict.response_constraints),
        )
    return ClaimVerdict(
        claim=claim,
        verdict="unknown",
        reason_code="negated_claim_positive_form_unknown",
        message="The negative claim cannot be verified because the positive form is unknown rather than contradicted.",
        supporting_facts=positive_verdict.supporting_facts,
        unknowns=positive_verdict.unknowns,
        response_constraints=["Do not treat lack of positive support as support for a negative claim unless the positive form is contradicted."],
    )


def _all_facts(repo: str | Path, where: str = "1=1", params: tuple = ()) -> list[CodeFact]:
    return open_store(repo).query_facts(where, params)


def _active_facts(repo: str | Path, where: str = "1=1") -> list[CodeFact]:
    return _all_facts(repo, active_fact_where(where))


def _unknown(claim: Claim, reason: str, message: str, facts: list[CodeFact] | None = None) -> ClaimVerdict:
    unknown = UnknownFact(reason, message)
    return ClaimVerdict(
        claim=claim,
        verdict="unknown",
        reason_code=reason,
        message=message,
        supporting_facts=facts or [],
        unknowns=[unknown],
        response_constraints=["Do not treat absence of current evidence as proof unless the claim verifier returned contradicted."],
    )


def _verdict_from_support(claim: Claim, facts: list[CodeFact], supported_reason: str, conditional_reason: str, message: str) -> ClaimVerdict:
    verdict, reason, unknowns, constraints = verdict_for_positive_support(facts, supported_reason=supported_reason, conditional_reason=conditional_reason)
    return ClaimVerdict(
        claim=claim,
        verdict=verdict,
        reason_code=reason,
        message=message,
        supporting_facts=facts,
        unknowns=unknowns,
        response_constraints=constraints,
    )


def _verify_definition_exists(repo: str | Path, claim: Claim) -> ClaimVerdict:
    symbol = claim.subject or claim.object
    if not symbol:
        return _unknown(claim, "claim_missing_symbol", "definition_exists requires subject or object.")
    facts = [
        fact for fact in _active_facts(repo, "fact_type='symbol' AND json_extract(payload_json, '$.declaration_or_definition')='definition'")
        if _fact_name_matches(fact, symbol)
    ]
    if facts:
        return _verdict_from_support(
            claim,
            facts,
            "definition_found",
            "definition_found_but_conditional",
            f"Definition evidence was found for {symbol}.",
        )
    inactive_or_conditional = [
        fact for fact in _all_facts(repo, "fact_type='symbol' AND json_extract(payload_json, '$.declaration_or_definition')='definition'")
        if _fact_name_matches(fact, symbol)
    ]
    if inactive_or_conditional and all(fact_build_status(fact) == "inactive" for fact in inactive_or_conditional):
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="definition_only_in_inactive_build_region",
            message=f"Only inactive definition evidence was found for {symbol}.",
            contradicting_facts=inactive_or_conditional,
            response_constraints=["The symbol appears only in inactive build regions in the current indexed build context."],
        )
    return _unknown(claim, "definition_not_found", f"No active definition evidence was found for {symbol}.")


def _call_matches(fact: CodeFact, subject: str, obj: str) -> bool:
    return call_endpoint_matches(fact, subject, "caller") and call_endpoint_matches(fact, obj, "callee")


def _calls_from(repo: str | Path, subject: str) -> list[CodeFact]:
    return [fact for fact in _active_facts(repo, "fact_type='call'") if call_endpoint_matches(fact, subject, "caller")]


def _verify_calls(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "calls requires subject and object.")
    calls = _active_facts(repo, "fact_type='call'")
    matched = [fact for fact in calls if _call_matches(fact, claim.subject, claim.object)]
    if matched:
        return _verdict_from_support(
            claim,
            matched,
            "call_edge_supported",
            "call_edge_conditional_or_candidate",
            f"Call evidence was found from {claim.subject} to {claim.object}.",
        )
    outgoing = [fact for fact in calls if call_endpoint_matches(fact, claim.subject, "caller")]
    uncertain_outgoing = [
        fact for fact in outgoing
        if fact.payload.get("resolution_status") in {"unresolved", "candidate_set", "ambiguous"}
        or fact.payload.get("unknown_type")
        or fact_build_status(fact) != "active"
    ]
    if outgoing and not uncertain_outgoing:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="resolved_outgoing_calls_do_not_include_target",
            message=f"Resolved outgoing call evidence for {claim.subject} did not include {claim.object}.",
            contradicting_facts=outgoing,
            response_constraints=["This contradiction is scoped to resolved direct call evidence in the current index."],
        )
    if outgoing:
        unknowns = unknowns_for_facts(outgoing) or [UnknownFact("call_target_not_resolved", "Outgoing calls exist, but unresolved/candidate edges prevent contradiction.")]
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="unresolved_or_candidate_outgoing_calls",
            message=f"No matching call edge was found, but outgoing evidence for {claim.subject} is incomplete or candidate-based.",
            supporting_facts=outgoing,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(outgoing),
        )
    return _unknown(claim, "caller_not_found_or_no_outgoing_calls", f"No outgoing call evidence was found for {claim.subject}.")


def _node_aliases(edge: CodeFact, endpoint: str) -> set[str]:
    if endpoint == "caller":
        values = [edge.caller, edge.subject, edge.payload.get("caller_qualified_name")]
    else:
        values = [edge.callee, edge.object, edge.payload.get("callee_qualified_name")]
        values.extend(edge.payload.get("candidate_qualified_names") or [])
        values.extend(edge.payload.get("global_candidate_qualified_names") or [])
    return {str(v) for v in values if isinstance(v, str) and v}


def _short_name(name: str) -> str:
    return name.split("::")[-1]


def _names_match(name: str, query: str) -> bool:
    return name == query or name.endswith("::" + query) or query.endswith("::" + name) or _short_name(name) == _short_name(query)


def _fact_name_values(fact: CodeFact) -> list[str]:
    values = [fact.symbol, fact.qualified_name, fact.subject, fact.object]
    for key in [
        "qualified_signature",
        "caller_qualified_name",
        "callee_qualified_name",
        "callback_qualified_name",
        "api_qualified_name",
    ]:
        value = fact.payload.get(key)
        if isinstance(value, str):
            values.append(value)
    namespace = fact.payload.get("namespace")
    qualified = fact.qualified_name or fact.subject
    if isinstance(namespace, str) and isinstance(qualified, str) and namespace and not qualified.startswith(namespace + "::"):
        values.append(namespace + "::" + qualified)
        if "(" in qualified:
            values.append(namespace + "::" + qualified.split("(", 1)[0])
    return [str(v) for v in values if isinstance(v, str) and v]


def _fact_name_matches(fact: CodeFact, query: str) -> bool:
    return any(_names_match(value.split("(", 1)[0], query.split("(", 1)[0]) for value in _fact_name_values(fact))


def _find_route(repo: str | Path, start: str, goal: str) -> tuple[list[str], list[CodeFact]] | None:
    edges = _active_facts(repo, "fact_type='call'")
    graph: dict[str, list[tuple[str, CodeFact]]] = defaultdict(list)
    known_names: set[str] = set()
    for edge in edges:
        callers = _node_aliases(edge, "caller")
        callees = _node_aliases(edge, "callee")
        known_names.update(callers)
        known_names.update(callees)
        for caller in callers:
            for callee in callees:
                graph[caller].append((callee, edge))
    starts = {name for name in known_names if _names_match(name, start)} or {start}
    goals = {name for name in known_names if _names_match(name, goal)} or {goal}
    queue: deque[tuple[list[str], list[CodeFact]]] = deque((([s], [])) for s in sorted(starts))
    seen = set(starts)
    while queue:
        route, facts = queue.popleft()
        if route[-1] in goals:
            return route, facts
        for nxt, edge in graph.get(route[-1], []):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append((route + [nxt], facts + [edge]))
    return None


def _verify_reaches(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "reaches requires subject and object.")
    found = _find_route(repo, claim.subject, claim.object)
    if found:
        route, edge_facts = found
        display_route = list(route)
        if display_route:
            display_route[0] = claim.subject
            display_route[-1] = claim.object
        path_fact = CodeFact(
            fact_type="call_path",
            path=edge_facts[0].path if edge_facts else "",
            start_line=edge_facts[0].start_line if edge_facts else 1,
            end_line=edge_facts[-1].end_line if edge_facts else 1,
            subject=claim.subject,
            predicate="reaches",
            object=claim.object,
            route=display_route,
            confidence="medium",
            source="claim_verifier_call_graph_bfs",
            payload={
                "edge_statuses": [edge.payload.get("resolution_status", "unknown") for edge in edge_facts],
                "ambiguous_edges": [f"{edge.caller}->{edge.callee}" for edge in edge_facts if edge.payload.get("resolution_status") in {"candidate_set", "ambiguous", "unresolved"}],
            },
        )
        facts = edge_facts + [path_fact]
        return _verdict_from_support(
            claim,
            facts,
            "call_path_supported",
            "call_path_conditional_or_candidate",
            f"A call path was found from {claim.subject} to {claim.object}.",
        )
    return _unknown(claim, "call_path_not_found", f"No call path evidence was found from {claim.subject} to {claim.object}.")


def _verify_includes(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "includes requires subject and object.")
    includes = _active_facts(repo, "fact_type='include'")
    matched: list[CodeFact] = []
    for fact in includes:
        values = [fact.object, fact.payload.get("target"), fact.payload.get("resolved_path")]
        if fact.subject == claim.subject and any(_names_match(str(v), claim.object) for v in values if v):
            matched.append(fact)
        if fact.predicate == "header_visible_in_tu" and fact.subject == claim.subject and any(_names_match(str(v), claim.object) for v in [fact.object, fact.payload.get("header") or fact.payload.get("resolved_path")] if v):
            matched.append(fact)
    if matched:
        return _verdict_from_support(
            claim,
            matched,
            "include_edge_supported",
            "include_edge_conditional_or_unresolved",
            f"Include evidence was found from {claim.subject} to {claim.object}.",
        )
    subject_includes = [fact for fact in includes if fact.subject == claim.subject]
    unresolved = [fact for fact in subject_includes if fact.payload.get("resolution_status") == "unresolved"]
    if subject_includes and not unresolved:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="resolved_includes_do_not_include_target",
            message=f"Resolved include evidence for {claim.subject} did not include {claim.object}.",
            contradicting_facts=subject_includes,
            response_constraints=["This contradiction is scoped to resolved include evidence in the current index."],
        )
    return _unknown(claim, "include_not_found", f"No include evidence was found from {claim.subject} to {claim.object}.", subject_includes)


def _facts_for_build_target(repo: str | Path, target: str) -> list[CodeFact]:
    # Build-active checks are used heavily by profile-matrix runs.  Avoid
    # scanning the entire fact table for every target; pull a small SQL
    # candidate set and then keep the existing semantic matcher as the final
    # authority.
    query = target.split("(", 1)[0]
    suffix = f"%::{query}"
    callish = f"{query}(%"
    qualified_callish = f"%::{query}(%"
    where = " OR ".join(
        [
            "path=?",
            "symbol=?",
            "qualified_name=?",
            "subject=?",
            "object=?",
            "caller=?",
            "callee=?",
            "qualified_name LIKE ?",
            "subject LIKE ?",
            "object LIKE ?",
            "caller LIKE ?",
            "callee LIKE ?",
            "qualified_name LIKE ?",
            "subject LIKE ?",
            "object LIKE ?",
            "caller LIKE ?",
            "callee LIKE ?",
        ]
    )
    params = (
        target,
        query,
        query,
        query,
        query,
        query,
        query,
        suffix,
        suffix,
        suffix,
        suffix,
        suffix,
        callish,
        callish,
        callish,
        callish,
        callish,
    )
    candidates = _all_facts(repo, f"({where})", params)
    if not candidates:
        # Fallback preserves older behavior for unusual payload-only facts.
        candidates = _all_facts(repo)
    matched = []
    seen: set[tuple[str, int, str, str, str]] = set()
    for fact in candidates:
        if fact.path == target or _fact_name_matches(fact, target):
            pass
        elif fact.caller and name_matches(fact.caller, target, qualified=fact.payload.get("caller_qualified_name")):
            pass
        elif fact.callee and name_matches(fact.callee, target, qualified=fact.payload.get("callee_qualified_name")):
            pass
        else:
            continue
        key = (fact.path, fact.start_line, fact.fact_type, fact.subject or "", fact.object or "")
        if key not in seen:
            seen.add(key)
            matched.append(fact)
    return matched


def _verify_build_active(repo: str | Path, claim: Claim) -> ClaimVerdict:
    target = claim.subject or claim.object
    if not target:
        return _unknown(claim, "claim_missing_symbol", "build_active requires subject or object.")
    facts = _facts_for_build_target(repo, target)
    if not facts:
        return _unknown(claim, "build_target_not_found", f"No fact evidence was found for {target}.")
    definition_facts = [fact for fact in facts if fact.predicate == "definition" or fact.payload.get("declaration_or_definition") == "definition"]
    status_facts = definition_facts or facts
    active = [fact for fact in status_facts if fact_build_status(fact) == "active"]
    conditional = [fact for fact in status_facts if fact_build_status(fact) == "conditional"]
    inactive = [fact for fact in status_facts if fact_build_status(fact) == "inactive"]
    if active:
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="target_has_active_build_evidence",
            message=f"Active build evidence was found for {target}.",
            supporting_facts=active[:10],
        )
    if conditional:
        unknowns = unknowns_for_facts(conditional)
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="target_has_conditional_build_evidence",
            message=f"Only conditional build evidence was found for {target}.",
            supporting_facts=conditional[:10],
            unknowns=unknowns,
            response_constraints=constraints_for_facts(conditional),
        )
    if inactive:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="target_only_has_inactive_build_evidence",
            message=f"Only inactive build evidence was found for {target}.",
            contradicting_facts=inactive[:10],
            response_constraints=["The current build context marks this target inactive."],
        )
    return _unknown(claim, "build_status_unknown", f"Facts exist for {target}, but no build_status could be established.", facts[:10])



def _verify_allocation_profile(repo: str | Path, claim: Claim) -> ClaimVerdict:
    mode = _normalize_allocation_mode(claim.subject or claim.payload.get("mode") or claim.payload.get("allocation_mode"))
    expected = _normalize_allocation_state(claim.object or claim.payload.get("state") or claim.payload.get("enabled"))
    if mode not in {"dynamic", "static"}:
        return _unknown(claim, "claim_missing_allocation_mode", "allocation_profile requires dynamic or static as subject/mode.")
    if expected not in {"enabled", "disabled"}:
        return _unknown(claim, "claim_invalid_allocation_state", "allocation_profile expects enabled or disabled.")
    macro_name = "configSUPPORT_DYNAMIC_ALLOCATION" if mode == "dynamic" else "configSUPPORT_STATIC_ALLOCATION"
    facts = _active_facts(repo, "fact_type='target_profile' AND predicate='allocation_setting'")
    matched = [
        fact for fact in facts
        if (str(fact.subject) == f"{mode}_allocation" or str(fact.payload.get("allocation_mode") or "") == mode)
    ]
    if not matched:
        # Fall back to build_config macro evidence so the claim remains useful
        # for projects indexed before allocation_setting facts existed.
        return _verify_build_config(repo, Claim("build_config", subject=macro_name, object="1" if expected == "enabled" else "0", payload={"allocation_profile_fallback": True}))
    desired_value = "1" if expected == "enabled" else "0"
    desired = [fact for fact in matched if str(fact.payload.get("macro_value") or fact.object) == desired_value or str(fact.object) == expected]
    if desired:
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="allocation_profile_supported",
            message=f"Target profile marks {mode} allocation as {expected}.",
            supporting_facts=desired[:10],
        )
    return ClaimVerdict(
        claim=claim,
        verdict="contradicted",
        reason_code="allocation_profile_mismatch",
        message=f"Target profile allocation evidence exists for {mode}, but it is not {expected}.",
        contradicting_facts=matched[:10],
        response_constraints=["Do not claim this allocation mode state for the active target profile; indexed allocation_profile evidence has a different value."],
    )


def _normalize_allocation_mode(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("_allocation", "").replace(" allocation", "")
    if text in {"dynamic", "malloc", "heap"}:
        return "dynamic"
    if text in {"static"}:
        return "static"
    return text or None


def _normalize_allocation_state(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "enabled", "enable", "on", "有効"}:
        return "enabled"
    if text in {"0", "false", "no", "disabled", "disable", "off", "無効"}:
        return "disabled"
    return text or None


def _verify_build_config(repo: str | Path, claim: Claim) -> ClaimVerdict:
    macro_name = claim.subject or claim.payload.get("macro_name")
    expected_value = claim.object or claim.payload.get("macro_value") or claim.payload.get("value")
    if not macro_name:
        return _unknown(claim, "claim_missing_macro", "build_config requires a macro name as subject.")
    facts = _active_facts(repo, "fact_type='build_config' AND predicate='macro_value'")
    matched_name = [
        fact for fact in facts
        if _names_match(str(fact.subject), str(macro_name)) or _names_match(str(fact.payload.get("macro_name") or ""), str(macro_name))
    ]
    if not matched_name:
        return _unknown(claim, "build_config_macro_not_found", f"No target build macro evidence was found for {macro_name}.")
    if expected_value is None or str(expected_value).strip() == "":
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="build_config_macro_present",
            message=f"Target build macro evidence was found for {macro_name}.",
            supporting_facts=matched_name[:10],
        )
    expected = str(expected_value).strip()
    matched_value = [
        fact for fact in matched_name
        if str(fact.object) == expected or str(fact.payload.get("macro_value")) == expected
    ]
    if matched_value:
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="build_config_macro_value_supported",
            message=f"Target build macro {macro_name} has value {expected}.",
            supporting_facts=matched_value[:10],
        )
    return ClaimVerdict(
        claim=claim,
        verdict="contradicted",
        reason_code="build_config_macro_value_mismatch",
        message=f"Target build macro {macro_name} exists, but not with value {expected}.",
        contradicting_facts=matched_name[:10],
        response_constraints=["Do not claim this macro value for the active target profile; indexed build_config evidence has a different value."],
    )


def _verify_callback_relation(repo: str | Path, claim: Claim, *, predicate: str) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", f"{claim.claim_type} requires subject and object.")
    relations = _active_facts(repo, f"fact_type='relation' AND predicate='{predicate}'")
    matched: list[CodeFact] = []
    for fact in relations:
        subject_values = [fact.subject, fact.payload.get("caller"), fact.payload.get("caller_qualified_name")]
        object_values = [
            fact.object,
            fact.payload.get("callback_symbol"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("callback_field"),
            fact.payload.get("callback_storage_expr"),
            fact.payload.get("storage_expr"),
        ]
        object_values.extend(fact.payload.get("candidate_qualified_names") or [])
        if any(_names_match(str(v), claim.subject) for v in subject_values if v) and any(_names_match(str(v), claim.object) for v in object_values if v):
            matched.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if predicate == "stores_callback" and not any(u.unknown_type == "callback_relation_not_execution" for u in unknowns):
            unknowns.append(UnknownFact("callback_relation_not_execution", "Callback storage is not direct execution evidence."))
        if predicate == "invokes_callback" and not any(u.unknown_type == "callback_target_unknown" for u in unknowns):
            unknowns.append(UnknownFact("callback_target_unknown", "Callback invocation target is not resolved to a concrete function."))
        return ClaimVerdict(
            claim=claim,
            verdict="supported" if not has_conditional_evidence(matched, unknowns) else "conditional",
            reason_code=f"{predicate}_supported",
            message=f"{predicate} evidence was found for {claim.subject} and {claim.object}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched),
        )
    return _unknown(claim, f"{predicate}_not_found", f"No {predicate} evidence was found for {claim.subject} and {claim.object}.")


def _verify_callback_dataflow(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "callback_dataflow requires subject and object.")
    callback_symbol = str(claim.payload.get("callback_symbol") or claim.payload.get("callback") or "").strip()
    relations = _active_facts(repo, "fact_type='relation' AND predicate='callback_dataflows_to'")
    matched: list[CodeFact] = []
    for fact in relations:
        subject_values = [fact.subject, fact.payload.get("creator_function")]
        object_values = [fact.object, fact.payload.get("invocation_function")]
        callback_values = [
            fact.payload.get("callback_symbol"),
            fact.payload.get("callback_field"),
            fact.payload.get("storage_expr"),
            fact.payload.get("callback_storage_expr"),
        ]
        if not any(_names_match(str(v), claim.subject) for v in subject_values if v):
            continue
        if not any(_names_match(str(v), claim.object) for v in object_values if v):
            continue
        if callback_symbol and not any(_names_match(str(v), callback_symbol) for v in callback_values if v):
            continue
        matched.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type == "callback_relation_not_execution" for u in unknowns):
            unknowns.append(UnknownFact("callback_relation_not_execution", "Callback dataflow is not direct execution evidence."))
        if not any(u.unknown_type == "callback_target_unknown" for u in unknowns):
            unknowns.append(UnknownFact("callback_target_unknown", "Callback dataflow links storage and invocation, but the concrete runtime callback target is unresolved."))
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="callback_dataflow_supported",
            message=f"Callback dataflow evidence links {claim.subject} to {claim.object}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched) + ["Do not present callback dataflow as a direct call or as proof that a concrete callback target always executes."],
        )
    return _unknown(claim, "callback_dataflow_not_found", f"No callback dataflow evidence was found from {claim.subject} to {claim.object}.")



def _verify_task_entry_dataflow(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "task_entry_dataflow requires subject and object.")
    task_entry_symbol = str(claim.payload.get("task_entry_symbol") or claim.payload.get("entry") or "").strip()
    relations = _active_facts(repo, "fact_type='relation' AND predicate='task_entry_dataflows_to'")
    matched: list[CodeFact] = []
    for fact in relations:
        subject_values = [fact.subject, fact.payload.get("creator_function")]
        object_values = [fact.object, fact.payload.get("stack_initialiser"), fact.payload.get("storage_function")]
        entry_values = [fact.payload.get("task_entry_symbol"), fact.payload.get("task_entry_field"), fact.payload.get("storage_expr")]
        if not any(_names_match(str(v), claim.subject) for v in subject_values if v):
            continue
        if not any(_names_match(str(v), claim.object) for v in object_values if v):
            continue
        if task_entry_symbol and not any(_names_match(str(v), task_entry_symbol) for v in entry_values if v):
            continue
        matched.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type == "task_entry_execution_deferred" for u in unknowns):
            unknowns.append(UnknownFact("task_entry_execution_deferred", "Task entry dataflow is deferred scheduler/context-switch execution, not a direct call."))
        if not any(u.unknown_type == "scheduler_dependent_execution" for u in unknowns):
            unknowns.append(UnknownFact("scheduler_dependent_execution", "The task entry executes only when the scheduler/port layer dispatches the task."))
        return ClaimVerdict(
            claim=claim,
            verdict="supported" if not has_conditional_evidence(matched, unknowns) else "conditional",
            reason_code="task_entry_dataflow_supported",
            message=f"Task-entry dataflow evidence was found from {claim.subject} to {claim.object}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched) + ["Do not present task-entry dataflow as a direct call; describe it as deferred scheduler-dependent execution."],
        )
    return _unknown(claim, "task_entry_dataflow_not_found", f"No task-entry dataflow evidence was found from {claim.subject} to {claim.object}.")



_SCHEDULER_SEMANTIC_PREDICATES = {
    "enters_critical_section": {"enter_critical", "enters_critical", "critical_enter", "critical_section_enter", "enters critical section", "enter critical section"},
    "exits_critical_section": {"exit_critical", "exits_critical", "critical_exit", "critical_section_exit", "exits critical section", "exit critical section"},
    "suspends_scheduler": {"suspend_scheduler", "suspends_scheduler", "scheduler_suspend", "suspends scheduler", "suspend scheduler"},
    "resumes_scheduler": {"resume_scheduler", "resumes_scheduler", "scheduler_resume", "resumes scheduler", "resume scheduler"},
    "requests_context_switch": {"yield", "request_yield", "context_switch", "requests_context_switch", "requests context switch", "request context switch"},
    "masks_interrupts_from_isr": {"mask_interrupts", "masks_interrupts", "masks_interrupts_from_isr", "set_interrupt_mask", "sets interrupt mask"},
    "clears_interrupt_mask_from_isr": {"clear_interrupt_mask", "clears_interrupt_mask", "clears_interrupt_mask_from_isr", "unmask_interrupts", "clears interrupt mask"},
}


def _normalize_scheduler_semantic(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _SCHEDULER_SEMANTIC_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_") for a in aliases}:
            return predicate
    return key


def _verify_scheduler_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "scheduler_semantic requires a subject function/API.")
    wanted = _normalize_scheduler_semantic(claim.object or claim.payload.get("semantic") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_scheduler_semantic", "scheduler_semantic requires a semantic object such as requests_context_switch or enters_critical_section.")
    relations = _active_facts(repo, "fact_type='relation'")
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    scheduler_predicates = set(_SCHEDULER_SEMANTIC_PREDICATES.keys())
    for fact in relations:
        if fact.predicate not in scheduler_predicates:
            continue
        if not any(_names_match(str(v), claim.subject) for v in [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name")] if v):
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if wanted == "requests_context_switch" and not any(u.unknown_type == "scheduler_dependent_execution" for u in unknowns):
            unknowns.append(UnknownFact("scheduler_dependent_execution", "Yield/context-switch request evidence does not prove an immediate context switch on every path."))
        if wanted in {"masks_interrupts_from_isr", "clears_interrupt_mask_from_isr"} and not any(u.unknown_type == "interrupt_mask_state_deferred" for u in unknowns):
            unknowns.append(UnknownFact("interrupt_mask_state_deferred", "Interrupt-mask relation shows masking/unmasking API usage, not the full runtime interrupt state."))
        return ClaimVerdict(
            claim=claim,
            verdict="supported" if not has_conditional_evidence(matched, unknowns) else "conditional",
            reason_code="scheduler_semantic_supported",
            message=f"Scheduler/yield semantic evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched),
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="scheduler_semantic_conflict",
            message=f"Scheduler semantic evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "scheduler_semantic_not_found", f"No scheduler/yield semantic evidence was found for {claim.subject}.")

_TASK_STATE_TRANSITION_PREDICATES = {
    "moves_task_to_ready_list": {"ready", "ready_list", "moves_task_to_ready_list", "move_task_to_ready_list", "moves task to ready list"},
    "moves_task_to_delayed_list": {"delayed", "delayed_list", "moves_task_to_delayed_list", "move_task_to_delayed_list", "moves task to delayed list"},
    "blocks_task_on_event_list": {"blocks", "event_list_block", "blocks_task_on_event_list", "block_task_on_event_list", "blocks task on event list"},
    "unblocks_task_from_event_list": {"unblocks", "event_list_unblock", "unblocks_task_from_event_list", "unblock_task_from_event_list", "unblocks task from event list"},
    "removes_task_from_list": {"removes", "remove_list", "removes_task_from_list", "remove_task_from_list", "removes task from list"},
}


def _normalize_task_state_transition(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _TASK_STATE_TRANSITION_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_") for a in aliases}:
            return predicate
    return key


def _verify_task_state_transition(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "task_state_transition requires a subject function/API.")
    wanted = _normalize_task_state_transition(claim.object or claim.payload.get("transition") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_task_state_transition", "task_state_transition requires a transition such as moves_task_to_ready_list.")
    relations = _active_facts(repo, "fact_type='relation'")
    predicates = set(_TASK_STATE_TRANSITION_PREDICATES.keys())
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    for fact in relations:
        if fact.predicate not in predicates:
            continue
        if not any(_names_match(str(value), claim.subject) for value in [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name")] if value):
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type == "task_state_transition_semantic" for u in unknowns):
            unknowns.append(UnknownFact("task_state_transition_semantic", "Task/list transition evidence describes FreeRTOS list-state movement, not a complete runtime scheduler proof."))
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="task_state_transition_supported",
            message=f"Task/list state-transition evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched) + ["Preserve FreeRTOS task/list state-transition semantics; do not reduce this evidence to a generic helper call."],
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="task_state_transition_conflict",
            message=f"Task/list transition evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "task_state_transition_not_found", f"No task/list state-transition evidence was found for {claim.subject}.")




_KERNEL_OBJECT_SEMANTIC_PREDICATES = {
    "sends_to_stream_buffer": {"send_stream", "sends_stream", "stream_send", "sends to stream buffer", "send to stream buffer"},
    "receives_from_stream_buffer": {"receive_stream", "receives_stream", "stream_receive", "receives from stream buffer", "receive from stream buffer"},
    "sends_to_message_buffer": {"send_message", "message_send", "sends to message buffer", "send to message buffer"},
    "receives_from_message_buffer": {"receive_message", "message_receive", "receives from message buffer", "receive from message buffer"},
    "sets_event_bits": {"set_event_bits", "sets event bits", "set event bits"},
    "clears_event_bits": {"clear_event_bits", "clears event bits", "clear event bits"},
    "waits_for_event_bits": {"wait_event_bits", "waits for event bits", "wait for event bits"},
    "syncs_event_bits": {"sync_event_bits", "syncs event bits", "sync event bits"},
    "notifies_task": {"notify_task", "notifies task", "task notify", "direct task notification"},
    "waits_for_task_notification": {"wait_task_notification", "waits for task notification", "task notification wait"},
    "gives_semaphore": {"give_semaphore", "gives semaphore", "semaphore give"},
    "takes_semaphore": {"take_semaphore", "takes semaphore", "semaphore take"},
    "creates_semaphore": {"create_semaphore", "creates semaphore", "semaphore create"},
    "gives_mutex": {"give_mutex", "gives mutex", "mutex give"},
    "takes_mutex": {"take_mutex", "takes mutex", "mutex take"},
    "creates_mutex": {"create_mutex", "creates mutex", "mutex create"},
}


def _normalize_kernel_object_semantic(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _KERNEL_OBJECT_SEMANTIC_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_") for a in aliases}:
            return predicate
    return key


def _verify_kernel_object_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "kernel_object_semantic requires a subject function/API.")
    wanted = _normalize_kernel_object_semantic(claim.object or claim.payload.get("semantic") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_kernel_object_semantic", "kernel_object_semantic requires a semantic object such as sends_to_stream_buffer or sets_event_bits.")
    relations = _active_facts(repo, "fact_type='relation'")
    predicates = set(_KERNEL_OBJECT_SEMANTIC_PREDICATES.keys())
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    for fact in relations:
        if fact.predicate not in predicates:
            continue
        if not any(_names_match(str(value), claim.subject) for value in [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name")] if value):
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type == "kernel_object_semantic" for u in unknowns):
            unknowns.append(UnknownFact("kernel_object_semantic", "Kernel-object evidence describes FreeRTOS synchronization/communication semantics, not a complete runtime schedule or object state proof."))
        constraints = constraints_for_facts(matched) + ["Preserve FreeRTOS kernel-object semantics; do not reduce stream/message/event/notification/semaphore/mutex evidence to a generic helper call."]
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="kernel_object_semantic_supported",
            message=f"Kernel-object semantic evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints,
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="kernel_object_semantic_conflict",
            message=f"Kernel-object semantic evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "kernel_object_semantic_not_found", f"No FreeRTOS kernel-object semantic evidence was found for {claim.subject}.")


_HOOK_ASSERT_TRACE_PREDICATES = {
    "invokes_trace_hook": {"trace_hook", "invokes trace hook", "trace", "instrumentation hook"},
    "invokes_assert_handler": {"assert_handler", "assert", "configassert", "invokes assert handler"},
    "invokes_application_hook": {"application_hook", "app_hook", "invokes application hook", "hook"},
    "coverage_marker": {"coverage_marker", "coverage", "test marker", "mtcoverage_test_marker"},
}


def _normalize_hook_assert_trace_semantic(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _HOOK_ASSERT_TRACE_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_") for a in aliases}:
            return predicate
    return key


def _verify_hook_assert_trace_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "hook_assert_trace_semantic requires a subject function/API.")
    wanted = _normalize_hook_assert_trace_semantic(claim.object or claim.payload.get("semantic") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_hook_assert_trace_semantic", "hook_assert_trace_semantic requires a semantic object such as invokes_trace_hook or invokes_assert_handler.")
    relations = _active_facts(repo, "fact_type='relation'")
    predicates = set(_HOOK_ASSERT_TRACE_PREDICATES.keys())
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    requested_api = str(claim.payload.get("api_name") or claim.payload.get("hook") or "").strip()
    for fact in relations:
        if fact.predicate not in predicates:
            continue
        if not any(_names_match(str(value), claim.subject) for value in [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name")] if value):
            continue
        if requested_api and not any(_names_match(str(value), requested_api) for value in [fact.object, fact.payload.get("api_name")] if value):
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type in {"trace_hook_target_unknown", "assert_handler_config_dependent", "application_defined_hook_target_unknown", "coverage_marker_not_runtime_behavior"} for u in unknowns):
            unknowns.append(UnknownFact("hook_assert_trace_semantic", "Hook/assert/trace evidence is configurable or application-defined and does not prove a concrete hook implementation."))
        constraints = constraints_for_facts(matched) + ["Preserve FreeRTOS hook/assert/trace semantics; do not treat trace hooks, configASSERT, application hooks, or coverage markers as ordinary direct kernel behavior."]
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="hook_assert_trace_semantic_supported",
            message=f"Hook/assert/trace semantic evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints,
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="hook_assert_trace_semantic_conflict",
            message=f"Hook/assert/trace semantic evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "hook_assert_trace_semantic_not_found", f"No FreeRTOS hook/assert/trace semantic evidence was found for {claim.subject}.")


_HEAP_ALLOCATOR_PREDICATES = {
    "allocates_heap_memory": {"allocates_heap_memory", "allocates heap memory", "heap allocate", "allocation"},
    "frees_heap_memory": {"frees_heap_memory", "frees heap memory", "heap free", "deallocation"},
    "coalesces_free_blocks": {"coalesces_free_blocks", "coalesces free blocks", "free block coalescing", "coalescing"},
    "uses_libc_allocator": {"uses_libc_allocator", "uses libc allocator", "libc allocator", "malloc wrapper"},
    "uses_multiple_heap_regions": {"uses_multiple_heap_regions", "uses multiple heap regions", "multiple heap regions", "multi region heap"},
    "does_not_support_free": {"does_not_support_free", "does not support free", "no free", "free unsupported"},
}


def _normalize_heap_allocator_semantic(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _HEAP_ALLOCATOR_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_") for a in aliases}:
            return predicate
    return key


def _verify_heap_allocator_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "heap_allocator_semantic requires a subject function/API.")
    wanted = _normalize_heap_allocator_semantic(claim.object or claim.payload.get("semantic") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_heap_allocator_semantic", "heap_allocator_semantic requires a semantic object such as allocates_heap_memory or coalesces_free_blocks.")
    relations = _active_facts(repo, "fact_type='relation'")
    predicates = set(_HEAP_ALLOCATOR_PREDICATES.keys())
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    requested_allocator = str(claim.payload.get("heap_allocator") or claim.payload.get("allocator") or "").strip()
    for fact in relations:
        if fact.predicate not in predicates:
            continue
        if not any(_names_match(str(value), claim.subject) for value in [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name"), fact.payload.get("heap_allocator")] if value):
            continue
        if requested_allocator and str(fact.payload.get("heap_allocator") or "") != requested_allocator:
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type in {"heap_runtime_state_unknown", "heap_coalescing_path_dependent", "external_allocator_behavior_unknown", "heap_region_configuration_required", "heap_free_not_supported"} for u in unknowns):
            unknowns.append(UnknownFact("heap_allocator_semantic", "Heap allocator semantic evidence describes implementation behavior, not a complete runtime heap-state proof."))
        constraints = constraints_for_facts(matched) + ["Preserve FreeRTOS heap allocator semantics; qualify allocation/free/coalescing behavior by the selected heap implementation."]
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="heap_allocator_semantic_supported",
            message=f"Heap allocator semantic evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints,
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="heap_allocator_semantic_conflict",
            message=f"Heap allocator semantic evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "heap_allocator_semantic_not_found", f"No FreeRTOS heap allocator semantic evidence was found for {claim.subject}.")


_PORT_ADVANCED_PREDICATES = {
    "uses_smp_scheduler": {"uses_smp_scheduler", "smp_scheduler", "smp scheduler", "smp"},
    "uses_core_affinity": {"uses_core_affinity", "core_affinity", "core affinity"},
    "uses_cross_core_yield": {"uses_cross_core_yield", "cross_core_yield", "cross-core yield", "cross core yield"},
    "uses_smp_locking": {"uses_smp_locking", "smp_locking", "smp locking", "smp lock"},
    "uses_mpu_wrappers": {"uses_mpu_wrappers", "mpu_wrappers", "mpu wrapper", "mpu wrappers"},
    "configures_mpu_regions": {"configures_mpu_regions", "mpu_regions", "mpu regions", "mpu region"},
    "checks_mpu_access": {"checks_mpu_access", "mpu_access", "mpu access"},
    "crosses_privilege_boundary": {"crosses_privilege_boundary", "privilege_boundary", "privilege boundary"},
    "uses_port_assembly": {"uses_port_assembly", "port_assembly", "port assembly"},
    "uses_secure_context_boundary": {"uses_secure_context_boundary", "secure_context_boundary", "secure context boundary"},
}


def _normalize_port_advanced_semantic(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    key = text.lower().replace("-", "_").replace(" ", "_")
    for predicate, aliases in _PORT_ADVANCED_PREDICATES.items():
        if text == predicate or key == predicate or key in {a.replace(" ", "_").replace("-", "_") for a in aliases}:
            return predicate
    return key


def _verify_port_advanced_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "port_advanced_semantic requires a subject function/API.")
    wanted = _normalize_port_advanced_semantic(claim.object or claim.payload.get("semantic") or claim.payload.get("predicate") or claim.payload.get("operation"))
    if not wanted:
        return _unknown(claim, "claim_missing_port_advanced_semantic", "port_advanced_semantic requires a semantic object such as uses_smp_scheduler or configures_mpu_regions.")
    relations = _active_facts(repo, "fact_type='relation'")
    predicates = set(_PORT_ADVANCED_PREDICATES.keys())
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    for fact in relations:
        if fact.predicate not in predicates:
            continue
        values = [fact.subject, fact.payload.get("caller"), fact.payload.get("api_name"), fact.payload.get("state_object")]
        if not any(_names_match(str(value), claim.subject) for value in values if value):
            continue
        if fact.predicate == wanted:
            matched.append(fact)
        else:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type in {
            "smp_runtime_interleaving_unknown", "core_affinity_runtime_state_unknown", "cross_core_yield_target_unknown",
            "smp_lock_order_runtime_unknown", "mpu_port_configuration_required", "mpu_region_layout_target_specific",
            "mpu_access_policy_target_specific", "privilege_boundary_target_specific", "assembly_boundary_unverified",
            "secure_context_boundary_unverified", "port_advanced_target_specific",
        } for u in unknowns):
            unknowns.append(UnknownFact("port_advanced_target_specific", "Advanced FreeRTOS port/SMP/MPU evidence is target-specific and does not prove complete runtime behavior."))
        constraints = constraints_for_facts(matched) + ["Preserve FreeRTOS SMP/MPU/advanced-port semantics; qualify behavior by target port, core count, MPU setup, and assembly/startup evidence."]
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="port_advanced_semantic_supported",
            message=f"Advanced port/SMP/MPU semantic evidence marks {claim.subject} as {wanted}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints,
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="port_advanced_semantic_conflict",
            message=f"Advanced port semantic evidence for {claim.subject} exists, but it does not include {wanted}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "port_advanced_semantic_not_found", f"No FreeRTOS advanced port/SMP/MPU semantic evidence was found for {claim.subject}.")

def _verify_port_boundary(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject:
        return _unknown(claim, "claim_missing_subject", "port_boundary requires a subject function/API.")
    requested_object = str(claim.object or claim.payload.get("object") or "port_layer").strip()
    relations = _active_facts(repo, "fact_type='relation' AND predicate IN ('crosses_port_boundary','has_port_boundary')")
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    for fact in relations:
        subject_matches = any(
            _names_match(str(value), claim.subject)
            for value in [fact.subject, fact.payload.get("caller"), fact.payload.get("port_function"), fact.payload.get("port_function_qualified_name")]
            if value
        )
        if not subject_matches:
            continue
        if requested_object and requested_object != "port_layer":
            object_matches = any(
                _names_match(str(value), requested_object)
                for value in [fact.object, fact.payload.get("callee"), fact.payload.get("port_api"), fact.payload.get("port_function")]
                if value
            )
            if object_matches:
                matched.append(fact)
            else:
                conflicting.append(fact)
        else:
            matched.append(fact)
    if matched:
        unknowns = _port_boundary_unknowns(matched)
        constraints = constraints_for_facts(matched)
        for fact in matched:
            constraint = fact.payload.get("response_constraint")
            if constraint and constraint not in constraints:
                constraints.append(str(constraint))
        return ClaimVerdict(
            claim=claim,
            verdict="conditional",
            reason_code="port_boundary_supported",
            message=f"Port-boundary evidence was found for {claim.subject}; behavior beyond the boundary is target/port/startup dependent.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints,
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="port_boundary_target_mismatch",
            message=f"Port-boundary evidence for {claim.subject} exists, but not for {requested_object}.",
            contradicting_facts=conflicting,
            unknowns=_port_boundary_unknowns(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "port_boundary_not_found", f"No FreeRTOS port-boundary evidence was found for {claim.subject}.")


def _port_boundary_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    by_type = {unknown.unknown_type: unknown for unknown in unknowns_for_facts(facts)}
    messages = {
        "port_layer_boundary": "The evidence reaches a FreeRTOS port-layer boundary; behavior beyond this point depends on the selected port implementation.",
        "assembly_boundary_unverified": "Assembly/compiler-specific startup or context-switch code is not verified by this C-source evidence.",
        "vector_table_unverified": "Exception/interrupt binding depends on vector-table or startup-file evidence that is not verified here.",
        "startup_file_missing": "Startup/linker/vector setup was not present in the verified evidence.",
        "port_stack_layout_target_specific": "Task stack layout and context-switch behavior are target-specific.",
    }
    affects = []
    for fact in facts:
        if fact.subject and fact.object:
            affects.append(f"{fact.subject}->{fact.object}")
    for fact in facts:
        values = []
        if fact.payload.get("unknown_type"):
            values.append(str(fact.payload.get("unknown_type")))
        values.extend(str(v) for v in fact.payload.get("unknown_types") or [])
        for value in values:
            if value in messages and value not in by_type:
                by_type[value] = UnknownFact(value, messages[value], severity="medium", affects=affects)
    return list(by_type.values())

def _normalize_execution_context(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"isr", "interrupt", "irq", "割り込み"}:
        return "isr"
    if normalized in {"task", "thread", "タスク"}:
        return "task"
    return normalized or None


def _verify_execution_context(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "execution_context requires subject and object context.")
    requested = _normalize_execution_context(claim.object)
    if requested not in {"isr", "task"}:
        return _unknown(claim, "unsupported_execution_context", f"Unsupported execution context: {claim.object}.")
    relations = _active_facts(repo, "fact_type='relation' AND predicate='has_execution_context'")
    matched: list[CodeFact] = []
    conflicting: list[CodeFact] = []
    for fact in relations:
        if not any(_names_match(str(v), claim.subject) for v in [fact.subject, fact.payload.get("function_qualified_name")] if v):
            continue
        context = _normalize_execution_context(fact.object or fact.payload.get("execution_context"))
        if context == requested:
            matched.append(fact)
        elif context in {"isr", "task"}:
            conflicting.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        return ClaimVerdict(
            claim=claim,
            verdict="supported" if not has_conditional_evidence(matched, unknowns) else "conditional",
            reason_code="execution_context_supported",
            message=f"Execution-context evidence marks {claim.subject} as {requested} context.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched),
        )
    if conflicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="execution_context_conflict",
            message=f"Execution-context evidence for {claim.subject} exists, but it does not match {requested}.",
            contradicting_facts=conflicting,
            unknowns=unknowns_for_facts(conflicting),
            response_constraints=constraints_for_facts(conflicting),
        )
    return _unknown(claim, "execution_context_not_found", f"No execution-context evidence was found for {claim.subject}.")


def _verify_target_profile(repo: str | Path, claim: Claim) -> ClaimVerdict:
    subject = str(claim.subject or claim.payload.get("attribute") or "name").strip()
    expected = claim.object or claim.payload.get("value") or claim.payload.get("name")
    facts = _active_facts(repo, "fact_type='target_profile'")
    if not facts:
        return _unknown(claim, "target_profile_not_found", "No target profile evidence was found in the current index.")

    subject_norm = subject.lower()
    matched: list[CodeFact] = []
    if subject_norm in {"name", "profile", "target_profile", "selected_profile"}:
        if expected is None or str(expected).strip() == "":
            matched = [fact for fact in facts if fact.predicate == "selected_profile"]
        else:
            wanted = str(expected).strip()
            matched = [
                fact for fact in facts
                if fact.predicate == "selected_profile"
                and (_names_match(str(fact.subject), wanted) or _names_match(str(fact.payload.get("target_profile_name") or ""), wanted))
            ]
    else:
        if expected is None or str(expected).strip() == "":
            matched = [fact for fact in facts if _names_match(str(fact.subject), subject)]
        else:
            wanted = str(expected).strip()
            matched = [
                fact for fact in facts
                if _names_match(str(fact.subject), subject)
                and (str(fact.object) == wanted or _names_match(str(fact.object), wanted))
            ]

    if matched:
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="target_profile_supported",
            message="Target profile evidence matched the claim.",
            supporting_facts=matched[:10],
        )

    selected = [fact for fact in facts if fact.predicate == "selected_profile"]
    attribute_facts = [fact for fact in facts if _names_match(str(fact.subject), subject)]
    contradicting = attribute_facts or selected
    if expected is not None and contradicting:
        return ClaimVerdict(
            claim=claim,
            verdict="contradicted",
            reason_code="target_profile_value_mismatch",
            message="Target profile evidence exists, but it does not match the requested value.",
            contradicting_facts=contradicting[:10],
            response_constraints=["Do not claim this target-profile value for the active index; indexed target_profile evidence has a different value."],
        )
    return _unknown(claim, "target_profile_attribute_not_found", f"No target profile evidence was found for {subject}.")


def _verify_file_active(repo: str | Path, claim: Claim) -> ClaimVerdict:
    target = str(claim.subject or claim.object or claim.payload.get("path") or claim.payload.get("file") or "").strip()
    expected = str(claim.object or claim.payload.get("status") or "active").strip().lower()
    if expected in {"", "yes", "true"}:
        expected = "active"
    if expected in {"no", "false", "inactive"}:
        expected = "inactive"
    if expected not in {"active", "inactive"}:
        return _unknown(claim, "claim_invalid_file_active_status", "file_active expects active or inactive status.")
    if not target:
        return _unknown(claim, "claim_missing_file_path", "file_active requires a file path as subject or payload.path.")
    facts = _all_facts(repo, "fact_type='target_file'")
    matched_path = [
        fact for fact in facts
        if _paths_match(str(fact.subject), target) or _paths_match(str(fact.payload.get("file_path") or ""), target)
    ]
    if not matched_path:
        return _unknown(claim, "target_file_selection_not_found", f"No target-profile file selection evidence was found for {target}.")
    wanted_predicate = "file_active" if expected == "active" else "file_inactive"
    matched_status = [fact for fact in matched_path if fact.predicate == wanted_predicate or fact.payload.get("selection_status") == expected]
    if matched_status:
        return ClaimVerdict(
            claim=claim,
            verdict="supported",
            reason_code="target_file_selection_supported",
            message=f"Target-profile file selection marks {target} as {expected}.",
            supporting_facts=matched_status[:10],
        )
    return ClaimVerdict(
        claim=claim,
        verdict="contradicted",
        reason_code="target_file_selection_mismatch",
        message=f"Target-profile file selection for {target} exists, but it is not {expected}.",
        contradicting_facts=matched_path[:10],
        response_constraints=["Do not claim this file selection status for the active target profile; indexed target_file evidence has a different status."],
    )



def _verify_usb_descriptor_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    subject = str(claim.subject or claim.payload.get("descriptor") or claim.payload.get("macro") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or "").strip()
    descriptor_kind = str(claim.payload.get("descriptor_kind") or claim.payload.get("class") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    callback = str(claim.payload.get("callback") or "").strip()
    interface_symbol = str(claim.payload.get("interface_symbol") or "").strip()
    endpoint_symbol = str(claim.payload.get("endpoint_symbol") or "").strip()
    array_name = str(claim.payload.get("array") or claim.payload.get("descriptor_array") or "").strip()

    facts = _active_facts(repo, "fact_type='usb_descriptor'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("descriptor_macro"),
            fact.payload.get("descriptor_kind"),
            fact.payload.get("usb_class"),
            fact.payload.get("callback_name"),
            fact.payload.get("descriptor_array"),
            fact.payload.get("returned_descriptor"),
        ]
        if subject and not any(_names_match(str(v), subject) for v in values if v):
            continue
        if expected:
            expected_values = [fact.object, fact.payload.get("usb_class"), fact.payload.get("descriptor_array"), fact.payload.get("returned_descriptor")]
            expected_values.extend(fact.payload.get("endpoint_symbols") or [])
            expected_values.extend(fact.payload.get("interface_symbols") or [])
            if not any(_names_match(str(v), expected) or str(v) == expected for v in expected_values if v):
                continue
        if descriptor_kind:
            kind_values = [fact.payload.get("descriptor_kind"), fact.payload.get("usb_class")]
            if not any(_names_match(str(v), descriptor_kind) for v in kind_values if v):
                continue
        if predicate and fact.predicate != predicate:
            continue
        if callback and not _names_match(str(fact.payload.get("callback_name") or fact.subject or ""), callback):
            continue
        if interface_symbol and interface_symbol not in (fact.payload.get("interface_symbols") or []):
            if not _names_match(str(fact.payload.get("interface_symbol") or ""), interface_symbol):
                continue
        if endpoint_symbol and endpoint_symbol not in (fact.payload.get("endpoint_symbols") or []):
            if not _names_match(str(fact.payload.get("endpoint_symbol") or ""), endpoint_symbol):
                continue
        if array_name and not _names_match(str(fact.payload.get("descriptor_array") or ""), array_name):
            continue
        matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "usb_descriptor_semantic_supported",
            "usb_descriptor_semantic_conditional",
            "USB descriptor semantic evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="usb_descriptor_semantic_not_matched",
            message="USB descriptor facts exist, but none matched the requested descriptor semantic claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("usb_descriptor_semantic_not_matched", "Descriptor evidence exists, but the requested descriptor, class, callback, interface, or endpoint was not found.")],
            response_constraints=["Do not claim this TinyUSB descriptor semantic unless matching usb_descriptor evidence is present for the active target."],
        )
    return _unknown(claim, "usb_descriptor_semantic_not_found", "No USB descriptor semantic evidence was found in the current index.")


def _verify_tinyusb_callback_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    callback = str(claim.subject or claim.payload.get("callback") or claim.payload.get("callback_name") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    implementation_kind = str(claim.payload.get("implementation_kind") or claim.payload.get("kind") or "").strip()
    linkage = str(claim.payload.get("linkage") or "").strip()
    family = str(claim.payload.get("callback_family") or claim.payload.get("family") or "").strip()
    role = str(claim.payload.get("callback_role") or claim.payload.get("role") or "").strip()
    requirement = str(claim.payload.get("callback_requirement") or claim.payload.get("requirement") or "").strip()
    override_status = str(claim.payload.get("override_status") or "").strip()
    application_path = claim.payload.get("application_path")
    weak_default = claim.payload.get("weak_default")

    facts = _active_facts(repo, "fact_type='tinyusb_callback'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("callback_name"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("implementation_kind"),
            fact.payload.get("linkage"),
            fact.payload.get("callback_family"),
            fact.payload.get("callback_role"),
            fact.payload.get("callback_requirement"),
            fact.payload.get("override_status"),
            fact.payload.get("weak_definition_path"),
            fact.payload.get("application_definition_path"),
        ]
        values.extend(fact.payload.get("candidate_qualified_names") or [])
        if callback and not any(_names_match(str(v), callback) or str(v) == callback for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if implementation_kind and not _names_match(str(fact.payload.get("implementation_kind") or fact.object or ""), implementation_kind):
            continue
        if linkage and str(fact.payload.get("linkage") or "") != linkage:
            continue
        if family and not _names_match(str(fact.payload.get("callback_family") or ""), family):
            continue
        if role and not _names_match(str(fact.payload.get("callback_role") or ""), role):
            continue
        if requirement and not _names_match(str(fact.payload.get("callback_requirement") or ""), requirement):
            continue
        if override_status and str(fact.payload.get("override_status") or "") != override_status:
            continue
        if application_path is not None and bool(fact.payload.get("application_path")) != bool(application_path):
            continue
        if weak_default is not None and bool(fact.payload.get("weak_default")) != bool(weak_default):
            continue
        matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_callback_semantic_supported",
            "tinyusb_callback_semantic_conditional",
            "TinyUSB callback semantic evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_callback_semantic_not_matched",
            message="TinyUSB callback facts exist, but none matched the requested callback semantic claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_callback_semantic_not_matched", "Callback evidence exists, but the requested weak default, strong implementation, override, family, role, or requirement was not found.")],
            response_constraints=["Do not claim this TinyUSB callback semantic unless matching tinyusb_callback evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_callback_semantic_not_found", "No TinyUSB callback semantic evidence was found in the current index.")


def _verify_tinyusb_driver_dispatch_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    wanted = str(claim.subject or claim.payload.get("driver_class") or claim.payload.get("class") or claim.payload.get("usb_class") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("callback_symbol") or claim.payload.get("callback_field") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    driver_class = str(claim.payload.get("driver_class") or claim.payload.get("class") or claim.payload.get("usb_class") or "").strip()
    callback_field = str(claim.payload.get("callback_field") or "").strip()
    callback_symbol = str(claim.payload.get("callback_symbol") or "").strip()
    driver_table = str(claim.payload.get("driver_table") or "").strip()
    config_macro = str(claim.payload.get("config_macro") or "").strip()
    map_name = str(claim.payload.get("map_name") or "").strip()
    map_kind = str(claim.payload.get("map_kind") or "").strip()
    dispatch_function = str(claim.payload.get("dispatch_function") or claim.payload.get("function") or "").strip()
    via_function = str(claim.payload.get("via_function") or "").strip()

    facts = _active_facts(repo, "fact_type='tinyusb_driver_dispatch'")
    matched: list[CodeFact] = []
    for fact in facts:
        callbacks = fact.payload.get("callbacks") or {}
        callback_values = []
        if isinstance(callbacks, dict):
            callback_values.extend(callbacks.values())
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("driver_class"),
            fact.payload.get("usb_class"),
            fact.payload.get("class_name"),
            fact.payload.get("driver_table"),
            fact.payload.get("config_macro"),
            fact.payload.get("callback_field"),
            fact.payload.get("callback_symbol"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("map_name"),
            fact.payload.get("map_kind"),
            fact.payload.get("endpoint_map"),
            fact.payload.get("interface_map"),
            fact.payload.get("binding_api"),
            fact.payload.get("dispatch_function"),
            fact.payload.get("dispatch_function_qualified_name"),
            fact.payload.get("via_function"),
        ]
        values.extend(callback_values)
        values.extend(fact.payload.get("callback_symbols") or [])
        values.extend(fact.payload.get("callback_fields") or [])
        values.extend(fact.payload.get("candidate_qualified_names") or [])

        if wanted and not any(_names_match(str(v), wanted) or str(v) == wanted for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if driver_class and not any(_names_match(str(v), driver_class) for v in [fact.payload.get("driver_class"), fact.payload.get("usb_class"), fact.subject] if v):
            continue
        if callback_field and not _names_match(str(fact.payload.get("callback_field") or fact.object or ""), callback_field):
            continue
        if callback_symbol:
            symbol_values = [fact.payload.get("callback_symbol"), fact.object, fact.payload.get("callback_qualified_name")]
            symbol_values.extend(fact.payload.get("candidate_qualified_names") or [])
            if not any(_names_match(str(v), callback_symbol) or str(v) == callback_symbol for v in symbol_values if v):
                continue
        if driver_table and not _names_match(str(fact.payload.get("driver_table") or fact.object or ""), driver_table):
            continue
        if config_macro and str(fact.payload.get("config_macro") or "") != config_macro:
            continue
        if map_name:
            map_values = [fact.payload.get("map_name"), fact.payload.get("endpoint_map"), fact.payload.get("interface_map"), fact.subject]
            if not any(str(v) == map_name or str(v).endswith("." + map_name) or map_name in str(v) for v in map_values if v):
                continue
        if map_kind and str(fact.payload.get("map_kind") or fact.object or "") != map_kind:
            continue
        if dispatch_function and not _names_match(str(fact.payload.get("dispatch_function") or fact.subject or ""), dispatch_function):
            continue
        if via_function and str(fact.payload.get("via_function") or "") != via_function:
            continue
        matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_driver_dispatch_semantic_supported",
            "tinyusb_driver_dispatch_semantic_conditional",
            "TinyUSB class-driver dispatch evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_driver_dispatch_semantic_not_matched",
            message="TinyUSB driver-dispatch facts exist, but none matched the requested class-driver, callback, map, binding, or dispatch claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_driver_dispatch_semantic_not_matched", "Driver-dispatch evidence exists, but the requested class-driver, callback field, endpoint/interface map, or indirect dispatch site was not found.")],
            response_constraints=["Do not claim this TinyUSB class-driver dispatch semantic unless matching tinyusb_driver_dispatch evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_driver_dispatch_semantic_not_found", "No TinyUSB class-driver dispatch semantic evidence was found in the current index.")


def _verify_tinyusb_device_runtime_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    wanted = str(claim.subject or claim.payload.get("api_name") or claim.payload.get("function") or claim.payload.get("queue_name") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or claim.payload.get("stage") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    api_name = str(claim.payload.get("api_name") or "").strip()
    runtime_model = str(claim.payload.get("runtime_model") or "").strip()
    stage = str(claim.payload.get("transfer_lifecycle_stage") or claim.payload.get("stage") or "").strip()
    queue_api = str(claim.payload.get("queue_api") or claim.payload.get("event_queue_api") or "").strip()
    osal_profile = str(claim.payload.get("osal_profile") or "").strip()
    controller_port = str(claim.payload.get("controller_port_path") or claim.payload.get("selected_controller_port") or "").strip()
    dcd_api = str(claim.payload.get("dcd_api") or claim.payload.get("dcd_transfer_api") or "").strip()
    queue_name = str(claim.payload.get("queue_name") or "").strip()
    hardware_boundary = claim.payload.get("hardware_boundary")
    consumes_event_queue = claim.payload.get("consumes_event_queue")
    queues_event = claim.payload.get("queues_event")
    dispatches_transfer_complete = claim.payload.get("dispatches_transfer_complete")
    dispatches_class_xfer_callback = claim.payload.get("dispatches_class_xfer_callback")

    facts = _active_facts(repo, "fact_type='tinyusb_device_runtime'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("api_name"),
            fact.payload.get("api_qualified_name"),
            fact.payload.get("runtime_model"),
            fact.payload.get("transfer_lifecycle_stage"),
            fact.payload.get("endpoint_state_operation"),
            fact.payload.get("dcd_transfer_api"),
            fact.payload.get("event_queue_api"),
            fact.payload.get("queue_api"),
            fact.payload.get("queue_name"),
            fact.payload.get("controller_port_path"),
            fact.payload.get("selected_controller_port"),
            fact.payload.get("task_function"),
            fact.payload.get("event_source"),
            fact.payload.get("osal_profile"),
        ]
        values.extend(fact.payload.get("dcd_api_calls") or [])
        if wanted and not any(_names_match(str(v), wanted) or str(v) == wanted for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if api_name and not _names_match(str(fact.payload.get("api_name") or fact.subject or ""), api_name):
            continue
        if runtime_model and str(fact.payload.get("runtime_model") or "") != runtime_model:
            continue
        if stage and str(fact.payload.get("transfer_lifecycle_stage") or fact.payload.get("endpoint_state_operation") or "") != stage:
            continue
        if queue_api:
            queue_values = [fact.payload.get("queue_api"), fact.payload.get("event_queue_api"), fact.object]
            if not any(str(v) == queue_api or _names_match(str(v), queue_api) for v in queue_values if v):
                continue
        if osal_profile and str(fact.payload.get("osal_profile") or "") != osal_profile:
            continue
        if controller_port:
            port_values = [fact.payload.get("controller_port_path"), fact.payload.get("selected_controller_port")]
            if not any(str(v) == controller_port or str(v).endswith("/" + controller_port) or controller_port.endswith("/" + str(v)) for v in port_values if v):
                continue
        if dcd_api:
            dcd_values = [fact.payload.get("dcd_transfer_api")]
            dcd_values.extend(fact.payload.get("dcd_api_calls") or [])
            if not any(str(v) == dcd_api or _names_match(str(v), dcd_api) for v in dcd_values if v):
                continue
        if queue_name and not _names_match(str(fact.payload.get("queue_name") or fact.subject or ""), queue_name):
            continue
        for key, expected_bool in [
            ("hardware_boundary", hardware_boundary),
            ("consumes_event_queue", consumes_event_queue),
            ("queues_event", queues_event),
            ("dispatches_transfer_complete", dispatches_transfer_complete),
            ("dispatches_class_xfer_callback", dispatches_class_xfer_callback),
        ]:
            if expected_bool is not None and bool(fact.payload.get(key)) != bool(expected_bool):
                break
        else:
            matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_device_runtime_semantic_supported",
            "tinyusb_device_runtime_semantic_conditional",
            "TinyUSB device runtime semantic evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_device_runtime_semantic_not_matched",
            message="TinyUSB device-runtime facts exist, but none matched the requested runtime, OSAL, DCD boundary, or endpoint transfer claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_device_runtime_semantic_not_matched", "Device runtime evidence exists, but the requested endpoint lifecycle, event queue, OSAL, DCD boundary, or task dispatch semantic was not found.")],
            response_constraints=["Do not claim this TinyUSB device runtime semantic unless matching tinyusb_device_runtime evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_device_runtime_semantic_not_found", "No TinyUSB device runtime semantic evidence was found in the current index.")



def _verify_tinyusb_host_runtime_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    wanted = str(claim.subject or claim.payload.get("api_name") or claim.payload.get("function") or claim.payload.get("queue_name") or claim.payload.get("enumeration_stage") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or claim.payload.get("stage") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    driver_class = str(claim.payload.get("class") or claim.payload.get("driver_class") or claim.payload.get("usb_class") or "").strip()
    callback_field = str(claim.payload.get("callback_field") or "").strip()
    callback_symbol = str(claim.payload.get("callback_symbol") or "").strip()
    driver_table = str(claim.payload.get("driver_table") or "").strip()
    config_macro = str(claim.payload.get("config_macro") or "").strip()
    map_name = str(claim.payload.get("map_name") or "").strip()
    map_kind = str(claim.payload.get("map_kind") or "").strip()
    queue_api = str(claim.payload.get("queue_api") or claim.payload.get("event_queue_api") or "").strip()
    queue_name = str(claim.payload.get("queue_name") or "").strip()
    osal_profile = str(claim.payload.get("osal_profile") or "").strip()
    controller_port = str(claim.payload.get("controller_port_path") or claim.payload.get("selected_controller_port") or "").strip()
    hcd_api = str(claim.payload.get("hcd_api") or claim.payload.get("hcd_transfer_api") or "").strip()
    stage = str(claim.payload.get("enumeration_stage") or claim.payload.get("transfer_lifecycle_stage") or claim.payload.get("stage") or "").strip()
    runtime_model = str(claim.payload.get("runtime_model") or "").strip()
    stage_api = str(claim.payload.get("stage_api") or "").strip()
    via_function = str(claim.payload.get("via_function") or "").strip()
    hardware_boundary = claim.payload.get("hardware_boundary")
    consumes_event_queue = claim.payload.get("consumes_event_queue")
    queues_event = claim.payload.get("queues_event")
    handles_device_attach = claim.payload.get("handles_device_attach")
    handles_transfer_complete = claim.payload.get("handles_transfer_complete")
    dispatches_enumeration = claim.payload.get("dispatches_enumeration")
    dispatches_class_xfer_callback = claim.payload.get("dispatches_class_xfer_callback")

    facts = _active_facts(repo, "fact_type='tinyusb_host_runtime'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("api_name"),
            fact.payload.get("api_qualified_name"),
            fact.payload.get("driver_table"),
            fact.payload.get("driver_class"),
            fact.payload.get("usb_class"),
            fact.payload.get("callback_field"),
            fact.payload.get("callback_symbol"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("map_name"),
            fact.payload.get("endpoint_map"),
            fact.payload.get("interface_map"),
            fact.payload.get("queue_api"),
            fact.payload.get("queue_name"),
            fact.payload.get("event_source"),
            fact.payload.get("task_function"),
            fact.payload.get("dispatch_function"),
            fact.payload.get("via_function"),
            fact.payload.get("hcd_transfer_api"),
            fact.payload.get("controller_port_path"),
            fact.payload.get("selected_controller_port"),
            fact.payload.get("enumeration_stage"),
            fact.payload.get("stage_api"),
            fact.payload.get("runtime_model"),
        ]
        values.extend(fact.payload.get("callback_symbols") or [])
        values.extend(fact.payload.get("callback_fields") or [])
        values.extend(fact.payload.get("candidate_qualified_names") or [])
        values.extend(fact.payload.get("hcd_api_calls") or [])

        if wanted and not any(_names_match(str(v), wanted) or str(v) == wanted for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if driver_class and not any(_names_match(str(v), driver_class) for v in [fact.payload.get("driver_class"), fact.payload.get("usb_class"), fact.subject] if v):
            continue
        if callback_field and not _names_match(str(fact.payload.get("callback_field") or fact.object or ""), callback_field):
            continue
        if callback_symbol:
            symbol_values = [fact.payload.get("callback_symbol"), fact.object, fact.payload.get("callback_qualified_name")]
            symbol_values.extend(fact.payload.get("candidate_qualified_names") or [])
            if not any(_names_match(str(v), callback_symbol) or str(v) == callback_symbol for v in symbol_values if v):
                continue
        if driver_table and not _names_match(str(fact.payload.get("driver_table") or fact.object or ""), driver_table):
            continue
        if config_macro and str(fact.payload.get("config_macro") or "") != config_macro:
            continue
        if map_name:
            map_values = [fact.payload.get("map_name"), fact.payload.get("endpoint_map"), fact.payload.get("interface_map"), fact.subject]
            if not any(str(v) == map_name or str(v).endswith("." + map_name) or map_name in str(v) for v in map_values if v):
                continue
        if map_kind and str(fact.payload.get("map_kind") or fact.object or "") != map_kind:
            continue
        if queue_api:
            queue_values = [fact.payload.get("queue_api"), fact.payload.get("event_queue_api"), fact.object]
            if not any(str(v) == queue_api or _names_match(str(v), queue_api) for v in queue_values if v):
                continue
        if queue_name and not _names_match(str(fact.payload.get("queue_name") or fact.subject or ""), queue_name):
            continue
        if osal_profile and str(fact.payload.get("osal_profile") or "") != osal_profile:
            continue
        if controller_port:
            port_values = [fact.payload.get("controller_port_path"), fact.payload.get("selected_controller_port")]
            if not any(str(v) == controller_port or str(v).endswith("/" + controller_port) or controller_port.endswith("/" + str(v)) for v in port_values if v):
                continue
        if hcd_api:
            hcd_values = [fact.payload.get("hcd_transfer_api"), fact.payload.get("api_name")]
            hcd_values.extend(fact.payload.get("hcd_api_calls") or [])
            if not any(str(v) == hcd_api or _names_match(str(v), hcd_api) for v in hcd_values if v):
                continue
        if stage:
            stage_values = [fact.payload.get("enumeration_stage"), fact.payload.get("transfer_lifecycle_stage"), fact.object]
            if not any(str(v) == stage or _names_match(str(v), stage) for v in stage_values if v):
                continue
        if stage_api and not _names_match(str(fact.payload.get("stage_api") or fact.subject or ""), stage_api):
            continue
        if runtime_model and str(fact.payload.get("runtime_model") or "") != runtime_model:
            continue
        if via_function and str(fact.payload.get("via_function") or "") != via_function:
            continue
        for key, expected_bool in [
            ("hardware_boundary", hardware_boundary),
            ("consumes_event_queue", consumes_event_queue),
            ("queues_event", queues_event),
            ("handles_device_attach", handles_device_attach),
            ("handles_transfer_complete", handles_transfer_complete),
            ("dispatches_enumeration", dispatches_enumeration),
            ("dispatches_class_xfer_callback", dispatches_class_xfer_callback),
        ]:
            if expected_bool is not None and bool(fact.payload.get(key)) != bool(expected_bool):
                break
        else:
            matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_host_runtime_semantic_supported",
            "tinyusb_host_runtime_semantic_conditional",
            "TinyUSB host runtime semantic evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_host_runtime_semantic_not_matched",
            message="TinyUSB host-runtime facts exist, but none matched the requested host class-driver, enumeration, HCD boundary, queue, or dispatch claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_host_runtime_semantic_not_matched", "Host runtime evidence exists, but the requested class-driver, enumeration, HCD boundary, queue, or dispatch semantic was not found.")],
            response_constraints=["Do not claim this TinyUSB host runtime semantic unless matching tinyusb_host_runtime evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_host_runtime_semantic_not_found", "No TinyUSB host runtime semantic evidence was found in the current index.")


def _verify_tinyusb_class_protocol_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    wanted = str(claim.subject or claim.payload.get("api_name") or claim.payload.get("callback_name") or claim.payload.get("class") or claim.payload.get("usb_class") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or claim.payload.get("operation") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    usb_class = str(claim.payload.get("class") or claim.payload.get("usb_class") or claim.payload.get("driver_class") or "").strip()
    api_name = str(claim.payload.get("api_name") or "").strip()
    callback_name = str(claim.payload.get("callback_name") or "").strip()
    protocol_operation = str(claim.payload.get("protocol_operation") or claim.payload.get("operation") or "").strip()
    protocol_stage = str(claim.payload.get("protocol_stage") or claim.payload.get("stage") or "").strip()
    report_kind = str(claim.payload.get("report_kind") or "").strip()
    report_id = str(claim.payload.get("report_id") or "").strip()
    scsi_command = str(claim.payload.get("scsi_command") or "").strip()
    transfer_direction = str(claim.payload.get("transfer_direction") or claim.payload.get("direction") or "").strip()
    descriptor_kind = str(claim.payload.get("descriptor_kind") or "").strip()

    facts = _active_facts(repo, "fact_type='tinyusb_class_protocol'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("usb_class"),
            fact.payload.get("class_name"),
            fact.payload.get("api_name"),
            fact.payload.get("api_qualified_name"),
            fact.payload.get("callback_name"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("protocol_operation"),
            fact.payload.get("protocol_stage"),
            fact.payload.get("report_kind"),
            fact.payload.get("report_id"),
            fact.payload.get("scsi_command"),
            fact.payload.get("transfer_direction"),
            fact.payload.get("descriptor_kind"),
            fact.payload.get("descriptor_array"),
            fact.payload.get("descriptor_macro"),
        ]
        values.extend(fact.payload.get("candidate_qualified_names") or [])
        values.extend(fact.payload.get("report_ids") or [])
        values.extend(fact.payload.get("report_kinds") or [])
        values.extend(fact.payload.get("class_callbacks") or [])
        values.extend(fact.payload.get("protocol_apis") or [])

        if wanted and not any(_names_match(str(v), wanted) or str(v) == wanted for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if usb_class and not any(_names_match(str(v), usb_class) for v in [fact.payload.get("usb_class"), fact.payload.get("class_name"), fact.subject] if v):
            continue
        if api_name and not _names_match(str(fact.payload.get("api_name") or fact.subject or ""), api_name):
            continue
        if callback_name and not _names_match(str(fact.payload.get("callback_name") or fact.subject or ""), callback_name):
            continue
        if protocol_operation and str(fact.payload.get("protocol_operation") or fact.object or "") != protocol_operation:
            continue
        if protocol_stage and str(fact.payload.get("protocol_stage") or fact.object or "") != protocol_stage:
            continue
        if report_kind and not _names_match(str(fact.payload.get("report_kind") or fact.object or ""), report_kind):
            continue
        if report_id:
            ids = [fact.payload.get("report_id"), fact.object]
            ids.extend(fact.payload.get("report_ids") or [])
            if not any(str(v) == report_id or _names_match(str(v), report_id) for v in ids if v):
                continue
        if scsi_command and not _names_match(str(fact.payload.get("scsi_command") or fact.object or ""), scsi_command):
            continue
        if transfer_direction and str(fact.payload.get("transfer_direction") or "") != transfer_direction:
            continue
        if descriptor_kind and str(fact.payload.get("descriptor_kind") or "") != descriptor_kind:
            continue
        matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_class_protocol_semantic_supported",
            "tinyusb_class_protocol_semantic_conditional",
            "TinyUSB class-specific protocol evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_class_protocol_semantic_not_matched",
            message="TinyUSB class-protocol facts exist, but none matched the requested CDC/MSC/HID semantic claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_class_protocol_semantic_not_matched", "Class-specific protocol evidence exists, but the requested CDC, MSC, HID, descriptor, report, or callback semantic was not found.")],
            response_constraints=["Do not claim this TinyUSB class-specific protocol semantic unless matching tinyusb_class_protocol evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_class_protocol_semantic_not_found", "No TinyUSB class-specific protocol evidence was found in the current index.")



def _verify_tinyusb_typec_pd_semantic(repo: str | Path, claim: Claim) -> ClaimVerdict:
    wanted = str(claim.subject or claim.payload.get("api_name") or claim.payload.get("callback_name") or claim.payload.get("event_id") or claim.payload.get("pd_message_type") or "").strip()
    expected = str(claim.object or claim.payload.get("object") or claim.payload.get("value") or claim.payload.get("operation") or "").strip()
    predicate = str(claim.payload.get("predicate") or "").strip()
    api_name = str(claim.payload.get("api_name") or "").strip()
    callback_name = str(claim.payload.get("callback_name") or "").strip()
    event_id = str(claim.payload.get("event_id") or "").strip()
    event_kind = str(claim.payload.get("event_kind") or "").strip()
    pd_message_type = str(claim.payload.get("pd_message_type") or claim.payload.get("message_type") or "").strip()
    message_category = str(claim.payload.get("message_category") or "").strip()
    power_role = str(claim.payload.get("power_role") or "").strip()
    data_role = str(claim.payload.get("data_role") or "").strip()
    tcd_api = str(claim.payload.get("tcd_api") or claim.payload.get("tcd_api_call") or "").strip()
    protocol_stage = str(claim.payload.get("protocol_stage") or claim.payload.get("stage") or "").strip()
    policy_action = str(claim.payload.get("policy_action") or "").strip()
    hardware_boundary = claim.payload.get("hardware_boundary")
    uses_osal_queue = claim.payload.get("uses_osal_queue")

    facts = _active_facts(repo, "fact_type='tinyusb_typec_pd'")
    matched: list[CodeFact] = []
    for fact in facts:
        values = [
            fact.subject,
            fact.object,
            fact.predicate,
            fact.payload.get("api_name"),
            fact.payload.get("api_qualified_name"),
            fact.payload.get("callback_name"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("event_id"),
            fact.payload.get("event_kind"),
            fact.payload.get("pd_message_type"),
            fact.payload.get("message_category"),
            fact.payload.get("power_role"),
            fact.payload.get("data_role"),
            fact.payload.get("protocol_stage"),
            fact.payload.get("policy_action"),
            fact.payload.get("queue_api"),
            fact.payload.get("controller_port_path"),
        ]
        values.extend(fact.payload.get("tcd_api_calls") or [])
        values.extend(fact.payload.get("event_ids") or [])
        values.extend((fact.payload.get("pd_header_fields") or {}).values())
        values.extend(fact.payload.get("pdo_types") or [])

        if wanted and not any(_names_match(str(v), wanted) or str(v) == wanted for v in values if v):
            continue
        if expected and not any(_names_match(str(v), expected) or str(v) == expected for v in values if v):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if api_name and not _names_match(str(fact.payload.get("api_name") or fact.subject or ""), api_name):
            continue
        if callback_name and not _names_match(str(fact.payload.get("callback_name") or fact.subject or fact.object or ""), callback_name):
            continue
        if event_id:
            ids = [fact.payload.get("event_id"), fact.subject, fact.object]
            ids.extend(fact.payload.get("event_ids") or [])
            if not any(str(v) == event_id or _names_match(str(v), event_id) for v in ids if v):
                continue
        if event_kind and not _names_match(str(fact.payload.get("event_kind") or fact.object or ""), event_kind):
            continue
        if pd_message_type and not any(_names_match(str(v), pd_message_type) for v in [fact.payload.get("pd_message_type"), fact.object, fact.subject] if v):
            continue
        if message_category and str(fact.payload.get("message_category") or "") != message_category:
            continue
        if power_role and not _names_match(str(fact.payload.get("power_role") or ""), power_role):
            continue
        if data_role and not _names_match(str(fact.payload.get("data_role") or ""), data_role):
            continue
        if tcd_api:
            calls = [fact.payload.get("api_name"), fact.subject, fact.object]
            calls.extend(fact.payload.get("tcd_api_calls") or [])
            if not any(_names_match(str(v), tcd_api) for v in calls if v):
                continue
        if protocol_stage and str(fact.payload.get("protocol_stage") or "") != protocol_stage:
            continue
        if policy_action and str(fact.payload.get("policy_action") or "") != policy_action:
            continue
        if hardware_boundary is not None and bool(fact.payload.get("hardware_boundary")) is not bool(hardware_boundary):
            continue
        if uses_osal_queue is not None and bool(fact.payload.get("uses_osal_queue")) is not bool(uses_osal_queue):
            continue
        matched.append(fact)

    if matched:
        return _verdict_from_support(
            claim,
            matched[:10],
            "tinyusb_typec_pd_semantic_supported",
            "tinyusb_typec_pd_semantic_conditional",
            "TinyUSB Type-C/USB-PD semantic evidence matched the claim.",
        )
    if facts:
        return ClaimVerdict(
            claim=claim,
            verdict="unknown",
            reason_code="tinyusb_typec_pd_semantic_not_matched",
            message="TinyUSB Type-C/USB-PD facts exist, but none matched the requested semantic claim.",
            supporting_facts=facts[:10],
            unknowns=[UnknownFact("tinyusb_typec_pd_semantic_not_matched", "Type-C/USB-PD evidence exists, but the requested TUC/TCD/event/PD-message/policy semantic was not found.")],
            response_constraints=["Do not claim this TinyUSB Type-C/USB-PD semantic unless matching tinyusb_typec_pd evidence is present for the active target."],
        )
    return _unknown(claim, "tinyusb_typec_pd_semantic_not_found", "No TinyUSB Type-C/USB-PD semantic evidence was found in the current index.")


def _paths_match(value: str, wanted: str) -> bool:
    left = value.strip().replace("\\", "/").strip("/")
    right = wanted.strip().replace("\\", "/").strip("/")
    return bool(left and right) and (left == right or left.endswith("/" + right) or right.endswith("/" + left))

def _verify_callback_registers(repo: str | Path, claim: Claim) -> ClaimVerdict:
    if not claim.subject or not claim.object:
        return _unknown(claim, "claim_missing_endpoint", "callback_registers requires subject and object.")
    relations = _active_facts(repo, "fact_type='relation' AND predicate='registers_callback'")
    matched = []
    for fact in relations:
        api_values = [fact.subject, fact.payload.get("api_name"), fact.payload.get("api_qualified_name")]
        callback_values = [fact.object, fact.payload.get("callback_symbol"), fact.payload.get("callback_qualified_name")]
        callback_values.extend(fact.payload.get("candidate_qualified_names") or [])
        callback_values.extend(fact.payload.get("global_candidate_qualified_names") or [])
        if any(_names_match(str(v), claim.subject) for v in api_values if v) and any(_names_match(str(v), claim.object) for v in callback_values if v):
            matched.append(fact)
    if matched:
        unknowns = unknowns_for_facts(matched)
        if not any(u.unknown_type == "callback_relation_not_execution" for u in unknowns):
            unknowns.append(UnknownFact("callback_relation_not_execution", "Callback registration is not direct execution evidence."))
        return ClaimVerdict(
            claim=claim,
            verdict="supported" if not has_conditional_evidence(matched, unknowns) else "conditional",
            reason_code="callback_registration_supported",
            message=f"Callback registration evidence was found from {claim.subject} to {claim.object}.",
            supporting_facts=matched,
            unknowns=unknowns,
            response_constraints=constraints_for_facts(matched) + ["A supported callback registration claim does not imply the callback executes on every path."],
        )
    return _unknown(claim, "callback_registration_not_found", f"No callback registration evidence was found from {claim.subject} to {claim.object}.")
