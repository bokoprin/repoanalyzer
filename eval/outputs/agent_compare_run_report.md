# TinyUSB MCP Golden E2E Cline CLI Run Report

## Environment

- repoanalyzer path: `C:\shinsuke\app\repoanalyzer_clean`
- TinyUSB path: `C:\shinsuke\app\tinyusb`
- MCP server: `python -m repoanalyzer.mcp.server --repo C:\shinsuke\app\tinyusb`
- Cline CLI model: `qwen3.6:27b_q4_k_s`
- Cline CLI options: `--json --thinking none --auto-approve true`
- TinyUSB index status before run: `clean`
- indexed files: `64`
- total facts: `12063`

## Runner

- runner: `eval/agent_compare/run_cline_cli_eval.py`
- case source: `eval/agent_compare/tinyusb_mcp_golden_cases.csv`
- output JSONL: `eval/outputs/tinyusb_answers_cline.jsonl`
- summary: `eval/outputs/cline_cli_eval_summary.json`
- raw Cline JSON streams: `eval/outputs/cline_events/*.events.jsonl`

Raw event streams are generated artifacts and are not committed. They were kept in the working tree for local inspection during the run.

## Result Summary

- cases executed: `10`
- JSONL lines: `10`
- JSONL parse check: passed
- successful case records: `10`
- repair runs: `0`
- cases using `collect_evidence`: `10`
- cases using `read_file_range`: `10`

## Important Caveat

Cline used the required repoanalyzer tools in every case, but it also called disallowed tools in several cases. The runner records these in `cline_cli_eval_summary.json` and appends the issue to each affected answer's `known_limitations`.

Observed disallowed tools included:

- `search_codebase`
- `run_commands`
- `read_files`
- `repo_status`
- `server_info`
- `verify_answer`
- `verify_text`

This means the saved answers are useful for evaluating repoanalyzer-assisted behavior, but not as a strict repoanalyzer-only benchmark.

## Files To Review

- `eval/outputs/tinyusb_answers_cline.jsonl`
- `eval/outputs/cline_cli_eval_summary.json`
- `eval/agent_compare/run_cline_cli_eval.py`
