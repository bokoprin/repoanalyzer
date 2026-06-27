# Sakura Windows message / dialog callback tracking

This phase models Sakura Editor style Windows GUI flow without treating event edges as unconditional calls.

## Scope

The lightweight C/C++ extractor records semantic relations for:

- dialog creation through `DialogBoxParam`, `DialogBox`, `CreateDialogParam`, `CreateDialog`
- dialog callback registration, for example `CSearchDialog::DlgProc`
- message handlers in dialog/window procedures such as `WM_INITDIALOG`, `WM_COMMAND`, `WM_NOTIFY`, `WM_CLOSE`
- control command handlers such as `IDC_BUTTON_FIND`, `IDOK`, `IDCANCEL`
- message bridge APIs such as `SendMessage`, `SendMessageCmd`, `PostMessage`, `PostMessageCmd`
- subclass callback registration through `SetWindowSubclass`
- dialog close operations through `EndDialog`

## Evidence model

These edges are emitted as `relation` facts, not as normal direct `call` facts.  The important payload markers are:

- `edge_status = semantic_windows_message_relation`
- `unknown_type = message_relation_not_unconditional_call`
- `unknown_type = dialog_callback_not_direct_call` for registered dialog procs
- `relation_kind = dialog_callback_registration`, `message_dispatch`, `control_command_dispatch`, `message_send`, or `subclass_callback_registration`

This allows downstream LLMs to say that Windows invokes the callback when the dialog receives a message, instead of claiming the creator function directly calls the dialog procedure.

## Deterministic question trace

For the question `Windows message / dialog callback はどう行われる？`, `collect-evidence` returns traces such as:

```text
sakura::CSearchDialog::OpenDialog
  -> sakura::DialogBoxParam
  -> sakura::CSearchDialog::DlgProc

sakura::CSearchDialog::DlgProc
  -> WM_INITDIALOG
  -> WM_COMMAND
  -> IDC_BUTTON_FIND

sakura::CSearchDialog::OnFindNext
  -> WM_COMMAND

sakura::CPropTypesColor::InitColorList
  -> sakura::CPropTypesColor::ColorList_SubclassProc
```

## Limitations

This is a static semantic approximation.  It does not prove which runtime message will actually arrive, nor does it evaluate resource templates, accelerator tables, or full Win32 message pump behavior.  Those should remain conditional/event-driven evidence.
