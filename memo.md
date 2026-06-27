# repoanalyzer 2.0


## repoanalyzer v2.0 の定義
- ローカルLLMやAIエージェントが、C/C++リポジトリを根拠付きで解析するための Code Evidence Engine

## ソフトの要求
- ローカルLLMでもクラウド最上級レベルのコード解析力を持たすために、事前にインデックスを作成し、MPCから該当コードを拾えるようにすること

## ソフトの目的
- repoanalyzer v2.0 は、C/C++リポジトリから型付きCodeFactを抽出し、LLMが根拠付きで安全にコード解析できるよう、EvidenceBundleをMCP経由で提供する Code Evidence Engine である。

## 今後の判断基準
この変更は、LLMがC/C++コードを正確に理解するためのEvidence品質を上げるか？