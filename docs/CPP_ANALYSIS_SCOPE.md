# C/C++ Analysis Scope

Current MVP supports fixture-scale extraction of:

- C/C++ source and header scanning
- `compile_commands.json` source-file gating for translation-unit sources
- per-source `-D` macro extraction from `compile_commands.json`
- simple config/header macro extraction from `-include` headers and translation-unit direct local `#include "..."` headers
- function declarations and definitions
- direct function calls inside function bodies
- include facts
- simple build guard spans
- branch-level build guard facts for `#if` / `#elif` / `#else` groups
- inactive fact marking for deterministically false branches such as `#if 0`
- conditional fact marking for unresolved preprocessor guards
- `payload.tu_context` on extracted facts, recording the translation-unit source, compile-commands participation, command-line macros, shallow header-derived macros, configured macros, and directly included headers used by the lightweight guard evaluator
- simple macro-based guard evaluation for:
  - `#ifdef NAME`
  - `#ifndef NAME`
  - `#if NAME`
  - integer `#if 0` / `#if 1`
  - `#if defined(NAME)` / `#if defined NAME`
  - boolean `!`, `&&`, `||`, and parentheses over the supported atoms
  - integer comparisons `==`, `!=`, `<`, `<=`, `>`, `>=` over supported integer atoms
  - limited integer arithmetic `+`, `-`, `*`, `/`, `%`, including unary `+`/`-`, over supported integer atoms
  - limited bitwise integer operations `&`, `|`, `^`, `~`, `<<`, `>>` over supported integer atoms
  - simple object-like macro aliases that resolve to integers, such as `ACTIVE_MODE -> CONFIG_MODE -> 2`

Important safety behavior:

- Missing macros are not treated as definitively false yet. They remain `conditional` because include-order-dependent macro definitions are only partially evaluated. Macro alias resolution is intentionally limited to simple identifier chains with cycle protection; unresolved aliases remain `conditional`.
- Header macro extraction is intentionally shallow: it reads simple object-like `#define` values from repository headers named by `-include` or directly included by a translation unit. It skips function-like macros, include guard sentinels, and defines in certainly inactive `#if 0` branches. Recursive include expansion and full preprocessor semantics are not implemented.
- Header facts are currently scanned once with `payload.tu_context.kind = "header_standalone"` and `precision = "header_unattributed"`; they are not yet duplicated per including translation unit. Source-file facts use `kind = "translation_unit"` when backed by `compile_commands.json`.
- Only deterministic inactive branches are removed from normal query results. Unresolved branches remain queryable with `payload.build_status = "conditional"`.
- `build_guard` facts now include legacy `payload.kind = "guard_block"` spans and newer `payload.kind = "guard_branch"` entries. Branch entries carry `directive`, `expression`, `status`, `effective_status`, `branch_index`, `group_start_line`, and `group_end_line` so clients can distinguish an active `#elif` branch from an inactive `#else` sibling.

Future work:

- recursive include expansion for config/header macros
- full include-order-aware macro propagation
- expression-style macro expansion beyond simple identifier aliases
- ternary and macro-function `#if` expression evaluation
- class methods and overloads
- callbacks/function pointers
- virtual dispatch/override candidates
- setting flow extraction

## Phase 2 build-aware ingest completion additions

Phase 2 now centralizes lightweight preprocessor line-status analysis in
`repoanalyzer/cpp/preprocessor_model.py`.  The model produces per-line
`active` / `inactive` / `conditional` status, inactive ranges, conditional
preprocessor guard stacks, and branch nodes used by `build_guard` facts.  This
keeps `#if` / `#elif` / `#else` interpretation consistent across normal facts,
inactive filtering, conditional evidence, and branch guard reporting.

All extracted facts now carry an explicit `payload.build_status`:

- `active`: the fact is visible under the current lightweight build context.
- `inactive`: the fact is inside a branch proven inactive by the supported
  preprocessor subset and is excluded from normal queries.
