# Repository Guidelines

## Project Structure & Module Organization

`repoanalyzer/` contains the Python package. Its main layers are `cpp/` for C/C++ discovery and semantic analysis, `store/` and `query/` for indexed facts, `evidence/` for evidence bundles and verification, `workflow/` for agent-facing orchestration, and `mcp/` for MCP tools and the server. `repoanalyzer/cli.py` exposes the Typer CLI.

Tests live in `tests/test_*.py`. C/C++ samples, `compile_commands.json`, and YAML cases belong in `tests/fixtures_cpp/<scenario>/`. Evaluation utilities are under `eval/agent_compare/`; generated results belong in ignored `eval/outputs/`. Design and contract documentation is under `docs/`, and reusable maintenance commands are under `scripts/`.

## Build, Test, and Development Commands

Use the repository virtual environment on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check repoanalyzer tests
```

Run only self-contained tests with `python -m pytest -q -m "not upstream"`; tests marked `upstream` require an external checkout. For a quick end-to-end check:

```powershell
.\.venv\Scripts\python.exe -m repoanalyzer.cli ingest tests/fixtures_cpp/basic_call
.\.venv\Scripts\python.exe -m repoanalyzer.cli eval tests/fixtures_cpp/basic_call tests/fixtures_cpp/basic_call/cases.yaml
```

## Coding Style & Naming Conventions

Target Python 3.11+, use four-space indentation, type annotations, and `from __future__ import annotations` in package modules. Follow `snake_case` for functions and modules, `PascalCase` for classes, and descriptive Typer command names in kebab case. Keep evidence and report output deterministic and JSON-serializable. Run Ruff before review; avoid unrelated formatting churn.

## Testing Guidelines

Pytest is the test framework; no coverage threshold is configured. Name files `test_<area>.py` and tests `test_<behavior>`. Add regression tests for behavioral changes and extend a focused fixture when modifying C/C++ parsing, build guards, call graphs, or evidence schemas. Assert safe-unknown behavior as well as successful resolution.

## Commit & Pull Request Guidelines

History favors short, scoped subjects such as `Add TinyUSB MCP golden evaluation runner`; Conventional Commit prefixes are not required. Keep each commit to one logical change. Pull requests should explain the affected layer, compatibility or schema impact, commands run, and any external checkout required. Link related issues and include representative CLI/JSON output when behavior changes.

Do not commit generated indexes, caches, `.tmp-cline/`, machine-specific configuration, or `eval/outputs/` artifacts unless the artifact itself is the reviewed deliverable.
