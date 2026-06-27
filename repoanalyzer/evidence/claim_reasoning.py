from __future__ import annotations

from repoanalyzer.core.models import CodeFact, UnknownFact
from repoanalyzer.evidence.build_status import build_context_unknowns
from repoanalyzer.evidence.semantic_status import semantic_unknowns
from repoanalyzer.evidence.constraints import constraints_from_unknowns

CONDITIONAL_RESOLUTION_STATUSES = {"conditional", "candidate_set", "ambiguous", "unresolved"}
CONDITIONAL_UNKNOWN_TYPES = {
    "conditional_build_evidence",
    "unsupported_preprocessor_expression",
    "ambiguous_symbol_resolution",
    "ambiguous_overload_resolution",
    "unresolved_member_receiver_type",
    "unresolved_call_target",
    "indirect_call_unresolved",
    "callback_relation_not_execution",
    "callback_target_unknown",
    "task_entry_execution_deferred",
    "scheduler_dependent_execution",
    "interrupt_mask_state_deferred",
    "port_layer_boundary",
    "assembly_boundary_unverified",
    "vector_table_unverified",
    "startup_file_missing",
    "port_stack_layout_target_specific",
    "smp_runtime_interleaving_unknown",
    "core_affinity_runtime_state_unknown",
    "cross_core_yield_target_unknown",
    "smp_lock_order_runtime_unknown",
    "mpu_port_configuration_required",
    "mpu_region_layout_target_specific",
    "mpu_access_policy_target_specific",
    "privilege_boundary_target_specific",
    "secure_context_boundary_unverified",
    "port_advanced_target_specific",
    "configNUMBER_OF_CORES_profile_dependent",
    "mpu_wrapper_configuration_dependent",
    "trace_hook_target_unknown",
    "assert_handler_config_dependent",
    "application_defined_hook_target_unknown",
    "coverage_marker_not_runtime_behavior",
    "virtual_dispatch_candidates",
    "unsupported_cpp_construct",
    "header_unattributed_evidence",
    "source_without_compile_commands",
    "unresolved_include_evidence",
}


def fact_build_status(fact: CodeFact) -> str:
    return str(fact.payload.get("build_status") or "active")


def has_conditional_evidence(facts: list[CodeFact], unknowns: list[UnknownFact]) -> bool:
    if any(fact_build_status(fact) != "active" for fact in facts):
        return True
    for fact in facts:
        if fact.payload.get("resolution_status") in CONDITIONAL_RESOLUTION_STATUSES:
            return True
        if fact.payload.get("callback_resolution_status") in {"candidate_set", "resolved_candidate"}:
            return True
        if fact.payload.get("unknown_type") in CONDITIONAL_UNKNOWN_TYPES:
            return True
    if any(unknown.unknown_type in CONDITIONAL_UNKNOWN_TYPES for unknown in unknowns):
        return True
    return False


def unknowns_for_facts(facts: list[CodeFact]) -> list[UnknownFact]:
    by_type: dict[str, UnknownFact] = {}
    for unknown in [*build_context_unknowns(facts), *semantic_unknowns(facts)]:
        by_type.setdefault(unknown.unknown_type, unknown)
    return list(by_type.values())


def constraints_for_facts(facts: list[CodeFact]) -> list[str]:
    return constraints_from_unknowns(unknowns_for_facts(facts))


def verdict_for_positive_support(facts: list[CodeFact], *, supported_reason: str, conditional_reason: str) -> tuple[str, str, list[UnknownFact], list[str]]:
    unknowns = unknowns_for_facts(facts)
    constraints = constraints_from_unknowns(unknowns)
    if has_conditional_evidence(facts, unknowns):
        return "conditional", conditional_reason, unknowns, constraints
    return "supported", supported_reason, unknowns, constraints
