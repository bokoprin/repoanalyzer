# FreeRTOS Phase7 embedded-C probe evaluation

This suite adds a FreeRTOS-Kernel-derived embedded-C probe next to the Sakura Editor-derived Phase7 suite.
Sakura remains the Windows GUI / command-dispatch / resource benchmark; this fixture exercises embedded-C patterns that Sakura does not cover.

The fixture is located at:

```bash
 tests/fixtures_cpp/phase7_freertos_probe
```

It intentionally uses one target-like profile instead of indexing every FreeRTOS portable port:

- common kernel sources: `tasks.c`, `queue.c`, `timers.c`, `list.c`
- ARM Cortex-M4F GCC port: `portable/GCC/ARM_CM4F/port.c`, `portmacro.h`
- selected public headers under `include/`
- `FreeRTOSConfig.h`
- `compile_commands.json` with FreeRTOS config macros such as `configSUPPORT_DYNAMIC_ALLOCATION=1` and `configUSE_TIMERS=1`

The case file is:

```bash
tests/fixtures_cpp/phase7_freertos_probe/phase7_freertos_probe_cases.yaml
```

Run it with:

```bash
PYTHONPATH=. python -m repoanalyzer.cli real-repo-eval \
  tests/fixtures_cpp/phase7_freertos_probe \
  tests/fixtures_cpp/phase7_freertos_probe/phase7_freertos_probe_cases.yaml \
  --output json
```

## Covered traces

The suite validates that repoanalyzer can collect and verify direct source-backed call evidence for these FreeRTOS paths:

- `xTaskCreate -> prvCreateTask -> prvInitialiseNewTask`
- `xTaskCreate -> prvAddNewTaskToReadyList`
- `vTaskStartScheduler -> xTimerCreateTimerTask`
- `vTaskStartScheduler -> xPortStartScheduler`
- `xPortSysTickHandler -> xTaskIncrementTick` with `execution_context: isr`
- `xQueueGenericSend -> prvCopyDataToQueue` with `execution_context: task`
- `xQueueReceive -> prvCopyDataFromQueue`
- `xQueueGenericSendFromISR -> prvCopyDataToQueue` with `execution_context: isr`
- `xTimerCreate -> prvInitialiseNewTimer`
- `prvProcessTimerOrBlockTask -> prvProcessExpiredTimer`
- `prvProcessReceivedCommands -> xQueueReceive`


## ISR/task execution-context evidence

The suite validates execution-context annotations as first-class evidence instead of leaving them implicit in naming conventions:

```text
xPortSysTickHandler runs in ISR context.
xQueueGenericSendFromISR runs in ISR context.
xQueueGenericSend runs in task context.
prvTimerTask runs in task context.
```

repoanalyzer emits these annotations as relation facts and also propagates the call-site context into call/reference payloads:

```text
predicate: has_execution_context
relation_kind: execution_context_annotation
subject: xQueueGenericSendFromISR
object: isr
execution_context_basis: freertos_from_isr_suffix
```

For call facts, `execution_context` means the caller/call-site context.  For example, `xQueueGenericSendFromISR -> prvCopyDataToQueue` is marked `isr`, while `xQueueGenericSend -> prvCopyDataToQueue` is marked `task`.  This lets downstream answer contracts avoid conflating task-context and ISR-context paths.

## Macro-wrapped task function support

The suite also validates a FreeRTOS-specific macro-wrapped task function:

```text
prvTimerTask calls prvProcessReceivedCommands.
```

In FreeRTOS this task function is declared through the `portTASK_FUNCTION` macro. repoanalyzer now normalizes known task-function macros such as `portTASK_FUNCTION( prvTimerTask, pvParameters )` as function definitions while preserving macro provenance in the symbol payload:

```text
macro_wrapped_function: true
macro_name: portTASK_FUNCTION
definition_source: macro_wrapped_function
```

This turns the earlier safe-unknown gap into source-backed evidence without pretending the source contained a direct `void prvTimerTask(...)` signature.

