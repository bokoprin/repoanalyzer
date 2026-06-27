# MCP Contract

Initial tools:

- `server_info`
- `read_file_range`
- `find_definitions`
- `find_references`
- `find_callers`
- `find_callees`
- `collect_evidence`

These tools return structured facts. The MCP client/LLM writes the final natural-language answer.

## Phase4 claim verification tools

The MCP surface includes claim verification helpers:

- `verify_claim(claim: dict) -> claim_verdict.v1`
- `verify_claims(claims: list[dict]) -> claim_evidence_bundle.v1`

A claim object has `claim_type`, optional `subject`, optional `object`, and optional `payload`.  Supported MVP claim types are `definition_exists`, `calls`, `reaches`, `includes`, `build_active`, and `callback_registers`.

## Phase4 natural-language claim extraction tools

The MCP surface also includes deterministic text-to-claim helpers:

- `extract_claims(text: str) -> claim_extraction.v1`
- `verify_text(text: str) -> claim_evidence_bundle.v1`

These tools support only explicit English/Japanese patterns for the MVP claim types.  They do not use an LLM, do not infer unstated claims, and do not transform negated natural-language claims into inverse structured claims.

## Phase5-A index status tool

The MCP surface includes:

- `repo_status() -> dict`

It reports whether the current index is `clean` or `dirty`, plus stale/missing/new file lists derived from the `file_index` manifest.

## Phase5-C paginated query tools

The MCP surface includes paginated variants for large repositories:

- `find_definitions_page(symbol, limit=None, offset=0)`
- `find_references_page(symbol, limit=None, offset=0)`
- `find_callers_page(symbol, limit=None, offset=0)`
- `find_callees_page(symbol, limit=None, offset=0)`

Each returns:

```json
{
  "items": [],
  "page": {
    "total": 0,
    "limit": 100,
    "offset": 0,
    "next_offset": null,
    "has_more": false,
    "result_cap": 500,
    "warnings": []
  }
}
```

`query_diagnostics()` returns `query_diagnostics.v1` with fact counts, file role counts, index freshness status, largest indexed files, and warnings for stale indexes or indexed vendor/generated/test files.

## Phase6 workflow tools

The MCP surface includes agent workflow helpers:

- `preflight() -> agent_preflight.v1`
- `plan_question(question: str) -> answer_plan.v1`
- `verify_answer(text: str, question: str | None = None) -> answer_verification_report.v1`
- `answer_contract(text: str, question: str | None = None) -> safe_answer_contract.v1`
- `workflow_run(question: str, answer_text: str | None = None) -> workflow_trace.v1`

These tools are meant to be used before an LLM sends a final answer.  A client should treat `safe_answer_contract.must_not_send=true` as a hard block, and should not present conditional claims without the returned `required_qualifications` / `response_constraints`.

## Phase6 extended workflow tools

Phase6 extension keeps repoanalyzer deterministic and evidence-first while making agent usage safer.

Additional behavior:

- `extract_claims` now supports a limited set of negated claims by setting `payload.polarity = "negative"` instead of silently dropping them.
- `verify_answer` and `answer_contract` include `policy_violations` when answer wording is unsafe for the current verdict, such as absolute language on contradicted, conditional, unknown, or stale claims.
- `workflow_run` can be recorded by CLI with `--record`; stored traces are readable through `workflow-history` and the MCP `workflow_history` tool.

Schemas:

- `answer_verification_report.v1` may include `policy_violations`.
- `safe_answer_contract.v1` may include `policy_violations`.
- `workflow_session_history.v1` returns recorded workflow traces with pagination metadata.
