# RepoAnalyzer TinyUSB Agent Evaluation Kit

このkitは、ClineとQwen Codeに同じTinyUSB golden質問を投げ、repoanalyzer MCPを使った回答品質を比較するためのものです。

## 含まれるファイル

- `tinyusb_mcp_golden_cases.csv`
  - 10件のgolden質問、期待根拠、禁止誤答、評価観点
- `cline_batch_prompt.md`
  - Clineに貼る一括実行プロンプト
- `qwen_code_batch_prompt.md`
  - Qwen Codeに貼る一括実行プロンプト
- `answer_schema.json`
  - 回答JSONLの1行あたりのJSON Schema
- `evaluation_rubric.md`
  - 採点基準と失敗原因ラベル
- `RUNBOOK.md`
  - 実行方法

## 最初のゴール

ClineとQwen Codeの両方で、以下を確認します。

```text
collect_evidence
→ read_file_range
→ 根拠付きJSONL回答
```

## その後

生成された2つのJSONLをChatGPTに貼って評価させます。
