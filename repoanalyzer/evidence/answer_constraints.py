from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from repoanalyzer.core.models import CodeFact


@dataclass(frozen=True)
class AnswerBuildContext:
    """Normalized build/target context that must shape final answers.

    This is deliberately small and JSON-friendly. It is not a renderer; it is a
    contract payload that tells an LLM which build/profile qualifications must
    be preserved when turning evidence into prose.
    """

    target_profiles: list[str] = field(default_factory=list)
    macros: dict[str, str] = field(default_factory=dict)
    active_files: list[str] = field(default_factory=list)
    inactive_files: list[str] = field(default_factory=list)
    conditional_files: list[str] = field(default_factory=list)
    inactive_symbols: list[str] = field(default_factory=list)
    conditional_symbols: list[str] = field(default_factory=list)
    build_conditions: list[dict[str, Any]] = field(default_factory=list)
    allocation_profile: dict[str, str] = field(default_factory=dict)
    api_contexts: dict[str, str] = field(default_factory=dict)
    isr_apis: list[str] = field(default_factory=list)
    task_context_apis: list[str] = field(default_factory=list)
    api_context_pairs: list[dict[str, str]] = field(default_factory=list)
    scheduler_semantics: list[dict[str, Any]] = field(default_factory=list)
    critical_section_functions: list[str] = field(default_factory=list)
    scheduler_control_functions: list[str] = field(default_factory=list)
    context_switch_requesters: list[str] = field(default_factory=list)
    interrupt_mask_functions: list[str] = field(default_factory=list)
    port_boundaries: list[dict[str, Any]] = field(default_factory=list)
    port_boundary_callers: list[str] = field(default_factory=list)
    port_boundary_callees: list[str] = field(default_factory=list)
    port_layer_functions: list[str] = field(default_factory=list)
    assembly_boundary_functions: list[str] = field(default_factory=list)
    vector_table_unverified_functions: list[str] = field(default_factory=list)
    task_state_transitions: list[dict[str, Any]] = field(default_factory=list)
    ready_list_functions: list[str] = field(default_factory=list)
    delayed_list_functions: list[str] = field(default_factory=list)
    event_blocking_functions: list[str] = field(default_factory=list)
    event_unblocking_functions: list[str] = field(default_factory=list)
    kernel_object_semantics: list[dict[str, Any]] = field(default_factory=list)
    stream_buffer_functions: list[str] = field(default_factory=list)
    message_buffer_functions: list[str] = field(default_factory=list)
    event_group_functions: list[str] = field(default_factory=list)
    task_notification_functions: list[str] = field(default_factory=list)
    semaphore_functions: list[str] = field(default_factory=list)
    mutex_functions: list[str] = field(default_factory=list)
    hook_assert_trace_semantics: list[dict[str, Any]] = field(default_factory=list)
    trace_hook_functions: list[str] = field(default_factory=list)
    assert_handler_functions: list[str] = field(default_factory=list)
    application_hook_functions: list[str] = field(default_factory=list)
    coverage_marker_functions: list[str] = field(default_factory=list)
    heap_allocator_semantics: list[dict[str, Any]] = field(default_factory=list)
    heap_allocation_functions: list[str] = field(default_factory=list)
    heap_free_functions: list[str] = field(default_factory=list)
    heap_coalescing_functions: list[str] = field(default_factory=list)
    heap_libc_allocator_functions: list[str] = field(default_factory=list)
    heap_multi_region_functions: list[str] = field(default_factory=list)
    port_advanced_semantics: list[dict[str, Any]] = field(default_factory=list)
    smp_functions: list[str] = field(default_factory=list)
    core_affinity_functions: list[str] = field(default_factory=list)
    smp_lock_functions: list[str] = field(default_factory=list)
    mpu_functions: list[str] = field(default_factory=list)
    privilege_boundary_functions: list[str] = field(default_factory=list)
    port_assembly_functions: list[str] = field(default_factory=list)
    secure_context_functions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "target_profiles": list(self.target_profiles),
            "macros": dict(self.macros),
            "active_files": list(self.active_files),
            "inactive_files": list(self.inactive_files),
            "conditional_files": list(self.conditional_files),
            "inactive_symbols": list(self.inactive_symbols),
            "conditional_symbols": list(self.conditional_symbols),
            "build_conditions": list(self.build_conditions),
            "allocation_profile": dict(self.allocation_profile),
            "api_contexts": dict(self.api_contexts),
            "isr_apis": list(self.isr_apis),
            "task_context_apis": list(self.task_context_apis),
            "api_context_pairs": list(self.api_context_pairs),
            "scheduler_semantics": list(self.scheduler_semantics),
            "critical_section_functions": list(self.critical_section_functions),
            "scheduler_control_functions": list(self.scheduler_control_functions),
            "context_switch_requesters": list(self.context_switch_requesters),
            "interrupt_mask_functions": list(self.interrupt_mask_functions),
            "port_boundaries": list(self.port_boundaries),
            "port_boundary_callers": list(self.port_boundary_callers),
            "port_boundary_callees": list(self.port_boundary_callees),
            "port_layer_functions": list(self.port_layer_functions),
            "assembly_boundary_functions": list(self.assembly_boundary_functions),
            "vector_table_unverified_functions": list(self.vector_table_unverified_functions),
            "task_state_transitions": list(self.task_state_transitions),
            "ready_list_functions": list(self.ready_list_functions),
            "delayed_list_functions": list(self.delayed_list_functions),
            "event_blocking_functions": list(self.event_blocking_functions),
            "event_unblocking_functions": list(self.event_unblocking_functions),
            "kernel_object_semantics": list(self.kernel_object_semantics),
            "stream_buffer_functions": list(self.stream_buffer_functions),
            "message_buffer_functions": list(self.message_buffer_functions),
            "event_group_functions": list(self.event_group_functions),
            "task_notification_functions": list(self.task_notification_functions),
            "semaphore_functions": list(self.semaphore_functions),
            "mutex_functions": list(self.mutex_functions),
            "hook_assert_trace_semantics": list(self.hook_assert_trace_semantics),
            "trace_hook_functions": list(self.trace_hook_functions),
            "assert_handler_functions": list(self.assert_handler_functions),
            "application_hook_functions": list(self.application_hook_functions),
            "coverage_marker_functions": list(self.coverage_marker_functions),
            "heap_allocator_semantics": list(self.heap_allocator_semantics),
            "heap_allocation_functions": list(self.heap_allocation_functions),
            "heap_free_functions": list(self.heap_free_functions),
            "heap_coalescing_functions": list(self.heap_coalescing_functions),
            "heap_libc_allocator_functions": list(self.heap_libc_allocator_functions),
            "heap_multi_region_functions": list(self.heap_multi_region_functions),
            "port_advanced_semantics": list(self.port_advanced_semantics),
            "smp_functions": list(self.smp_functions),
            "core_affinity_functions": list(self.core_affinity_functions),
            "smp_lock_functions": list(self.smp_lock_functions),
            "mpu_functions": list(self.mpu_functions),
            "privilege_boundary_functions": list(self.privilege_boundary_functions),
            "port_assembly_functions": list(self.port_assembly_functions),
            "secure_context_functions": list(self.secure_context_functions),
        }
        return {key: value for key, value in data.items() if value not in (None, [], {})}


