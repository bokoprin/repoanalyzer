from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.query.definitions import find_definitions
from repoanalyzer.query._store import open_store
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.workflow.answer_check import verify_answer
from repoanalyzer.workflow.contracts import build_answer_contract
from repoanalyzer.evidence.target_profile_diff import build_target_profile_diff

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_freertos_probe"
CASE_FILE = FIXTURE / "phase7_freertos_probe_cases.yaml"
TIMERS_OFF_CASE_FILE = FIXTURE / "phase7_freertos_timers_off_cases.yaml"
STATIC_ONLY_CASE_FILE = FIXTURE / "phase7_freertos_static_only_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_freertos_probe_real_repo_eval_passes_and_resolves_macro_wrapped_task(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = repo / CASE_FILE.name

    report = run_real_repo_eval(repo, case_file)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["metrics"]["indexed_files"] >= 9
    assert payload["metrics"]["total_facts"] >= 150
    assert payload["metrics"]["scenario_count"] == 36
    assert payload["metrics"]["passed_scenarios"] == 36
    assert payload["metrics"]["failed_scenarios"] == 0

    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] >= 9
    assert diagnostics["total_facts"] >= 150
    assert diagnostics["warnings"] == []

    config_bundle = verify_claim_text(repo, "configUSE_TIMERS is 1 in the target build.")
    assert config_bundle.verdicts[0].claim.claim_type == "build_config"
    assert config_bundle.verdicts[0].verdict == "supported"
    assert config_bundle.verdicts[0].supporting_facts[0].fact_type == "build_config"
    assert config_bundle.verdicts[0].supporting_facts[0].payload.get("macro_value") == "1"

    profile_bundle = verify_claim_text(repo, "target profile is freertos-gcc-arm-cm4f-timers-on.")
    assert profile_bundle.verdicts[0].claim.claim_type == "target_profile"
    assert profile_bundle.verdicts[0].verdict == "supported"
    assert profile_bundle.verdicts[0].supporting_facts[0].fact_type == "target_profile"
    assert profile_bundle.verdicts[0].quality_profile is not None
    assert profile_bundle.verdicts[0].quality_profile.target_profile == "freertos-gcc-arm-cm4f-timers-on"

    active_port = verify_claim(repo, {"claim_type": "target_profile", "subject": "active_port", "object": "portable/GCC/ARM_CM4F"})
    assert active_port.verdict == "supported"
    assert active_port.supporting_facts[0].payload.get("target_profile_name") == "freertos-gcc-arm-cm4f-timers-on"

    bundle = verify_claim_text(repo, "prvTimerTask calls prvProcessReceivedCommands.")
    assert bundle.overall_verdict == "supported"
    assert len(bundle.verdicts) == 1
    verdict = bundle.verdicts[0]
    assert verdict.claim.claim_type == "calls"
    assert verdict.claim.subject == "prvTimerTask"
    assert verdict.claim.object == "prvProcessReceivedCommands"
    assert verdict.verdict == "supported"
    assert verdict.support_level in {"strong", "medium"}

    defs = find_definitions(repo, "prvTimerTask")
    assert len(defs) == 1
    assert defs[0].payload.get("macro_wrapped_function") is True
    assert defs[0].payload.get("macro_name") == "portTASK_FUNCTION"
    assert defs[0].payload.get("definition_source") == "macro_wrapped_function"

    store = open_store(repo)
    metadata = store.all_metadata()
    assert metadata["target_profile"]["name"] == "freertos-gcc-arm-cm4f-timers-on"
    target_profile_facts = store.query_facts("fact_type='target_profile'")
    assert any(f.predicate == "selected_profile" and f.subject == "freertos-gcc-arm-cm4f-timers-on" for f in target_profile_facts)
    assert any(f.predicate == "target_attribute" and f.subject == "active_port" and f.object == "portable/GCC/ARM_CM4F" for f in target_profile_facts)
    assert any(f.predicate == "target_file_selection" and f.subject == "active_path_prefix" and f.object == "portable" for f in target_profile_facts)
    target_file_facts = store.query_facts("fact_type='target_file'")
    assert any(f.subject == "portable/GCC/ARM_CM4F/port.c" and f.predicate == "file_active" and "active_port" in (f.payload.get("selection_reasons") or []) for f in target_file_facts)
    assert any(f.subject == "portable/GCC/ARM_CM3/port.c" and f.predicate == "file_inactive" and "non_selected_port" in (f.payload.get("selection_reasons") or []) for f in target_file_facts)
    assert any(f.subject == "portable/MemMang/heap_4.c" and f.predicate == "file_active" and "selected_heap" in (f.payload.get("selection_reasons") or []) for f in target_file_facts)
    assert any(f.subject == "portable/MemMang/heap_3.c" and f.predicate == "file_inactive" and "non_selected_heap" in (f.payload.get("selection_reasons") or []) for f in target_file_facts)

    timer_active = verify_claim(repo, {"claim_type": "build_active", "subject": "xTimerCreateTimerTask"})
    assert timer_active.verdict == "supported"
    timer_fact = timer_active.supporting_facts[0]
    assert timer_fact.payload.get("guard_expressions") == ["( configUSE_TIMERS == 1 )"]
    assert timer_fact.payload.get("guard_macro_values") == {"configUSE_TIMERS": "1"}
    chain = timer_fact.payload.get("build_guard_chain") or []
    assert chain and chain[0]["evaluated_with"] == {"configUSE_TIMERS": "1"}
    assert chain[0]["effective_status"] == "active"

    heap4_active = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/MemMang/heap_4.c", "object": "active"})
    assert heap4_active.verdict == "supported"
    heap3_inactive = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/MemMang/heap_3.c", "object": "inactive"})
    assert heap3_inactive.verdict == "supported"
    cm3_active = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/GCC/ARM_CM3/port.c", "object": "active"})
    assert cm3_active.verdict == "contradicted"


    callback_relations = store.query_facts("fact_type='relation' AND predicate IN ('stores_callback', 'invokes_callback', 'callback_dataflows_to')")
    execution_contexts = store.query_facts("fact_type='relation' AND predicate='has_execution_context'")
    storage = [fact for fact in callback_relations if fact.predicate == "stores_callback" and fact.subject == "prvInitialiseNewTimer" and fact.object == "pxCallbackFunction"]
    invocation = [fact for fact in callback_relations if fact.predicate == "invokes_callback" and fact.subject == "prvProcessExpiredTimer" and fact.object == "pxCallbackFunction"]
    dataflow = [fact for fact in callback_relations if fact.predicate == "callback_dataflows_to" and fact.subject == "xTimerCreate" and fact.object == "prvProcessExpiredTimer"]
    assert storage
    assert storage[0].payload.get("relation_kind") == "callback_storage"
    assert storage[0].payload.get("storage_expr") == "pxNewTimer->pxCallbackFunction"
    assert invocation
    assert invocation[0].payload.get("relation_kind") == "callback_invocation"
    assert invocation[0].payload.get("callback_storage_expr") == "pxTimer->pxCallbackFunction"
    assert invocation[0].payload.get("unknown_type") == "callback_target_unknown"
    assert dataflow
    assert dataflow[0].payload.get("relation_kind") == "callback_dataflow_trace"
    assert dataflow[0].payload.get("callback_symbol") == "pxCallbackFunction"
    assert dataflow[0].payload.get("storage_function") == "prvInitialiseNewTimer"
    assert dataflow[0].payload.get("invocation_function") == "prvProcessExpiredTimer"
    assert len(dataflow[0].payload.get("dataflow_steps") or []) == 3

    context_by_subject = {(fact.subject, fact.object): fact for fact in execution_contexts}
    assert ("xPortSysTickHandler", "isr") in context_by_subject
    assert ("xQueueGenericSendFromISR", "isr") in context_by_subject
    assert ("xQueueGenericSend", "task") in context_by_subject
    assert ("prvTimerTask", "task") in context_by_subject

    tick_bundle = verify_claim_text(repo, "xPortSysTickHandler runs in ISR context.")
    assert tick_bundle.verdicts[0].claim.claim_type == "execution_context"
    assert tick_bundle.verdicts[0].verdict == "supported"
    assert tick_bundle.verdicts[0].quality_profile is not None
    assert tick_bundle.verdicts[0].quality_profile.execution_context == "isr"

    mixed_bundle = verify_claim_text(repo, "xQueueGenericSend runs in task context. xQueueGenericSendFromISR runs in ISR context.")
    assert mixed_bundle.overall_verdict == "supported"
    assert mixed_bundle.support_level in {"medium", "strong"}
    assert {v.quality_profile.execution_context for v in mixed_bundle.verdicts if v.quality_profile} == {"task", "isr"}

    api_contract = build_answer_contract(
        str(repo),
        "xQueueGenericSend runs in task context. xQueueGenericSendFromISR runs in ISR context.",
    )
    assert api_contract.can_answer is True
    assert api_contract.build_context["api_contexts"]["xQueueGenericSend"] == "task"
    assert api_contract.build_context["api_contexts"]["xQueueGenericSendFromISR"] == "isr"
    assert "xQueueGenericSendFromISR" in api_contract.build_context["isr_apis"]
    assert "xQueueGenericSend" in api_contract.build_context["task_context_apis"]
    assert {"task_api": "xQueueGenericSend", "isr_api": "xQueueGenericSendFromISR"} in api_contract.build_context["api_context_pairs"]
    assert any("Do not treat xQueueGenericSend and xQueueGenericSendFromISR as interchangeable" in c for c in api_contract.response_constraints)
    assert any("ISR-context and task-context" in c for c in api_contract.response_constraints)
    assert any("distinguish xQueueGenericSend from xQueueGenericSendFromISR" in item for item in api_contract.answer_obligations)

    scheduler_relations = store.query_facts("fact_type='relation' AND predicate IN ('enters_critical_section','exits_critical_section','suspends_scheduler','resumes_scheduler','requests_context_switch','masks_interrupts_from_isr','clears_interrupt_mask_from_isr')")
    assert any(f.subject == "xQueueGenericSend" and f.predicate == "enters_critical_section" and f.payload.get("api_name") == "taskENTER_CRITICAL" for f in scheduler_relations)
    assert any(f.subject == "xQueueGenericSend" and f.predicate == "exits_critical_section" and f.payload.get("api_name") == "taskEXIT_CRITICAL" for f in scheduler_relations)
    assert any(f.subject == "xQueueGenericSend" and f.predicate == "requests_context_switch" and f.payload.get("api_name") == "portYIELD_WITHIN_API" for f in scheduler_relations)
    assert any(f.subject == "xQueueGenericSendFromISR" and f.predicate == "masks_interrupts_from_isr" and f.payload.get("api_name") == "portSET_INTERRUPT_MASK_FROM_ISR" for f in scheduler_relations)
    assert any(f.subject == "xQueueGenericSendFromISR" and f.predicate == "clears_interrupt_mask_from_isr" and f.payload.get("api_name") == "portCLEAR_INTERRUPT_MASK_FROM_ISR" for f in scheduler_relations)
    assert any(f.subject == "xQueueGenericSendFromISR" and f.predicate == "requests_context_switch" and f.payload.get("api_name") == "portYIELD_FROM_ISR" for f in scheduler_relations)
    assert any(f.subject == "prvProcessTimerOrBlockTask" and f.predicate == "suspends_scheduler" and f.payload.get("api_name") == "vTaskSuspendAll" for f in scheduler_relations)
    assert any(f.subject == "prvProcessTimerOrBlockTask" and f.predicate == "resumes_scheduler" and f.payload.get("api_name") == "xTaskResumeAll" for f in scheduler_relations)

    scheduler_bundle = verify_claim_text(repo, "xQueueGenericSend enters critical section. xQueueGenericSendFromISR requests context switch. prvProcessTimerOrBlockTask suspends scheduler.")
    assert scheduler_bundle.overall_verdict == "conditional"
    assert any(v.claim.claim_type == "scheduler_semantic" and v.claim.subject == "xQueueGenericSend" and v.claim.object == "enters_critical_section" and v.verdict == "supported" for v in scheduler_bundle.verdicts)
    assert any(v.claim.claim_type == "scheduler_semantic" and v.claim.subject == "xQueueGenericSendFromISR" and v.claim.object == "requests_context_switch" and v.verdict == "conditional" for v in scheduler_bundle.verdicts)
    assert "scheduler_dependent_execution" in scheduler_bundle.unknown_reasons

    scheduler_contract = build_answer_contract(
        str(repo),
        "xQueueGenericSend enters critical section. xQueueGenericSendFromISR requests context switch. prvProcessTimerOrBlockTask suspends scheduler.",
    )
    assert scheduler_contract.can_answer is True
    assert "xQueueGenericSend" in scheduler_contract.build_context["critical_section_functions"]
    assert "xQueueGenericSendFromISR" in scheduler_contract.build_context["context_switch_requesters"]
    assert "prvProcessTimerOrBlockTask" in scheduler_contract.build_context["scheduler_control_functions"]
    assert any("context-switch/yield request" in item for item in scheduler_contract.response_constraints)

    port_boundary_relations = store.query_facts("fact_type='relation' AND predicate IN ('crosses_port_boundary','has_port_boundary')")
    assert any(f.subject == "vTaskStartScheduler" and f.predicate == "crosses_port_boundary" and f.object == "xPortStartScheduler" for f in port_boundary_relations)
    assert any(f.subject == "prvInitialiseNewTask" and f.predicate == "crosses_port_boundary" and f.object == "pxPortInitialiseStack" for f in port_boundary_relations)
    assert any(f.subject == "xPortSysTickHandler" and f.predicate == "has_port_boundary" for f in port_boundary_relations)

    port_bundle = verify_claim_text(repo, "vTaskStartScheduler crosses port boundary to xPortStartScheduler. prvInitialiseNewTask crosses port boundary to pxPortInitialiseStack. xPortSysTickHandler has port boundary.")
    assert port_bundle.overall_verdict == "conditional"
    assert any(v.claim.claim_type == "port_boundary" and v.claim.subject == "vTaskStartScheduler" and v.claim.object == "xPortStartScheduler" and v.verdict == "conditional" for v in port_bundle.verdicts)
    assert "port_layer_boundary" in port_bundle.unknown_reasons
    assert "assembly_boundary_unverified" in port_bundle.unknown_reasons
    assert "vector_table_unverified" in port_bundle.unknown_reasons

    port_contract = build_answer_contract(
        str(repo),
        "vTaskStartScheduler crosses port boundary to xPortStartScheduler. prvInitialiseNewTask crosses port boundary to pxPortInitialiseStack. xPortSysTickHandler has port boundary.",
    )
    assert port_contract.can_answer is True
    assert "vTaskStartScheduler" in port_contract.build_context["port_boundary_callers"]
    assert "xPortStartScheduler" in port_contract.build_context["port_boundary_callees"]
    assert "pxPortInitialiseStack" in port_contract.build_context["port_layer_functions"]
    assert "xPortStartScheduler" in port_contract.build_context["assembly_boundary_functions"]
    assert "xPortSysTickHandler" in port_contract.build_context["vector_table_unverified_functions"]
    assert any("FreeRTOS port layer boundary" in item for item in port_contract.response_constraints)
    assert any("Preserve port-boundary unknowns" in item for item in port_contract.answer_obligations)

    storage_verdict = verify_claim_text(repo, "prvInitialiseNewTimer stores callback pxCallbackFunction.").verdicts[0]
    assert storage_verdict.claim.claim_type == "stores_callback"
    assert storage_verdict.verdict == "conditional"
    assert "callback_relation_not_execution" in storage_verdict.unknown_reasons

    invocation_verdict = verify_claim_text(repo, "prvProcessExpiredTimer invokes callback pxCallbackFunction.").verdicts[0]
    assert invocation_verdict.claim.claim_type == "invokes_callback"
    assert invocation_verdict.verdict == "conditional"
    assert "callback_target_unknown" in invocation_verdict.unknown_reasons

    dataflow_verdict = verify_claim_text(repo, "xTimerCreate dataflows callback pxCallbackFunction to prvProcessExpiredTimer.").verdicts[0]
    assert dataflow_verdict.claim.claim_type == "callback_dataflow"
    assert dataflow_verdict.verdict == "conditional"
    assert dataflow_verdict.reason_code == "callback_dataflow_supported"
    assert "callback_relation_not_execution" in dataflow_verdict.unknown_reasons
    assert "callback_target_unknown" in dataflow_verdict.unknown_reasons

    task_entry_relations = store.query_facts("fact_type='relation' AND predicate IN ('stores_task_entry', 'initializes_stack_with_task_entry', 'task_entry_dataflows_to')")
    stores_entry = [fact for fact in task_entry_relations if fact.predicate == "stores_task_entry" and fact.subject == "prvInitialiseNewTask" and fact.object == "pxTaskCode"]
    stack_entry = [fact for fact in task_entry_relations if fact.predicate == "initializes_stack_with_task_entry" and fact.subject == "prvInitialiseNewTask" and fact.object == "pxPortInitialiseStack"]
    task_dataflow = [fact for fact in task_entry_relations if fact.predicate == "task_entry_dataflows_to" and fact.subject == "xTaskCreate" and fact.object == "pxPortInitialiseStack"]
    assert stores_entry
    assert stores_entry[0].payload.get("storage_expr") == "pxNewTCB->pxTaskCode"
    assert stores_entry[0].payload.get("unknown_type") == "task_entry_execution_deferred"
    assert stack_entry
    assert stack_entry[0].payload.get("task_entry_symbol") == "pxTaskCode"
    assert task_dataflow
    assert task_dataflow[0].payload.get("relation_kind") == "task_entry_dataflow_trace"
    assert task_dataflow[0].payload.get("task_entry_symbol") == "pxTaskCode"
    assert task_dataflow[0].payload.get("storage_function") == "prvInitialiseNewTask"
    assert task_dataflow[0].payload.get("stack_initialiser") == "pxPortInitialiseStack"
    assert task_dataflow[0].payload.get("deferred_execution") is True
    assert len(task_dataflow[0].payload.get("dataflow_steps") or []) >= 3

    task_entry_verdict = verify_claim_text(repo, "xTaskCreate dataflows task entry pxTaskCode to pxPortInitialiseStack.").verdicts[0]
    assert task_entry_verdict.claim.claim_type == "task_entry_dataflow"
    assert task_entry_verdict.verdict == "conditional"
    assert task_entry_verdict.reason_code == "task_entry_dataflow_supported"
    assert "task_entry_execution_deferred" in task_entry_verdict.unknown_reasons
    assert "scheduler_dependent_execution" in task_entry_verdict.unknown_reasons

    heap_relations = store.query_facts("fact_type='relation' AND predicate IN ('allocates_heap_memory','frees_heap_memory','coalesces_free_blocks','uses_libc_allocator','uses_multiple_heap_regions')")
    assert any(f.subject == "pvPortMalloc" and f.predicate == "allocates_heap_memory" and f.payload.get("heap_allocator") == "heap_4" for f in heap_relations)
    assert any(f.subject == "vPortFree" and f.predicate == "frees_heap_memory" and f.payload.get("heap_allocator") == "heap_4" for f in heap_relations)
    assert any(f.subject == "prvInsertBlockIntoFreeList" and f.predicate == "coalesces_free_blocks" and f.payload.get("heap_allocator") == "heap_4" for f in heap_relations)

    heap_bundle = verify_claim_text(repo, "pvPortMalloc allocates heap memory. vPortFree frees heap memory. prvInsertBlockIntoFreeList coalesces free blocks.")
    assert heap_bundle.overall_verdict == "conditional"

    port_adv_relations = store.query_facts("fact_type='relation' AND predicate IN ('uses_smp_scheduler','uses_core_affinity','uses_cross_core_yield','uses_smp_locking','uses_mpu_wrappers','configures_mpu_regions','checks_mpu_access','crosses_privilege_boundary','uses_port_assembly','uses_secure_context_boundary')")
    assert any(f.subject == "prvSelectHighestPriorityTask" and f.predicate == "uses_smp_scheduler" for f in port_adv_relations)
    assert any(f.subject == "xTaskCreateAffinitySet" and f.predicate == "uses_core_affinity" for f in port_adv_relations)
    assert any(f.subject == "prvYieldCore" and f.predicate == "uses_cross_core_yield" for f in port_adv_relations)
    assert any(f.subject == "xTaskCreateRestricted" and f.predicate == "configures_mpu_regions" for f in port_adv_relations)
    assert any(f.subject == "xPortIsAuthorizedToAccessBuffer" and f.predicate == "checks_mpu_access" for f in port_adv_relations)
    assert any(f.subject == "MPU_xTaskCreate" and f.predicate == "crosses_privilege_boundary" for f in port_adv_relations)
    assert any(f.subject == "vPortSVCHandler" and f.predicate == "uses_port_assembly" for f in port_adv_relations)
    assert any(f.subject == "SecureContext_LoadContext" and f.predicate == "uses_secure_context_boundary" for f in port_adv_relations)

    port_adv_bundle = verify_claim_text(repo, "prvSelectHighestPriorityTask uses SMP scheduler. xTaskCreateAffinitySet uses core affinity. xTaskCreateRestricted configures MPU regions. MPU_xTaskCreate crosses privilege boundary. vPortSVCHandler uses port assembly. SecureContext_LoadContext uses secure context boundary.")
    assert port_adv_bundle.overall_verdict == "conditional"
    assert {v.claim.claim_type for v in port_adv_bundle.verdicts} == {"port_advanced_semantic"}
    assert any("port_advanced_target_specific" in v.unknown_reasons or "configNUMBER_OF_CORES_profile_dependent" in v.unknown_reasons for v in port_adv_bundle.verdicts)

    port_adv_contract = build_answer_contract(str(repo), "prvSelectHighestPriorityTask uses SMP scheduler. xTaskCreateAffinitySet uses core affinity. xTaskCreateRestricted configures MPU regions. MPU_xTaskCreate crosses privilege boundary. vPortSVCHandler uses port assembly. SecureContext_LoadContext uses secure context boundary.")
    assert port_adv_contract.can_answer is True
    assert port_adv_contract.build_context["smp_functions"]
    assert "xTaskCreateRestricted" in port_adv_contract.build_context["mpu_functions"]
    assert "MPU_xTaskCreate" in port_adv_contract.build_context["privilege_boundary_functions"]
    assert "vPortSVCHandler" in port_adv_contract.build_context["port_assembly_functions"]
    assert "SecureContext_LoadContext" in port_adv_contract.build_context["secure_context_functions"]
    assert any(v.claim.claim_type == "heap_allocator_semantic" and v.claim.subject == "pvPortMalloc" and v.claim.object == "allocates_heap_memory" and v.verdict == "conditional" for v in heap_bundle.verdicts)
    assert any(v.claim.claim_type == "heap_allocator_semantic" and v.claim.subject == "vPortFree" and v.claim.object == "frees_heap_memory" and v.verdict == "conditional" for v in heap_bundle.verdicts)
    assert any(v.claim.claim_type == "heap_allocator_semantic" and v.claim.subject == "prvInsertBlockIntoFreeList" and v.claim.object == "coalesces_free_blocks" and v.verdict == "conditional" for v in heap_bundle.verdicts)
    assert "heap_allocator_semantic" in heap_bundle.unknown_reasons

    heap_contract = build_answer_contract(str(repo), "pvPortMalloc allocates heap memory. vPortFree frees heap memory. prvInsertBlockIntoFreeList coalesces free blocks.")
    assert heap_contract.can_answer is True
    assert "pvPortMalloc" in heap_contract.build_context["heap_allocation_functions"]
    assert "vPortFree" in heap_contract.build_context["heap_free_functions"]
    assert "prvInsertBlockIntoFreeList" in heap_contract.build_context["heap_coalescing_functions"]
    assert any("free-block coalescing" in item for item in heap_contract.response_constraints)


