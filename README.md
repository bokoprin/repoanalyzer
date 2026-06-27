# repoanalyzer

C/C++ Code Evidence Engine for MCP-based LLM agents.

This rewrite intentionally focuses on one narrow goal: make local LLMs better at code analysis by giving them typed, source-grounded evidence from a C/C++ repository.

## Current MVP

- C/C++ fixture ingest
- build-aware source gating and lightweight preprocessor guard evaluation, including simple object-like macro aliases and limited integer/bitwise expressions
- fact payloads record the translation-unit macro context used for guard evaluation
- SQLite Code Fact Store
- definitions/references/callers/callees query primitives
- EvidenceBundle collection
- expected-evidence evaluation
- minimal MCP tool surface

## Non-goals for this core

- natural-language answer rendering
- GUI/Lab
- generic multi-language RAG
- embedding-first retrieval
- large OSS benchmark before golden fixtures pass

## Quick start

```bash
python -m repoanalyzer.cli ingest tests/fixtures_cpp/basic_call
python -m repoanalyzer.cli eval tests/fixtures_cpp/basic_call tests/fixtures_cpp/basic_call/cases.yaml
python -m repoanalyzer.cli collect-evidence tests/fixtures_cpp/basic_call "init_device はどこから呼ばれる？" --mode callers
```

- Phase 2 build-aware ingest now stores explicit `build_status` on facts, centralizes line-status analysis in `preprocessor_model.py`, records shallow include resolution, emits `header_visible_in_tu` relations, projects directly visible header facts into translation-unit context, and reports unsupported preprocessor expression diagnostics in fact payloads and EvidenceBundle unknowns.

### Phase 3 semantic call graph MVP

The active implementation now includes a lightweight C/C++ semantic extraction layer. It records qualified symbols, class/namespace scopes, constructors/destructors, shallow inheritance, member/static/constructor calls, overload candidates, function-pointer calls, callback registration relations, virtual-dispatch candidate sets, and a conservative cross-translation-unit symbol table for resolving calls to definitions in other compiled sources.

This layer is deliberately evidence-oriented rather than compiler-complete. When a semantic target cannot be proven, repoanalyzer keeps candidate facts and emits semantic unknowns/constraints in the EvidenceBundle so the final LLM answer can distinguish resolved, cross-TU resolved, candidate, indirect, virtual, and unsupported cases.

### Phase3 semantic MVP completion

The C/C++ semantic MVP now resolves simple `using` / `typedef` aliases, normalizes member receiver types through the cross-TU symbol table, enriches callback and function-pointer candidates across translation units, indexes projected header inline functions, and marks template declarations as unsupported semantic constructs rather than pretending they are fully instantiated. It also indexes shallow class/struct data members and resolves chained receiver calls such as `GetDocument()->m_cLayoutMgr.SearchWord(...)`, `object.member.method(...)`, and `ptr->member.method(...)` when function return types and field types are available.

### Phase4 claim verification

Phase4 adds structured claim verification.  Use it when an agent has a concrete claim and needs a verdict rather than another broad evidence search.

```bash
python -m repoanalyzer.cli verify-claim . \
  --claim-type calls \
  --subject app::Device::start \
  --object app::cross_target
```

The result is a `claim_verdict.v1` object whose verdict is one of `supported`, `conditional`, `unknown`, or `contradicted`.  Batch verification is available through `verify-claims` with a JSON file, and regression tests for claim verification can be run with `claim-eval`.

```bash
python -m repoanalyzer.cli claim-eval . tests/fixtures_cpp/<fixture>/claim_cases.yaml
```

Phase4 deliberately treats callback registration, indirect calls, virtual dispatch candidates, conditional build evidence, and unsupported C++ constructs as conditional/unknown rather than over-claiming direct execution.

### Phase4 natural-language claim extraction

Phase4 also includes a deterministic, limited natural-language claim extractor.  It is not an LLM and does not infer unstated claims.  It maps explicit English/Japanese patterns into the same structured claim types used by `verify-claim` / `verify-claims`.

```bash
python -m repoanalyzer.cli extract-claims \
  'app::phase3_driver は app::Device::start を呼び出す。app::Device::start の定義が存在する。'

python -m repoanalyzer.cli verify-text . \
  'app::phase3_driver は app::Device::start を呼び出す。app::registerCallback は app::callback_target をコールバック登録する。'
```