@dataclass(frozen=True)
class AnswerConstraintSummary:
    response_constraints: list[str] = field(default_factory=list)
    required_qualifications: list[str] = field(default_factory=list)
    answer_obligations: list[str] = field(default_factory=list)
    build_context: AnswerBuildContext = field(default_factory=AnswerBuildContext)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "response_constraints": list(self.response_constraints),
            "required_qualifications": list(self.required_qualifications),
            "answer_obligations": list(self.answer_obligations),
            "build_context": self.build_context.to_dict(),
        }
        return {key: value for key, value in data.items() if value not in (None, [], {})}


def answer_constraints_from_facts(facts: Iterable[CodeFact]) -> AnswerConstraintSummary:
    target_profiles: list[str] = []
    macros: dict[str, str] = {}
    active_files: list[str] = []
    inactive_files: list[str] = []
    conditional_files: list[str] = []
    inactive_symbols: list[str] = []
    conditional_symbols: list[str] = []
    build_conditions: list[dict[str, Any]] = []
    allocation_profile: dict[str, str] = {}
    api_contexts: dict[str, str] = {}
    scheduler_semantics: list[dict[str, Any]] = []
    critical_section_functions: list[str] = []
    scheduler_control_functions: list[str] = []
    context_switch_requesters: list[str] = []
    interrupt_mask_functions: list[str] = []
    port_boundaries: list[dict[str, Any]] = []
    port_boundary_callers: list[str] = []
    port_boundary_callees: list[str] = []
    port_layer_functions: list[str] = []
    assembly_boundary_functions: list[str] = []
    vector_table_unverified_functions: list[str] = []
    task_state_transitions: list[dict[str, Any]] = []
    ready_list_functions: list[str] = []
    delayed_list_functions: list[str] = []
    event_blocking_functions: list[str] = []
    event_unblocking_functions: list[str] = []
    kernel_object_semantics: list[dict[str, Any]] = []
    stream_buffer_functions: list[str] = []
    message_buffer_functions: list[str] = []
    event_group_functions: list[str] = []
    task_notification_functions: list[str] = []
    semaphore_functions: list[str] = []
    mutex_functions: list[str] = []
    hook_assert_trace_semantics: list[dict[str, Any]] = []
    trace_hook_functions: list[str] = []
    assert_handler_functions: list[str] = []
    application_hook_functions: list[str] = []
    coverage_marker_functions: list[str] = []
    heap_allocator_semantics: list[dict[str, Any]] = []
    heap_allocation_functions: list[str] = []
    heap_free_functions: list[str] = []
    heap_coalescing_functions: list[str] = []
    heap_libc_allocator_functions: list[str] = []
    heap_multi_region_functions: list[str] = []
    port_advanced_semantics: list[dict[str, Any]] = []
    smp_functions: list[str] = []
    core_affinity_functions: list[str] = []
    smp_lock_functions: list[str] = []
    mpu_functions: list[str] = []
    privilege_boundary_functions: list[str] = []
    port_assembly_functions: list[str] = []
    secure_context_functions: list[str] = []
    constraints: list[str] = []
    qualifications: list[str] = []
    obligations: list[str] = []

    for fact in facts:
        payload = fact.payload or {}
        profile = _profile_name(fact)
        if profile:
            target_profiles.append(profile)

        if fact.fact_type == "build_config" and fact.predicate == "macro_value":
            macro_name = str(fact.subject or payload.get("macro_name") or "").strip()
            macro_value = str(fact.object or payload.get("macro_value") or "").strip()
            if macro_name and macro_value:
                macros[macro_name] = macro_value
                constraints.append(_scope_prefix(profile) + f"When mentioning build configuration, state that {macro_name}={macro_value} for this target profile.")
                obligations.append(f"Preserve the target macro value {macro_name}={macro_value}.")

        if fact.fact_type == "target_profile" and fact.predicate == "allocation_setting":
            mode = str(payload.get("allocation_mode") or fact.subject or "").replace("_allocation", "").strip()
            setting = str(payload.get("allocation_setting") or fact.object or "").strip()
            macro_name = str(payload.get("macro_name") or "").strip()
            macro_value = str(payload.get("macro_value") or "").strip()
            if mode and setting:
                allocation_profile[mode] = setting
                if macro_name and macro_value:
                    macros[macro_name] = macro_value
                macro_text = f" ({macro_name}={macro_value})" if macro_name and macro_value else ""
                constraints.append(_scope_prefix(profile) + f"When discussing FreeRTOS allocation APIs, state that {mode} allocation is {setting}{macro_text} for this target profile.")
                obligations.append(f"Preserve the {mode} allocation setting when answering API availability questions.")

        if fact.fact_type == "target_file":
            path = str(fact.subject or payload.get("file_path") or fact.path).strip()
            status = str(payload.get("selection_status") or ("active" if fact.predicate == "file_active" else "inactive" if fact.predicate == "file_inactive" else "unknown"))
            reasons = [str(value) for value in payload.get("selection_reasons") or []]
            reason_text = f" because of {', '.join(reasons)}" if reasons else ""
            if status == "active":
                active_files.append(path)
                constraints.append(_scope_prefix(profile) + f"If discussing {path}, identify it as active in the target profile{reason_text}.")
                obligations.append(f"Do not omit that {path} is target-active when using it as behavior evidence.")
            elif status == "inactive":
                inactive_files.append(path)
                constraints.append(_scope_prefix(profile) + f"If discussing {path}, identify it as source-present but inactive in the target profile{reason_text}.")
                constraints.append(f"Do not describe behavior from {path} as active target-build behavior unless a different active target profile is selected.")
                qualifications.append(f"Qualify any claim involving {path}: it is inactive for the indexed target profile.")
                obligations.append(f"Distinguish source presence from target-build activity for {path}.")

        for api_name, context, basis in _execution_context_items(fact):
            if api_name and context in {"isr", "task"}:
                api_contexts.setdefault(api_name, context)
                if context == "isr":
                    constraints.append(_scope_prefix(profile) + f"When discussing {api_name}, identify it as ISR-context evidence; do not use task-context API evidence as a substitute.")
                    obligations.append(f"Preserve the ISR execution context for {api_name}; prefer the matching FromISR API in ISR-context explanations.")
                else:
                    constraints.append(_scope_prefix(profile) + f"When discussing {api_name}, identify it as task-context evidence; do not present it as ISR-safe unless a supported FromISR variant is used.")
                    obligations.append(f"Preserve the task execution context for {api_name}; do not use it as ISR-context evidence without a supported FromISR counterpart.")

        sched = _scheduler_semantic_item(fact)
        if sched:
            scheduler_semantics.append(sched)
            function = sched["function"]
            predicate = sched["predicate"]
            api = sched.get("api_name") or predicate
            if predicate in {"enters_critical_section", "exits_critical_section"}:
                critical_section_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve critical-section semantics from {api}; do not describe it as only a normal call edge.")
                obligations.append(f"Mention critical-section entry/exit semantics for {function} when using this evidence.")
            elif predicate in {"suspends_scheduler", "resumes_scheduler"}:
                scheduler_control_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve scheduler suspension/resumption semantics from {api}.")
                obligations.append(f"Mention scheduler-control semantics for {function} when using this evidence.")
            elif predicate == "requests_context_switch":
                context_switch_requesters.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, describe {api} as a context-switch/yield request, not proof that a switch has already occurred on every path.")
                obligations.append(f"Qualify context-switch claims for {function} as scheduler/port dependent.")
            elif predicate in {"masks_interrupts_from_isr", "clears_interrupt_mask_from_isr"}:
                interrupt_mask_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve ISR interrupt-mask semantics from {api}.")
                obligations.append(f"Mention ISR interrupt-mask set/clear semantics for {function} when relevant.")

        task_transition = _task_state_transition_item(fact)
        if task_transition:
            task_state_transitions.append(task_transition)
            function = task_transition["function"]
            predicate = task_transition["predicate"]
            if predicate == "moves_task_to_ready_list":
                ready_list_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve ready-list transition semantics; do not describe the evidence as only a raw list helper call.")
                obligations.append(f"Mention ready-list/task-state transition semantics for {function} when using this evidence.")
            elif predicate == "moves_task_to_delayed_list":
                delayed_list_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve delayed-list transition semantics and qualify scheduler timing effects.")
                obligations.append(f"Mention delayed-list/task wait-state transition semantics for {function} when relevant.")
            elif predicate == "blocks_task_on_event_list":
                event_blocking_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that it places a task on an event/wait list; do not imply the task is ready until unblocking evidence is present.")
                obligations.append(f"Mention event-list blocking/wait-state semantics for {function} when using this evidence.")
            elif predicate == "unblocks_task_from_event_list":
                event_unblocking_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that it unblocks/removes a task from an event list and may pair with ready-list insertion evidence.")
                obligations.append(f"Mention event-list unblocking semantics for {function} when using this evidence.")
            elif predicate == "removes_task_from_list":
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve task-list removal semantics rather than treating uxListRemove as an ordinary helper call.")
                obligations.append(f"Mention task-list removal semantics for {function} when relevant.")

        kernel_object = _kernel_object_semantic_item(fact)
        if kernel_object:
            kernel_object_semantics.append(kernel_object)
            function = kernel_object["function"]
            category = kernel_object["category"]
            predicate = kernel_object["predicate"]
            if category == "stream_buffer":
                stream_buffer_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve stream-buffer send/receive semantics; do not reduce it to generic queue/list helper evidence.")
                obligations.append(f"Mention FreeRTOS stream-buffer communication semantics for {function} when using this evidence.")
            elif category == "message_buffer":
                message_buffer_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve message-buffer message-boundary semantics; do not conflate it with raw byte-stream copying.")
                obligations.append(f"Mention FreeRTOS message-buffer semantics for {function} when relevant.")
            elif category == "event_group":
                event_group_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve event-group bit semantics ({predicate}); do not describe it as a generic flag variable update.")
                obligations.append(f"Mention FreeRTOS event-group set/clear/wait/sync semantics for {function} when using this evidence.")
            elif category == "task_notification":
                task_notification_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve direct-to-task notification semantics; do not treat it as a normal task function call.")
                obligations.append(f"Mention direct-to-task notification send/wait semantics for {function} when relevant.")
            elif category == "semaphore":
                semaphore_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve semaphore give/take/create semantics and distinguish it from ordinary queue send/receive behavior.")
                obligations.append(f"Mention FreeRTOS semaphore semantics for {function} when using this evidence.")
            elif category == "mutex":
                mutex_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve mutex ownership/recursive-mutex semantics and do not reduce it to a generic queue operation.")
                obligations.append(f"Mention FreeRTOS mutex ownership/recursive semantics for {function} when using this evidence.")

        hook_semantic = _hook_assert_trace_item(fact)
        if hook_semantic:
            hook_assert_trace_semantics.append(hook_semantic)
            function = hook_semantic["function"]
            predicate = hook_semantic["predicate"]
            api_name = hook_semantic.get("api_name") or predicate
            category = hook_semantic.get("category") or "hook_assert_trace"
            if predicate == "invokes_trace_hook":
                trace_hook_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve trace hook/instrumentation semantics from {api_name}; do not treat it as guaranteed application behavior.")
                obligations.append(f"Mention that {api_name} is configurable FreeRTOS trace-hook evidence for {function}.")
            elif predicate == "invokes_assert_handler":
                assert_handler_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, qualify configASSERT/assert behavior by the target FreeRTOSConfig.h definition.")
                obligations.append(f"Mention configASSERT/assert-handler semantics for {function} when using this evidence.")
            elif predicate == "invokes_application_hook":
                application_hook_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that {api_name} is an application-defined hook and its body may be outside the analyzed kernel source.")
                obligations.append(f"Mention application-hook extension semantics for {function} when using this evidence.")
            elif predicate == "coverage_marker":
                coverage_marker_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, treat {api_name} as coverage/test marker evidence, not ordinary runtime kernel behavior.")
                obligations.append(f"Mention coverage-marker semantics for {function} when using this evidence.")
            else:
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve FreeRTOS hook/assert/trace semantics ({category}).")
                obligations.append(f"Mention hook/assert/trace semantics for {function} when using this evidence.")

        heap_semantic = _heap_allocator_semantic_item(fact)
        if heap_semantic:
            heap_allocator_semantics.append(heap_semantic)
            function = heap_semantic["function"]
            predicate = heap_semantic["predicate"]
            allocator = heap_semantic.get("heap_allocator") or "selected heap"
            if predicate == "allocates_heap_memory":
                heap_allocation_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve FreeRTOS {allocator} heap allocation semantics; do not reduce it to a generic call edge.")
                obligations.append(f"Mention selected-heap allocation semantics for {function} when using this evidence.")
            elif predicate == "frees_heap_memory":
                heap_free_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve FreeRTOS {allocator} heap free semantics and qualify it by the selected heap implementation.")
                obligations.append(f"Mention selected-heap free/deallocation semantics for {function} when using this evidence.")
            elif predicate == "coalesces_free_blocks":
                heap_coalescing_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that {allocator} has free-block coalescing evidence; do not generalize this to all FreeRTOS heap implementations.")
                obligations.append(f"Mention heap free-block coalescing semantics for {function} when relevant.")
            elif predicate == "uses_libc_allocator":
                heap_libc_allocator_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that {allocator} delegates to the C library allocator; qualify concrete behavior as external libc-dependent.")
                obligations.append(f"Mention libc allocator wrapper semantics for {function} when using this evidence.")
            elif predicate == "uses_multiple_heap_regions":
                heap_multi_region_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve {allocator} multi-region heap semantics and require region configuration evidence for concrete layout claims.")
                obligations.append(f"Mention multi-region heap configuration semantics for {function} when using this evidence.")
            elif predicate == "does_not_support_free":
                heap_free_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that {allocator} does not support ordinary free/deallocation semantics.")
                obligations.append(f"Mention no-free allocator semantics for {function} when using this evidence.")

        port_advanced = _port_advanced_semantic_item(fact)
        if port_advanced:
            port_advanced_semantics.append(port_advanced)
            function = port_advanced["function"]
            predicate = port_advanced["predicate"]
            category = port_advanced.get("category") or "port_advanced"
            api_name = port_advanced.get("api_name") or predicate
            if category == "smp":
                smp_functions.append(function)
                if predicate == "uses_core_affinity":
                    core_affinity_functions.append(function)
                    constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve FreeRTOS core-affinity semantics from {api_name}; qualify it by configUSE_CORE_AFFINITY and configNUMBER_OF_CORES.")
                    obligations.append(f"Mention core-affinity/profile dependence for {function} when using this evidence.")
                elif predicate == "uses_smp_locking":
                    smp_lock_functions.append(function)
                    constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve SMP lock semantics from {api_name}; do not claim lock ordering or inter-core timing without runtime evidence.")
                    obligations.append(f"Mention SMP lock/order uncertainty for {function} when relevant.")
                elif predicate == "uses_cross_core_yield":
                    constraints.append(_scope_prefix(profile) + f"When discussing {function}, describe {api_name} as cross-core yield/request evidence, not proof that another core immediately switched.")
                    obligations.append(f"Qualify cross-core yield behavior for {function} as port/runtime dependent.")
                else:
                    constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve SMP scheduler semantics and qualify by configNUMBER_OF_CORES and runtime core state.")
                    obligations.append(f"Mention SMP scheduler/core-count dependence for {function} when using this evidence.")
            elif category == "mpu":
                mpu_functions.append(function)
                if predicate == "crosses_privilege_boundary":
                    privilege_boundary_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve MPU/privilege semantics from {api_name}; qualify by MPU port configuration and memory-region setup.")
                obligations.append(f"Mention MPU/privilege target-specific constraints for {function} when using this evidence.")
            elif predicate == "uses_port_assembly":
                port_assembly_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, state that advanced port assembly evidence is involved; do not infer startup/vector behavior from C evidence alone.")
                obligations.append(f"Qualify assembly/startup boundary behavior for {function}.")
            elif predicate == "uses_secure_context_boundary":
                secure_context_functions.append(function)
                constraints.append(_scope_prefix(profile) + f"When discussing {function}, preserve secure-context boundary semantics and require secure-port evidence for concrete behavior claims.")
                obligations.append(f"Mention secure-context target-port dependence for {function} when relevant.")

        port_boundary = _port_boundary_item(fact)
        if port_boundary:
            port_boundaries.append(port_boundary)
            caller = str(port_boundary.get("caller") or port_boundary.get("function") or "").strip()
            callee = str(port_boundary.get("callee") or port_boundary.get("function") or "").strip()
            boundary_kind = str(port_boundary.get("port_boundary_kind") or "port_layer")
            unknown_types = [str(value) for value in port_boundary.get("unknown_types") or []]
            if caller:
                port_boundary_callers.append(caller)
            if callee and callee != "port_layer":
                port_boundary_callees.append(callee)
            port_function = callee if callee and callee != "port_layer" else caller
            if port_function:
                port_layer_functions.append(port_function)
            if "assembly_boundary_unverified" in unknown_types and port_function:
                assembly_boundary_functions.append(port_function)
            if "vector_table_unverified" in unknown_types and port_function:
                vector_table_unverified_functions.append(port_function)
            label = f"{caller} -> {callee}" if caller and callee and callee != "port_layer" else (port_function or "FreeRTOS port boundary")
            constraints.append(_scope_prefix(profile) + f"When discussing {label}, state that it reaches a FreeRTOS port layer boundary ({boundary_kind}); do not claim behavior beyond the boundary without port/startup/assembly evidence.")
            qualifications.append(f"Qualify {label} as target-port dependent evidence.")
            obligations.append(f"Preserve port-boundary unknowns for {label}, including assembly/vector/startup limits when present.")

        build_status = str(payload.get("build_status") or "active")
        guard_chain = payload.get("build_guard_chain") or []
        if isinstance(guard_chain, list) and guard_chain:
            label = _fact_label(fact) or fact.path
            condition = _condition_summary(fact, label, build_status)
            if condition:
                build_conditions.append(condition)
                expressions = ", ".join(condition.get("guard_expressions") or [])
                macro_text = _macro_text(condition.get("macro_values") or {})
                if expressions:
                    constraints.append(_scope_prefix(profile) + f"When explaining why {label} is {build_status}, cite build guard {expressions}{macro_text}.")
                    obligations.append(f"Preserve the build-condition provenance for {label}; do not only state {build_status} without the guard reason.")

        if build_status in {"inactive", "conditional"} and fact.fact_type != "target_file":
            label = _fact_label(fact)
            if build_status == "inactive":
                inactive_files.append(fact.path)
                if label:
                    inactive_symbols.append(label)
                constraints.append(_scope_prefix(profile) + f"Treat evidence for {label or fact.path} as inactive in the target build, not active runtime behavior.")
                qualifications.append(f"Qualify {label or fact.path} as inactive for the indexed target profile.")
                obligations.append(f"Separate source-visible evidence for {label or fact.path} from target-active behavior.")
            else:
                conditional_files.append(fact.path)
                if label:
                    conditional_symbols.append(label)
                constraints.append(_scope_prefix(profile) + f"Treat evidence for {label or fact.path} as conditional build evidence; do not state it is definitely active.")
                qualifications.append(f"Qualify {label or fact.path} as conditional for the indexed target profile.")
                obligations.append(f"Mention unresolved/conditional build guards for {label or fact.path}.")

    api_context_pairs = _api_context_pairs(api_contexts)
    for pair in api_context_pairs:
        task_api = pair["task_api"]
        isr_api = pair["isr_api"]
        constraints.append(f"Do not treat {task_api} and {isr_api} as interchangeable; {isr_api} is ISR-context evidence and {task_api} is task-context evidence.")
        qualifications.append(f"Qualify API claims that compare {task_api} and {isr_api} by execution context.")
        obligations.append(f"When answering ISR/task API questions, distinguish {task_api} from {isr_api} and preserve their execution contexts.")
    if any(ctx == "isr" for ctx in api_contexts.values()) and any(ctx == "task" for ctx in api_contexts.values()):
        constraints.append("Evidence includes both ISR-context and task-context APIs; split the answer by execution context and do not merge their call constraints.")
        qualifications.append("Qualify FreeRTOS API statements by ISR or task context when both contexts appear in the evidence.")
        obligations.append("State whether each FreeRTOS API is ISR-context or task-context evidence before deriving usage guidance.")

    target_profiles = _dedupe(target_profiles)
    if target_profiles:
        if len(target_profiles) == 1:
            constraints.insert(0, f"Scope build-sensitive statements to target profile '{target_profiles[0]}'.")
            obligations.insert(0, f"State the active target profile when answering build-sensitive questions: {target_profiles[0]}.")
        else:
            constraints.insert(0, f"Evidence spans multiple target profiles {target_profiles}; do not merge their active/inactive file results.")
            qualifications.insert(0, "Qualify build-sensitive claims by the target profile that produced each piece of evidence.")
            obligations.insert(0, "Keep target-profile-specific evidence separated in the answer.")

    context = AnswerBuildContext(
        target_profiles=target_profiles,
        macros=dict(sorted(macros.items())),
        active_files=_dedupe(active_files),
        inactive_files=_dedupe(inactive_files),
        conditional_files=_dedupe(conditional_files),
        inactive_symbols=_dedupe(inactive_symbols),
        conditional_symbols=_dedupe(conditional_symbols),
        build_conditions=_dedupe_conditions(build_conditions),
        allocation_profile=dict(sorted(allocation_profile.items())),
        api_contexts=dict(sorted(api_contexts.items())),
        isr_apis=_dedupe([name for name, context in api_contexts.items() if context == "isr"]),
        task_context_apis=_dedupe([name for name, context in api_contexts.items() if context == "task"]),
        api_context_pairs=_dedupe_api_pairs(api_context_pairs),
        scheduler_semantics=_dedupe_scheduler_semantics(scheduler_semantics),
        critical_section_functions=_dedupe(critical_section_functions),
        scheduler_control_functions=_dedupe(scheduler_control_functions),
        context_switch_requesters=_dedupe(context_switch_requesters),
        interrupt_mask_functions=_dedupe(interrupt_mask_functions),
        port_boundaries=_dedupe_port_boundaries(port_boundaries),
        port_boundary_callers=_dedupe(port_boundary_callers),
        port_boundary_callees=_dedupe(port_boundary_callees),
        port_layer_functions=_dedupe(port_layer_functions),
        assembly_boundary_functions=_dedupe(assembly_boundary_functions),
        vector_table_unverified_functions=_dedupe(vector_table_unverified_functions),
        task_state_transitions=_dedupe_task_state_transitions(task_state_transitions),
        ready_list_functions=_dedupe(ready_list_functions),
        delayed_list_functions=_dedupe(delayed_list_functions),
        event_blocking_functions=_dedupe(event_blocking_functions),
        event_unblocking_functions=_dedupe(event_unblocking_functions),
        kernel_object_semantics=_dedupe_kernel_object_semantics(kernel_object_semantics),
        stream_buffer_functions=_dedupe(stream_buffer_functions),
        message_buffer_functions=_dedupe(message_buffer_functions),
        event_group_functions=_dedupe(event_group_functions),
        task_notification_functions=_dedupe(task_notification_functions),
        semaphore_functions=_dedupe(semaphore_functions),
        mutex_functions=_dedupe(mutex_functions),
        hook_assert_trace_semantics=_dedupe_hook_assert_trace_semantics(hook_assert_trace_semantics),
        trace_hook_functions=_dedupe(trace_hook_functions),
        assert_handler_functions=_dedupe(assert_handler_functions),
        application_hook_functions=_dedupe(application_hook_functions),
        coverage_marker_functions=_dedupe(coverage_marker_functions),
        heap_allocator_semantics=_dedupe_heap_allocator_semantics(heap_allocator_semantics),
        heap_allocation_functions=_dedupe(heap_allocation_functions),
        heap_free_functions=_dedupe(heap_free_functions),
        heap_coalescing_functions=_dedupe(heap_coalescing_functions),
        heap_libc_allocator_functions=_dedupe(heap_libc_allocator_functions),
        heap_multi_region_functions=_dedupe(heap_multi_region_functions),
        port_advanced_semantics=_dedupe_port_advanced_semantics(port_advanced_semantics),
        smp_functions=_dedupe(smp_functions),
        core_affinity_functions=_dedupe(core_affinity_functions),
        smp_lock_functions=_dedupe(smp_lock_functions),
        mpu_functions=_dedupe(mpu_functions),
        privilege_boundary_functions=_dedupe(privilege_boundary_functions),
        port_assembly_functions=_dedupe(port_assembly_functions),
        secure_context_functions=_dedupe(secure_context_functions),
    )
    return AnswerConstraintSummary(
        response_constraints=_dedupe(constraints),
        required_qualifications=_dedupe(qualifications),
        answer_obligations=_dedupe(obligations),
        build_context=context,
    )


