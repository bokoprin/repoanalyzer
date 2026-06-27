from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path

from repoanalyzer.core.models import CodeFact, EvidenceBundle, UnknownFact
from repoanalyzer.core.unknowns import call_graph_incomplete, definition_not_found
from repoanalyzer.query import find_callers, find_callees, find_definitions
from .answerability import assess_answerability
from .build_status import build_context_unknowns, index_freshness_unknowns
from .constraints import constraints_from_unknowns
from .semantic_status import semantic_unknowns
from .quality_gate import build_support_profile, quality_unknowns
from .answer_constraints import answer_constraints_from_facts
from repoanalyzer.query._store import open_store
from repoanalyzer.query._active import active_fact_where
from repoanalyzer.query._semantic import name_matches

_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*")
_STOP_WORDS = {"where", "call", "called", "from", "function", "path", "どこ", "呼ばれる", "到達", "最終的"}


def _guess_symbol(question: str, *, prefer_last: bool = False) -> str | None:
    candidates = [m.group(0) for m in _IDENTIFIER_RE.finditer(question)]
    candidates = [c for c in candidates if c not in _STOP_WORDS]
    if not candidates:
        return None
    return candidates[-1] if prefer_last else candidates[0]


def _intent(question: str) -> str:
    q = question.lower()
    if ((("resource" in q or "accelerator" in q or "toolbar" in q or "menu" in q)
         and ("command" in q or "id" in q or "binding" in q or "対応" in question or "つなが" in question))
        or (("リソース" in question or "アクセラレータ" in question or "ツールバー" in question or "メニュー" in question)
            and ("command" in q or "コマンド" in question or "対応" in question or "id" in q or "ID" in question))):
        return "ui_resource_command_binding"
    if ((("plugin" in q or "macro" in q or "external" in q or "extension" in q)
         and ("execute" in q or "execution" in q or "path" in q or "route" in q or "command" in q))
        or (("プラグイン" in question or "マクロ" in question or "外部コマンド" in question or "外部" in question)
            and ("実行" in question or "経路" in question or "どう" in question or "command" in q or "コマンド" in question))):
        return "extension_execution"
    if (("windows" in q and ("message" in q or "dialog" in q or "callback" in q))
        or "wm_command" in q or "wm_initdialog" in q or "dlgproc" in q or "dialog callback" in q
        or ("メッセージ" in question and ("dialog" in q or "ダイアログ" in question or "callback" in q or "コールバック" in question))
        or ("ダイアログ" in question and ("コールバック" in question or "メッセージ" in question or "どう" in question))):
        return "windows_message_dialog"
    if (("設定" in question and ("読み" in question or "書" in question or "保存" in question or "ロード" in question or "どう" in question))
        or "csharedata" in q or "commonsetting" in q or "profile" in q or "ini" in q):
        return "config_profile_io"
    if (("ファイル" in question and ("読み" in question or "ロード" in question or "開" in question or "どう" in question))
        or "文字コード" in question or "encoding" in q or "file loading" in q or "character encoding" in q):
        return "file_loading_encoding"
    if (("undo" in q or "redo" in q or "アンドゥ" in question or "リドゥ" in question or "元に戻" in question or "やり直" in question)
        and ("編集" in question or "edit" in q or "operation" in q or "追跡" in question or "どう" in question)):
        return "undo_edit_execution"
    if ("検索" in question and ("実行" in question or "どう" in question)) or "how is search executed" in q:
        return "search_execution"
    if "到達" in question or "path" in q or "call path" in q or "最終的" in question:
        return "call_path"
    if "呼ばれる" in question or "caller" in q or "called from" in q:
        return "callers"
    if "呼ぶ" in question or "callee" in q or "calls" in q:
        return "callees"
    if "定義" in question or "definition" in q:
        return "definition"
    return "evidence"


def _all_calls(repo: str | Path) -> list[CodeFact]:
    return open_store(repo).query_facts(active_fact_where("fact_type='call'"))


def _shortest_call_path(repo: str | Path, start: str, goal: str) -> list[str] | None:
    edges = _all_calls(repo)
    graph: dict[str, set[str]] = defaultdict(set)
    aliases: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not edge.caller or not edge.callee:
            continue
        caller_names = {edge.caller}
        callee_names = {edge.callee}
        if edge.payload.get("caller_qualified_name"):
            caller_names.add(edge.payload["caller_qualified_name"])
        if edge.payload.get("callee_qualified_name"):
            callee_names.add(edge.payload["callee_qualified_name"])
        for name in caller_names:
            aliases[_short_name(name)].add(name)
        for name in callee_names:
            aliases[_short_name(name)].add(name)
        for caller in caller_names:
            for callee in callee_names:
                graph[caller].add(callee)
    starts = aliases.get(start, {start})
    goals = aliases.get(goal, {goal})
    queue: deque[list[str]] = deque([[candidate] for candidate in sorted(starts)])
    seen = set(starts)
    while queue:
        route = queue.popleft()
        node = route[-1]
        if node in goals:
            return route
        for nxt in sorted(graph.get(node, [])):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(route + [nxt])
    return None


