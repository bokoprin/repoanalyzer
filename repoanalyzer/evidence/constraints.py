from __future__ import annotations

from repoanalyzer.core.models import UnknownFact


def constraints_from_unknowns(unknowns: list[UnknownFact]) -> list[str]:
    constraints: list[str] = []
    for unknown in unknowns:
        if unknown.unknown_type == "call_graph_incomplete":
            constraints.append("Do not claim that no path exists; say the current index did not provide enough call graph evidence.")
        if unknown.unknown_type == "definition_not_found":
            constraints.append("Do not infer a definition location without evidence.")
        if unknown.unknown_type == "conditional_build_evidence":
            constraints.append("Facts marked build_status=conditional are guarded by unresolved preprocessor conditions; describe them as conditional, not definitely active in the target build.")
        if unknown.unknown_type == "source_without_compile_commands":
            constraints.append("Facts from source_without_compile_commands were scanned without a compile_commands entry; avoid claiming target-build completeness.")
        if unknown.unknown_type == "header_unattributed_evidence":
            constraints.append("Facts from header_unattributed contexts may depend on the including translation unit; prefer projected header facts when available.")
        if unknown.unknown_type == "unresolved_include_evidence":
            constraints.append("Do not assume unresolved include targets are absent; say the current include resolution did not find them.")
        if unknown.unknown_type == "unsupported_preprocessor_expression":
            constraints.append("Facts guarded by unsupported preprocessor expressions are conditional; do not claim their target-build activity is known until the expression is supported or manually verified.")
        if unknown.unknown_type == "index_freshness":
            constraints.append("The repository has changed since ingest; re-run ingest before making completeness or absence claims from this index.")
        if unknown.unknown_type == "ambiguous_symbol_resolution":
            constraints.append("Do not collapse same-named symbols across scopes; mention candidate qualified names.")
        if unknown.unknown_type == "ambiguous_overload_resolution":
            constraints.append("Do not claim a specific overload unless argument evidence resolves it.")
        if unknown.unknown_type == "unresolved_member_receiver_type":
            constraints.append("Do not infer the member target without receiver type evidence.")
        if unknown.unknown_type == "unresolved_call_target":
            constraints.append("Do not claim a call target was resolved when the semantic index only has an unresolved reference.")
        if unknown.unknown_type == "indirect_call_unresolved":
            constraints.append("Treat indirect call targets as candidates, not guaranteed runtime calls.")
        if unknown.unknown_type == "callback_relation_not_execution":
            constraints.append("A callback registration/storage relation is not the same as a direct call path or guaranteed execution.")
        if unknown.unknown_type == "callback_target_unknown":
            constraints.append("A callback invocation site was found, but the concrete runtime callback target remains unknown; do not present it as a direct call to a specific function.")
        if unknown.unknown_type == "task_entry_execution_deferred":
            constraints.append("Task-entry dataflow is not a direct function call; describe it as deferred execution prepared through TCB/stack initialisation.")
        if unknown.unknown_type == "scheduler_dependent_execution":
            constraints.append("Task-entry execution depends on scheduler/context-switch/port-layer behavior; do not claim it executes immediately or on every path.")
        if unknown.unknown_type == "port_layer_boundary":
            constraints.append("The evidence reaches a FreeRTOS port-layer boundary; say that behavior beyond this point is target/port specific.")
        if unknown.unknown_type == "assembly_boundary_unverified":
            constraints.append("Do not claim the path is fully verified past assembly/compiler-specific code unless assembly/startup evidence is available.")
        if unknown.unknown_type == "vector_table_unverified":
            constraints.append("Do not infer interrupt/exception entry binding without vector-table or startup-file evidence.")
        if unknown.unknown_type == "startup_file_missing":
            constraints.append("Mention that startup/linker/vector setup was not verified for this path.")
        if unknown.unknown_type == "port_stack_layout_target_specific":
            constraints.append("Treat task stack initialisation as target-specific; do not infer exact runtime stack/context-switch behavior from generic C evidence alone.")
        if unknown.unknown_type in {"smp_runtime_interleaving_unknown", "core_affinity_runtime_state_unknown", "cross_core_yield_target_unknown", "smp_lock_order_runtime_unknown", "configNUMBER_OF_CORES_profile_dependent"}:
            constraints.append("Qualify SMP/core-affinity/yield evidence by configNUMBER_OF_CORES, runtime core state, and selected port; do not infer exact inter-core scheduling from local C evidence alone.")
        if unknown.unknown_type in {"mpu_port_configuration_required", "mpu_region_layout_target_specific", "mpu_access_policy_target_specific", "privilege_boundary_target_specific", "mpu_wrapper_configuration_dependent"}:
            constraints.append("Qualify MPU/privilege evidence by the selected MPU-capable port, wrapper configuration, and concrete memory-region setup.")
        if unknown.unknown_type == "secure_context_boundary_unverified":
            constraints.append("Do not infer secure-context behavior without secure-port/startup evidence.")
        if unknown.unknown_type == "port_advanced_target_specific":
            constraints.append("Advanced FreeRTOS port semantics are target-specific; keep answers scoped to the selected profile and available port evidence.")
        if unknown.unknown_type == "mixed_execution_context":
            constraints.append("Evidence spans both ISR and task contexts; keep those execution contexts separate and do not describe the path as a single uniform context.")
        if unknown.unknown_type == "virtual_dispatch_candidates":
            constraints.append("Virtual dispatch candidates depend on runtime receiver type; do not claim all candidates execute.")
        if unknown.unknown_type == "unsupported_cpp_construct":
            constraints.append("The current semantic extractor does not support this C++ construct; keep the answer scoped to extracted evidence.")
        if unknown.unknown_type == "upstream_source_missing":
            constraints.append("Do not present the claim as upstream-source verified; mention that upstream source evidence is missing and scope the answer to available compact evidence.")
        if unknown.unknown_type == "no_upstream_metadata":
            constraints.append("Treat compact-only evidence as snapshot-scoped; do not imply it has been validated against upstream source files.")
        if unknown.unknown_type == "upstream_metadata_not_source_path":
            constraints.append("Do not use non-source upstream metadata as direct source-code evidence.")
        if unknown.unknown_type == "some_upstream_refs_skipped":
            constraints.append("Mention that some upstream references were skipped and therefore the trace is only partially source-validated.")
        if unknown.unknown_type == "weak_anchor_match":
            constraints.append("Do not overstate traceability when upstream anchors are weak or manifest-linked only.")
        if unknown.unknown_type == "source_coverage_not_mapped":
            constraints.append("A coverage report exists but did not map these facts; avoid upstream coverage claims for this evidence.")
        if unknown.unknown_type == "compact_source_missing":
            constraints.append("Do not rely on missing compact evidence files; regenerate the snapshot or fetch the missing source.")
        if unknown.unknown_type == "compact_sha256_mismatch":
            constraints.append("Do not rely on compact evidence with a manifest hash mismatch; regenerate the snapshot before answering.")
    return constraints