def answer_constraints_from_verdicts(verdicts: Iterable[Any]) -> AnswerConstraintSummary:
    facts: list[CodeFact] = []
    constraints: list[str] = []
    qualifications: list[str] = []
    obligations: list[str] = []
    for verdict in verdicts:
        facts.extend([fact for fact in getattr(verdict, "supporting_facts", []) or [] if isinstance(fact, CodeFact)])
        facts.extend([fact for fact in getattr(verdict, "contradicting_facts", []) or [] if isinstance(fact, CodeFact)])
        profile = getattr(verdict, "quality_profile", None)
        if profile is not None:
            target_profile = getattr(profile, "target_profile", None)
            if target_profile and target_profile not in {"not_tracked", "mixed"}:
                constraints.append(f"Scope build-sensitive statements to target profile '{target_profile}'.")
            build_status = getattr(profile, "build_status", None)
            if build_status == "inactive":
                constraints.append("Do not present inactive-build evidence as active target behavior.")
                qualifications.append("Qualify claims backed by inactive evidence as source-present but target-inactive.")
            elif build_status == "conditional":
                constraints.append("Do not present conditional-build evidence as definitely active target behavior.")
                qualifications.append("Qualify claims backed by conditional build evidence.")
            elif build_status == "mixed":
                constraints.append("Evidence mixes active/inactive/conditional build states; split the answer by build status.")
                qualifications.append("Qualify each build-sensitive claim by its active/inactive/conditional status.")
        claim = getattr(verdict, "claim", None)
        claim_type = getattr(claim, "claim_type", None)
        if claim_type == "build_config" and getattr(verdict, "verdict", None) == "contradicted":
            constraints.append("Do not claim the requested macro value; indexed build_config evidence has a different target-profile value.")
            obligations.append("When correcting the answer, include the indexed macro value if available.")
        if claim_type in {"build_active", "file_active"} and getattr(verdict, "verdict", None) in {"contradicted", "conditional"}:
            subject = getattr(claim, "subject", None) or getattr(claim, "object", None) or "the target"
            constraints.append(f"For {subject}, distinguish source existence from active target-profile membership.")
            obligations.append(f"State whether {subject} is active, inactive, or conditional for the indexed target profile.")

    fact_summary = answer_constraints_from_facts(facts)
    context = fact_summary.build_context
    return AnswerConstraintSummary(
        response_constraints=_dedupe([*constraints, *fact_summary.response_constraints]),
        required_qualifications=_dedupe([*qualifications, *fact_summary.required_qualifications]),
        answer_obligations=_dedupe([*obligations, *fact_summary.answer_obligations]),
        build_context=context,
    )