def _call_path_facts(repo: str | Path, route: list[str]) -> list[CodeFact]:
    if len(route) < 2:
        return []
    calls = _all_calls(repo)
    facts: list[CodeFact] = []
    for caller, callee in zip(route, route[1:]):
        for fact in calls:
            if _edge_has_endpoint(fact, caller, "caller") and _edge_has_endpoint(fact, callee, "callee"):
                facts.append(fact)
                break
    if facts:
        first = facts[0]
        facts.append(
            CodeFact(
                fact_type="call_path",
                path=first.path,
                start_line=first.start_line,
                end_line=facts[-1].end_line,
                subject=route[0],
                predicate="reaches",
                object=route[-1],
                route=route,
                confidence="medium",
                source="call_graph_bfs",
                payload={
                    "route_qualified": [_qualified_node_for_route_step(step, facts) for step in route],
                    "edge_statuses": [fact.payload.get("resolution_status", "unknown") for fact in facts],
                    "ambiguous_edges": [f"{fact.caller}->{fact.callee}" for fact in facts if fact.payload.get("resolution_status") in {"ambiguous", "candidate_set"}],
                },
            )
        )
    return facts



def _edge_has_endpoint(fact: CodeFact, value: str, endpoint: str) -> bool:
    if endpoint == "caller":
        values = [fact.caller, fact.payload.get("caller_qualified_name"), fact.subject]
    else:
        values = [fact.callee, fact.payload.get("callee_qualified_name"), fact.object]
        values.extend(fact.payload.get("candidate_qualified_names") or [])
    return any(v == value for v in values if isinstance(v, str))


def _short_name(name: str) -> str:
    return name.split("::")[-1]


def _qualified_node_for_route_step(step: str, facts: list[CodeFact]) -> str:
    for fact in facts:
        if fact.caller == step and fact.payload.get("caller_qualified_name"):
            return str(fact.payload["caller_qualified_name"])
        if fact.callee == step and fact.payload.get("callee_qualified_name"):
            return str(fact.payload["callee_qualified_name"])
    return step



def _command_dispatch_facts(repo: str | Path, command_id: str) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation' AND predicate='dispatches_to'"))
    return [fact for fact in relations if fact.subject == command_id or fact.payload.get("command_id") == command_id]


def _search_execution_facts(repo: str | Path) -> list[CodeFact]:
    """Build a deterministic evidence trace for "検索はどう実行される？".

    The trace is still evidence, not prose: command-dispatch relation(s), the
    function call path from the selected handler to the search core, and branch
    calls from CSearchAgent::SearchWord to concrete search implementations.
    """
    facts: list[CodeFact] = []
    command_ids = ["F_SEARCH_NEXT", "F_SEARCH_PREV", "F_SEARCH_DIALOG"]
    targets = [
        "CSearchAgent::SearchString",
        "sakura::CSearchAgent::SearchString",
        "CSearchAgent::SearchWord",
        "sakura::CSearchAgent::SearchWord",
    ]
    selected_dispatch: CodeFact | None = None
    route: list[str] | None = None
    selected_target: str | None = None

    for command_id in command_ids:
        for dispatch in _command_dispatch_facts(repo, command_id):
            handler = str(dispatch.payload.get("handler_qualified_name") or dispatch.object or "")
            if not handler:
                continue
            for target in targets:
                route = _shortest_call_path(repo, handler, target)
                if route:
                    selected_dispatch = dispatch
                    selected_target = target
                    break
            if route:
                break
        if route:
            break

    if selected_dispatch:
        facts.append(selected_dispatch)
    if route:
        facts.extend(_call_path_facts(repo, route))
        command_id = str(selected_dispatch.payload.get("command_id") or selected_dispatch.subject) if selected_dispatch else "F_SEARCH_NEXT"
        overall_route = [command_id] + list(route)
        first = facts[0]
        facts.append(
            CodeFact(
                fact_type="call_path",
                path=first.path,
                start_line=first.start_line,
                end_line=facts[-1].end_line if facts else first.end_line,
                subject=command_id,
                predicate="reaches",
                object=selected_target,
                route=overall_route,
                confidence="medium",
                source="command_dispatch_trace",
                payload={
                    "route_kind": "command_execution_trace",
                    "question_class": "search_execution",
                    "command_id": command_id,
                    "handler_qualified_name": route[0],
                    "target": selected_target,
                    "edge_statuses": ["conditional_dispatch"] + [fact.payload.get("resolution_status", "unknown") for fact in facts if fact.fact_type == "call"],
                },
            )
        )

    # Add concrete implementation branch facts so an LLM can say SearchWord can
    # reach normal string and word-only search paths without inventing them.
    for branch_target in ["CSearchAgent::SearchString", "sakura::CSearchAgent::SearchString", "CSearchAgent::SearchStringWord", "sakura::CSearchAgent::SearchStringWord"]:
        branch_facts = find_callers(repo, branch_target)
        for fact in branch_facts:
            if name_matches(fact.caller, "CSearchAgent::SearchWord") or name_matches(str(fact.payload.get("caller_qualified_name") or ""), "CSearchAgent::SearchWord"):
                facts.append(fact)
    # Stable order / de-duplication.
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique


