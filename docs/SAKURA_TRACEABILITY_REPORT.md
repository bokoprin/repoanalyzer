# Sakura Phase7 traceability report

`source_fetch_manifest.yaml` now supports two complementary checks:

1. `snapshot-generate --source-mode both` recreates the compact Phase7 snapshot and copies source-like upstream files from a local checkout into `upstream_sources/`.
2. `snapshot-traceability-report` validates the relationship between each compact slice and its upstream evidence files.

The report is intentionally evidence-aware rather than byte-for-byte equivalence based.  Compact slices are curated, source-derived fixtures, so they are not expected to be identical to the upstream file.  The report therefore checks:

- the compact destination exists;
- the compact destination matches the manifest `sha256` when present;
- source-like `upstream.path` / `upstream.paths` entries have copied files under `upstream_sources/`;
- strong lexical anchors from the compact slice appear in the copied upstream evidence.

## CLI

```bash
PYTHONPATH=. python -m repoanalyzer.cli snapshot-traceability-report \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/source_fetch_manifest.yaml \
  /tmp/generated_sakura_snapshot
```

The command writes `.repoanalyzer-traceability-report.json` into the snapshot root by default and prints the same payload to stdout.

## Status values

- `content_anchored`: at least some strong compact-slice anchors were found in copied upstream files.
- `manifest_linked`: upstream evidence files exist, but not enough compact anchors were found. This is still useful metadata evidence, but weaker than content anchoring.
- `upstream_missing`: source-like upstream refs exist in the manifest but were not copied into `upstream_sources/`.
- `upstream_refs_skipped`: upstream refs were metadata notes rather than source paths, such as `dialog/message samples`.
- `no_upstream_metadata`: the manifest source has no upstream metadata, for example evaluation YAML.

## Safety model

The report does not perform network access. It only inspects the compact snapshot, the manifest, and files already copied under `upstream_sources/`. Missing upstream files are warnings unless the compact file itself is missing or the compact manifest hash mismatches.

# Sakura Phase7 coverage gap report

`snapshot-coverage-gap-report` lifts the file-level traceability report to real-repo-eval scenario granularity.  It answers a different question from `snapshot-traceability-report`: for each trace/scenario, which compact files provide the local evidence, which upstream files have been copied and checked, which upstream files are still missing, and what an LLM must treat as unknown or only partially supported.

## CLI

```bash
PYTHONPATH=. python -m repoanalyzer.cli snapshot-coverage-gap-report \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/source_fetch_manifest.yaml \
  /tmp/generated_sakura_snapshot \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/phase7_sakura_cross_trace_cases.yaml
```

The command writes `.repoanalyzer-coverage-gap-report.json` into the snapshot root by default and prints the same payload to stdout.

## Scenario support status

- `upstream_supported`: mapped compact evidence exists and all source-like upstream refs for the mapped trace are present under `upstream_sources/`.
- `partially_supported`: at least one upstream source ref is present, but another mapped source ref is missing or skipped.
- `upstream_missing`: compact evidence exists, but all source-like upstream refs for the mapped trace are missing from `upstream_sources/`.
- `compact_only`: compact evidence exists, but the manifest has no source-like upstream evidence metadata for that trace.
- `unknown`: the scenario could not be mapped to compact evidence or compact evidence integrity failed.
- `not_applicable`: the scenario checks repository/index health rather than a source trace, for example `query_diagnostics` or `repo_status`.

## Report fields

Each entry contains:

- `compact_evidence`: compact files mapped to the scenario, including their file-level traceability status and anchor matches.
- `upstream_evidence.present`: upstream source refs already copied and available for checking.
- `upstream_evidence.missing`: source-like upstream refs that are declared in the manifest but absent from the generated snapshot.
- `upstream_evidence.skipped`: upstream refs that are metadata notes rather than source paths.
- `recommended_additions`: missing upstream source paths that should be copied next to strengthen the trace.
- `unknown_reasons`: machine-readable reasons such as `upstream_source_missing`, `no_upstream_metadata`, `weak_anchor_match`, or `non_trace_scenario`.

## Safety model

Missing upstream sources are coverage gaps, not command failures.  The command exits non-zero only when the underlying compact evidence is not trustworthy, such as a missing compact destination or manifest hash mismatch. This keeps the report safe-unknown-aware: it can be used in CI or an LLM workflow to decide which claims must remain partial or unknown without treating every missing upstream checkout as a broken snapshot.
