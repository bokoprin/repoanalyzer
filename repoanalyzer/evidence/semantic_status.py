from __future__ import annotations

from repoanalyzer.core.models import CodeFact, UnknownFact

_SEMANTIC_UNKNOWN_MESSAGES = {
    "ambiguous_symbol_resolution": "A symbol name maps to multiple scoped candidates; do not collapse same-named symbols across scopes.",
    "ambiguous_overload_resolution": "A call has multiple overload candidates and the current argument evidence does not select one.",
    "unresolved_member_receiver_type": "A member call receiver type could not be inferred by the lightweight semantic extractor.",
    "unresolved_call_target": "A call target could not be resolved against the current semantic symbol table.",
    "indirect_call_unresolved": "An indirect function-pointer call has candidate targets but is not a guaranteed direct runtime call.",
    "callback_relation_not_execution": "A callback relation was found; registration is not the same as direct execution.",
    "callback_target_unknown": "A callback invocation site was found, but the concrete runtime callback target could not be resolved from local evidence.",
    "task_entry_execution_deferred": "A task entry was registered for deferred scheduler execution rather than directly called.",
    "scheduler_dependent_execution": "The task entry depends on scheduler/context-switch/port-layer behavior before it can execute.",
    "interrupt_mask_state_deferred": "The exact interrupt mask state is runtime/port dependent; do not infer full interrupt state from this local evidence alone.",
    "port_layer_boundary": "The evidence reaches a FreeRTOS port-layer boundary; behavior beyond this point depends on the selected port implementation.",
    "assembly_boundary_unverified": "The path may continue through assembly or compiler/architecture-specific startup code that is not verified by the C-source evidence.",
    "vector_table_unverified": "The interrupt/exception entry binding depends on a vector table or startup file that is not verified by this evidence.",
    "startup_file_missing": "The startup/linker/vector setup needed to prove the runtime entry path is not present in the analyzed evidence.",
    "port_stack_layout_target_specific": "Task stack initialization is target-specific; do not infer exact runtime stack/context-switch behavior without port-specific evidence.",
    "smp_runtime_interleaving_unknown": "SMP scheduler evidence depends on runtime inter-core scheduling state; do not infer exact core interleaving from local C evidence.",
    "core_affinity_runtime_state_unknown": "Core-affinity evidence depends on runtime task affinity masks and selected core count.",
    "cross_core_yield_target_unknown": "Cross-core yield evidence requests or marks a yield; it does not prove which core switches immediately.",
    "smp_lock_order_runtime_unknown": "SMP lock evidence does not prove complete runtime lock ordering or contention behavior.",
    "mpu_port_configuration_required": "MPU wrapper evidence depends on selecting an MPU-capable port and configuration.",
    "mpu_region_layout_target_specific": "MPU region setup is target/application specific; do not infer exact memory permissions without region evidence.",
    "mpu_access_policy_target_specific": "MPU access checks depend on the selected MPU port policy and runtime address/size inputs.",
    "privilege_boundary_target_specific": "Privilege-boundary behavior depends on MPU port, privilege mode, and syscall/SVC setup.",
    "secure_context_boundary_unverified": "Secure-context behavior depends on the selected secure port and secure context implementation.",
    "port_advanced_target_specific": "Advanced FreeRTOS port/SMP/MPU semantics are target specific and require profile/port qualification.",
    "configNUMBER_OF_CORES_profile_dependent": "SMP evidence depends on configNUMBER_OF_CORES and the selected target profile.",
    "mpu_wrapper_configuration_dependent": "MPU wrapper evidence depends on portUSING_MPU_WRAPPERS and MPU wrapper configuration.",
    "trace_hook_target_unknown": "A FreeRTOS trace macro was invoked, but the concrete trace hook implementation is application/configuration dependent.",
    "assert_handler_config_dependent": "configASSERT was found, but assert behavior depends on the application's FreeRTOSConfig.h definition.",
    "application_defined_hook_target_unknown": "An application hook was invoked, but the application-defined hook body may be outside the analyzed source.",
    "coverage_marker_not_runtime_behavior": "A coverage/test marker was found; it is diagnostic evidence, not ordinary runtime kernel behavior.",
    "virtual_dispatch_candidates": "A virtual call has runtime dispatch candidates; the actual target depends on receiver runtime type.",
    "unsupported_cpp_construct": "The current semantic extractor does not support this C++ construct; keep conclusions scoped to extracted evidence.",
    "cross_tu_ambiguous_resolution": "A cross-translation-unit lookup found multiple candidates; do not claim one target without more evidence.",
}


def semantic_unknowns(facts: list[CodeFact]) -> list[UnknownFact]:
    grouped: dict[str, list[str]] = {}
    for fact in facts:
        unknown_values = []
        if fact.payload.get("unknown_type"):
            unknown_values.append(fact.payload.get("unknown_type"))
        for value in fact.payload.get("unknown_types") or []:
            if value not in unknown_values:
                unknown_values.append(value)
        for unknown_type in unknown_values:
            if unknown_type not in _SEMANTIC_UNKNOWN_MESSAGES:
                continue
            label = _affected_label(fact)
            grouped.setdefault(unknown_type, [])
            if label not in grouped[unknown_type]:
                grouped[unknown_type].append(label)
    return [
        UnknownFact(unknown_type, _SEMANTIC_UNKNOWN_MESSAGES[unknown_type], severity="medium", affects=affects)
        for unknown_type, affects in grouped.items()
    ]


def _affected_label(fact: CodeFact) -> str:
    if fact.caller and fact.callee:
        return f"{fact.caller}->{fact.callee}"
    if fact.subject and fact.object:
        return f"{fact.subject}->{fact.object}"
    if fact.qualified_name:
        return fact.qualified_name
    if fact.symbol:
        return fact.symbol
    return fact.path