_FILE_IO_RELATION_PREDICATES = {
    "opens_file",
    "reads_file_size",
    "maps_file_buffer",
    "detects_character_encoding",
    "uses_encoding_detector",
    "creates_encoding_converter",
    "determines_encoding_trait",
    "converts_file_to_internal_encoding",
    "reads_file_line",
    "scans_line_boundary",
    "configures_eol_detection",
    "closes_file",
    "checks_autodetect_requested",
    "stores_detected_encoding",
    "tracks_bom_status",
}


def _file_io_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _FILE_IO_RELATION_PREDICATES]


def _relation_for_subject(relations: list[CodeFact], subject: str, predicate: str | None = None, operation_kind: str | None = None) -> CodeFact | None:
    for fact in relations:
        if not name_matches(fact.subject, subject):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if operation_kind and fact.payload.get("operation_kind") != operation_kind:
            continue
        return fact
    return None


def _append_file_io_semantic_trace(
    facts: list[CodeFact],
    relations: list[CodeFact],
    *,
    subject: str,
    route_kind: str,
    question_class: str,
    steps: list[tuple[str, str | None]],
) -> None:
    route = [subject]
    selected: list[CodeFact] = []
    for predicate, operation_kind in steps:
        relation = _relation_for_subject(relations, subject, predicate, operation_kind)
        if not relation:
            continue
        selected.append(relation)
        if relation.object and relation.object not in route:
            route.append(str(relation.object))
    if not selected:
        return
    facts.extend(selected)
    first = selected[0]
    facts.append(
        CodeFact(
            fact_type="call_path",
            path=first.path,
            start_line=first.start_line,
            end_line=selected[-1].end_line,
            subject=subject,
            predicate="reaches",
            object=route[-1],
            route=route,
            confidence="medium",
            source="file_io_encoding_trace",
            payload={
                "route_kind": route_kind,
                "question_class": question_class,
                "edge_statuses": [relation.payload.get("edge_status", "semantic_file_io_relation") for relation in selected],
                "semantic_relations": [relation.predicate for relation in selected],
            },
        )
    )