def _port_advanced_semantic_item(fact: CodeFact) -> dict[str, Any] | None:
    predicates = {
        "uses_smp_scheduler", "uses_core_affinity", "uses_cross_core_yield", "uses_smp_locking",
        "uses_mpu_wrappers", "configures_mpu_regions", "checks_mpu_access", "crosses_privilege_boundary",
        "uses_port_assembly", "uses_secure_context_boundary",
    }
    if fact.fact_type != "relation" or fact.predicate not in predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or payload.get("state_object") or ""),
        "category": str(payload.get("port_advanced_category") or "port_advanced"),
        "operation_kind": str(payload.get("operation_kind") or fact.predicate),
        "api_name": str(payload.get("api_name") or fact.predicate),
        "path_category": str(payload.get("path_category") or ""),
        "line": fact.start_line,
    }


def _dedupe_port_advanced_semantics(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("api_name")), str(item.get("line")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out


def _kernel_object_semantic_item(fact: CodeFact) -> dict[str, Any] | None:
    predicates = {
        "sends_to_stream_buffer", "receives_from_stream_buffer",
        "sends_to_message_buffer", "receives_from_message_buffer",
        "sets_event_bits", "clears_event_bits", "waits_for_event_bits", "syncs_event_bits",
        "notifies_task", "waits_for_task_notification",
        "gives_semaphore", "takes_semaphore", "creates_semaphore",
        "gives_mutex", "takes_mutex", "creates_mutex",
    }
    if fact.fact_type != "relation" or fact.predicate not in predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or payload.get("state_object") or ""),
        "category": str(payload.get("kernel_object_category") or "kernel_object"),
        "operation_kind": str(payload.get("operation_kind") or fact.predicate),
        "api_name": str(payload.get("api_name") or fact.predicate),
        "execution_context": str(payload.get("execution_context") or "not_tracked"),
    }


