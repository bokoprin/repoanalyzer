# Sakura Editor command dispatch evidence design

This note records the Sakura Editor driven command-dispatch hardening used to answer questions such as:

> 検索はどう実行される？

## Goal

Keep repoanalyzer focused on C/C++ evidence.  A UI command id is not a direct call by itself, but Sakura Editor's `CViewCommander::HandleCommand` switch maps command ids to handler methods.  The index should expose that mapping as conditional dispatch evidence, then connect the selected handler to ordinary call graph evidence.

## Extracted evidence

For switch cases such as:

```cpp
case F_SEARCH_NEXT:
    Command_SEARCH_NEXT(true, bRedraw, false, hwnd, message);
    break;
```

repoanalyzer emits a `relation` fact:

```json
{
  "fact_type": "relation",
  "subject": "F_SEARCH_NEXT",
  "predicate": "dispatches_to",
  "object": "sakura::CViewCommander::Command_SEARCH_NEXT",
  "payload": {
    "relation_kind": "command_dispatch",
    "dispatch_kind": "switch_case",
    "edge_status": "conditional_dispatch"
  }
}
```

This is deliberately not treated as unconditional runtime execution.  It means the command id dispatches to the handler when that switch case is selected.

## Search execution trace

For `検索はどう実行される？`, evidence collection now builds a deterministic trace:

```text
F_SEARCH_NEXT
  -> CViewCommander::Command_SEARCH_NEXT     conditional dispatch
  -> CLayoutMgr::SearchWord                  resolved call
  -> CSearchAgent::SearchWord                resolved call
  -> CSearchAgent::SearchString              resolved call
```

The bundle also includes branch evidence from `CSearchAgent::SearchWord` to `SearchStringWord`, so an LLM can describe the normal string-search and word-only branches without inventing them.

## Safety constraints

- `dispatches_to` is conditional dispatch evidence, not proof that the handler always executes.
- The handler-to-search-core path is ordinary call graph evidence and may still be conditional if build or semantic status requires qualification.
- If the switch case, handler, or search core is missing from the index, the answer must stay partial or unknown.
