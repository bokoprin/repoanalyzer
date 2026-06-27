# attic/reference

このディレクトリは、旧 repoanalyzer から移植候補として一時退避した参照コードです。
新しい実行経路からは import しません。

残した主な意図:

- 旧 SQLite schema / store 実装の参考
- 旧 scanner / tree-sitter / callgraph / dependency 抽出ロジックの参考
- 旧 C/C++ v2 実装の build context / build guard / call relation 周辺の参考

新しい実装は `repoanalyzer/` 配下の core/cpp/store/evidence/query/mcp/evidence_eval を正とします。