def _dedupe_kernel_object_semantics(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("category")))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out


def _hook_assert_trace_item(fact: CodeFact) -> dict[str, Any] | None:
    predicates = {"invokes_trace_hook", "invokes_assert_handler", "invokes_application_hook", "coverage_marker"}
    if fact.fact_type != "relation" or fact.predicate not in predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or ""),
        "category": str(payload.get("hook_assert_trace_category") or "hook_assert_trace"),
        "operation_kind": str(payload.get("operation_kind") or fact.predicate),
        "api_name": str(payload.get("api_name") or fact.object or fact.predicate),
        "execution_context": str(payload.get("execution_context") or "not_tracked"),
    }


def _dedupe_hook_assert_trace_semantics(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("api_name")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out


def _heap_allocator_semantic_item(fact: CodeFact) -> dict[str, Any] | None:
    predicates = {
        "allocates_heap_memory", "frees_heap_memory", "coalesces_free_blocks",
        "uses_libc_allocator", "uses_multiple_heap_regions", "does_not_support_free",
    }
    if fact.fact_type != "relation" or fact.predicate not in predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or payload.get("state_object") or ""),
        "heap_allocator": str(payload.get("heap_allocator") or ""),
        "category": str(payload.get("heap_allocator_category") or "heap_allocator"),
        "operation_kind": str(payload.get("operation_kind") or fact.predicate),
        "api_name": str(payload.get("api_name") or fact.predicate),
        "execution_context": str(payload.get("execution_context") or "not_tracked"),
    }


