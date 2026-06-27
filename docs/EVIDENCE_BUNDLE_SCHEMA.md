# EvidenceBundle Schema

The primary output is structured evidence, not a final answer.

```json
{
  "schema_version": "evidence_bundle.v1",
  "question": "...",
  "interpreted_intent": "callers",
  "answerability": "answerable",
  "facts": [],
  "unknowns": [],
  "response_constraints": [],
  "support_level": "medium",
  "unknown_reasons": [],
  "quality_profile": {
    "support_level": "medium",
    "source_coverage_status": "not_tracked",
    "semantic_resolution_status": "resolved",
    "build_status": "active"
  }
}
```

## Evidence Quality Gate

The quality gate is a cross-cutting profile added to `EvidenceBundle` and `claim_verdict.v1`.  It summarizes whether the returned facts are safe to use as strong support, need qualification, or should remain unknown.

Fields:

- `support_level`: `strong`, `medium`, `weak`, or `unknown`.
- `source_coverage_status`: `upstream_supported`, `partially_supported`, `upstream_missing`, `compact_only`, `not_tracked`, or `unknown`.  This is derived from `.repoanalyzer-coverage-gap-report.json` when present; normal full checkouts without that report are `not_tracked` rather than automatically weak.
- `semantic_resolution_status`: `resolved`, `unresolved`, `candidate_or_ambiguous`, `dynamic_candidate`, `not_tracked`, or similar conservative status.
- `build_status`: `active`, `conditional`, `inactive`, `mixed`, or `build_unknown`.
- `unknown_reasons`: normalized reason codes propagated into response constraints.

`verify-claim` and `verify-text` apply the gate to verdicts.  Weak positive support is downgraded from `supported` to `conditional`; weak absence/contradiction evidence is downgraded to `unknown`.

## Answerability

- `answerable`: facts are present and no blocking or conditional unknown is reported.
- `partial`: facts are present, but the bundle also contains unknowns or conditional evidence that must be stated carefully.
- `insufficient_evidence`: no usable facts were found for the current query.

## Conditional build evidence

Facts under unresolved preprocessor guards are kept queryable, but their payload contains
`build_status: "conditional"`. When a collected bundle contains one or more such facts,
repoanalyzer adds a `conditional_build_evidence` unknown and a response constraint telling
LLM clients not to describe those facts as definitely active in the target build.

Example:

```json
{
  "answerability": "partial",
  "facts": [
    {
      "fact_type": "call",
      "caller": "feature_entry",
      "callee": "init_device",
      "payload": {
        "build_status": "conditional",
        "guard_expressions": ["FEATURE_EXTRA"]
      }
    }
  ],
  "unknowns": [
    {
      "unknown_type": "conditional_build_evidence",
      "message": "1 fact(s) are conditional on unresolved preprocessor guard(s). Guard expression(s): FEATURE_EXTRA.",
      "severity": "medium",
      "affects": ["feature_entry->init_device"]
    }
  ],
  "response_constraints": [
    "Facts marked build_status=conditional are guarded by unresolved preprocessor conditions; describe them as conditional, not definitely active in the target build."
  ]
}
```

## Additional Phase 2 build-context unknowns

EvidenceBundle may now include these build-context unknowns:

- `source_without_compile_commands`: at least one returned fact came from a
  source file scanned without a compile_commands entry, so target-build
  completeness is lower.
- `header_unattributed_evidence`: at least one returned fact came from a
  standalone header context rather than a translation-unit projection.
- `unresolved_include_evidence`: at least one include fact was not resolved by
  the current shallow include resolver.

These complement `conditional_build_evidence`, which is emitted when returned
facts have `payload.build_status == "conditional"`.

### `unsupported_preprocessor_expression`

Produced when returned facts are guarded by a preprocessor expression outside the
supported lightweight evaluator subset.  Affected facts remain available as
`build_status=conditional`, and their payload explains the reason using fields
such as `guard_evaluation_reasons`, `unsupported_preprocessor_kinds`, and
`unresolved_guard_symbols`.

