# repoanalyzer完成作業 前準備レポート

## 判定

前準備フェーズの接続・実行・評価経路を確立した。repoanalyzer自体の完成は判定していない。

## 使用対象

- repoanalyzer remote: `https://github.com/bokoprin/repoanalyzer.git`
- baseline commit: `d3380e38e1339d11bbd0893da43475b97820c5e2`
- branch / default branch: `main` / `main`
- local LLM model ID: `qwen3.6:27b_ud-q4_k_xl`
- external repository: `https://github.com/benhoyt/inih.git`
- external commit: `577ae2dee1f0d9c2d11c7f10375c1715f3d6940c`
- external license: New BSD

ユーザーの未コミット `.env` は内容を読まず、変更・削除・stageを行っていない。以後の誤commitを防ぐため `.env` と `.env.*` を `.gitignore` へ追加した。

## 変更前baseline

`eval/preparation/results/baseline.json` に機械可読で保存した。

- Python: 3.14.2
- 自己完結pytest: 165 passed、1 upstream deselected、0 failed
- 構文検査: PASS
- CLI `--help`: PASS
- Ruff: 既存25 errors
- mypy: 既存47 errors / 14 files
- fixture ingest: 3 files / 25 facts
- fixture index: clean
- definition / reference / caller / callee / source range / evidence: PASS

Ruffとmypyの失敗は前準備コード追加前に採取した既存baselineであり、今回発生分と混同しない。

## LLM接続

`C:\Users\<user>\.qwen\settings.json` のOpenAI互換providerを参照した。接続URL、APIキー、設定内の秘密値は結果・ログ・Git差分へ保存していない。

- `/v1/models`: HTTP 200
- exact model match: PASS
- minimal chat completion: HTTP 200
- returned model ID: exact match
- OpenAI互換tool call probe: `finish_reason=tool_calls`、1 tool call

実測値は `eval/preparation/results/llm_connectivity.json` に保存した。

## MCP実プロセス

MCP Python clientから `repoanalyzer.mcp.server` をstdio子プロセスとして起動した。関数直接呼び出しではない。

- initialize: PASS
- protocol version: `2025-11-25`
- server name: `repoanalyzer`
- tool count: 24
- 主要8 tool: 全件response errorなし
- evidence answerability: `answerable`

詳細は `eval/preparation/results/mcp_process_smoke.json` に保存した。

## Qwen + MCP評価ハーネス

`scripts/run_qwen_mcp_e2e.py` は次を非対話で行う。

1. `.qwen`または明示環境変数から接続をプロセス内へ解決
2. `/v1/models`でexact model IDを確認
3. stdio MCP子プロセスをinitialize
4. MCP schemaをOpenAI互換function toolsへ変換
5. Qwenのtool callをMCPへ送信
6. MCP responseをQwenへ返して複数turn継続
7. tool履歴、response、最終回答、時間を安全なJSONへ保存
8. MCP未使用・tool error・空回答・turn超過を失敗判定

## 外部repository smoke

`scripts/run_external_smoke.py` で固定SHAのinihを取得し、`ini.c`向けcompile commandを生成してingestした。

- ingest: indexed
- indexed files: 3
- facts: 312
- index: clean
- Qwen MCP calls: 4
- tool順序: `repo_status`、`find_definitions`、`find_callees`、`read_file_range`
- tool errors: 0
- final answer: `ini_parse` は `ini.c:279-290` に定義され、repository関数 `ini_parse_file` をline 287で直接呼ぶ
- source anchor検証: 2/2 PASS
- answer / MCP evidence required strings: 3/3 PASS

詳細は `eval/preparation/results/inih_smoke_result.json` に保存した。

## 最終品質ゲート

- 自己完結pytest: 178 passed、1 upstream deselected、0 failed
- focused E2E / evaluator tests: 13 passed
- Ruff: PASS
- mypy: 142 source files、0 issues
- compileall: PASS
- pip-audit: 既知脆弱性なし（ローカルeditable package自体はPyPI監査対象外）
- Bandit: Critical 0、High 0
- Bandit Medium 4件: 既存SQLite層のSQL断片。可変値はプレースホルダー化され、raw条件は内部呼び出しだけであることをレビュー済み
- `.qwen`接続URL・APIキーの完全一致scan: 446 files、0 matches

変更前baselineにあったRuff 25件とmypy 47件は、baseline記録後に挙動を変えない静的解析修正として解消した。

## 残る完成作業

- dedicated symbol searchの要否と仕様を決める
- 複数の外部C/C++ repository・build system・target profileへscenarioを拡張する
- conditional compilation、macro、callback、virtual dispatch、cross-TUを実repositoryで評価する
- MCP tool schema互換性を複数client/modelで評価する
- Qwenのtool選択失敗、長いtool response、timeout、context上限をfault injectionする
- 回答のsupported / conditional / unknown disciplineを自動採点する

## 現在フェーズ

- フェーズ: 完成作業の前準備
- 進捗率: 100%（前準備の範囲）
- repoanalyzer完成率: 判定しない
- コミットコメント案: `ローカルQwenと実プロセスMCPの再現可能なE2E評価基盤を追加`