def _dedupe_heap_allocator_semantics(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("heap_allocator")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out

def _port_boundary_item(fact: CodeFact) -> dict[str, Any] | None:
    if fact.fact_type != "relation" or fact.predicate not in {"crosses_port_boundary", "has_port_boundary"}:
        return None
    payload = fact.payload or {}
    caller = str(fact.subject or payload.get("caller") or payload.get("port_function") or "").strip()
    callee = str(fact.object or payload.get("callee") or payload.get("port_api") or "").strip()
    unknown_types = [str(value) for value in payload.get("unknown_types") or []]
    if payload.get("unknown_type") and str(payload.get("unknown_type")) not in unknown_types:
        unknown_types.insert(0, str(payload.get("unknown_type")))
    return {
        "function": caller,
        "caller": caller,
        "callee": callee,
        "predicate": str(fact.predicate),
        "port_boundary_kind": str(payload.get("port_boundary_kind") or "port_layer"),
        "unknown_types": unknown_types,
        "path": fact.path,
        "line": fact.start_line,
    }


def _dedupe_port_boundaries(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("caller")), str(item.get("callee")), str(item.get("port_boundary_kind")), str(item.get("line")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out

def _scheduler_semantic_item(fact: CodeFact) -> dict[str, Any] | None:
    scheduler_predicates = {
        "enters_critical_section",
        "exits_critical_section",
        "suspends_scheduler",
        "resumes_scheduler",
        "requests_context_switch",
        "masks_interrupts_from_isr",
        "clears_interrupt_mask_from_isr",
    }
    if fact.fact_type != "relation" or fact.predicate not in scheduler_predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or ""),
        "api_name": str(payload.get("api_name") or ""),
        "operation_kind": str(payload.get("operation_kind") or ""),
        "execution_context": str(payload.get("execution_context") or ""),
        "path": fact.path,
        "line": fact.start_line,
    }