def test_phase7_freertos_timers_off_profile_marks_timer_code_inactive(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = repo / TIMERS_OFF_CASE_FILE.name

    report = run_real_repo_eval(repo, case_file)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["metrics"]["scenario_count"] == 11
    assert payload["metrics"]["passed_scenarios"] == 11
    assert payload["metrics"]["failed_scenarios"] == 0

    config_bundle = verify_claim_text(repo, "configUSE_TIMERS is 0 in the target build.")
    assert config_bundle.verdicts[0].claim.claim_type == "build_config"
    assert config_bundle.verdicts[0].verdict == "supported"
    assert config_bundle.verdicts[0].supporting_facts[0].payload.get("macro_value") == "0"

    profile = verify_claim(repo, {"claim_type": "target_profile", "subject": "name", "object": "freertos-gcc-arm-cm4f-timers-off"})
    assert profile.verdict == "supported"

    heap4_active = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/MemMang/heap_4.c", "object": "active"})
    assert heap4_active.verdict == "supported"
    heap3_inactive = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/MemMang/heap_3.c", "object": "inactive"})
    assert heap3_inactive.verdict == "supported"
    cm3_inactive = verify_claim(repo, {"claim_type": "file_active", "subject": "portable/GCC/ARM_CM3/port.c", "object": "inactive"})
    assert cm3_inactive.verdict == "supported"

    timer_active = verify_claim(repo, {"claim_type": "build_active", "subject": "xTimerCreateTimerTask"})
    assert timer_active.verdict == "unknown" or timer_active.verdict == "contradicted"
    # The raw fact store must retain inactive evidence, so LLMs can explain why
    # the timer service path is absent for this target profile.
    store = open_store(repo)
    inactive_timer_defs = [
        fact for fact in store.query_facts("fact_type='symbol' AND symbol='xTimerCreateTimerTask'")
        if fact.payload.get("build_status") == "inactive"
    ]
    assert inactive_timer_defs
    inactive_fact = inactive_timer_defs[0]
    assert inactive_fact.payload.get("guard_expressions") == ["( configUSE_TIMERS == 1 )"]
    assert inactive_fact.payload.get("guard_macro_values") == {"configUSE_TIMERS": "0"}
    chain = inactive_fact.payload.get("build_guard_chain") or []
    assert chain and chain[0]["evaluated_with"] == {"configUSE_TIMERS": "0"}
    assert chain[0]["effective_status"] == "inactive"

    call_bundle = verify_claim_text(repo, "vTaskStartScheduler calls xTimerCreateTimerTask.")
    assert call_bundle.overall_verdict in {"contradicted", "unknown"}
    assert call_bundle.verdicts[0].verdict in {"contradicted", "unknown"}


def test_phase7_freertos_answer_contract_preserves_target_profile_constraints(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / TIMERS_OFF_CASE_FILE.name)
    assert report.ok, report.to_dict()

    verified = verify_answer(
        repo,
        "configUSE_TIMERS is 0 in the target build. portable/MemMang/heap_3.c is inactive in the target profile.",
    )
    assert verified.overall_verdict == "supported"
    assert verified.safety_level == "safe"
    assert verified.build_context["target_profiles"] == ["freertos-gcc-arm-cm4f-timers-off"]
    assert verified.build_context["macros"]["configUSE_TIMERS"] == "0"
    assert "portable/MemMang/heap_3.c" in verified.build_context["inactive_files"]
    assert any("Scope build-sensitive statements to target profile 'freertos-gcc-arm-cm4f-timers-off'" in c for c in verified.response_constraints)
    assert any("source-present but inactive" in c and "portable/MemMang/heap_3.c" in c for c in verified.response_constraints)
    assert any("Distinguish source presence from target-build activity" in item for item in verified.answer_obligations)

    contract = build_answer_contract(
        str(repo),
        "configUSE_TIMERS is 0 in the target build. portable/MemMang/heap_3.c is inactive in the target profile.",
    )
    assert contract.can_answer is True
    assert contract.must_not_send is False
    assert contract.build_context["macros"] == {"configUSE_TIMERS": "0"}
    assert "portable/MemMang/heap_3.c" in contract.build_context["inactive_files"]
    assert any("inactive for the indexed target profile" in q for q in contract.required_qualifications)
    assert any("Do not describe behavior from portable/MemMang/heap_3.c as active" in c for c in contract.response_constraints)


def test_phase7_freertos_target_profile_diff_explains_timer_macro_change(tmp_path: Path) -> None:
    on_repo = tmp_path / "on"
    off_repo = tmp_path / "off"
    shutil.copytree(FIXTURE, on_repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    shutil.copytree(FIXTURE, off_repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))

    assert run_real_repo_eval(on_repo, on_repo / CASE_FILE.name).ok
    assert run_real_repo_eval(off_repo, off_repo / TIMERS_OFF_CASE_FILE.name).ok

    diff = build_target_profile_diff(on_repo, off_repo, "xTimerCreateTimerTask").to_dict()
    assert diff["status_changed"] is True
    assert diff["left"]["status"] == "active"
    assert diff["right"]["status"] == "inactive"
    assert diff["macro_differences"] == {"configUSE_TIMERS": {"left": "1", "right": "0"}}
    assert diff["left"]["build_guard_chain"][0]["evaluated_with"] == {"configUSE_TIMERS": "1"}
    assert diff["right"]["build_guard_chain"][0]["evaluated_with"] == {"configUSE_TIMERS": "0"}


def test_phase7_freertos_collect_evidence_includes_build_answer_constraints(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / TIMERS_OFF_CASE_FILE.name)
    assert report.ok, report.to_dict()

    bundle = collect_evidence(repo, "xTimerCreateTimerTask の定義は？", mode="definition")
    assert bundle.facts
    assert any(f.payload.get("build_status") == "inactive" for f in bundle.facts)
    assert any("Scope build-sensitive statements to target profile 'freertos-gcc-arm-cm4f-timers-off'" in c for c in bundle.response_constraints)
    assert any("inactive in the target build" in c for c in bundle.response_constraints)


def test_phase7_freertos_static_only_allocation_profile_marks_dynamic_apis_inactive(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / STATIC_ONLY_CASE_FILE.name)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["metrics"]["scenario_count"] == 10
    assert payload["metrics"]["passed_scenarios"] == 10
    assert payload["metrics"]["failed_scenarios"] == 0

    dynamic = verify_claim_text(repo, "dynamic allocation is disabled in the target profile.").verdicts[0]
    assert dynamic.claim.claim_type == "allocation_profile"
    assert dynamic.verdict == "supported"
    assert dynamic.supporting_facts[0].payload.get("macro_name") == "configSUPPORT_DYNAMIC_ALLOCATION"
    assert dynamic.supporting_facts[0].payload.get("macro_value") == "0"

    static = verify_claim_text(repo, "static allocation is enabled in the target profile.").verdicts[0]
    assert static.claim.claim_type == "allocation_profile"
    assert static.verdict == "supported"
    assert static.supporting_facts[0].payload.get("macro_name") == "configSUPPORT_STATIC_ALLOCATION"
    assert static.supporting_facts[0].payload.get("macro_value") == "1"

    task_dynamic = verify_claim(repo, {"claim_type": "build_active", "subject": "xTaskCreate"})
    assert task_dynamic.verdict == "contradicted"
    assert task_dynamic.reason_code == "target_only_has_inactive_build_evidence"
    inactive_fact = task_dynamic.contradicting_facts[0]
    assert inactive_fact.payload.get("guard_macro_values", {}).get("configSUPPORT_DYNAMIC_ALLOCATION") == "0"
    assert any(item.get("expression") == "( configSUPPORT_DYNAMIC_ALLOCATION == 1 )" for item in inactive_fact.payload.get("build_guard_chain") or [])

    task_static = verify_claim(repo, {"claim_type": "build_active", "subject": "xTaskCreateStatic"})
    assert task_static.verdict == "supported"

    contract = build_answer_contract(
        str(repo),
        "dynamic allocation is disabled in the target profile. static allocation is enabled in the target profile.",
    )
    assert contract.can_answer is True
    assert contract.build_context["allocation_profile"] == {"dynamic": "disabled", "static": "enabled"}
    assert contract.build_context["macros"]["configSUPPORT_DYNAMIC_ALLOCATION"] == "0"
    assert contract.build_context["macros"]["configSUPPORT_STATIC_ALLOCATION"] == "1"
    assert any("dynamic allocation is disabled" in c for c in contract.response_constraints)


def test_phase7_freertos_allocation_profile_diff_explains_dynamic_api_change(tmp_path: Path) -> None:
    dynamic_repo = tmp_path / "dynamic"
    static_repo = tmp_path / "static"
    shutil.copytree(FIXTURE, dynamic_repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    shutil.copytree(FIXTURE, static_repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))

    from repoanalyzer.cpp.ingest import ingest_repo

    ingest_repo(dynamic_repo, config_path=dynamic_repo / "repoanalyzer_dynamic_only.yml")
    ingest_repo(static_repo, config_path=static_repo / "repoanalyzer_static_only.yml")

    diff = build_target_profile_diff(dynamic_repo, static_repo, "xTaskCreate").to_dict()
    assert diff["status_changed"] is True
    assert diff["left"]["status"] == "active"
    assert diff["right"]["status"] == "inactive"
    assert diff["macro_differences"]["configSUPPORT_DYNAMIC_ALLOCATION"] == {"left": "1", "right": "0"}
    assert any(item.get("evaluated_with") == {"configSUPPORT_DYNAMIC_ALLOCATION": "1"} for item in diff["left"]["build_guard_chain"])
    assert any(item.get("evaluated_with") == {"configSUPPORT_DYNAMIC_ALLOCATION": "0"} for item in diff["right"]["build_guard_chain"])


def test_phase7_freertos_profile_matrix_compares_real_target_profiles(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)

    from repoanalyzer.evidence.profile_matrix import run_profile_matrix

    report = run_profile_matrix(repo, repo / "phase7_freertos_profile_matrix.yaml")
    payload = report.to_dict()

    assert report.ok, payload
    assert payload["schema_version"] == "profile_matrix_report.v1"
    assert payload["coverage_summary"]["profile_count"] == 4
    assert payload["coverage_summary"]["target_count"] == 9
    assert payload["coverage_summary"]["changed_target_count"] >= 3

    profiles = {profile["id"]: profile for profile in payload["profiles"]}
    assert profiles["timers_on"]["macros"]["configUSE_TIMERS"] == "1"
    assert profiles["timers_off"]["macros"]["configUSE_TIMERS"] == "0"
    assert profiles["static_only"]["allocation_profile"] == {"dynamic": "disabled", "static": "enabled"}
    assert profiles["dynamic_only"]["allocation_profile"] == {"dynamic": "enabled", "static": "disabled"}

    target_matrix = {target["id"]: target for target in payload["target_matrix"]}
    assert target_matrix["timer_service_task"]["statuses"] == {
        "timers_on": "active",
        "timers_off": "inactive",
        "dynamic_only": "active",
        "static_only": "active",
    }
    assert target_matrix["timer_service_task"]["changed"] is True
    assert target_matrix["timer_service_task"]["macro_differences"]["configUSE_TIMERS"] == {
        "timers_on": "1",
        "timers_off": "0",
        "dynamic_only": "1",
        "static_only": "1",
    }
    assert target_matrix["dynamic_task_create"]["statuses"]["static_only"] == "inactive"
    assert target_matrix["static_task_create"]["statuses"]["dynamic_only"] == "inactive"
    assert target_matrix["selected_heap"]["changed"] is False
    assert target_matrix["non_selected_heap"]["changed"] is False

    static_contract = profiles["static_only"]["answer_contracts"]["allocation_contract"]
    assert static_contract["build_context"]["allocation_profile"] == {"dynamic": "disabled", "static": "enabled"}
    assert any("dynamic allocation is disabled" in item for item in static_contract["response_constraints"])


def test_phase7_freertos_hook_assert_trace_semantics_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    relations = store.query_facts(
        "fact_type='relation' AND predicate IN ('invokes_trace_hook','invokes_assert_handler','invokes_application_hook','coverage_marker')"
    )
    assert any(f.subject == "xTaskCreate" and f.predicate == "invokes_trace_hook" and f.object == "traceTASK_CREATE" for f in relations)
    assert any(f.subject == "xTaskCreate" and f.predicate == "invokes_assert_handler" and f.object == "configASSERT" for f in relations)
    assert any(f.subject == "pvPortMalloc" and f.predicate == "invokes_application_hook" and f.payload.get("api_name") == "vApplicationMallocFailedHook" for f in relations)
    assert any(f.subject == "prvIdleTask" and f.predicate == "coverage_marker" and f.payload.get("api_name") == "mtCOVERAGE_TEST_MARKER" for f in relations)

    bundle = verify_claim_text(
        repo,
        "xTaskCreate invokes trace hook traceTASK_CREATE. "
        "xTaskCreate invokes assert handler configASSERT. "
        "pvPortMalloc invokes application hook vApplicationMallocFailedHook. "
        "prvIdleTask hits coverage marker.",
    )
    assert bundle.overall_verdict == "conditional"
    assert {v.claim.object for v in bundle.verdicts if v.claim.claim_type == "hook_assert_trace_semantic"} == {
        "invokes_trace_hook",
        "invokes_assert_handler",
        "invokes_application_hook",
        "coverage_marker",
    }
    assert "trace_hook_target_unknown" in bundle.unknown_reasons
    assert "assert_handler_config_dependent" in bundle.unknown_reasons
    assert "application_defined_hook_target_unknown" in bundle.unknown_reasons
    assert "coverage_marker_not_runtime_behavior" in bundle.unknown_reasons

    contract = build_answer_contract(
        str(repo),
        "xTaskCreate invokes trace hook traceTASK_CREATE. "
        "xTaskCreate invokes assert handler configASSERT. "
        "pvPortMalloc invokes application hook vApplicationMallocFailedHook. "
        "prvIdleTask hits coverage marker.",
    )
    assert contract.can_answer is True
    assert contract.safety_level == "must_qualify"
    assert "xTaskCreate" in contract.build_context["trace_hook_functions"]
    assert "xTaskCreate" in contract.build_context["assert_handler_functions"]
    assert "pvPortMalloc" in contract.build_context["application_hook_functions"]
    assert "prvIdleTask" in contract.build_context["coverage_marker_functions"]
    assert any("trace hook/instrumentation semantics" in item for item in contract.response_constraints)
    assert any("configASSERT/assert behavior" in item for item in contract.response_constraints)
    assert any("application-defined hook" in item for item in contract.response_constraints)
    assert any("coverage/test marker evidence" in item for item in contract.response_constraints)
