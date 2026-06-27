# Sakura UI resource command binding

This note documents the Phase 7 Sakura Editor validation slice for Windows UI resource command binding.

## Goal

Connect GUI entry declarations to command execution evidence without treating resource bindings as direct calls:

- `.rc` menu entries: `MENUITEM "Find &Next", F_SEARCH_NEXT`
- `.rc` accelerator entries: `VK_F3, F_SEARCH_NEXT, VIRTKEY, NOINVERT`
- Sakura-style toolbar tables: `/* 225 */ F_SEARCH_NEXT`
- runtime accelerator setup: `CreateAcceleratorTable`, `ACCEL.cmd`, `GetFuncCodeAt`
- command dispatch: `F_SEARCH_NEXT -> CViewCommander::Command_SEARCH_NEXT`

## Relation model

The extractor emits semantic `relation` facts rather than unconditional `call` facts.

| Predicate | Meaning |
| --- | --- |
| `binds_menu_item_to_command` | A menu resource item maps to a command ID. |
| `binds_accelerator_to_command` | A resource or runtime accelerator maps to a command ID. |
| `binds_toolbar_button_to_command` | A toolbar slot maps to a command ID. |
| `creates_accelerator_table` | Runtime accelerator table creation. |
| `looks_up_accelerator_command` | Runtime lookup from key/status to function code. |
| `translates_accelerator_to_command` | Runtime accelerator command ID becomes an `EFunctionCode`. |
| `routes_resource_command_to_handler` | `WM_COMMAND` or equivalent resource command is routed into command dispatch. |

All of these use `edge_status = semantic_ui_resource_relation` and `unknown_type = resource_binding_not_unconditional_call`.

## Deterministic evidence question

The question:

```text
リソースID / accelerator / menu / toolbar から command ID への対応はどう行われる？
```

returns trace facts such as:

```text
IDR_MAINMENU:Find &Next
  -> F_SEARCH_NEXT
  -> sakura::CViewCommander::Command_SEARCH_NEXT

IDR_ACCELERATOR:VK_F3
  -> F_SEARCH_NEXT
  -> sakura::CViewCommander::Command_SEARCH_NEXT

toolbar_slot_225
  -> F_SEARCH_NEXT
  -> sakura::CViewCommander::Command_SEARCH_NEXT
```

This is evidence-safe because the first edge is a UI resource binding and the second edge is the existing conditional command dispatch relation.

## Fixture

The validation fixture is:

```text
tests/fixtures_cpp/semantic_sakura_ui_resource
```

It includes both a `.rc` resource script and a C++ translation unit with Sakura-style `CKeyBind`, `CMenuDrawer`, and `CViewCommander` patterns.