def _dedupe_scheduler_semantics(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("api_name")), str(item.get("line")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out


def _task_state_transition_item(fact: CodeFact) -> dict[str, Any] | None:
    task_state_predicates = {
        "moves_task_to_ready_list",
        "moves_task_to_delayed_list",
        "blocks_task_on_event_list",
        "unblocks_task_from_event_list",
        "removes_task_from_list",
    }
    if fact.fact_type != "relation" or fact.predicate not in task_state_predicates:
        return None
    payload = fact.payload or {}
    function = str(fact.subject or payload.get("caller") or "").strip()
    if not function:
        return None
    return {
        "function": function,
        "predicate": str(fact.predicate),
        "object": str(fact.object or payload.get("state_object") or ""),
        "api_name": str(payload.get("api_name") or ""),
        "operation_kind": str(payload.get("operation_kind") or ""),
        "path": fact.path,
        "line": fact.start_line,
    }


def _dedupe_task_state_transitions(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("function")), str(item.get("predicate")), str(item.get("api_name")), str(item.get("line")))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: v for k, v in item.items() if v not in (None, "", [], {})})
    return out


def _execution_context_items(fact: CodeFact) -> list[tuple[str, str, str | None]]:
    payload = fact.payload or {}
    items: list[tuple[str, str, str | None]] = []

    def add(name: Any, context: Any, basis: Any = None) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        if not isinstance(context, str) or context not in {"isr", "task"}:
            return
        items.append((name.strip(), context, str(basis) if basis else None))

    if fact.fact_type == "relation" and fact.predicate == "has_execution_context":
        add(fact.subject, fact.object or payload.get("execution_context"), payload.get("execution_context_basis"))

    if fact.fact_type == "call":
        add(fact.caller or fact.subject, payload.get("caller_execution_context") or payload.get("execution_context"), payload.get("caller_execution_context_basis") or payload.get("execution_context_basis"))
        add(fact.callee or fact.object, payload.get("callee_execution_context"), payload.get("callee_execution_context_basis"))

    if fact.fact_type == "relation":
        add(fact.subject, payload.get("caller_execution_context") or payload.get("creator_execution_context") or payload.get("storage_execution_context") or payload.get("invocation_execution_context") or payload.get("execution_context"), payload.get("execution_context_basis"))
        # Some relation payloads only describe callee/invocation context.  Use
        # the relation object as a label in those cases if it is a function/API.
        add(fact.object, payload.get("callee_execution_context") or payload.get("invocation_execution_context"), payload.get("callee_execution_context_basis"))

    # Deterministic fallback for public FreeRTOS APIs.  This keeps answer
    # contracts useful even when a call relation rather than an explicit
    # has_execution_context relation is the only supporting evidence.
    for name in (fact.subject, fact.object, fact.symbol, fact.qualified_name, fact.caller, fact.callee):
        if not isinstance(name, str) or not name:
            continue
        if name.endswith("FromISR"):
            add(name, "isr", "name_suffix")
        elif _looks_like_freertos_task_api(name):
            add(name, "task", "name_heuristic")

    return _dedupe_context_items(items)


