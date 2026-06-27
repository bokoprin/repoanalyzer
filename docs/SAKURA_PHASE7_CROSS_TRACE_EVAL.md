# Sakura Phase7 cross-trace evaluation suite

This suite is a larger Sakura Editor-derived validation snapshot for Phase7.  It is not a full upstream checkout; it is a compact, source-derived fixture that keeps the evidence patterns discovered while probing Sakura Editor and validates them together in one repository-shaped snapshot.

The fixture lives at:

```text
/tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot
```

It intentionally spans these topics:

- UI resource/menu/accelerator/toolbar binding to `F_*` command IDs
- `F_*` command dispatch to `CViewCommander::Command_*`
- search and grep call chains
- grep replace writer/encoding chains
- undo/redo and edit-buffer replay
- file loading and character encoding detection
- `CShareData` / `CDataProfile` / INI profile I/O
- Windows message and dialog callback registration/dispatch
- macro, plugin, and external command execution paths

The Phase7 case file is:

```text
/tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/phase7_sakura_cross_trace_cases.yaml
```

It is designed to be run with:

```bash
PYTHONPATH=. python -m repoanalyzer.cli real-repo-eval \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot \
  tests/fixtures_cpp/phase7_sakura_cross_trace_snapshot/phase7_sakura_cross_trace_cases.yaml
```

The suite verifies that the snapshot can answer the following high-level questions without inventing unsupported direct calls:

```text
検索はどう実行される？
Undo/Redo と編集操作はどう追跡される？
ファイル読み込み・文字コード判定はどう行われる？
設定読み書き / CShareData / CommonSetting / profile / ini系はどう行われる？
Windows message / dialog callback はどう行われる？
リソースID / accelerator / menu / toolbar から command ID への対応はどう行われる？
プラグイン / マクロ / 外部コマンド実行経路はどう行われる？
```

## Design notes

The suite deliberately checks both ordinary call graph evidence and semantic relation evidence.

For example, command dispatch, dialog callbacks, UI resource bindings, macro/plugin execution, and external process launch are not represented as unconditional direct calls.  They are recorded as conditional or semantic relations such as `dispatches_to`, `registers_dialog_callback`, `binds_accelerator_to_command`, `executes_macro`, `invokes_plugin_hook`, and `launches_external_process`.

This keeps answers evidence-aware and safe-unknown-aware: downstream LLMs can say that a command ID is bound to a handler, or that Windows will later invoke a dialog callback, without falsely claiming that the registration statement directly calls the callback.

## Regression role

This suite is intended as a Phase7 guardrail.  A change to one semantic extractor should not silently break other Sakura-derived traces.  The dedicated test is:

```text
tests/test_phase7_sakura_cross_trace_suite.py
```

It runs `real_repo_eval`, checks the aggregate metrics, and then asks the major cross-trace questions directly through `collect_evidence`.