## Timer callback storage and invocation relations

The suite now also validates callback/function-pointer evidence without treating it as an unconditional direct call:

```text
prvInitialiseNewTimer stores callback pxCallbackFunction.
prvProcessExpiredTimer invokes callback pxCallbackFunction.
```

These are emitted as relation facts:

```text
predicate: stores_callback
relation_kind: callback_storage
storage_expr: pxNewTimer->pxCallbackFunction
object: pxCallbackFunction
```

and:

```text
predicate: invokes_callback
relation_kind: callback_invocation
callback_storage_expr: pxTimer->pxCallbackFunction
unknown_type: callback_target_unknown
```

The verifier supports structured claim types `stores_callback` and `invokes_callback`.  These verdicts are intentionally conditional because callback storage/invocation evidence is not the same as a direct call to a concrete callback target.

## Timer callback dataflow trace

The suite also validates a conservative callback dataflow relation:

```text
xTimerCreate dataflows callback pxCallbackFunction to prvProcessExpiredTimer.
```

This relation links three pieces of evidence:

1. `xTimerCreate` passes `pxCallbackFunction` to `prvInitialiseNewTimer`.
2. `prvInitialiseNewTimer` stores it into `pxNewTimer->pxCallbackFunction`.
3. `prvProcessExpiredTimer` later invokes `pxTimer->pxCallbackFunction(...)`.

repoanalyzer emits this as a relation fact rather than a direct call:

```text
predicate: callback_dataflows_to
relation_kind: callback_dataflow_trace
subject: xTimerCreate
object: prvProcessExpiredTimer
callback_symbol: pxCallbackFunction
storage_function: prvInitialiseNewTimer
invocation_function: prvProcessExpiredTimer
unknown_type: callback_target_unknown
```

The verifier supports structured and deterministic-text `callback_dataflow` claims.  The verdict remains `conditional` because the trace proves argument-passing/storage/invocation-site linkage, but it does not resolve the concrete runtime callback target or prove that the callback executes on every path.

## Task entry dataflow trace

The suite also validates a conservative FreeRTOS task-entry dataflow relation:

```text
xTaskCreate dataflows task entry pxTaskCode to pxPortInitialiseStack.
```

This relation links task-entry argument passing through task creation helper code:

1. `xTaskCreate` passes `pxTaskCode` to `prvCreateTask`.
2. `prvCreateTask` forwards `pxTaskCode` to `prvInitialiseNewTask`.
3. `prvInitialiseNewTask` stores the entry in the TCB-like field and passes it to `pxPortInitialiseStack`.

repoanalyzer emits this as semantic relation evidence rather than a direct call:

```text
predicate: task_entry_dataflows_to
relation_kind: task_entry_dataflow_trace
subject: xTaskCreate
object: pxPortInitialiseStack
task_entry_symbol: pxTaskCode
storage_function: prvInitialiseNewTask
stack_initialiser: pxPortInitialiseStack
unknown_type: task_entry_execution_deferred
```

The verifier supports structured and deterministic-text `task_entry_dataflow` claims.  The verdict remains `conditional` because the trace proves task-entry registration/stack-initialisation linkage, but it does not prove an immediate direct call to the task entry and does not verify scheduler/port-layer execution on every path.
## Build-aware FreeRTOS target profile checks

The fixture now includes a second target profile that sets `configUSE_TIMERS=0` via `compile_commands_timers_off.json` and `repoanalyzer_timers_off.yml`.

```bash
PYTHONPATH=. python -m repoanalyzer.cli real-repo-eval \
  tests/fixtures_cpp/phase7_freertos_probe \
  tests/fixtures_cpp/phase7_freertos_probe/phase7_freertos_timers_off_cases.yaml \
  --output json
```

repoanalyzer emits `build_config` facts for target-profile macro values, for example:

```text
fact_type: build_config
predicate: macro_value
subject: configUSE_TIMERS
object: 0
build_status_precision: target_profile_macro
```