Example constraint:

```text
Facts guarded by unsupported preprocessor expressions are conditional; do not
claim their target-build activity is known until the expression is supported or
manually verified.
```

## Phase 3 semantic unknowns

Phase 3 may add semantic unknowns when a fact has an unresolved or candidate-based semantic interpretation:

- `ambiguous_symbol_resolution`: same short name maps to multiple scoped symbols.
- `ambiguous_overload_resolution`: overload candidates remain after argument-count and literal-hint filtering.
- `unresolved_member_receiver_type`: a dot/arrow member call receiver type could not be inferred.
- `unresolved_call_target`: a call target could not be resolved in the current semantic symbol table.
- `indirect_call_unresolved`: a function pointer call has candidate targets but is not a guaranteed direct call.
- `callback_relation_not_execution`: callback registration/table facts are relations, not direct execution paths.
- `virtual_dispatch_candidates`: runtime virtual dispatch target depends on receiver dynamic type.
- `unsupported_cpp_construct`: the lightweight semantic extractor cannot safely model the construct.
- `cross_tu_ambiguous_resolution`: cross-translation-unit lookup found multiple plausible candidates.

Semantic call facts can include payload fields such as:

- `caller_qualified_name`
- `callee_qualified_name`
- `caller_symbol_id`
- `callee_symbol_id`
- `callee_signature`
- `resolution_scope`, including `translation_unit`, `cross_translation_unit`, and `global_symbol_table`
- `local_resolution_status` when a cross-TU pass improves a previously unresolved local call
- `callee_definition_path` / `callee_definition_line` for resolved cross-TU targets
- `cross_tu` boolean indicating whether the selected definition is in another indexed source
- `resolution_status`
- `resolution_basis`
- `candidate_symbol_ids`
- `candidate_qualified_names`
- `receiver_expr`
- `receiver_type`
- `argument_count`
- `argument_type_hints`

Call path facts may include `route_qualified`, `edge_statuses`, and `ambiguous_edges` in payload.

### Phase3 semantic MVP payload additions

Phase3 semantic facts may include:

- `receiver_type_original`: the locally inferred receiver type before alias normalization.
- `receiver_type_resolved`: the receiver type after global alias/type normalization.
- `callback_qualified_name`, `callback_definition_path`, `callback_resolution_status`: cross-TU callback candidate enrichment.
- `unsupported_cpp_construct_kind`: currently used for template declarations that are indexed but not instantiated.

The following unknowns are expected and intentional:

- `callback_relation_not_execution`: registration/table evidence is not a direct call.
- `indirect_call_unresolved`: function pointer evidence is a candidate set.
- `unsupported_cpp_construct`: the extractor found a construct such as a template declaration but does not model full C++ semantics for it.

## Claim verification schema: `claim_verdict.v1`

Phase4 adds claim-level verification on top of evidence collection.  A claim verifier does not try to write the final natural-language answer.  It classifies a structured claim using indexed facts and returns one of:

- `supported`: the claim is supported by active, resolved evidence.
- `conditional`: the claim has evidence, but build conditions, callback/indirect semantics, candidate sets, or unsupported constructs prevent a definite claim.
- `unknown`: the current index does not provide enough evidence to support or contradict the claim.
- `contradicted`: the current resolved evidence contradicts the claim within the verifier's stated scope.

Supported MVP claim types are:

- `definition_exists`
- `calls`
- `reaches`
- `includes`
- `build_active`
- `callback_registers`

A single verdict is serialized as `claim_verdict.v1`; multiple claims are serialized as `claim_evidence_bundle.v1` with an `overall_verdict`.

`contradicted` is intentionally conservative.  Absence of a fact is not enough for contradiction when unresolved calls, candidate sets, conditional build evidence, callback relations, or unsupported C++ constructs could affect the answer.

