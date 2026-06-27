# Sakura Editor Undo/Redo edit-operation evidence design

This note records the Sakura Editor driven Undo/Redo and edit-operation hardening.

## Goal

Repoanalyzer should not only say that one function calls another.  For editor-like C/C++ applications, it should expose the role of important calls:

- UI command id dispatches to an edit command.
- Edit commands mutate the edit buffer.
- Commands prepare or flush Undo buffers.
- Undo/Redo consumes operation history and replays edits into the buffer.
- Modified-state updates are visible as explicit evidence.

These relations are semantic evidence, not final prose.  They help an LLM answer questions such as `Undo/Redo と編集操作はどう追跡される？` without inventing behavior.

## Extracted relation facts

Examples:

```json
{
  "fact_type": "relation",
  "subject": "sakura::CViewCommander::Command_WCHAR",
  "predicate": "performs_edit_operation",
  "object": "sakura::CEditView::InsertData_CEditView",
  "payload": {
    "relation_kind": "edit_buffer_mutation",
    "operation_kind": "insert_text",
    "edge_status": "semantic_operation_relation"
  }
}
```

Undo/Redo history access is represented separately:

```json
{
  "fact_type": "relation",
  "subject": "sakura::CViewCommander::Command_UNDO",
  "predicate": "consumes_undo_history",
  "object": "sakura::COpeBuf::DoUndo",
  "payload": {
    "relation_kind": "undo_redo_history_access",
    "operation_kind": "undo_history_pop"
  }
}
```

The replay step is represented as an edit operation:

```json
{
  "fact_type": "relation",
  "subject": "sakura::CViewCommander::Command_UNDO",
  "predicate": "performs_edit_operation",
  "object": "sakura::CEditView::ReplaceData_CEditView3",
  "payload": {
    "relation_kind": "edit_buffer_mutation",
    "operation_kind": "replace_text"
  }
}
```

## Deterministic evidence trace

For `Undo/Redo と編集操作はどう追跡される？`, evidence collection composes command dispatch facts and semantic operation relations into traces:

```text
F_WCHAR
  -> CViewCommander::Command_WCHAR
  -> CEditView::InsertData_CEditView

F_UNDO
  -> CViewCommander::Command_UNDO
  -> COpeBuf::DoUndo
  -> CEditView::ReplaceData_CEditView3

F_REDO
  -> CViewCommander::Command_REDO
  -> COpeBuf::DoRedo
  -> CEditView::ReplaceData_CEditView3
```

The Undo/Redo traces are intentionally semantic traces, not claims that `DoUndo` directly calls `ReplaceData_CEditView3`.  They show that the command consumes history and then replays edit-buffer mutation inside the same command flow.

## Safety notes

- `dispatches_to` is conditional dispatch evidence.
- `performs_edit_operation` means the function contains a recognized edit-buffer mutation call.
- `consumes_undo_history` / `consumes_redo_history` means the function reads the Undo/Redo operation buffer.
- These facts do not prove all branches execute at runtime.