- `conditional`: the fact is guarded by an unresolved preprocessor condition and
  remains queryable, but EvidenceBundle reports it as partial evidence.

Include facts are enriched with shallow include resolution when the target can
be resolved through compile_commands include paths or local source-relative
lookup:

- `payload.resolution_status`: `resolved` or `unresolved`.
- `payload.resolved_path`: repo-relative header path when resolved.
- `payload.resolution_scope`: currently `compile_commands_include_path`.

For every translation unit, Phase 2 also records `header_visible_in_tu` include
relation facts for forced includes and directly included local headers known to
that TU.  Directly visible headers are additionally projected into the including
TU context as `header_projected_into_tu` facts.  Standalone header facts are kept
as `header_standalone` / `header_unattributed`, so downstream consumers can
separate precise projected evidence from header facts whose TU macro context is
not yet attributed.

This remains intentionally shallow.  It is not a full preprocessor and does not
support function-like macros, recursive include expansion, generated headers, or
full include-order semantics.

## Unsupported preprocessor expression diagnostics

When the lightweight evaluator cannot safely evaluate a guard expression, Phase 2
keeps guarded facts queryable as `build_status=conditional` and records why the
guard was not resolved.  Conditional fact payloads may include:

- `guard_evaluation_reasons`: high-level reasons such as `unresolved_macro` or
  `unsupported_preprocessor_expression`.
- `unsupported_preprocessor_kinds`: narrower unsupported forms such as
  `ternary_operator`, `function_like_macro_call`, `tokenization_failed`, or
  `expression_syntax`.
- `unresolved_guard_symbols`: macro names that were required but unavailable in
  the current translation-unit macro context.

The evaluator intentionally does not claim inactive status for these cases.
EvidenceBundle surfaces unsupported guard diagnostics as
`unsupported_preprocessor_expression` unknowns so downstream LLMs can describe
those facts as conditional and avoid target-build certainty.

## Phase 3 semantic C/C++ MVP

Phase 3 adds a lightweight semantic extractor on top of the Phase 2 build-aware ingest pipeline. It is intentionally not a full C++ compiler frontend, but it now records enough semantic structure for evidence-aware call graph answers in common fixture-scale C/C++ code.

Supported in the Phase 3 MVP:

- namespace, class, and struct scopes with qualified names
- class/struct type facts and shallow inheritance relation facts
- function, method, constructor, and destructor symbol facts
- multiline function signatures
- normalized signatures, argument counts, owner type, namespace, qualifiers, and symbol IDs in symbol payloads
- free calls, namespace-qualified calls, static member calls, constructor syntax, dot/arrow member calls
- chained receiver calls such as `GetDocument()->m_cLayoutMgr.SearchWord(...)`, `object.member.method(...)`, and `ptr->member.method(...)`
- simple local receiver type inference for `Type obj;`, `Type* ptr;`, function parameters, shallow data members, and function-return roots
- overload resolution by argument count and simple literal type hints (`int`, string literal, bool, nullptr)
- function pointer assignments and function pointer call candidate sets
- callback registration and callback table initializer relation facts
- virtual dispatch candidate facts based on inheritance and method override candidates
- conservative cross-translation-unit symbol table resolution for direct/member/static/constructor calls
- declaration-to-definition relation facts when a header declaration is bound to a definition in another translation unit
- qualified route metadata for call-path facts, including cross-TU resolved edges

Cross-TU resolution remains conservative: it prefers active definitions over declarations, uses qualified names, owner types, argument counts, and simple literal type hints, and keeps ambiguous or indirect cases as candidate/unknown evidence rather than pretending runtime certainty.

Still outside the Phase 3 MVP:

- standard-compliant overload resolution
- template instantiation and template-dependent member calls
- complete type checking and alias analysis
- function-like macro expansion
- clang AST parity
- precise runtime type inference for virtual dispatch