The verifier supports `build_config` claims, so a target-profile assertion such as `configUSE_TIMERS is 0 in the target build` can be supported while `configUSE_TIMERS == 1` is contradicted for the same index.

When `configUSE_TIMERS=0`, timer-service definitions guarded by `#if ( configUSE_TIMERS == 1 )` are retained as inactive evidence.  This lets repoanalyzer explain that `xTimerCreateTimerTask` exists in source but is inactive for the selected target profile, instead of either losing the evidence or treating it as active.  `build_active` now prioritizes definition facts over header declarations so guarded inactive definitions are not hidden by conditional header prototypes.


## Target profile as first-class build context

The FreeRTOS probe now uses `cpp.target_profile` as the primary build-context
entry point instead of scattering target information across `compile_commands`,
`include_dirs`, and `macros` only. A profile can declare:

```yaml
cpp:
  target_profile:
    name: freertos-gcc-arm-cm4f-timers-on
    compile_commands: compile_commands.json
    include_dirs:
      - .
      - include
      - portable/GCC/ARM_CM4F
      - portable/MemMang
    macros:
      - configUSE_TIMERS=1
    config_headers:
      - FreeRTOSConfig.h
    active_path_prefixes:
      - tasks.c
      - queue.c
      - timers.c
      - include
      - portable
    inactive_path_prefixes: []
    active_port: portable/GCC/ARM_CM4F
    heap: heap_4
```

Ingest records this as `target_profile` facts and index metadata. Evidence facts
also carry the active target profile through `tu_context.target_profile`, and
claim verification supports structured and natural-language target-profile
claims, for example:

- `target profile is freertos-gcc-arm-cm4f-timers-on.`
- `active_port is portable/GCC/ARM_CM4F in the target profile.`

`repo-status` is target-profile aware: when an index was created with
`active_path_prefixes` / `inactive_path_prefixes`, status checks compare the
current tree against the same selected target slice instead of treating every
other FreeRTOS port as a dirty “new” file.


## Target-profile file selection evidence

`cpp.target_profile` now drives both indexing and explicit file-selection
evidence.  For each candidate C/C++ file, ingest emits a `target_file` fact:

```text
fact_type: target_file
predicate: file_active | file_inactive
subject: portable/GCC/ARM_CM4F/port.c
object: freertos-gcc-arm-cm4f-timers-on
selection_reasons:
  - active_port
```

The selection combines multiple target-profile inputs:

- `active_path_prefixes` keeps the target slice small.
- `active_port` marks the selected FreeRTOS portable port active and other
  `portable/*` ports inactive.
- `heap` marks the selected `portable/MemMang/heap_*.c` implementation active
  and other heap implementations inactive.
- `compile_commands` keeps source files outside the selected translation units
  inactive even when they live under a broad active prefix.
- config macros such as `configUSE_TIMERS` continue to drive line/symbol-level
  active or inactive evidence inside selected files.

The verifier supports `file_active` claims, so LLM workflows can ask whether a
file is active for the selected target profile without inferring from path names
alone. Examples:

```text
portable/GCC/ARM_CM4F/port.c is active in the target profile.
portable/GCC/ARM_CM3/port.c is inactive in the target profile.
portable/MemMang/heap_4.c is active in the target profile.
portable/MemMang/heap_3.c is inactive in the target profile.
```

Inactive file-selection evidence is not treated as absence. It is retained as a
positive explanation that the source file exists but is outside the selected
profile.

## Target-profile-aware answer contract

The FreeRTOS probe now propagates target-profile file selection and macro evidence into the workflow answer contract, not only into low-level claim verdicts.

When a verified answer uses facts such as:

- `configUSE_TIMERS is 0 in the target build.`
- `portable/MemMang/heap_3.c is inactive in the target profile.`

`verify-answer`, `answer-contract`, and `workflow-run` expose:

- `build_context.target_profiles`
- `build_context.macros`
- `build_context.active_files`
- `build_context.inactive_files`
- `response_constraints`
- `answer_obligations`

