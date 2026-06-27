# Code Evidence Engine Design

repoanalyzer is a C/C++ Code Evidence Engine for LLM agents.

## Goal

Give local LLMs and coding agents reliable, typed evidence from a C/C++ repository:

- definitions
- references
- direct calls
- call paths
- include facts
- build guards
- unknowns and answerability

## Non-goals for the current core

- natural-language answer generation
- generic multi-language RAG
- GUI/Lab UI
- embedding-first semantic search
- large OSS evaluation before fixture correctness passes

## Architecture

```text
cpp ingest -> SQLite Code Fact Store -> query primitives -> EvidenceBundle -> MCP/eval
```