`verify-text` returns a `claim_evidence_bundle.v1` with `extracted_claims` metadata, including the matched text span and pattern id.  Unsupported or negated natural-language claims are not converted into inverse claims in this MVP; they are reported as extraction warnings.

### Evidence Quality Gate

EvidenceBundle and claim verification now include a normalized quality profile so LLM clients can separate source-grounded support from weak or incomplete evidence.  The profile combines source coverage from `.repoanalyzer-coverage-gap-report.json` when available, semantic resolution status, build status, and derived unknown reasons.

Returned bundles/verdicts include:

- `support_level`: `strong`, `medium`, `weak`, or `unknown`
- `unknown_reasons`: normalized reason codes such as `upstream_source_missing`, `unresolved_call_target`, or `conditional_build_evidence`
- `quality_profile`: `source_coverage_status`, `semantic_resolution_status`, `build_status`, `execution_context` / `execution_contexts`, and response constraints

When weak supporting evidence would otherwise produce an unconditional `supported` claim, `verify-claim` / `verify-text` downgrade it to `conditional`.  When contradiction depends on weak source/semantic/build evidence, the verdict is downgraded to `unknown` rather than using absence-style reasoning unsafely.

### Phase5-A store / index hardening

Phase5-A adds the first large-repo hardening layer without changing the meaning of existing C/C++ facts.

```bash
python -m repoanalyzer.cli repo-status .
python -m repoanalyzer.cli find-callers . init_device --limit 20 --offset 0
```

The SQLite index now records `schema_migrations`, `index_metadata`, and a `file_index` manifest containing path, hash, size, line count, mtime, source kind, and indexed timestamp. `repo-status` compares the current repository against that manifest and reports `clean` or `dirty` with `stale`, `missing`, and `new` file lists.

`repoanalyzer.yml` can exclude large or noisy trees during discovery:

```yaml
index:
  exclude_patterns:
    - vendor/**
    - generated/**
```

If files change after ingest, `collect-evidence` adds an `index_freshness` unknown and a response constraint so agents do not make completeness or absence claims from stale evidence.

### Phase5-B safe incremental ingest

Phase5-B adds a conservative incremental ingest mode for large-repo workflows:

```bash
python -m repoanalyzer.cli ingest . --incremental
python -m repoanalyzer.cli repo-status .
```

The incremental path is deliberately safe rather than clever. It updates changed, new, or deleted C/C++ source files when the build context is unchanged, then recomputes cross-TU resolution across the retained and refreshed facts. It refuses to mutate the index and returns `full_reingest_required` when header files, `compile_commands.json`, configured macros, include dirs, or exclude patterns change, because those inputs can affect many translation units.

`ingest --incremental` exits with status code `2` when a full ingest is required. Agents should then run a normal full ingest instead of relying on the stale index.

### Phase5-C: large repo query hardening

Phase5-C adds paginated query helpers and diagnostics:

```bash
python -m repoanalyzer.cli find-callers-page <repo> target --limit 100 --offset 0
python -m repoanalyzer.cli query-diagnostics <repo>
```

The paginated commands return `items` plus `page` metadata including `total`, `next_offset`, and warnings. `query-diagnostics` reports fact counts, indexed file roles (`project`, `vendor`, `generated`, `test`), largest files, and index freshness warnings.

Claim verification now treats dirty indexes conservatively: supported claims become conditional and contradicted claims become unknown until ingest is rerun.

### Phase6: LLM / MCP workflow hardening

Phase6 adds an agent-facing workflow layer on top of evidence collection and claim verification.  repoanalyzer still does not write the final natural-language answer; it returns deterministic workflow reports that an LLM client can use to decide whether a draft answer is safe to send.

```bash
python -m repoanalyzer.cli preflight .
python -m repoanalyzer.cli plan-question 'Does start_device call init_device?'
python -m repoanalyzer.cli verify-answer . 'start_device calls init_device'
python -m repoanalyzer.cli answer-contract . 'start_device calls init_device'
python -m repoanalyzer.cli workflow-run . 'Does start_device call init_device?' --answer-text 'start_device calls init_device'
python -m repoanalyzer.cli workflow-eval . tests/fixtures_cpp/<fixture>/workflow_cases.yaml
```

The workflow layer emits stable schemas:

- `agent_preflight.v1`: index readiness, freshness, diagnostics, required actions, and recommended tools.
- `answer_plan.v1`: deterministic tool plan for a question, including claim extraction / verification steps when applicable.
- `answer_verification_report.v1`: draft-answer claim verification with `safe`, `must_qualify`, `needs_more_evidence`, or `unsafe` safety levels.
- `safe_answer_contract.v1`: allowed, qualified, unknown, and prohibited claims plus required qualifications.
- `workflow_trace.v1`: preflight + plan + optional answer verification + safe answer contract in one agent trace.

The safety contract is intentionally conservative.  Contradicted claims produce `must_not_send=true`; conditional claims require explicit qualification; unsupported or unextracted claims require more evidence rather than being silently accepted.

### Phase6 extension: safer workflow sessions and claim extraction

Phase6 extension adds deterministic workflow hardening beyond the initial LLM/MCP workflow MVP:

- limited negated natural-language claim extraction, e.g. `A does not call B`;
- list decomposition for simple claim lists, e.g. `A calls B and C`;
- policy violations for unsafe answer wording such as absolute wording on contradicted or uncertain claims;
- recorded workflow traces via `workflow-run --record` and `workflow-history`.

Example:

```bash
python -m repoanalyzer.cli workflow-run . \
  'Does start_device call init_device?' \
  --answer-text 'start_device calls init_device' \
  --record --label smoke

python -m repoanalyzer.cli workflow-history .
```

## Phase7 real C/C++ repo validation

Phase7 adds a real-repository validation runner for C/C++ usage. It is intended to run against local real repositories or copied fixture repositories and classify failures before deciding the next parser/build/semantic improvements.

```bash
python -m repoanalyzer.cli real-repo-eval path/to/repo path/to/real_repo_cases.yaml
python -m repoanalyzer.cli real-repo-eval path/to/repo path/to/real_repo_cases.yaml --output json
```

The case file can run ingest, repo-status, query diagnostics, evidence checks, claim verification, and workflow safety checks in one report. The report schema is `real_repo_eval_report.v1` and includes timings, index metrics, diagnostics, scenario results, and failure categories such as `evidence_mismatch`, `claim_mismatch`, `workflow_mismatch`, `index_not_clean`, and `performance_budget_exceeded`.

MCP exposes the same runner as `real_repo_eval(case_file)` for an already bound repository.

## Sakura Editor driven C/C++ hardening

Recent C/C++ semantic hardening is driven by Sakura Editor style code patterns instead of synthetic-only cases.
The current resolver can follow member receiver chains such as:

- `GetDocument()->m_cLayoutMgr.SearchWord(...)`
- `pcEditView->GetCommander().Command_ADDTAIL(...)`
- `CEditWnd::getInstance()->SetDrawSwitchOfAllViews(...)`
- `CDocTypeManager().GetTypeConfigMini(...)`

For Grep replace style flows it also handles:

- local object construction such as `CWriteData output(...)` as constructor calls;
- local object writer calls such as `output.OutputHead()`, `output.AppendBuffer(...)`, and `output.Close()`;
- implicit `this` data-member receivers such as `pcCodeBase->UnicodeToCode(...)` inside `CWriteData::Output`;
- template/smart-pointer-like field declarations such as `std::unique_ptr<CCodeBase> pcCodeBase` by resolving the contained type conservatively;
- temporary object receivers such as `CDocTypeManager().GetTypeConfigMini(...)`.

For UI command dispatch, switch cases such as `case F_SEARCH_NEXT: Command_SEARCH_NEXT(...);` are indexed as `relation` facts with `predicate=dispatches_to`, `relation_kind=command_dispatch`, and `edge_status=conditional_dispatch`.  `collect-evidence "検索はどう実行される？"` composes this conditional dispatch relation with the normal call graph so the evidence path can run from `F_SEARCH_NEXT` to `CSearchAgent::SearchString`.

The implementation remains safe-unknown aware. If a receiver chain or temporary object root cannot be tied to a known class/struct or field, the edge remains unresolved rather than being promoted to supported evidence.

### Sakura Editor Undo/Redo edit-operation tracking

