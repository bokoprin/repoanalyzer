# Phase7 FreeRTOS probe fixture

This fixture is a compact FreeRTOS-Kernel-derived embedded-C probe. It preserves the call shapes found in the uploaded FreeRTOS-Kernel source while keeping regression tests small and stable.

Covered paths:

- task creation: `xTaskCreate -> prvCreateTask -> prvInitialiseNewTask` and `xTaskCreate -> prvAddNewTaskToReadyList`
- scheduler start: `vTaskStartScheduler -> xTimerCreateTimerTask` and `vTaskStartScheduler -> xPortStartScheduler`
- tick ISR: `xPortSysTickHandler -> xTaskIncrementTick` plus `execution_context: isr`
- queues: `xQueueGenericSend`, `xQueueGenericSendFromISR`, and `xQueueReceive`, including task-vs-ISR context annotations
- timers: `xTimerCreate`, `prvProcessTimerOrBlockTask`, `prvProcessReceivedCommands`, callback storage, callback invocation, and callback dataflow

The suite includes a FreeRTOS macro-wrapped task function: `prvTimerTask` is declared through the `portTASK_FUNCTION` macro. repoanalyzer now treats this known macro as a function definition while preserving macro provenance, so `prvTimerTask -> prvProcessReceivedCommands` should be verifiable.

The timer probe intentionally treats `pxNewTimer->pxCallbackFunction = pxCallbackFunction` as `stores_callback` and `pxTimer->pxCallbackFunction(...)` as `invokes_callback` rather than direct calls to a concrete function.


The callback dataflow scenario links `xTimerCreate` passing `pxCallbackFunction` into `prvInitialiseNewTimer`, storage in `pxNewTimer->pxCallbackFunction`, and later invocation in `prvProcessExpiredTimer`. It remains conditional because the concrete runtime callback target is not resolved.

Execution-context evidence is exposed as `has_execution_context` relations and as `execution_context` payload fields on call/relation facts. `FromISR` APIs and interrupt handlers are marked `isr`; normal FreeRTOS task APIs and `portTASK_FUNCTION` entries are marked `task`.


Build-profile checks:

- `phase7_freertos_probe_cases.yaml` uses `configUSE_TIMERS=1` and expects timer-service evidence to be active.
- `phase7_freertos_timers_off_cases.yaml` uses `configUSE_TIMERS=0` and expects guarded timer-service definitions to remain indexed but inactive.
- `build_config` facts expose target-profile macro values so claim verification can distinguish `configUSE_TIMERS=1` from `configUSE_TIMERS=0`.
