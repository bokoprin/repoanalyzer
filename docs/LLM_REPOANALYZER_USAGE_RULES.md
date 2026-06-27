# LLM repoanalyzer usage rules

repoanalyzer is a build-aware / evidence-aware / safe-unknown-aware evidence engine for C/C++ code analysis.  It does not write the final answer.  The LLM writes the answer after using repoanalyzer MCP tools and checking the relevant source lines.

## Required loop

For repository questions, follow this loop:

1. Call `preflight()` before reasoning from the index.
2. If preflight reports missing/dirty/degraded index, ask for re-ingest or qualify the answer. Do not make completeness, absence, or contradiction claims from a stale index.
3. Call `plan_question(question)` when the tool sequence is unclear.
4. Call `collect_evidence(question)` or a focused `find_*` tool.
5. Inspect returned `facts`. Treat file path and line range as candidates, not as a final answer.
6. Call `read_file_range(path, start_line, end_line)` for the most relevant facts.
7. Answer only after checking the returned source text.
8. Preserve repoanalyzer's uncertainty: distinguish `supported`, `conditional`, `unknown`, and `unsupported`.
9. For a draft final answer with concrete claims, call `verify_answer(text, question)` or `answer_contract(text, question)` before sending.

## Safety rules

- Never rely on LLM memory alone for code claims when repoanalyzer tools are available.
- Never claim a symbol is absent unless preflight is clean and the relevant query returned a safe absence/unknown result.
- Never turn `conditional` evidence into unconditional wording.
- Mention target profile/build context when evidence is build-sensitive.
- If repoanalyzer returns unknowns or response constraints, reflect them in the final answer.
- If `collect_evidence` is broad or low confidence, switch to `find_definitions_page`, `find_callers_page`, `find_callees_page`, or `find_references_page`, then inspect source with `read_file_range`.

## TinyUSB golden path

Use TinyUSB `tinyusb_upstream_device_cdc_msc` first for E2E validation.  Good starter questions are:

1. TinyUSBのCDC/MSC configuration descriptorはどこで定義されている？
2. dcd_event_handler から tud_task まではどうつながる？
3. endpoint transfer完了時にclass driverのxfer_cbへdispatchされる流れは？

For each question, the LLM should obtain facts, read the cited file ranges, and answer with explicit source-grounded qualifications.