This makes build-sensitive output constraints explicit.  An LLM consuming the contract must preserve the active target profile, macro values, and active/inactive file status.  Inactive source evidence must be described as source-present but target-inactive, not as active runtime behavior.

For example, in the `freertos-gcc-arm-cm4f-timers-off` profile, the contract requires the answer to mention that `configUSE_TIMERS=0` and that `portable/MemMang/heap_3.c` is inactive due to heap selection.  In the uploaded real FreeRTOS source profile, the contract similarly records `freertos-gcc-arm-cm4f-template-heap4`, `configUSE_TIMERS=1`, `portable/GCC/ARM_CM4F/port.c` as active, and `portable/MemMang/heap_3.c` as inactive.

## Build condition provenance and target profile diff

The FreeRTOS probe now preserves preprocessor provenance for build-sensitive
facts.  Symbols and calls inside guards such as `#if ( configUSE_TIMERS == 1 )`
carry a `build_guard_chain` payload even when the guard evaluates active for the
selected profile.  Each guard entry records the expression, local/effective
status, and the target-profile macro values used during evaluation.

For example, `xTimerCreateTimerTask` is active in the timers-on profile because
`configUSE_TIMERS=1` satisfies `( configUSE_TIMERS == 1 )`.  The same symbol is
retained as inactive evidence in the timers-off profile because
`configUSE_TIMERS=0` makes that guard inactive.  This distinction is surfaced in
`answer-contract` as `build_context.build_conditions` so final answers can say
why a symbol is active or inactive instead of only saying that it is present or
absent.

A `target-profile-diff` CLI command compares the indexed provenance for one
symbol/path across two indexed target-profile repos:

```bash
python3 -m repoanalyzer.cli target-profile-diff <timers-on-repo> <timers-off-repo> \
  --target xTimerCreateTimerTask
```

The report includes both profile statuses, macro differences, and the guard
chains that explain the status change.

## Allocation Profile

The FreeRTOS probe now treats `configSUPPORT_DYNAMIC_ALLOCATION` and
`configSUPPORT_STATIC_ALLOCATION` as first-class allocation-profile evidence.
Target-profile facts include `allocation_setting` entries for dynamic/static
allocation, and guarded API definitions preserve the macro guard provenance.

Representative static-only profile behavior:

- `dynamic allocation is disabled in the target profile` is supported by
  `configSUPPORT_DYNAMIC_ALLOCATION=0`.
- `static allocation is enabled in the target profile` is supported by
  `configSUPPORT_STATIC_ALLOCATION=1`.
- dynamic APIs such as `xTaskCreate`, `xTimerCreate`, and
  `xQueueGenericCreate` are source-present but target-inactive.
- static APIs such as `xTaskCreateStatic`, `xTimerCreateStatic`, and
  `xQueueGenericCreateStatic` remain target-active.

This is intentionally build-aware: dynamic/static API availability must be
scoped to the indexed target profile and must not be inferred from source
presence alone.

## ISR/task API answer contract

The FreeRTOS probe now promotes `execution_context` evidence into the answer
contract.  When an answer cites both a normal task-context API and its `FromISR`
variant, the contract records the API contexts and emits guardrails that prevent
LLMs from treating the two APIs as interchangeable.

Example evidence:

- `xQueueGenericSend runs in task context`
- `xQueueGenericSendFromISR runs in ISR context`

The answer contract includes:

- `build_context.api_contexts.xQueueGenericSend = task`
- `build_context.api_contexts.xQueueGenericSendFromISR = isr`
- `build_context.api_context_pairs[] = { task_api: xQueueGenericSend, isr_api: xQueueGenericSendFromISR }`

It also requires answers to state that `xQueueGenericSendFromISR` is ISR-context
evidence and `xQueueGenericSend` is task-context evidence.  The contract must not
allow behavior supported only by the task-context API to be presented as ISR-safe
unless the corresponding `FromISR` API is supported by evidence.