## Claim extraction schema: `claim_extraction.v1`

Phase4 finishing adds deterministic natural-language claim extraction.  The extractor maps explicit English/Japanese text patterns to structured claim objects.  It deliberately avoids broad language understanding; unsupported wording is left as a warning rather than guessed.

Supported extracted claim types match the structured verifier MVP:

- `definition_exists`
- `calls`
- `reaches`
- `includes`
- `build_active`
- `callback_registers`

An extraction result has this shape:

```json
{
  "schema_version": "claim_extraction.v1",
  "text": "app::phase3_driver は app::Device::start を呼び出す。",
  "claims": [
    {
      "claim_type": "calls",
      "subject": "app::phase3_driver",
      "object": "app::Device::start",
      "payload": {
        "extraction": {
          "source": "deterministic_natural_language_pattern",
          "pattern_id": "ja_calls_wo_yobu",
          "span": [0, 45],
          "text": "app::phase3_driver は app::Device::start を呼び出す"
        }
      }
    }
  ],
  "extracted_claims": [
    {
      "claim": {"claim_type": "calls", "subject": "app::phase3_driver", "object": "app::Device::start"},
      "text": "app::phase3_driver は app::Device::start を呼び出す",
      "span": [0, 45],
      "pattern_id": "ja_calls_wo_yobu",
      "confidence": "high"
    }
  ],
  "warnings": []
}
```

`verify-text` runs extraction and then structured batch verification.  Its `claim_evidence_bundle.v1` may include `extracted_claims` and `extraction_warnings`.  If no supported claim pattern is found, the bundle has `overall_verdict: unknown`, no verdicts, and a `no_supported_claim_patterns` extraction warning.

Negated natural-language claims are not converted to inverse claims in this MVP.  For example, `A does not call B` is reported as `negated_claim_not_extracted` rather than being transformed into a contradiction query.

## Phase5-A index freshness unknown

Phase5-A may add:

- `index_freshness`: the current repository file manifest differs from the last ingest. This is emitted when one or more indexed files are stale, missing, or when new indexable files are present.

When this unknown is present, clients must avoid completeness or absence claims until the index is refreshed.

## Phase5-C claim freshness note

Claim verification uses the repo status file manifest. If the index is dirty, claim verdicts include an `index_freshness` unknown. A supported verdict is downgraded to conditional, and a contradicted verdict is downgraded to unknown, because stale indexes must not be used as proof of absence or completeness.

## Phase6 workflow schemas

Phase6 adds agent-facing workflow schemas.  They are not replacements for `EvidenceBundle` or `claim_verdict`; they compose the earlier outputs into safe LLM workflow decisions.

### `agent_preflight.v1`

Reports whether the repo index is ready for answering.  It includes `index_ready`, `safety_level`, `status`, `diagnostics`, `required_actions`, `warnings`, and `recommended_tools`.

### `answer_plan.v1`

A deterministic plan for a question.  It identifies an interpreted intent, recommended tools, extracted claim candidates when present, and the workflow steps an agent should follow.

### `answer_verification_report.v1`

Verifies a draft answer by extracting deterministic natural-language claims and running claim verification.  Its `safety_level` is one of:

- `safe`: all extracted claims are supported.
- `must_qualify`: at least one claim is conditional and must be qualified.
- `needs_more_evidence`: extracted claims are unknown or no supported claim pattern was extracted.
- `unsafe`: at least one claim is contradicted.

### `safe_answer_contract.v1`

Groups claims into `allowed_claims`, `qualified_claims`, `unknown_claims`, and `prohibited_claims`.  It also provides `can_answer`, `must_not_send`, `required_qualifications`, and `response_constraints` for an LLM client.

### `workflow_trace.v1`

Combines preflight, planning, optional answer verification, and the safe answer contract.  It is useful for regression tests and for agent logs.