def _file_loading_encoding_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for Sakura-style file loading and encoding detection."""
    facts: list[CodeFact] = []
    relations = _file_io_relations(repo)
    question_class = "file_loading_encoding"
    _append_file_io_semantic_trace(
        facts,
        relations,
        subject="sakura::CFileLoad::FileOpen",
        route_kind="file_open_encoding_trace",
        question_class=question_class,
        steps=[
            ("opens_file", "win32_create_file"),
            ("reads_file_size", "win32_get_file_size"),
            ("maps_file_buffer", "create_file_mapping"),
            ("maps_file_buffer", "map_view_of_file"),
            ("checks_autodetect_requested", "autodetect_branch"),
            ("detects_character_encoding", "detect_encoding_from_buffer"),
            ("stores_detected_encoding", "store_detected_encoding"),
            ("creates_encoding_converter", "create_code_base"),
            ("determines_encoding_trait", "encoding_trait_lookup"),
            ("tracks_bom_status", "bom_detected"),
            ("configures_eol_detection", "configure_encoded_eol"),
        ],
    )
    _append_file_io_semantic_trace(
        facts,
        relations,
        subject="sakura::CFileLoad::ReadLine_core",
        route_kind="line_read_conversion_trace",
        question_class=question_class,
        steps=[
            ("scans_line_boundary", "scan_line_boundary_by_encoding"),
            ("converts_file_to_internal_encoding", "file_to_internal_conversion"),
        ],
    )
    _append_file_io_semantic_trace(
        facts,
        relations,
        subject="sakura::CCodeMediator::CheckKanjiCode",
        route_kind="encoding_detector_trace",
        question_class=question_class,
        steps=[
            ("uses_encoding_detector", "charset_detector"),
            ("detects_character_encoding", "detect_encoding_from_buffer"),
        ],
    )
    # Preserve useful file-level detection fallback if present.
    for relation in relations:
        if name_matches(relation.subject, "sakura::CCodeMediator::CheckKanjiCodeOfFile"):
            facts.append(relation)
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique


_EDIT_RELATION_PREDICATES = {
    "performs_edit_operation",
    "updates_document_modified_state",
    "updates_undo_buffer",
    "consumes_undo_history",
    "consumes_redo_history",
    "iterates_operation_block",
    "inspects_operation_block",
    "uses_undo_operation_block",
    "creates_undo_operation_block",
    "marks_undo_redo_execution",
}


def _edit_operation_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _EDIT_RELATION_PREDICATES]


def _first_relation_for_subject(relations: list[CodeFact], subject: str, predicate: str | None = None, operation_kind: str | None = None) -> CodeFact | None:
    for fact in relations:
        if not name_matches(fact.subject, subject):
            continue
        if predicate and fact.predicate != predicate:
            continue
        if operation_kind and fact.payload.get("operation_kind") != operation_kind:
            continue
        return fact
    return None


def _append_dispatch_trace(facts: list[CodeFact], repo: str | Path, command_id: str, target: str, *, route_kind: str, question_class: str, relations: list[CodeFact]) -> None:
    for dispatch in _command_dispatch_facts(repo, command_id):
        handler = str(dispatch.payload.get("handler_qualified_name") or dispatch.object or "")
        if not handler:
            continue
        route = _shortest_call_path(repo, handler, target)
        if not route:
            continue
        facts.append(dispatch)
        facts.extend(_call_path_facts(repo, route))
        first = facts[-1] if facts else dispatch
        facts.append(
            CodeFact(
                fact_type="call_path",
                path=dispatch.path,
                start_line=dispatch.start_line,
                end_line=first.end_line,
                subject=command_id,
                predicate="reaches",
                object=target,
                route=[command_id] + route,
                confidence="medium",
                source="edit_operation_trace",
                payload={
                    "route_kind": route_kind,
                    "question_class": question_class,
                    "command_id": command_id,
                    "handler_qualified_name": handler,
                    "target": target,
                    "edge_statuses": ["conditional_dispatch"] + ["resolved_call"] * max(0, len(route) - 1),
                },
            )
        )
        for relation in relations:
            if name_matches(relation.subject, handler) or name_matches(str(relation.payload.get("caller_qualified_name") or ""), handler):
                facts.append(relation)
        return


def _append_undo_redo_semantic_trace(facts: list[CodeFact], repo: str | Path, command_id: str, *, question_class: str, relations: list[CodeFact]) -> None:
    history_predicate = "consumes_undo_history" if command_id == "F_UNDO" else "consumes_redo_history"
    route_kind = "undo_execution_trace" if command_id == "F_UNDO" else "redo_execution_trace"
    for dispatch in _command_dispatch_facts(repo, command_id):
        handler = str(dispatch.payload.get("handler_qualified_name") or dispatch.object or "")
        if not handler:
            continue
        history = _first_relation_for_subject(relations, handler, history_predicate)
        replay = _first_relation_for_subject(relations, handler, "performs_edit_operation", "replace_text")
        flag = _first_relation_for_subject(relations, handler, "marks_undo_redo_execution", "enter_undo_redo_execution")
        if not (history or replay or flag):
            continue
        facts.append(dispatch)
        for relation in [flag, history, replay]:
            if relation:
                facts.append(relation)
        route = [command_id, handler]
        if history:
            route.append(str(history.object))
        if replay:
            route.append(str(replay.object))
        facts.append(
            CodeFact(
                fact_type="call_path",
                path=dispatch.path,
                start_line=dispatch.start_line,
                end_line=(replay or history or flag or dispatch).end_line,
                subject=command_id,
                predicate="reaches",
                object=route[-1],
                route=route,
                confidence="medium",
                source="edit_operation_trace",
                payload={
                    "route_kind": route_kind,
                    "question_class": question_class,
                    "command_id": command_id,
                    "handler_qualified_name": handler,
                    "history_access": history.object if history else None,
                    "edit_replay": replay.object if replay else None,
                    "edge_statuses": ["conditional_dispatch", "semantic_undo_redo_relation", "semantic_edit_replay"],
                },
            )
        )
        return




_EXTENSION_EXECUTION_RELATION_PREDICATES = {
    "records_macro_command",
    "executes_macro",
    "loads_macro",
    "saves_macro",
    "creates_macro_manager",
    "maps_macro_function",
    "registers_plugin_hook",
    "unregisters_plugin_hook",
    "enumerates_plugin_hook",
    "invokes_plugin_hook",
    "maps_plugin_command_id",
    "launches_external_process",
}


def _extension_execution_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _EXTENSION_EXECUTION_RELATION_PREDICATES]


def _append_extension_trace(
    facts: list[CodeFact],
    relations: list[CodeFact],
    *,
    route_kind: str,
    subject_contains: str | None = None,
    predicates: list[str],
) -> None:
    selected: list[CodeFact] = []
    for predicate in predicates:
        candidates = [relation for relation in relations if relation.predicate == predicate]
        if subject_contains:
            candidates = [relation for relation in candidates if subject_contains in str(relation.subject)]
        if candidates:
            selected.append(candidates[0])
    if not selected:
        return
    facts.extend(selected)
    route = [str(selected[0].subject)]
    for relation in selected:
        obj = str(relation.object) if relation.object else ""
        if obj and obj not in route:
            route.append(obj)
    first = selected[0]
    facts.append(
        CodeFact(
            fact_type="call_path",
            path=first.path,
            start_line=first.start_line,
            end_line=selected[-1].end_line,
            subject=str(selected[0].subject),
            predicate="reaches",
            object=route[-1],
            route=route,
            confidence="medium",
            source="extension_execution_trace",
            payload={
                "route_kind": route_kind,
                "question_class": "extension_execution",
                "edge_statuses": [relation.payload.get("edge_status", "semantic_extension_execution_relation") for relation in selected],
                "semantic_relations": [relation.predicate for relation in selected],
            },
        )
    )


def _extension_execution_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for macro/plugin/external-command execution paths."""
    facts: list[CodeFact] = []
    relations = _extension_execution_relations(repo)

    _append_extension_trace(
        facts,
        relations,
        route_kind="macro_command_execution_trace",
        subject_contains="CViewCommander::HandleCommand",
        predicates=["records_macro_command", "executes_macro"],
    )
    _append_extension_trace(
        facts,
        relations,
        route_kind="macro_load_and_replay_trace",
        subject_contains="CSMacroMgr::Exec",
        predicates=["loads_macro", "executes_macro"],
    )
    for relation in relations:
        if relation.predicate == "maps_macro_function" and relation.subject in {"F_SEARCH_NEXT", "F_GREP", "F_FILEOPEN2"}:
            facts.append(relation)

    _append_extension_trace(
        facts,
        relations,
        route_kind="plugin_hook_registration_trace",
        subject_contains="CJackManager::RegisterPlug",
        predicates=["registers_plugin_hook", "maps_plugin_command_id"],
    )
    _append_extension_trace(
        facts,
        relations,
        route_kind="plugin_hook_invocation_trace",
        subject_contains="CJackManager::InvokePlugins",
        predicates=["enumerates_plugin_hook", "invokes_plugin_hook"],
    )
    _append_extension_trace(
        facts,
        relations,
        route_kind="plugin_command_execution_trace",
        subject_contains="CViewCommander::HandleCommand",
        predicates=["maps_plugin_command_id", "invokes_plugin_hook"],
    )
    _append_extension_trace(
        facts,
        relations,
        route_kind="external_command_launch_trace",
        subject_contains="CViewCommander::Command_EXECEXTCOMMAND",
        predicates=["launches_external_process"],
    )

    for relation in relations:
        if relation.predicate in {"creates_macro_manager", "saves_macro", "unregisters_plugin_hook"}:
            facts.append(relation)

    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique

_UI_RESOURCE_RELATION_PREDICATES = {
    "binds_menu_item_to_command",
    "binds_accelerator_to_command",
    "binds_toolbar_button_to_command",
    "creates_accelerator_table",
    "translates_accelerator_to_command",
    "looks_up_accelerator_command",
    "routes_resource_command_to_handler",
}


def _ui_resource_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _UI_RESOURCE_RELATION_PREDICATES]


def _relations_by_predicate_object(relations: list[CodeFact], predicate: str, obj: str) -> list[CodeFact]:
    return [fact for fact in relations if fact.predicate == predicate and fact.object == obj]


def _append_ui_resource_trace(
    facts: list[CodeFact],
    repo: str | Path,
    relations: list[CodeFact],
    *,
    command_id: str,
    binding_predicate: str,
    route_kind: str,
) -> None:
    bindings = _relations_by_predicate_object(relations, binding_predicate, command_id)
    if not bindings:
        return
    binding = bindings[0]
    facts.append(binding)
    for dispatch in _command_dispatch_facts(repo, command_id):
        handler = str(dispatch.payload.get("handler_qualified_name") or dispatch.object or "")
        if not handler:
            continue
        facts.append(dispatch)
        route = [str(binding.subject), command_id, handler]
        facts.append(
            CodeFact(
                fact_type="call_path",
                path=binding.path,
                start_line=binding.start_line,
                end_line=dispatch.end_line,
                subject=str(binding.subject),
                predicate="reaches",
                object=handler,
                route=route,
                confidence="medium",
                source="ui_resource_command_trace",
                payload={
                    "route_kind": route_kind,
                    "question_class": "ui_resource_command_binding",
                    "command_id": command_id,
                    "handler_qualified_name": handler,
                    "edge_statuses": [
                        binding.payload.get("edge_status", "semantic_ui_resource_relation"),
                        dispatch.payload.get("edge_status", "conditional_dispatch"),
                    ],
                    "semantic_relations": [binding.predicate, dispatch.predicate],
                },
            )
        )
        return


