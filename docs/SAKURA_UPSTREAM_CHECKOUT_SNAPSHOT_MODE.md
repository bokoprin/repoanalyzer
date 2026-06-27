# Sakura upstream checkout snapshot mode

This mode extends the Phase7 Sakura snapshot generator from a local compact-slice copier into a reproducible checkout copier.

The original `snapshot_manifest.v1` remains local-first:

```bash
python -m repoanalyzer.cli snapshot-generate source_fetch_manifest.yaml out
```

That copies each entry's local `source` to `destination` and is intended for compact, already-curated validation snapshots.

The new upstream checkout mode uses each source entry's `upstream.repository` and `upstream.path` / `upstream.paths` metadata. It never accesses the network. Instead, callers provide a local checkout root:

```bash
python -m repoanalyzer.cli snapshot-generate source_fetch_manifest.yaml out \
  --source-mode upstream \
  --checkout-root sakura-editor/sakura=/path/to/sakura
```

Supported modes:

- `local`: copy compact local sources only. This is the default and preserves the Phase7 cross-trace fixture behavior.
- `upstream`: copy only files from the checkout described by `upstream` metadata.
- `both`: copy compact local sources and upstream checkout files side by side. This is useful for audit bundles.

Upstream files are written under:

```text
upstream_sources/<repository-slug>/<upstream-path>
```

unless the entry provides `upstream.destination` or `upstream.destinations`.

Example manifest entry:

```yaml
sources:
  - destination: modules/search_command/src/command_dispatch.cpp
    source: modules/search_command/src/command_dispatch.cpp
    sha256: <compact-slice-sha256>
    upstream:
      repository: sakura-editor/sakura
      ref: bca1be151a053722e46cc70b82c2320d2dd3795a
      path: sakura_core/cmd/CViewCommander.cpp
      sha256: <optional-upstream-file-sha256>
```

For entries derived from multiple upstream files, `upstream.paths` may be a list:

```yaml
upstream:
  repository: sakura-editor/sakura
  paths:
    - sakura_core/macro/CSMacroMgr.cpp
    - sakura_core/plugin/CJackManager.cpp
```

A legacy string such as `file1.cpp + file2.cpp` is also split on `+`. Descriptive fragments that do not look like source paths are skipped and listed in `skipped_upstream_sources` rather than treated as proven evidence.

The generation report now records:

- `source_mode`
- `checkout_roots`
- `upstream_copied_files`
- `skipped_upstream_sources`

This keeps the answer discipline clear: compact slices support the Phase7 semantic expectations; upstream copies are source evidence that can be inspected separately and regenerated from a real checkout.
