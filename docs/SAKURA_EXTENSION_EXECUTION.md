# Sakura plugin / macro / external-command execution tracking

This hardening step models Sakura Editor-style extension execution as semantic
evidence rather than as unconditional direct calls.

The target patterns are:

- macro recording and replay through `CSMacroMgr::Append`, `CSMacroMgr::Exec`,
  `Load`, `LoadKeyMacro`, `LoadKeyMacroStr`, and `ExecKeyMacro2`;
- macro function-table bindings such as `F_SEARCH_NEXT -> L"SearchNext"` in
  `CSMacroMgr::m_MacroFuncInfoCommandArr`;
- plugin jack registration and invocation through `CJackManager::RegisterPlug`,
  `GetUsablePlug`, `InvokePlugins`, `CPlug::Invoke`, and plugin command-id
  lookup via `GetCommandById` / `GetCommandCode` / `GetPluginFunctionCode`;
- external process/target launch markers such as `ShellExecute*`,
  `CreateProcess*`, `WinExec`, and Sakura-style `OpenNewEditor`.

These edges use `fact_type=relation` and `edge_status=semantic_extension_execution_relation`.
They intentionally avoid claiming that a plugin, macro, or external command is a
normal statically known call target.  The payload includes an `execution_category`
field such as `macro_execution`, `plugin_execution`, or `external_process`.

The deterministic question:

```bash
python -m repoanalyzer.cli collect-evidence <repo> \
  'プラグイン / マクロ / 外部コマンド実行経路はどう行われる？'
```

returns traces such as:

- `macro_command_execution_trace`:
  `CViewCommander::HandleCommand -> CSMacroMgr::Append -> CSMacroMgr::Exec`
- `macro_load_and_replay_trace`:
  `CSMacroMgr::Exec -> CShareData::macro_configuration` and macro replay facts
- `plugin_hook_registration_trace`:
  `CJackManager::RegisterPlug -> CPlug::GetFunctionCode`-style command mapping
- `plugin_hook_invocation_trace`:
  `CJackManager::InvokePlugins -> GetUsablePlug -> CPlug::Invoke`
- `plugin_command_execution_trace`:
  `CViewCommander::HandleCommand -> GetCommandById -> CPlug::Invoke`
- `external_command_launch_trace`:
  `CViewCommander::Command_EXECEXTCOMMAND -> ShellExecuteW/CreateProcessW`

The fixture is `tests/fixtures_cpp/semantic_sakura_extension_execution` and is
covered by `tests/test_sakura_extension_execution.py`.