def _ui_resource_command_binding_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for resource/menu/accelerator/toolbar -> F_* command IDs."""
    facts: list[CodeFact] = []
    relations = _ui_resource_relations(repo)
    command_id = "F_SEARCH_NEXT"
    _append_ui_resource_trace(
        facts,
        repo,
        relations,
        command_id=command_id,
        binding_predicate="binds_menu_item_to_command",
        route_kind="menu_resource_to_command_trace",
    )
    _append_ui_resource_trace(
        facts,
        repo,
        relations,
        command_id=command_id,
        binding_predicate="binds_accelerator_to_command",
        route_kind="accelerator_to_command_trace",
    )
    _append_ui_resource_trace(
        facts,
        repo,
        relations,
        command_id=command_id,
        binding_predicate="binds_toolbar_button_to_command",
        route_kind="toolbar_to_command_trace",
    )
    # Runtime accelerator construction/translation relations qualify how static
    # accelerator bindings become command IDs at runtime.
    for relation in relations:
        if relation.predicate in {"creates_accelerator_table", "translates_accelerator_to_command", "looks_up_accelerator_command", "routes_resource_command_to_handler"}:
            facts.append(relation)
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique

_WINDOWS_MESSAGE_RELATION_PREDICATES = {
    "creates_dialog",
    "registers_dialog_callback",
    "handles_windows_message",
    "handles_control_command",
    "sends_windows_message",
    "posts_windows_message",
    "dispatches_windows_message",
    "translates_windows_message",
    "closes_dialog",
    "registers_window_subclass_callback",
    "removes_window_subclass_callback",
}


def _windows_message_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _WINDOWS_MESSAGE_RELATION_PREDICATES]


def _append_windows_message_trace(
    facts: list[CodeFact],
    relations: list[CodeFact],
    *,
    subject: str,
    route_kind: str,
    steps: list[tuple[str, str | None]],
) -> None:
    route = [subject]
    selected: list[CodeFact] = []
    for predicate, operation_kind in steps:
        relation = _relation_for_subject(relations, subject, predicate, operation_kind)
        if not relation:
            continue
        selected.append(relation)
        obj = str(relation.object) if relation.object else ""
        if obj and obj not in route:
            route.append(obj)
    if not selected:
        return
    facts.extend(selected)
    first = selected[0]
    facts.append(
        CodeFact(
            fact_type="call_path",
            path=first.path,
            start_line=first.start_line,
            end_line=selected[-1].end_line,
            subject=subject,
            predicate="reaches",
            object=route[-1],
            route=route,
            confidence="medium",
            source="windows_message_dialog_trace",
            payload={
                "route_kind": route_kind,
                "question_class": "windows_message_dialog",
                "edge_statuses": [relation.payload.get("edge_status", "semantic_windows_message_relation") for relation in selected],
                "semantic_relations": [relation.predicate for relation in selected],
            },
        )
    )


def _windows_message_dialog_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for Sakura-style Windows dialog/message callbacks."""
    facts: list[CodeFact] = []
    relations = _windows_message_relations(repo)
    _append_windows_message_trace(
        facts,
        relations,
        subject="sakura::CSearchDialog::OpenDialog",
        route_kind="dialog_creation_callback_trace",
        steps=[
            ("creates_dialog", "modal_dialog_create"),
            ("registers_dialog_callback", "register_dialog_proc"),
        ],
    )
    _append_windows_message_trace(
        facts,
        relations,
        subject="sakura::CSearchDialog::DlgProc",
        route_kind="dialog_message_dispatch_trace",
        steps=[
            ("handles_windows_message", "handle_wm_initdialog"),
            ("handles_windows_message", "handle_wm_command"),
            ("handles_control_command", "handle_control_idc_button_find"),
        ],
    )
    _append_windows_message_trace(
        facts,
        relations,
        subject="sakura::CSearchDialog::OnFindNext",
        route_kind="wm_command_bridge_trace",
        steps=[
            ("sends_windows_message", "send_command_message"),
        ],
    )
    _append_windows_message_trace(
        facts,
        relations,
        subject="sakura::CPropTypesColor::InitColorList",
        route_kind="subclass_callback_registration_trace",
        steps=[
            ("registers_window_subclass_callback", "set_window_subclass_callback"),
        ],
    )
    # Keep close/message-loop relations so downstream answers can mention cleanup.
    for relation in relations:
        if relation.predicate in {"closes_dialog", "posts_windows_message", "dispatches_windows_message", "translates_windows_message"}:
            facts.append(relation)
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique

_CONFIG_PROFILE_RELATION_PREDICATES = {
    "loads_shared_settings",
    "saves_shared_settings",
    "runs_profile_io",
    "resolves_ini_path",
    "selects_profile_mode",
    "reads_profile",
    "writes_profile",
    "maps_profile_key",
    "checks_profile_mode",
    "accesses_shared_data",
    "refreshes_shared_strings",
    "applies_language_setting",
    "backs_up_ini_file",
    "loads_config_section",
    "saves_config_section",
    "accesses_common_setting",
}


def _config_profile_relations(repo: str | Path) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    return [fact for fact in relations if fact.predicate in _CONFIG_PROFILE_RELATION_PREDICATES]


