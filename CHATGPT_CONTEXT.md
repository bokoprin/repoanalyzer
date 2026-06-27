# repoanalyzer ChatGPT Context

This archive contains the source and supporting context needed to discuss repoanalyzer design and implementation with ChatGPT.

## Project Purpose

repoanalyzer is a C/C++ Code Evidence Engine for MCP-based LLM agents. Its current MVP focuses on typed, source-grounded evidence from C/C++ repositories.

## Included

- epoanalyzer/: Python package source.
- 	ests/: pytest tests and C/C++ fixtures.
- docs/: design and contract documents.
- ttic/reference/: older reference implementation useful for design comparison.
- Root project files: README.md, memo.md, pyproject.toml, .gitignore.
- 	ool/export_chatgpt_context.bat: the export tool that created this archive.
- Generated context files: REPO_TREE.txt, GIT_STATUS.txt, GIT_DIFF.patch, ENVIRONMENT.txt.

## Excluded

The archive intentionally excludes Git internals, export output, caches, virtual environments, generated indexes, Python bytecode, .env* files, and filenames that look like secrets, tokens, credentials, passwords, or keys.

## Suggested ChatGPT Prompt

Use this archive as the complete working context for repoanalyzer. Start from README.md, memo.md, docs/, and pyproject.toml, then inspect epoanalyzer/ and 	ests/ before proposing design or implementation changes. Treat ttic/reference/ as historical reference, not active source.