The Sakura Editor driven C++ hardening now extracts semantic edit-operation relations in addition to raw call edges.  It can expose command dispatch, edit-buffer mutation, Undo/Redo history access, operation-block lifecycle, and modified-state updates.  For example, `Undo/Redo と編集操作はどう追跡される？` returns deterministic traces from `F_WCHAR`, `F_UNDO`, and `F_REDO` to the relevant edit/Undo operations.

See `docs/SAKURA_UNDO_EDIT_TRACKING.md`.

- Sakura file loading / encoding tracking: `collect-evidence <repo> "ファイル読み込み・文字コード判定はどう行われる？"` returns file-open, encoding-detection, and line-conversion semantic traces.

### Sakura Windows message / dialog callback tracking

Repoanalyzer can now extract Sakura Editor style Windows GUI event relations, including `DialogBoxParam`/`CreateDialogParam` dialog callback registration, `WM_INITDIALOG`/`WM_COMMAND` handlers, control IDs such as `IDC_BUTTON_FIND`, `SendMessage`/`PostMessage` bridges, `EndDialog`, and `SetWindowSubclass` subclass callbacks.  These are represented as semantic relations with `edge_status=semantic_windows_message_relation` so LLMs do not mistake event callback edges for unconditional direct calls.

### Sakura UI resource command binding validation

Phase 7 now includes a Sakura Editor-inspired UI resource binding slice.
It indexes Windows `.rc` resource scripts and extracts semantic relations for
menu items, accelerators, toolbar slots, accelerator runtime setup, and
resource-command routing.  The deterministic question
`リソースID / accelerator / menu / toolbar から command ID への対応はどう行われる？`
returns menu/accelerator/toolbar -> `F_*` command ID -> `Command_*` traces while
marking resource bindings as non-call semantic edges.

See `docs/SAKURA_UI_RESOURCE_COMMAND_BINDING.md`.

### Sakura plugin / macro / external-command execution tracking

Repoanalyzer can now extract Sakura Editor style extension execution relations:
macro command recording/replay, macro function table bindings, plugin jack
registration/invocation, plugin command-id mapping, and external process launch
markers such as `ShellExecute*` / `CreateProcess*`.  These are semantic relation
facts with `edge_status=semantic_extension_execution_relation`, not unconditional
direct calls.

The deterministic question
`プラグイン / マクロ / 外部コマンド実行経路はどう行われる？` returns macro,
plugin, and external-command execution traces while preserving that these are
dynamic extension/process-boundary paths.

See `docs/SAKURA_EXTENSION_EXECUTION.md`.




## FreeRTOS embedded-C probe evaluation

Phase7 also includes a FreeRTOS-Kernel-derived embedded-C probe at `tests/fixtures_cpp/phase7_freertos_probe`.  This complements the Sakura Editor GUI benchmark with RTOS task creation, scheduler start, SysTick ISR, queue send/receive, timer internals, timer callback storage/invocation/dataflow relations, task-entry dataflow relations, queue/list state-transition relations, ISR/task execution-context annotations, target-profile file selection evidence, target-profile-aware answer contracts, port-boundary unknown evidence, and `portTASK_FUNCTION` macro-wrapped task extraction.

The case file `phase7_freertos_probe_cases.yaml` runs `real-repo-eval` against a single target-like profile using common kernel sources, the ARM_CM4F GCC port, selected headers, and a `compile_commands.json` containing representative FreeRTOS config macros.  It verifies supported direct call evidence such as `xTaskCreate -> prvCreateTask`, `vTaskStartScheduler -> xPortStartScheduler`, `xPortSysTickHandler -> xTaskIncrementTick`, queue/timer internals, and `prvTimerTask -> prvProcessReceivedCommands`. It also verifies `has_execution_context` relations for `xPortSysTickHandler`, `xQueueGenericSendFromISR`, normal task-context APIs, and `prvTimerTask`.  It also verifies `stores_callback` / `invokes_callback` / `callback_dataflow` relation facts for timer callback function-pointer storage, invocation, and xTimerCreate-to-expiry dataflow, while keeping concrete callback targets unknown unless separately proven. It verifies `task_entry_dataflow` for `xTaskCreate -> pxTaskCode -> prvInitialiseNewTask -> pxPortInitialiseStack` as deferred scheduler-dependent task entry registration rather than a direct call to the task function.  Queue/list state-transition checks verify `moves_task_to_ready_list`, `blocks_task_on_event_list`, `unblocks_task_from_event_list`, and `moves_task_to_delayed_list` as semantic FreeRTOS list-state evidence rather than plain helper calls.  Target-file checks verify that the selected ARM_CM4F port and `heap_4.c` are active, while non-selected ports and heaps are retained as inactive target-profile evidence.