## Scheduler / Yield Semantics

The FreeRTOS probe also exercises scheduler-side semantics that should not be
flattened into ordinary direct-call evidence:

- `taskENTER_CRITICAL()` -> `enters_critical_section`
- `taskEXIT_CRITICAL()` -> `exits_critical_section`
- `vTaskSuspendAll()` -> `suspends_scheduler`
- `xTaskResumeAll()` -> `resumes_scheduler`
- `portYIELD_WITHIN_API()` / `portYIELD_FROM_ISR(...)` -> `requests_context_switch`
- `portSET_INTERRUPT_MASK_FROM_ISR()` -> `masks_interrupts_from_isr`
- `portCLEAR_INTERRUPT_MASK_FROM_ISR(...)` -> `clears_interrupt_mask_from_isr`

These relations are semantic evidence, not proof that a context switch has
already happened or that a critical section covers all possible paths.  The
answer contract therefore carries obligations to preserve critical-section,
scheduler suspension/resumption, ISR interrupt-mask, and scheduler-dependent
yield qualifications when an LLM turns the evidence into prose.

## Port Boundary Unknown

The FreeRTOS probe now records conservative port-layer boundary evidence.  Calls
from common kernel code into target-specific port functions are represented as
semantic relations rather than as fully verified runtime paths:

- `vTaskStartScheduler -> xPortStartScheduler` -> `crosses_port_boundary`
- `prvInitialiseNewTask -> pxPortInitialiseStack` -> `crosses_port_boundary`
- `xPortSysTickHandler` definitions under the selected port -> `has_port_boundary`

These relations deliberately keep unknowns such as `port_layer_boundary`,
`assembly_boundary_unverified`, `startup_file_missing`,
`port_stack_layout_target_specific`, and `vector_table_unverified`.  This lets a
final answer say that C-source evidence reaches the selected FreeRTOS port layer
while avoiding unsupported claims about startup code, vector-table binding,
assembly context-switch code, or exact stack layout.

The answer contract exposes this under `build_context.port_boundaries`,
`port_boundary_callers`, `port_boundary_callees`, `port_layer_functions`,
`assembly_boundary_functions`, and `vector_table_unverified_functions`, and it
adds obligations to preserve the port-boundary qualifications in natural
language answers.

## Queue/List State Transition

The FreeRTOS probe now records semantic task/list state transitions separately
from raw list helper calls.  The lightweight extractor recognizes common
FreeRTOS idioms such as:

- `prvAddTaskToReadyList(...)` / ready-list insertions -> `moves_task_to_ready_list`
- `vTaskPlaceOnEventList(...)` / event-list insertions -> `blocks_task_on_event_list`
- `xTaskRemoveFromEventList(...)` -> `unblocks_task_from_event_list`
- `prvAddCurrentTaskToDelayedList(...)` / delayed-list insertions -> `moves_task_to_delayed_list`
- `uxListRemove(...)` -> `removes_task_from_list`

These relations intentionally carry `task_state_transition_semantic`: they show
source-backed list-state movement, not a complete proof of every runtime
scheduler state transition.  `verify-text` supports claims such as
`prvAddNewTaskToReadyList moves task to ready list` and returns conditional
verdicts with this qualification.  `answer-contract` exposes the evidence under
`build_context.task_state_transitions`, `ready_list_functions`,
`delayed_list_functions`, `event_blocking_functions`, and
`event_unblocking_functions`, so final LLM answers must distinguish ready,
delayed, blocked, and unblocked task-list state evidence.

## Kernel Object Semantics Pack

The FreeRTOS probe now includes semantic evidence for kernel communication and
synchronization objects.  These relations are intentionally not modeled as plain
call edges; they preserve the RTOS meaning that an LLM must carry into a final
answer.

Covered relation families:

