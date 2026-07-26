# ローカルLLM + repoanalyzer MCP E2E環境

## 目的

この環境は、固定commitの実在C/C++リポジトリをrepoanalyzerでindex化し、ローカルQwenがstdio MCP子プロセスを通じて根拠付き回答を生成できるかを非対話で評価するためのものです。

これは完成判定ではありません。parser、build profile、実リポジトリcoverage、回答品質を改善する前に、接続・実行・記録・検証経路を再現可能にする前準備です。

## 前提

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,mcp]"
```

- Python 3.11以上
- Git
- Windows上で子プロセスとstdio通信を利用できること
- Codex実行ユーザーの `C:\Users\<user>\.qwen\settings.json` にOpenAI互換providerがあること
- exact model ID `qwen3.6:27b_ud-q4_k_xl` が `/v1/models` に存在すること

接続URLとAPIキーは `.qwen\settings.json` からプロセス内だけへ読み込みます。標準出力、結果JSON、Git管理対象へは保存しません。環境変数を使う場合は次の名前だけを使用します。

```text
REPOANALYZER_LLM_BASE_URL
REPOANALYZER_LLM_API_KEY
REPOANALYZER_LLM_MODEL
```

設定例は `docs/examples/local_llm_e2e.example.json` にあります。値はplaceholderであり、実接続値を書き込まないでください。

## LLM疎通

```powershell
.\.venv\Scripts\python.exe scripts\check_local_llm.py `
  --model "qwen3.6:27b_ud-q4_k_xl" `
  --output eval\preparation\results\llm_connectivity.json
```

この確認はexact model IDだけを受け入れ、`/v1/models` と最小chat completionのHTTP status、時間、model ID、finish reasonだけを保存します。指定modelがない場合は類似名へfallbackしません。

## MCP実プロセスsmoke

```powershell
.\.venv\Scripts\python.exe -m repoanalyzer.cli ingest tests\fixtures_cpp\basic_call
.\.venv\Scripts\python.exe scripts\mcp_process_smoke.py `
  --repo tests\fixtures_cpp\basic_call `
  --output eval\preparation\results\mcp_process_smoke.json
```

smokeは `python -m repoanalyzer.mcp.server --repo <repo>` をstdio子プロセスとして起動し、initialize、tool一覧、次のtoolを呼びます。

- `server_info`
- `repo_status`
- `find_definitions`
- `find_references`
- `find_callers`
- `find_callees`
- `read_file_range`
- `collect_evidence`

専用の曖昧symbol search toolは現時点でありません。前準備では `find_definitions` と `find_references` をsymbol lookupとして使い、汎用検索は次フェーズの評価項目に残します。

## Qwen + MCP runner

任意のindex済みrepositoryに対して実行できます。

```powershell
.\.venv\Scripts\python.exe scripts\run_qwen_mcp_e2e.py `
  --repo <indexed-repository> `
  --model "qwen3.6:27b_ud-q4_k_xl" `
  --question "<source-grounded question>" `
  --output eval\outputs\preparation\manual-e2e.json
```

runnerはMCP tool schemaをOpenAI互換function toolsへ変換します。Qwenが返した`tool_calls`をMCPへ送り、結果をtool messageとしてQwenへ戻す処理を最大8turn繰り返します。

保存結果にはLLM requestごとのHTTP status・時間・finish reason、tool名・引数・MCP response・時間、最終回答を含めます。MCPを1回も使わない回答、tool error、空回答、最大turn超過は失敗です。

## 固定SHA外部smoke

scenarioは `eval/preparation/inih_smoke.json` です。

- repository: `https://github.com/benhoyt/inih.git`
- commit: `577ae2dee1f0d9c2d11c7f10375c1715f3d6940c`
- license: New BSD
- question: `ini_parse` の定義ファイルと、return前に呼ぶrepository関数

```powershell
.\.venv\Scripts\python.exe scripts\run_external_smoke.py
```

scriptは `.e2e-work\inih` を準備し、固定commitとoriginを検証してから`compile_commands.json`を生成します。既存checkoutにtracked変更がある状態でcommit切替が必要な場合は停止し、変更を上書きしません。

成功条件は次のすべてです。

- ingestが`indexed`
- index statusが`clean`
- QwenがMCPを実呼び出し
- 必須tool `repo_status`、`find_definitions`、`find_callees`、`read_file_range`を使用
- 最終回答に`ini.c`、`ini_parse`、`ini_parse_file`が存在
- 同じ文字列がMCP evidenceにも存在
- pinned source内の定義・call anchorが一致

## 結果

review対象の初回結果は `eval/preparation/results/` に保存します。反復評価や大規模batchはignoredの `eval/outputs/` に保存してください。

- `baseline.json`: 変更前回帰・静的解析・fixture smoke
- `llm_connectivity.json`: exact model疎通
- `mcp_process_smoke.json`: stdio MCP processと主要tool
- `inih_smoke_result.json`: 外部repository ingest、Qwen tool loop、source検証

秘密情報が疑われる結果はcommitせず、接続設定を読み直して再生成してください。