The companion case file `phase7_freertos_timers_off_cases.yaml` runs the same probe with `configUSE_TIMERS=0`.  It validates `build_config` macro-value evidence, target-file active/inactive evidence, and confirms that timer-service definitions guarded by `#if ( configUSE_TIMERS == 1 )` are retained as inactive target-profile evidence.

Known `portTASK_FUNCTION` and `portTASK_FUNCTION_PROTO` macro invocations are normalized as macro-wrapped function definitions/declarations while preserving macro provenance in symbol payloads. See `docs/FREERTOS_PROBE_EVAL.md`.

## Sakura Phase7 cross-trace evaluation suite

Phase7 now includes a larger Sakura Editor-derived validation snapshot at `tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot`.

The case file `phase7_sakura_cross_trace_cases.yaml` runs `real-repo-eval` across the major Sakura traces added during hardening: UI resource binding, command dispatch, search/grep, grep replace, undo/redo, file loading and encoding, config/profile I/O, Windows message/dialog callbacks, and macro/plugin/external command execution.

See `docs/SAKURA_PHASE7_CROSS_TRACE_EVAL.md` for the design and usage.


- `docs/SAKURA_SNAPSHOT_GENERATOR.md` describes the source-fetch manifest and reproducible snapshot generator for Phase7 Sakura cross-trace validation.


## Sakura upstream checkout snapshot mode

`repoanalyzer cli snapshot-generate` now supports `--source-mode upstream` and `--source-mode both`.
These modes use `snapshot_manifest.v1` entries' `upstream.repository` and `upstream.path` / `upstream.paths` metadata to copy files from a local repository checkout into `upstream_sources/` without network access.
The default `local` mode is unchanged and continues to regenerate the compact Phase7 cross-trace snapshot.
See `docs/SAKURA_UPSTREAM_CHECKOUT_SNAPSHOT_MODE.md`.

### Sakura Phase7 traceability and coverage gap reports

`snapshot-traceability-report` validates the relationship between a generated compact Sakura Phase7 snapshot and files copied under `upstream_sources/`.  It checks compact-file existence and manifest hash, upstream evidence availability, and lexical anchors that connect compact slices back to copied upstream files.

`snapshot-coverage-gap-report` lifts that file-level evidence to real-repo-eval scenario granularity. For each trace it reports compact evidence, upstream evidence already present, missing upstream source files, skipped metadata refs, recommended source additions, and unknown reasons. This is the safe-unknown-aware layer that tells an LLM when a trace is upstream-supported, partially supported, compact-only, upstream-missing, unknown, or not applicable.



- FreeRTOS target-profile evidence now includes build-condition provenance: guarded symbols/calls carry `build_guard_chain` and macro evaluation details, `answer-contract` exposes `build_context.build_conditions`, and `target-profile-diff` compares active/inactive status across indexed profiles. FreeRTOS task entry dataflow now links `xTaskCreate` task-entry arguments to `pxPortInitialiseStack` while preserving deferred scheduler-dependent execution constraints. Port-boundary evidence marks paths such as `vTaskStartScheduler -> xPortStartScheduler` and `prvInitialiseNewTask -> pxPortInitialiseStack` as target-port dependent rather than fully verified beyond the selected C port source.

### FreeRTOS allocation profile evidence

FreeRTOS target profiles can now expose dynamic/static allocation settings as
first-class evidence. `configSUPPORT_DYNAMIC_ALLOCATION` and
`configSUPPORT_STATIC_ALLOCATION` produce allocation-profile facts, guarded API
symbols keep their `build_guard_chain`, and answer contracts preserve allocation
constraints for API availability questions.

FreeRTOS answer contracts also preserve ISR/task API context.  If evidence cites
`xQueueGenericSend` and `xQueueGenericSendFromISR`, the contract records
`build_context.api_contexts`, `isr_apis`, `task_context_apis`, and
`api_context_pairs`, and emits constraints that the task-context API and
`FromISR` variant must not be treated as interchangeable.


### FreeRTOS scheduler/yield semantics