- `sends_to_stream_buffer` / `receives_from_stream_buffer`
- `sends_to_message_buffer` / `receives_from_message_buffer`
- `sets_event_bits` / `clears_event_bits` / `waits_for_event_bits` / `syncs_event_bits`
- `notifies_task` / `waits_for_task_notification`
- `gives_semaphore` / `takes_semaphore` / `creates_semaphore`
- `gives_mutex` / `takes_mutex` / `creates_mutex`

For public APIs implemented as FreeRTOS macros, such as `xMessageBufferSend` or
`xSemaphoreGive`, repoanalyzer emits macro-level kernel-object semantic evidence
from the header so the public API meaning is not lost behind stream-buffer or
queue internals.

These verdicts are normally `conditional`: they establish supported source-level
kernel-object semantics but do not prove the full runtime object state, scheduling
order, wake-up behavior, or application-specific configuration.

## Hook / Assert / Trace Semantics Pack

The FreeRTOS probe now records hook/assert/trace evidence separately from normal
call edges.  Covered relation families are:

- `invokes_trace_hook` for `trace*` instrumentation macros
- `invokes_assert_handler` for `configASSERT(...)`
- `invokes_application_hook` for application callbacks such as
  `vApplicationMallocFailedHook`, `vApplicationStackOverflowHook`,
  `vApplicationIdleHook`, and `vApplicationTickHook`
- `coverage_marker` for `mtCOVERAGE_TEST_MARKER(...)`

These relations intentionally carry safe-unknown reasons such as
`trace_hook_target_unknown`, `assert_handler_config_dependent`,
`application_defined_hook_target_unknown`, and
`coverage_marker_not_runtime_behavior`.  They allow final answers to say that
source evidence reaches trace/assert/application-hook/coverage-marker extension
points without claiming a concrete hook implementation or runtime behavior that
is not present in the analyzed source.

## Batch 3: Heap Allocator Semantics

The FreeRTOS probe now captures heap implementation behavior as semantic evidence
instead of reducing it to ordinary call edges.  The extractor emits
`heap_allocator_semantic` relations such as:

- `allocates_heap_memory` for `pvPortMalloc`
- `frees_heap_memory` for `vPortFree`
- `coalesces_free_blocks` for `prvInsertBlockIntoFreeList` in heap_4/heap_5-like allocators
- `uses_libc_allocator` for heap_3-style `malloc`/`free` wrappers
- `uses_multiple_heap_regions` for heap_5-style `vPortDefineHeapRegions`

These relations are intentionally conditional evidence.  They describe allocator
implementation semantics, not a complete runtime heap-state proof.  Answer
contracts must preserve the selected heap implementation and must not generalize
heap_4 coalescing or heap_5 multi-region behavior to every FreeRTOS heap.

## Batch 4: SMP / MPU / Port Advanced Semantics

The FreeRTOS probe now records advanced target-specific port evidence for SMP,
MPU, privilege, assembly, and secure-context boundaries.  These relations are
not treated as ordinary call edges; they preserve the fact that the behavior is
port/profile/runtime dependent and often requires evidence outside common C
kernel source.

Covered relation families:

- `uses_smp_scheduler`
- `uses_core_affinity`
- `uses_cross_core_yield`
- `uses_smp_locking`
- `uses_mpu_wrappers`
- `configures_mpu_regions`
- `checks_mpu_access`
- `crosses_privilege_boundary`
- `uses_port_assembly`
- `uses_secure_context_boundary`

The corresponding verdicts are normally `conditional` with safe-unknown reasons
such as `smp_runtime_interleaving_unknown`,
`configNUMBER_OF_CORES_profile_dependent`, `core_affinity_runtime_state_unknown`,
`mpu_region_layout_target_specific`, `privilege_boundary_target_specific`,
`assembly_boundary_unverified`, and `secure_context_boundary_unverified`.

Answer contracts must preserve these boundaries.  For example, evidence that a
function uses SMP scheduling or core affinity should be qualified by the selected
target profile, core count, and runtime core state.  Evidence that a function
crosses a privilege or assembly boundary should not be expanded into a complete
runtime proof unless the relevant port/startup/assembly/MPU evidence is present.