def _looks_like_freertos_task_api(name: str) -> bool:
    if name.endswith("FromISR"):
        return False
    prefixes = ("xQueue", "xTask", "xTimer", "xSemaphore", "vTask", "vTimer")
    return name.startswith(prefixes)


def _dedupe_context_items(items: Iterable[tuple[str, str, str | None]]) -> list[tuple[str, str, str | None]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str | None]] = []
    for name, context, basis in items:
        key = (name, context)
        if key in seen:
            continue
        seen.add(key)
        out.append((name, context, basis))
    return out


def _api_context_pairs(api_contexts: dict[str, str]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for name, context in sorted(api_contexts.items()):
        if context == "isr" and name.endswith("FromISR"):
            task_api = name[: -len("FromISR")]
            if api_contexts.get(task_api) == "task":
                pairs.append({"task_api": task_api, "isr_api": name})
        elif context == "task":
            isr_api = f"{name}FromISR"
            if api_contexts.get(isr_api) == "isr":
                pairs.append({"task_api": name, "isr_api": isr_api})
    return _dedupe_api_pairs(pairs)


def _dedupe_api_pairs(items: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        task_api = str(item.get("task_api") or "").strip()
        isr_api = str(item.get("isr_api") or "").strip()
        if not task_api or not isr_api:
            continue
        key = (task_api, isr_api)
        if key in seen:
            continue
        seen.add(key)
        out.append({"task_api": task_api, "isr_api": isr_api})
    return out


def _profile_name(fact: CodeFact) -> str | None:
    payload = fact.payload or {}
    for key in ("target_profile", "target_profile_name"):
        value = payload.get(key)
        if isinstance(value, str) and value and value not in {"not_tracked", "default"}:
            return value
    context = payload.get("tu_context")
    if isinstance(context, dict):
        value = context.get("target_profile")
        if isinstance(value, str) and value and value not in {"not_tracked", "default"}:
            return value
    return None


def _fact_label(fact: CodeFact) -> str | None:
    for value in (fact.qualified_name, fact.symbol, fact.caller, fact.callee, fact.subject, fact.object):
        if isinstance(value, str) and value:
            return value
    return None


def _scope_prefix(profile: str | None) -> str:
    return f"For target profile '{profile}', " if profile else ""


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item is None:
            continue
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _condition_summary(fact: CodeFact, label: str, build_status: str) -> dict[str, Any] | None:
    payload = fact.payload or {}
    chain = payload.get("build_guard_chain")
    if not isinstance(chain, list) or not chain:
        return None
    expressions = _dedupe([str(item.get("expression")) for item in chain if item.get("expression")])
    macro_values: dict[str, str] = {}
    for item in chain:
        for name, value in (item.get("evaluated_with") or {}).items():
            macro_values[str(name)] = str(value)
    return {
        "label": label,
        "path": fact.path,
        "build_status": build_status,
        "guard_expressions": expressions,
        "macro_values": dict(sorted(macro_values.items())),
        "build_guard_chain": chain,
    }


def _macro_text(values: dict[str, str]) -> str:
    if not values:
        return ""
    return " evaluated with " + ", ".join(f"{name}={value}" for name, value in sorted(values.items()))


def _dedupe_conditions(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("label")), str(item.get("path")), str(item.get("build_status")))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