FreeRTOS probe fixtures now extract scheduler-side semantic relations such as
`enters_critical_section`, `exits_critical_section`, `suspends_scheduler`,
`resumes_scheduler`, `requests_context_switch`, and ISR interrupt-mask
set/clear relations.  These are intentionally separate from direct call edges
and are propagated into answer contracts so final answers must qualify
critical-section, scheduler-control, yield, and ISR-mask behavior.


### FreeRTOS port boundary unknowns

FreeRTOS probe fixtures now extract `crosses_port_boundary` and
`has_port_boundary` relations for transitions from common kernel code into the
selected port layer, such as `xPortStartScheduler`, `pxPortInitialiseStack`, and
`xPortSysTickHandler`.  These facts intentionally remain conditional and carry
unknown reasons for port-layer, assembly/startup, vector-table, and
target-specific stack-layout evidence, so answer contracts require final answers
to qualify behavior beyond the C-source port boundary.

### FreeRTOS queue/list state-transition semantics

FreeRTOS probe fixtures now extract task/list state-transition relations such as
`moves_task_to_ready_list`, `moves_task_to_delayed_list`,
`blocks_task_on_event_list`, `unblocks_task_from_event_list`, and
`removes_task_from_list`.  These facts preserve that FreeRTOS task state is
represented through ready/delayed/event lists and should not be collapsed into
generic calls to `vListInsert`, `vListInsertEnd`, or `uxListRemove`.  Answer
contracts expose this under `build_context.task_state_transitions`,
`ready_list_functions`, `delayed_list_functions`, `event_blocking_functions`,
and `event_unblocking_functions`.


## FreeRTOS Profile Matrix

`profile-matrix` runs multiple target profiles against one repository and compares build-sensitive evidence such as timer APIs, dynamic/static allocation APIs, selected heap files, and answer-contract build context. See `docs/FREERTOS_PROFILE_MATRIX.md`.

### FreeRTOS kernel-object semantics

The Phase7 FreeRTOS probe includes a Kernel Object Semantics Pack for stream and
message buffers, event groups, direct-to-task notifications, semaphores, and
mutexes.  The extractor emits semantic relations such as
`sends_to_stream_buffer`, `sets_event_bits`, `notifies_task`, `takes_semaphore`,
and `gives_mutex`, including header macro APIs such as `xMessageBufferSend` and
`xSemaphoreGive`.  Answer contracts preserve these as RTOS synchronization and
communication semantics rather than reducing them to generic call/helper edges.

### FreeRTOS hook/assert/trace semantics

The Phase7 FreeRTOS probe includes a Hook / Assert / Trace Semantics Pack.  The
extractor emits semantic relations for `trace*` instrumentation macros,
`configASSERT`, application hooks such as `vApplicationMallocFailedHook` and
`vApplicationIdleHook`, and `mtCOVERAGE_TEST_MARKER`.  These are not modeled as
plain direct calls: trace hooks are configurable instrumentation, assert handling
is defined by the target `FreeRTOSConfig.h`, application hooks may live outside
the kernel source tree, and coverage markers are diagnostic/test evidence rather
than ordinary runtime kernel behavior.  Answer contracts expose this under
`build_context.hook_assert_trace_semantics`, `trace_hook_functions`,
`assert_handler_functions`, `application_hook_functions`, and
`coverage_marker_functions`.

### FreeRTOS heap allocator semantics

The Phase7 FreeRTOS fixture includes heap allocator semantic evidence.  It can
verify statements such as `pvPortMalloc allocates heap memory`, `vPortFree frees
heap memory`, and `prvInsertBlockIntoFreeList coalesces free blocks`.  These are
reported as semantic/conditional evidence so final answers qualify allocator
behavior by the selected heap implementation (`heap_3`, `heap_4`, `heap_5`, etc.)
instead of treating all FreeRTOS heaps as equivalent.

### FreeRTOS Batch 4: SMP / MPU / Port Advanced Semantics

The Phase7 FreeRTOS probe includes advanced port semantics for SMP scheduling,
core affinity, cross-core yield, SMP locks, MPU wrappers/region setup/access
checks, privilege boundaries, port assembly, and secure context boundaries.  The
relations are emitted as safe-unknown-aware evidence and propagated into answer
contracts so final answers do not overclaim behavior beyond target-profile,
startup, assembly, vector-table, or MPU-region evidence.
