# TinyUSB MCP E2E agent comparison runbook

目的は、ClineとQwen Codeに同じgolden質問を投げ、repoanalyzer MCPを使った回答品質がどう変わるかを見ることです。

## 前提

repoanalyzerとTinyUSBの環境構築は完了済みとします。

- repoanalyzer: `C:\shinsuke\app\repoanalyzer_clean`
- TinyUSB: `C:\shinsuke\app\tinyusb`
- Python: `C:\shinsuke\app\repoanalyzer_clean\.venv\Scripts\python.exe`
- MCP server command:

```powershell
C:\shinsuke\app\repoanalyzer_clean\.venv\Scripts\python.exe -m repoanalyzer.mcp.server --repo C:\shinsuke\app\tinyusb
```

## 1. ファイル配置

このkit内のファイルを repoanalyzer repository の以下へ配置するのがおすすめです。

```text
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\tinyusb_mcp_golden_cases.csv
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\answer_schema.json
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\cline_batch_prompt.md
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\qwen_code_batch_prompt.md
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\evaluation_rubric.md
C:\shinsuke\app\repoanalyzer_clean\eval\agent_compare\RUNBOOK.md
C:\shinsuke\app\repoanalyzer_clean\eval\outputs\
```

## 2. index状態確認

```powershell
cd C:\shinsuke\app\repoanalyzer_clean
.\.venv\Scripts\python.exe -m repoanalyzer.cli repo-status C:\shinsuke\app\tinyusb
.\.venv\Scripts\python.exe -m repoanalyzer.cli query-diagnostics C:\shinsuke\app\tinyusb
```

`status: clean` であることを確認します。

## 3. Clineで実行

1. Clineに `repoanalyzer-tinyusb` MCP serverが登録されていることを確認します。
2. `cline_batch_prompt.md` の全文をClineへ貼ります。
3. 出力を `eval/outputs/tinyusb_answers_cline.jsonl` として保存します。
4. ClineがJSONLではなくMarkdownで返した場合は、そのまま保存せず、JSONLのみで再出力するように依頼します。

## 4. Qwen Codeで実行

1. Qwen Codeから同じ `repoanalyzer-tinyusb` MCP serverが利用できる状態にします。
2. `qwen_code_batch_prompt.md` の全文をQwen Codeへ貼ります。
3. 出力を `eval/outputs/tinyusb_answers_qwen_code.jsonl` として保存します。
4. MCPが見えない場合は、MCP設定差分として記録します。回答性能比較ではなく、接続性の問題として扱います。

## 5. 私へ評価依頼するとき

以下を貼ってください。

```text
1. tinyusb_answers_cline.jsonl
2. tinyusb_answers_qwen_code.jsonl
3. Cline側のMCP tool利用履歴が見える場合はその要約
4. Qwen Code側のMCP tool利用履歴が見える場合はその要約
5. 失敗caseやエラー全文
```

私は以下を返します。

```text
case_idごとのCline/Qwen Code比較
10点満点スコア
失敗原因ラベル
repoanalyzer側の修正候補
LLM利用ルール側の修正候補
golden case側の修正候補
次のBatchで実装すべき優先順位
```

## 6. 比較の観点

ClineとQwen Codeで差が出た場合、以下に分けて見ます。

- MCP toolを見つける能力
- collect_evidenceを最初に使うか
- read_file_rangeで根拠確認するか
- find_definitions/find_callers/find_calleesを追加で使えるか
- JSONLスキーマを守れるか
- conditional/unknownを表現できるか
- 根拠にない補完を避けられるか

## 7. 重要な注意

この評価はLLM単体性能ではなく、以下を含む総合性能です。

```text
agent UI / tool orchestration / MCP接続 / prompt遵守 / repoanalyzer evidence品質 / model性能
```

そのため、失敗した場合は必ず「repoanalyzerが悪い」とは限りません。
失敗原因を分類してから、repoanalyzerを直すか、agent promptを直すか、golden caseを直すかを決めます。
