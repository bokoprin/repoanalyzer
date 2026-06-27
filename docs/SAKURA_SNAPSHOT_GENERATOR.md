# Sakura snapshot generator / source fetch manifest

This feature turns the hand-assembled Sakura Editor-derived Phase7 compact snapshot into a reproducible artifact.

The generator is intentionally **local-first**:

- the manifest records upstream repository/ref/path metadata for traceability;
- generation copies from local source slices, so tests and local LLM workflows do not require network access;
- `sha256` guards catch accidental drift in source slices;
- generated files such as `compile_commands.json` and `README.md` are derived from the manifest;
- the output includes `.repoanalyzer-source-fetch-manifest.yaml` and `.repoanalyzer-snapshot-report.json`.

## Manifest schema

The supported schema is `snapshot_manifest.v1`.

Key fields:

```yaml
schema_version: snapshot_manifest.v1
snapshot_id: phase7_sakura_cross_trace_snapshot
source_root: .
sources:
  - source: modules/search_command/src/command_dispatch.cpp
    destination: modules/search_command/src/command_dispatch.cpp
    sha256: ...
    upstream:
      repository: sakura-editor/sakura
      ref: bca1be151a053722e46cc70b82c2320d2dd3795a
      paths: sakura_core/cmd/CViewCommander.cpp
compile_commands:
  output: compile_commands.json
  entries:
    - directory: .
      command: clang++ -I. -Iinclude -std=c++17 -c modules/search_command/src/command_dispatch.cpp
      file: modules/search_command/src/command_dispatch.cpp
```

`upstream` metadata is evidence metadata only.  It is not fetched by this command.
This keeps repoanalyzer usable in offline/local-LLM settings and avoids silently changing test inputs when upstream changes.

## CLI

```bash
PYTHONPATH=. python -m repoanalyzer.cli snapshot-generate \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/source_fetch_manifest.yaml \
  /tmp/phase7_sakura_snapshot
```

The command prints a `snapshot_generation_report.v1` JSON object.

## Phase7 workflow

A generated snapshot can be fed directly into real-repo-eval:

```bash
PYTHONPATH=. python -m repoanalyzer.cli real-repo-eval \
  /tmp/phase7_sakura_snapshot \
  /tmp/phase7_sakura_snapshot/phase7_sakura_cross_trace_cases.yaml \
  --output json
```

This makes the Sakura cross-trace validation reproducible from a manifest rather than from an implicit hand-edited directory.