Unsupported or ambiguous semantic cases are preserved as facts with `resolution_status`, `candidate_qualified_names`, and `unknown_type` payload fields where possible. EvidenceBundle generation turns these into response constraints instead of allowing the LLM to treat them as fully resolved facts.

## Phase3 MVP semantic completion

The lightweight C/C++ semantic layer now includes a Phase3 MVP completion pass:

- `using` and simple `typedef` type aliases are indexed as `type_alias` facts and are used by cross-TU type normalization.
- Local receiver type inference handles alias, typedef, pointer/reference, and limited `auto var = Type{...}` / `auto var = Type(...)` declarations.
- Member calls through aliases are normalized through the global symbol table before cross-TU call resolution.
- Function pointer calls and callback registration/table relations are enriched with cross-translation-unit candidate symbols. These remain candidate evidence, not guaranteed runtime execution.
- Directly included inline/header functions participate in the global table through header projection.
- Class/struct data members are indexed as `has_field` relation facts and used by cross-TU receiver-chain resolution.
- Function-return roots and field chains can resolve Sakura Editor style calls such as `GetDocument()->m_cLayoutMgr.SearchWord(...)` when the return type and field type are available as active facts.
- Sakura Editor style UI command switch cases such as `case F_SEARCH_NEXT: Command_SEARCH_NEXT(...);` are indexed as conditional `dispatches_to` relations rather than unconditional calls.
- Evidence collection has a deterministic Sakura search execution trace mode for questions such as `検索はどう実行される？`, composing `F_SEARCH_NEXT -> Command_SEARCH_NEXT` dispatch evidence with call graph evidence down to `CSearchAgent::SearchString`.
- Template declarations are marked as `unsupported_cpp_construct` so answers stay scoped to extracted evidence instead of implying full template instantiation support.

This is still not a clang-equivalent semantic analyzer. Template instantiation, full overload resolution, ADL, high-precision alias analysis, and runtime type certainty remain out of scope for this MVP.

## Phase5-B safe incremental ingest scope

Phase5-B supports conservative incremental ingest for source-only changes:

- changed `.c/.cc/.cpp/.cxx` files are re-extracted;
- new source files are indexed when already part of the current source discovery/build context;
- deleted source files have their file metadata and dependent facts removed;
- cross-TU call resolution is recomputed over retained plus refreshed facts.

The incremental path refuses to update the index and reports `full_reingest_required` when any changed path is a header, when the build context signature changes, or when the existing index lacks the signature needed for safety. Header changes, compile command changes, configured macro changes, include-dir changes, and exclude-pattern changes should be handled by a full ingest.

## Phase5-C large-repo query/MCP hardening

Phase5-C adds large-repository query safeguards without changing C/C++ semantic facts:

- paginated query helpers for definitions, references, callers, and callees;
- MCP page tools returning `{items, page}` metadata with `total`, `limit`, `offset`, `next_offset`, and warnings;
- `query-diagnostics` / `query_diagnostics` reporting fact counts, indexed file roles, largest files, and index freshness warnings;
- heuristic path role classification for diagnostics (`project`, `vendor`, `generated`, `test`);
- claim verification now adds an `index_freshness` unknown when the repo changed after ingest. Supported claims are downgraded to conditional, and contradicted claims are downgraded to unknown, because stale indexes must not be used for absence/completeness claims.

Unbounded legacy query functions remain available for compatibility, but MCP/agent workflows should prefer paginated page tools for large result sets.

## Phase7: real C/C++ repo validation

Phase7 keeps the project focused on C/C++. It does not start multi-language support. Instead it adds a `real_repo_eval` runner that exercises ingest, diagnostics, evidence collection, claim verification, and workflow safety checks against a local C/C++ repository.

The runner is designed to classify failures so future work can be driven by observed C/C++ repo failures rather than speculative feature additions.
