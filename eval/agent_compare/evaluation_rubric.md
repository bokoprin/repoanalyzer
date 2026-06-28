# RepoAnalyzer TinyUSB agent answer evaluation rubric

このrubricは、ClineとQwen Codeに同じgolden質問を投げた後、回答JSONLを比較評価するために使います。

## スコア

各caseを10点満点で採点します。

### 1. Tool use: 0-3点

- 3: collect_evidenceを使い、必要に応じてfind_*も使い、根拠ファイルをread_file_rangeで確認している
- 2: collect_evidenceとread_file_rangeは使ったが、必要な追加探索が不足
- 1: repoanalyzer toolは使ったが、read_file_range確認が不足
- 0: toolを使っていない、またはtool利用の痕跡が不明

### 2. Evidence quality: 0-3点

- 3: required_files/required_symbolsをほぼ満たし、ファイル行の根拠が妥当
- 2: 中心根拠はあるが、一部不足
- 1: 関連根拠はあるが、質問の核心に届いていない
- 0: 根拠が無関係、または根拠なし

### 3. Answer correctness: 0-3点

- 3: expected_pointsを満たし、誤りがない
- 2: 主回答は正しいが、軽微な誤りや不足がある
- 1: 部分的に正しいが、重要な誤りがある
- 0: 主回答が誤り

### 4. Safety / conditional handling: 0-1点

- 1: conditional/unknown/unsupportedを適切に区別し、forbidden_claimsを避けている
- 0: 根拠なし断定、conditional欠落、forbidden_claims該当がある

## 失敗原因ラベル

- PASS: 8点以上、重大な誤りなし
- LLM_TOOL_FAILURE: tool利用順やread_file_range確認に問題
- EVIDENCE_MISSING: repoanalyzerが必要根拠を返せていない
- EVIDENCE_NOISY: 根拠が多すぎる/紛らわしく、LLMが誤誘導された
- CONDITIONAL_MISSING: build/profile/guard依存を断定した
- HALLUCINATION: 根拠にないファイル、行、定義、因果関係を断定した
- QUESTION_AMBIGUOUS: golden質問側が曖昧
- AGENT_LIMITATION: MCP接続不可、出力形式不遵守などエージェント側制約

## 評価時に私へ貼るもの

1. `tinyusb_answers_cline.jsonl`
2. `tinyusb_answers_qwen_code.jsonl`
3. Cline/Qwen CodeのMCP接続状態メモ
4. 途中で失敗したcaseがあれば、そのエラー全文

貼ってもらえれば、caseごとにスコア、失敗原因、repoanalyzer修正案、LLMルール修正案を返します。