def _append_config_profile_trace(
    facts: list[CodeFact],
    relations: list[CodeFact],
    *,
    subject: str,
    route_kind: str,
    steps: list[tuple[str, str | None]],
) -> None:
    route = [subject]
    selected: list[CodeFact] = []
    for predicate, operation_kind in steps:
        relation = _relation_for_subject(relations, subject, predicate, operation_kind)
        if not relation:
            continue
        selected.append(relation)
        if relation.object and relation.object not in route:
            route.append(str(relation.object))
    if not selected:
        return
    facts.extend(selected)
    first = selected[0]
    facts.append(
        CodeFact(
            fact_type="call_path",
            path=first.path,
            start_line=first.start_line,
            end_line=selected[-1].end_line,
            subject=subject,
            predicate="reaches",
            object=route[-1],
            route=route,
            confidence="medium",
            source="config_profile_io_trace",
            payload={
                "route_kind": route_kind,
                "question_class": "config_profile_io",
                "edge_statuses": [relation.payload.get("edge_status", "semantic_config_profile_relation") for relation in selected],
                "semantic_relations": [relation.predicate for relation in selected],
            },
        )
    )


def _config_profile_io_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for Sakura-style CShareData/profile/INI I/O."""
    facts: list[CodeFact] = []
    relations = _config_profile_relations(repo)
    _append_config_profile_trace(
        facts,
        relations,
        subject="sakura::CShareData_IO::LoadShareData",
        route_kind="load_share_data_trace",
        steps=[
            ("runs_profile_io", "shared_settings_io_core"),
        ],
    )
    _append_config_profile_trace(
        facts,
        relations,
        subject="sakura::CShareData_IO::SaveShareData",
        route_kind="save_share_data_trace",
        steps=[
            ("runs_profile_io", "shared_settings_io_core"),
        ],
    )
    _append_config_profile_trace(
        facts,
        relations,
        subject="sakura::CShareData_IO::ShareData_IO_2",
        route_kind="profile_core_io_trace",
        steps=[
            ("accesses_shared_data", "get_dll_share_data"),
            ("selects_profile_mode", "profile_reading_mode"),
            ("selects_profile_mode", "profile_writing_mode"),
            ("resolves_ini_path", "select_ini_path"),
            ("reads_profile", "read_ini_profile"),
            ("maps_profile_key", "read_or_write_profile_key"),
            ("loads_config_section", "ShareData_IO_Common"),
            ("writes_profile", "write_ini_profile"),
        ],
    )
    _append_config_profile_trace(
        facts,
        relations,
        subject="sakura::CShareData_IO::ShareData_IO_Mru",
        route_kind="mru_section_profile_mapping_trace",
        steps=[
            ("accesses_shared_data", "get_dll_share_data"),
            ("maps_profile_key", "read_or_write_profile_key"),
            ("checks_profile_mode", "is_reading_mode"),
        ],
    )
    # Keep language/common-setting side relations so LLMs can qualify shared setting effects.
    for relation in relations:
        if relation.predicate in {"accesses_common_setting", "applies_language_setting", "refreshes_shared_strings", "backs_up_ini_file"}:
            facts.append(relation)
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique


def _undo_edit_execution_facts(repo: str | Path) -> list[CodeFact]:
    """Build deterministic evidence for Undo/Redo and edit-operation tracking."""
    facts: list[CodeFact] = []
    relations = _edit_operation_relations(repo)
    _append_dispatch_trace(
        facts,
        repo,
        "F_WCHAR",
        "sakura::CEditView::InsertData_CEditView",
        route_kind="edit_command_trace",
        question_class="undo_edit_execution",
        relations=relations,
    )
    _append_undo_redo_semantic_trace(facts, repo, "F_UNDO", question_class="undo_edit_execution", relations=relations)
    _append_undo_redo_semantic_trace(facts, repo, "F_REDO", question_class="undo_edit_execution", relations=relations)
    # Stable order / de-duplication.
    seen: set[tuple] = set()
    unique: list[CodeFact] = []
    for fact in facts:
        key = (fact.fact_type, fact.path, fact.start_line, fact.subject, fact.predicate, fact.object, tuple(fact.route))
        if key in seen:
            continue
        seen.add(key)
        unique.append(fact)
    return unique


def _semantic_relations_for_symbol(repo: str | Path, symbol: str) -> list[CodeFact]:
    store = open_store(repo)
    relations = store.query_facts(active_fact_where("fact_type='relation'"))
    matched: list[CodeFact] = []
    for fact in relations:
        payload_names = [
            fact.payload.get("callback_symbol"),
            fact.payload.get("callback_qualified_name"),
            fact.payload.get("api_name"),
        ]
        payload_names.extend(fact.payload.get("candidate_qualified_names") or [])
        payload_names.extend(fact.payload.get("global_candidate_qualified_names") or [])
        if name_matches(fact.object, symbol) or name_matches(fact.subject, symbol) or any(name_matches(str(name) if name else None, symbol) for name in payload_names):
            matched.append(fact)
    return matched



def _inactive_definition_facts(repo: str | Path, symbol: str) -> list[CodeFact]:
    store = open_store(repo)
    if not _has_explicit_target_profile(store):
        return []
    facts = store.query_facts("fact_type='symbol' AND json_extract(payload_json, '$.declaration_or_definition')='definition'")
    return [
        fact for fact in facts
        if str(fact.payload.get("build_status") or "active") == "inactive"
        and name_matches(fact.symbol, symbol, qualified=fact.qualified_name, subject=fact.subject)
    ]

def _has_explicit_target_profile(store) -> bool:
    facts = store.query_facts("fact_type='target_profile' AND predicate='selected_profile'")
    for fact in facts:
        name = str(fact.subject or fact.payload.get("target_profile_name") or "").strip()
        if name and name != "default":
            return True
    return False


def collect_evidence(repo: str | Path, question: str, *, mode: str | None = None) -> EvidenceBundle:
    interpreted = mode or _intent(question)
    facts: list[CodeFact] = []
    unknowns: list[UnknownFact] = []

    if interpreted == "search_execution":
        facts.extend(_search_execution_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No search execution trace was found from command dispatch to search core."))

    elif interpreted == "extension_execution":
        facts.extend(_extension_execution_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No plugin/macro/external-command execution trace was found in the current index."))

    elif interpreted == "ui_resource_command_binding":
        facts.extend(_ui_resource_command_binding_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No UI resource/menu/accelerator/toolbar command binding trace was found in the current index."))

    elif interpreted == "windows_message_dialog":
        facts.extend(_windows_message_dialog_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No Windows message/dialog callback trace was found in the current index."))

    elif interpreted == "config_profile_io":
        facts.extend(_config_profile_io_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No settings/profile/INI trace was found in the current index."))

    elif interpreted == "file_loading_encoding":
        facts.extend(_file_loading_encoding_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No file loading / encoding-detection trace was found in the current index."))

    elif interpreted == "undo_edit_execution":
        facts.extend(_undo_edit_execution_facts(repo))
        if not facts:
            unknowns.append(call_graph_incomplete("No Undo/Redo edit-operation trace was found from command dispatch to edit/undo semantics."))

    elif interpreted == "callers":
        symbol = _guess_symbol(question)
        if symbol:
            facts.extend(find_callers(repo, symbol))
            facts.extend(_semantic_relations_for_symbol(repo, symbol))
            if not facts:
                unknowns.append(call_graph_incomplete(f"No callers found for '{symbol}' in the current index."))
        else:
            unknowns.append(UnknownFact("ambiguous_symbol", "Could not identify the target symbol from the question."))

    elif interpreted == "callees":
        symbol = _guess_symbol(question)
        if symbol:
            facts.extend(find_callees(repo, symbol))
            if not facts:
                unknowns.append(call_graph_incomplete(f"No callees found for '{symbol}' in the current index."))
        else:
            unknowns.append(UnknownFact("ambiguous_symbol", "Could not identify the target symbol from the question."))

    elif interpreted == "definition":
        symbol = _guess_symbol(question)
        if symbol:
            facts.extend(find_definitions(repo, symbol))
            if not facts:
                inactive = _inactive_definition_facts(repo, symbol)
                if inactive:
                    facts.extend(inactive)
                    unknowns.append(UnknownFact("inactive_build_evidence", f"Only inactive target-build definition evidence was found for '{symbol}'."))
                else:
                    unknowns.append(definition_not_found(symbol))
        else:
            unknowns.append(UnknownFact("ambiguous_symbol", "Could not identify the target symbol from the question."))

    elif interpreted == "call_path":
        identifiers = [m.group(0) for m in _IDENTIFIER_RE.finditer(question)]
        identifiers = [identifier for identifier in identifiers if identifier not in _STOP_WORDS]
        if len(identifiers) >= 2:
            start, goal = identifiers[0], identifiers[-1]
            route = _shortest_call_path(repo, start, goal)
            if route:
                facts.extend(_call_path_facts(repo, route))
            else:
                unknowns.append(call_graph_incomplete(f"No call path found from '{start}' to '{goal}' in the current index."))
        else:
            unknowns.append(UnknownFact("ambiguous_symbol", "Could not identify call path endpoints from the question."))

    else:
        # Minimal MVP: return definitions for the first symbol if one is present.
        symbol = _guess_symbol(question)
        if symbol:
            facts.extend(find_definitions(repo, symbol))
            facts.extend(find_callers(repo, symbol))
        if not facts:
            unknowns.append(UnknownFact("low_confidence_retrieval", "No relevant facts found for the current MVP query."))

    unknowns.extend(build_context_unknowns(facts))
    unknowns.extend(index_freshness_unknowns(repo))
    unknowns.extend(semantic_unknowns(facts))
    profile = build_support_profile(repo, facts, unknowns)
    unknowns.extend(quality_unknowns(profile, unknowns, facts))
    answer_summary = answer_constraints_from_facts(facts)
    response_constraints = constraints_from_unknowns(unknowns)
    response_constraints.extend(profile.response_constraints)
    response_constraints.extend(answer_summary.response_constraints)

    return EvidenceBundle(
        question=question,
        interpreted_intent=interpreted,
        answerability=assess_answerability(facts, unknowns),
        facts=facts,
        unknowns=unknowns,
        response_constraints=_dedupe(response_constraints),
        support_level=profile.support_level,
        unknown_reasons=profile.unknown_reasons,
        quality_profile=profile,
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
