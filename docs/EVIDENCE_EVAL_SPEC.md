# Evidence Eval Spec

Evaluation cases assert whether repoanalyzer reaches expected evidence.

```yaml
cases:
  - id: cpp_basic_call_001
    question: "init_device はどこから呼ばれる？"
    mode: callers
    expected:
      must_include:
        - fact_type: call
          caller: start_device
          callee: init_device
      must_not_include: []
    answerability: answerable
    required_unknowns: []
```
