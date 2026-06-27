from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from repoanalyzer.core.models import CodeFact
from repoanalyzer.core.source_kinds import CPP_SOURCE_EXTENSIONS


@dataclass(frozen=True)
class GlobalSymbol:
    symbol: str
    qualified_name: str
    signature: str
    argument_count: int
    symbol_id: str | None
    path: str
    start_line: int
    end_line: int
    kind: str | None
    namespace: str | None
    owner_type: str | None
    declaration_or_definition: str
    build_status: str
    return_type: str | None = None

    @property
    def display_name(self) -> str:
        return self.qualified_name or self.symbol


@dataclass(frozen=True)
class TypeField:
    owner_type: str
    name: str
    type_name: str
    is_pointer: bool
    path: str
    start_line: int

_EDIT_OPERATION_RELATION_PREDICATES = {
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

_FILE_IO_ENCODING_RELATION_PREDICATES = {
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

_SEMANTIC_OPERATION_RELATION_PREDICATES = (
    _EDIT_OPERATION_RELATION_PREDICATES
    | _FILE_IO_ENCODING_RELATION_PREDICATES
    | _CONFIG_PROFILE_RELATION_PREDICATES
)


def apply_cross_tu_resolution(facts: list[CodeFact]) -> list[CodeFact]:
    """Resolve lightweight semantic call facts against a repo-wide symbol table.

    This is deliberately conservative: direct/member/static/constructor calls may be
    upgraded from unresolved/ambiguous to resolved when the global active symbol table
    selects one definition. Indirect, callback, and virtual candidate facts stay as
    candidate relations rather than becoming guaranteed direct calls.
    """
    table = GlobalSymbolTable.from_facts(facts)
    resolved: list[CodeFact] = []
    for fact in facts:
        if fact.fact_type == "call" and fact.source == "semantic_cpp_lightweight":
            resolved.append(_resolve_call_fact(fact, table))
        elif fact.fact_type == "reference" and fact.payload.get("reference_kind") == "call" and fact.source == "semantic_cpp_lightweight":
            resolved.append(_resolve_reference_fact(fact, table))
        elif fact.fact_type == "relation" and fact.predicate in {"registers_callback", "callback_candidate"} and fact.source == "semantic_cpp_lightweight":
            resolved.append(_resolve_callback_relation_fact(fact, table))
        elif fact.fact_type == "relation" and fact.predicate == "dispatches_to" and fact.source == "semantic_cpp_lightweight":
            resolved.append(_resolve_command_dispatch_relation_fact(fact, table))
        elif fact.fact_type == "relation" and fact.predicate in _SEMANTIC_OPERATION_RELATION_PREDICATES and fact.source == "semantic_cpp_lightweight":
            resolved.append(_resolve_semantic_operation_relation_fact(fact, table))
        else:
            resolved.append(fact)
    resolved.extend(_symbol_table_relation_facts(table))
    resolved.extend(_tinyusb_callback_override_facts(resolved))
    return resolved



def _tinyusb_callback_override_facts(facts: list[CodeFact]) -> list[CodeFact]:
    """Add cross-translation-unit TinyUSB weak override evidence.

    Per-file analysis can identify weak defaults and strong application callback
    definitions, but link-time override semantics require a repo-wide view.
    Create an explicit semantic fact when an active strong ``tud_*_cb`` /
    ``tuh_*_cb`` definition has the same callback name as an active
    ``TU_ATTR_WEAK`` default.
    """
    callback_facts = [
        fact for fact in facts
        if fact.fact_type == "tinyusb_callback" and fact.payload.get("build_status") != "inactive"
    ]
    weak_by_name: dict[str, list[CodeFact]] = {}
    strong_by_name: dict[str, list[CodeFact]] = {}
    for fact in callback_facts:
        name = str(fact.payload.get("callback_name") or fact.subject or "").strip()
        if not name:
            continue
        if fact.payload.get("linkage") == "weak" or fact.predicate == "declares_weak_callback_default":
            weak_by_name.setdefault(name, []).append(fact)
        elif fact.payload.get("linkage") == "strong" or fact.predicate == "declares_tinyusb_callback_implementation":
            strong_by_name.setdefault(name, []).append(fact)

    override_facts: list[CodeFact] = []
    seen: set[tuple[str, str, int, str, int]] = set()
    for name, weak_defs in sorted(weak_by_name.items()):
        strong_defs = strong_by_name.get(name, [])
        for weak in weak_defs:
            for strong in strong_defs:
                if weak.path == strong.path and weak.start_line == strong.start_line:
                    continue
                key = (name, weak.path, weak.start_line, strong.path, strong.start_line)
                if key in seen:
                    continue
                seen.add(key)
                family = str(strong.payload.get("callback_family") or weak.payload.get("callback_family") or "tinyusb")
                role = str(strong.payload.get("callback_role") or weak.payload.get("callback_role") or name)
                payload = {
                    "relation_kind": "tinyusb_callback_override",
                    "callback_name": name,
                    "callback_family": family,
                    "callback_role": role,
                    "callback_requirement": strong.payload.get("callback_requirement") or weak.payload.get("callback_requirement"),
                    "override_status": "overridden_by_application",
                    "weak_default_available": True,
                    "application_override": True,
                    "weak_definition_path": weak.path,
                    "weak_definition_line": weak.start_line,
                    "weak_definition_symbol_id": weak.payload.get("symbol_id"),
                    "application_definition_path": strong.path,
                    "application_definition_line": strong.start_line,
                    "application_definition_symbol_id": strong.payload.get("symbol_id"),
                    "candidate_qualified_names": [
                        value for value in [
                            weak.payload.get("callback_qualified_name"),
                            strong.payload.get("callback_qualified_name"),
                        ] if value
                    ],
                    "semantic_phase": "phase7_tinyusb_weak_callback_semantics",
                    "resolution_status": "semantic_relation",
                    "build_status": "active",
                    "response_constraint": "TinyUSB weak override evidence is link-level callback binding; it does not prove that the callback is invoked on every runtime path.",
                }
                payload = {k: v for k, v in payload.items() if v not in (None, [], {})}
                override_facts.append(
                    CodeFact(
                        fact_type="tinyusb_callback",
                        path=strong.path,
                        start_line=strong.start_line,
                        end_line=strong.end_line,
                        subject=name,
                        predicate="overrides_weak_callback",
                        object=strong.payload.get("callback_qualified_name") or strong.subject or name,
                        confidence="high",
                        source="semantic_cpp_lightweight",
                        payload=payload,
                    )
                )
    return override_facts

class GlobalSymbolTable:
    def __init__(self, symbols: list[GlobalSymbol], type_aliases: dict[str, str], fields: list[TypeField] | None = None, type_names: set[str] | None = None) -> None:
        self.type_aliases = type_aliases
        self.symbols = symbols
        self.fields = fields or []
        self.type_names = type_names or set()
        self.by_qname: dict[str, list[GlobalSymbol]] = {}
        self.by_short: dict[str, list[GlobalSymbol]] = {}
        self.by_owner_member: dict[tuple[str, str], list[GlobalSymbol]] = {}
        self.by_type_field: dict[tuple[str, str], TypeField] = {}
        self.by_type_short: dict[str, set[str]] = {}
        self.qname_aliases: dict[str, str] = {}
        for type_name in self.type_names:
            self.by_type_short.setdefault(type_name.split("::")[-1], set()).add(type_name)
        for field in self.fields:
            owner = self.normalize_type(_strip_type_suffix(field.owner_type)) or _strip_type_suffix(field.owner_type) or field.owner_type
            self.by_type_field[(owner, field.name)] = field
        for symbol in symbols:
            self.by_qname.setdefault(symbol.qualified_name, []).append(symbol)
            self.by_short.setdefault(symbol.symbol, []).append(symbol)
            if symbol.owner_type:
                self.by_owner_member.setdefault((symbol.owner_type, symbol.symbol), []).append(symbol)

    @classmethod
    def from_facts(cls, facts: Iterable[CodeFact]) -> "GlobalSymbolTable":
        fact_list = list(facts)
        type_aliases = _unique_type_aliases(fact_list)
        symbols: list[GlobalSymbol] = []
        type_names: set[str] = set()
        for fact in fact_list:
            if fact.payload.get("build_status") == "inactive":
                continue
            if fact.fact_type == "type" and fact.kind in {"class", "struct"} and isinstance(fact.qualified_name, str):
                type_names.add(fact.qualified_name)
        aliases: dict[str, str] = {}
        seen: set[tuple[str, str, str, int]] = set()
        for fact in fact_list:
            if fact.fact_type != "symbol":
                continue
            if fact.payload.get("build_status") == "inactive":
                continue
            raw_qname = str(fact.qualified_name or fact.payload.get("qualified_name") or fact.symbol or "")
            if not raw_qname or not fact.symbol:
                continue
            payload = fact.payload
            qname, owner_type, namespace = _normalize_symbol_identity(
                raw_qname,
                payload.get("owner_type"),
                payload.get("namespace"),
                type_aliases,
            )
            if qname != raw_qname:
                aliases[raw_qname] = qname
            key = (str(qname), str(payload.get("signature", "")), fact.path, fact.start_line)
            if key in seen:
                continue
            seen.add(key)
            symbols.append(
                GlobalSymbol(
                    symbol=fact.symbol,
                    qualified_name=str(qname),
                    signature=str(payload.get("signature", "")),
                    argument_count=int(payload.get("argument_count", 0) or 0),
                    symbol_id=payload.get("symbol_id"),
                    path=fact.path,
                    start_line=fact.start_line,
                    end_line=fact.end_line,
                    kind=fact.kind,
                    namespace=namespace,
                    owner_type=owner_type,
                    declaration_or_definition=str(payload.get("declaration_or_definition", fact.predicate or "")),
                    build_status=str(payload.get("build_status", "active")),
                    return_type=str(payload.get("return_type")) if payload.get("return_type") else None,
                )
            )
        fields = _type_fields_from_facts(fact_list, type_aliases)
        table = cls(symbols, type_aliases, fields, type_names)
        table.qname_aliases = aliases
        return table

    def normalize_qname(self, qname: str | None) -> str | None:
        if not qname:
            return None
        if qname in self.qname_aliases:
            return self.qname_aliases[qname]
        if "::" in qname:
            head, tail = qname.split("::", 1)
            qualified_type = self.type_aliases.get(head)
            if qualified_type:
                return f"{qualified_type}::{tail}"
        return qname

    def candidates_for_call(self, fact: CodeFact) -> list[GlobalSymbol]:
        payload = fact.payload
        target = str(payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        normalized_target = self.normalize_qname(target) or target
        member_name = payload.get("member_name")
        receiver_type = _strip_type_suffix(payload.get("receiver_type"))
        receiver_type = self.normalize_type(receiver_type)
        if not receiver_type and member_name and payload.get("receiver_chain_steps"):
            receiver_type, _trace, _unresolved = self.resolve_receiver_chain_type(fact)
            receiver_type = self.normalize_type(_strip_type_suffix(receiver_type))
        if receiver_type and member_name:
            return self.by_owner_member.get((receiver_type, str(member_name)), [])
        if "::" in normalized_target:
            return self._qualified_candidates(normalized_target)
        caller_namespace = _caller_namespace(fact, self)
        candidates = list(self.by_short.get(normalized_target, []))
        if caller_namespace:
            ns_candidates = [c for c in candidates if c.namespace == caller_namespace or not c.namespace or c.qualified_name.startswith(caller_namespace + "::")]
            if ns_candidates:
                candidates = ns_candidates
        return candidates

    def normalize_type(self, type_name: str | None) -> str | None:
        if not type_name:
            return None
        return self.type_aliases.get(type_name, type_name)

    def field_for(self, owner_type: str | None, field_name: str) -> TypeField | None:
        owner = self.normalize_type(_strip_type_suffix(owner_type)) if owner_type else None
        if not owner:
            return None
        return self.by_type_field.get((owner, field_name))

    def return_type_for_call_root(self, name: str, args: list[str], caller_qname: str | None) -> str | None:
        caller_symbol = self.symbol_for_qname(caller_qname)
        candidates: list[GlobalSymbol] = []
        if "::" in name:
            candidates.extend(self._qualified_candidates(name))
        else:
            if caller_symbol and caller_symbol.owner_type:
                candidates.extend(self.by_owner_member.get((caller_symbol.owner_type, name), []))
            if caller_symbol and caller_symbol.namespace:
                candidates.extend([s for s in self.by_short.get(name, []) if s.namespace == caller_symbol.namespace or not s.namespace])
            candidates.extend(self.by_short.get(name, []))
        selected, _status, _unknown = _select_global_candidate(
            CodeFact(
                fact_type="call",
                path="",
                start_line=0,
                end_line=0,
                payload={"argument_count": len(args)},
            ),
            candidates,
        )
        if not selected or not selected.return_type:
            return None
        return self.normalize_type(selected.return_type) or selected.return_type

    def temporary_object_type_for_root(self, name: str, caller_qname: str | None) -> str | None:
        clean = name.strip()
        if not clean:
            return None
        normalized = self.normalize_type(clean)
        if normalized and _strip_type_suffix(normalized) in self.type_names:
            return normalized
        if clean in self.type_names:
            return clean
        caller_symbol = self.symbol_for_qname(caller_qname)
        if caller_symbol and caller_symbol.namespace:
            candidate = f"{caller_symbol.namespace}::{clean}"
            if candidate in self.type_names:
                return candidate
        matches = self.by_type_short.get(clean, set())
        if len(matches) == 1:
            return next(iter(matches))
        return None

    def return_type_for_member_step(self, owner_type: str | None, method: str, args: list[str]) -> tuple[str | None, GlobalSymbol | None, str]:
        owner = self.normalize_type(_strip_type_suffix(owner_type)) if owner_type else None
        if not owner:
            return None, None, "missing_owner_type"
        candidates = self.by_owner_member.get((owner, method), [])
        selected, status, _unknown = _select_global_candidate(
            CodeFact(
                fact_type="call",
                path="",
                start_line=0,
                end_line=0,
                payload={"argument_count": len(args)},
            ),
            list(candidates),
        )
        if not selected or not selected.return_type:
            return None, selected, status
        return self.normalize_type(selected.return_type) or selected.return_type, selected, status

    def resolve_receiver_chain_type(self, fact: CodeFact) -> tuple[str | None, list[dict], str | None]:
        payload = fact.payload
        steps = payload.get("receiver_chain_steps") or []
        if not isinstance(steps, list) or len(steps) < 1:
            return None, [], None
        trace: list[dict] = []
        root_name = str(payload.get("receiver_chain_root_name") or "")
        root_kind = str(payload.get("receiver_chain_root_kind") or "variable")
        current_type: str | None = _strip_type_suffix(payload.get("receiver_chain_root_type"))
        if root_kind == "function_return":
            if not current_type:
                current_type = self.return_type_for_call_root(root_name, list(payload.get("receiver_chain_root_args") or []), str(payload.get("caller_qualified_name") or ""))
            if current_type:
                trace.append({"kind": "function_return", "name": root_name, "type": current_type})
            else:
                current_type = self.temporary_object_type_for_root(root_name, str(payload.get("caller_qualified_name") or ""))
                trace.append({"kind": "temporary_object", "name": root_name, "type": current_type})
            if not current_type:
                return None, trace, root_name
        else:
            if not current_type:
                caller_symbol = self.symbol_for_qname(str(payload.get("caller_qualified_name") or ""))
                if caller_symbol and caller_symbol.owner_type:
                    field = self.field_for(caller_symbol.owner_type, root_name)
                    if field:
                        current_type = field.type_name + ("*" if field.is_pointer and not field.type_name.endswith("*") else "")
                        trace.append({"kind": "implicit_this_field", "name": root_name, "owner_type": caller_symbol.owner_type, "type": current_type})
            if not current_type:
                trace.append({"kind": "variable", "name": root_name, "type": None})
                return None, trace, root_name
        for step in steps[:-1]:
            if not isinstance(step, dict):
                continue
            name = str(step.get("name") or "")
            owner = self.normalize_type(_strip_type_suffix(current_type)) or _strip_type_suffix(current_type)
            if step.get("step_kind") == "method_return":
                return_type, selected, status = self.return_type_for_member_step(owner, name, list(step.get("args") or []))
                trace.append({
                    "kind": "method_return",
                    "op": step.get("op"),
                    "name": name,
                    "args": list(step.get("args") or []),
                    "owner_type": owner,
                    "type": return_type,
                    "resolution_status": status,
                    "callee_qualified_name": selected.qualified_name if selected else None,
                })
                if not return_type:
                    return None, trace, name
                current_type = return_type
                continue
            field = self.field_for(owner, name)
            trace.append({"kind": "field", "op": step.get("op"), "name": name, "owner_type": owner, "type": field.type_name if field else None, "is_pointer": field.is_pointer if field else False})
            if not field:
                return None, trace, name
            current_type = field.type_name + ("*" if field.is_pointer and not field.type_name.endswith("*") else "")
        return current_type, trace, None

    def _qualified_candidates(self, target: str) -> list[GlobalSymbol]:
        if target in self.by_qname:
            return list(self.by_qname[target])
        suffix = "::" + target
        return [s for s in self.symbols if s.qualified_name.endswith(suffix)]

    def symbol_for_qname(self, qname: str | None) -> GlobalSymbol | None:
        normalized = self.normalize_qname(qname)
        if not normalized:
            return None
        candidates = self.by_qname.get(normalized, [])
        defs = [c for c in candidates if c.declaration_or_definition == "definition"]
        return (defs or candidates or [None])[0]



def _type_fields_from_facts(facts: Iterable[CodeFact], type_aliases: dict[str, str]) -> list[TypeField]:
    fields: list[TypeField] = []
    seen: set[tuple[str, str, str]] = set()
    for fact in facts:
        if fact.payload.get("build_status") == "inactive":
            continue
        if fact.fact_type != "relation" or fact.predicate != "has_field":
            continue
        payload = fact.payload
        owner = payload.get("owner_type") or fact.subject
        field_name = payload.get("field_name") or fact.symbol
        field_type = payload.get("field_type") or fact.object
        if not isinstance(owner, str) or not isinstance(field_name, str) or not isinstance(field_type, str):
            continue
        owner_norm = type_aliases.get(_strip_type_suffix(owner) or owner, _strip_type_suffix(owner) or owner)
        field_type_norm = type_aliases.get(_strip_type_suffix(field_type) or field_type, _strip_type_suffix(field_type) or field_type)
        suffix = "*" if "*" in field_type else ""
        key = (owner_norm, field_name, field_type_norm + suffix)
        if key in seen:
            continue
        seen.add(key)
        fields.append(TypeField(owner_norm, field_name, field_type_norm + suffix, bool(payload.get("is_pointer")) or "*" in field_type, fact.path, fact.start_line))
    return fields


def _unique_type_aliases(facts: Iterable[CodeFact]) -> dict[str, str]:
    by_short: dict[str, set[str]] = {}
    aliases: dict[str, set[str]] = {}
    for fact in facts:
        if fact.payload.get("build_status") == "inactive":
            continue
        if fact.fact_type == "type" and fact.kind != "type_alias":
            if not fact.qualified_name or not fact.symbol:
                continue
            by_short.setdefault(fact.symbol, set()).add(fact.qualified_name)
        elif fact.fact_type == "type" and fact.kind == "type_alias":
            target = fact.payload.get("alias_target") or fact.object
            if not isinstance(target, str) or not target:
                continue
            names = [fact.symbol, fact.qualified_name]
            for name in names:
                if isinstance(name, str) and name:
                    aliases.setdefault(name, set()).add(target)
                    aliases.setdefault(name.split("::")[-1], set()).add(target)
    resolved: dict[str, str] = {short: next(iter(qnames)) for short, qnames in by_short.items() if len(qnames) == 1}
    for alias, targets in aliases.items():
        if len(targets) == 1:
            resolved[alias] = next(iter(targets))
    # Follow simple alias chains once the direct map has been built.
    for alias in list(resolved):
        resolved[alias] = _resolve_type_alias_target(resolved[alias], resolved)
    return resolved


def _resolve_type_alias_target(target: str, aliases: dict[str, str]) -> str:
    suffix = ""
    base = target.strip()
    while base.endswith("*") or base.endswith("&"):
        suffix = base[-1] + suffix
        base = base[:-1].strip()
    seen: set[str] = set()
    while base in aliases and base not in seen:
        seen.add(base)
        nxt = aliases[base].strip()
        extra = ""
        while nxt.endswith("*") or nxt.endswith("&"):
            extra = nxt[-1] + extra
            nxt = nxt[:-1].strip()
        base = nxt
        suffix = extra + suffix
    return base + suffix

def _normalize_symbol_identity(
    qname: str,
    owner_type: object,
    namespace: object,
    type_aliases: dict[str, str],
) -> tuple[str, str | None, str | None]:
    owner = str(owner_type) if owner_type else None
    ns = str(namespace) if namespace else None
    if owner:
        owner = type_aliases.get(owner, owner)
        short = qname.split("::")[-1]
        if owner and not qname.startswith(owner + "::"):
            qname = f"{owner}::{short}"
        if not ns and "::" in owner:
            ns = "::".join(owner.split("::")[:-1]) or None
        return qname, owner, ns
    if "::" in qname:
        head, tail = qname.split("::", 1)
        qualified_type = type_aliases.get(head)
        if qualified_type:
            owner = qualified_type
            qname = f"{qualified_type}::{tail}"
            ns = "::".join(qualified_type.split("::")[:-1]) or ns
    return qname, owner, ns

def _resolve_call_fact(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    normalized_caller = table.normalize_qname(str(payload.get("caller_qualified_name"))) if payload.get("caller_qualified_name") else None
    fact = _with_normalized_caller(fact, payload, normalized_caller)
    payload = dict(fact.payload)
    call_kind = fact.call_kind or ""
    if call_kind in {"function_pointer", "virtual_candidate"} or payload.get("resolution_status") == "candidate_set":
        return _enrich_candidate_set(fact, table)

    if not payload.get("receiver_type") and payload.get("receiver_chain_steps"):
        receiver_type, trace, unresolved_at = table.resolve_receiver_chain_type(fact)
        if receiver_type:
            payload["receiver_type"] = receiver_type
            payload["receiver_type_resolved"] = table.normalize_type(_strip_type_suffix(receiver_type)) or _strip_type_suffix(receiver_type)
            payload["receiver_chain_cross_tu"] = trace
            payload["resolution_basis"] = "receiver_chain_cross_tu"
            fact = replace(fact, payload=payload)
        elif trace:
            payload["receiver_chain_cross_tu"] = trace
            if unresolved_at:
                payload["receiver_chain_unresolved_at"] = unresolved_at
            fact = replace(fact, payload=payload)

    candidates = table.candidates_for_call(fact)
    selected, status, unknown = _select_global_candidate(fact, candidates)
    if not candidates:
        return fact

    original_status = payload.get("resolution_status")
    payload.setdefault("local_resolution_status", original_status or "unknown")
    payload["global_candidate_qualified_names"] = sorted({c.qualified_name for c in candidates})
    payload["global_candidate_symbol_ids"] = [c.symbol_id for c in candidates if c.symbol_id]

    if selected:
        receiver_type = _strip_type_suffix(payload.get("receiver_type"))
        normalized_receiver_type = table.normalize_type(receiver_type) if receiver_type else None
        if normalized_receiver_type:
            original_receiver_type = payload.get("receiver_type")
            suffix = "*" if isinstance(original_receiver_type, str) and "*" in str(original_receiver_type) else ""
            payload.setdefault("receiver_type_original", original_receiver_type)
            payload["receiver_type_resolved"] = normalized_receiver_type
            payload["receiver_type"] = normalized_receiver_type + suffix
        payload.update(
            {
                "resolution_status": "resolved",
                "resolution_scope": _resolution_scope(fact, selected),
                "callee_symbol_id": selected.symbol_id,
                "callee_qualified_name": selected.qualified_name,
                "callee_signature": selected.signature,
                "callee_definition_path": selected.path,
                "callee_definition_line": selected.start_line,
                "cross_tu": selected.path != fact.path,
            }
        )
        payload.pop("unknown_type", None)
        callee = selected.display_name if payload.get("member_name") else (fact.callee or selected.display_name)
        if fact.callee and "::" in str(fact.callee):
            callee = selected.display_name
        new_call_kind = fact.call_kind
        if fact.call_kind == "member_unresolved" and payload.get("member_name"):
            new_call_kind = "member_direct"
        return replace(fact, callee=callee, object=callee, call_kind=new_call_kind, confidence="high", payload=payload)

    payload.update({"resolution_status": "ambiguous", "resolution_scope": "global_symbol_table", "unknown_type": unknown or "ambiguous_symbol_resolution"})
    return replace(fact, confidence="medium", payload=payload)




def _resolve_callback_relation_fact(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    callback = payload.get("callback_symbol") or fact.object
    if not isinstance(callback, str) or not callback:
        return fact
    candidates = table._qualified_candidates(callback) or table.by_short.get(callback.split("::")[-1], [])
    candidates = _dedupe_symbols(candidates)
    if not candidates:
        return fact
    names = sorted({c.qualified_name for c in candidates})
    ids = sorted({c.symbol_id for c in candidates if c.symbol_id})
    payload["candidate_qualified_names"] = names
    payload["candidate_symbol_ids"] = ids
    payload["resolution_status"] = "candidate_set"
    payload["resolution_scope"] = "cross_translation_unit_callback_candidates" if any(c.path != fact.path for c in candidates) else "translation_unit_callback_candidates"
    payload["callback_resolution_status"] = "resolved_candidate" if len(candidates) == 1 else "candidate_set"
    if len(candidates) == 1:
        payload["callback_qualified_name"] = candidates[0].qualified_name
        payload["callback_symbol_id"] = candidates[0].symbol_id
        payload["callback_definition_path"] = candidates[0].path
        payload["callback_definition_line"] = candidates[0].start_line
    return replace(fact, object=callback, confidence="medium", payload=payload)



def _resolve_semantic_operation_relation_fact(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    subject = fact.subject
    normalized_subject = table.normalize_qname(str(subject)) if subject else None
    if normalized_subject:
        payload["caller_qualified_name"] = normalized_subject
        subject = normalized_subject

    callee = payload.get("callee_qualified_name") or payload.get("operation_callee") or fact.object
    obj = fact.object
    if isinstance(callee, str) and callee and callee not in {"COpeBlk", "m_bDoing_UndoRedo"}:
        symbol = table.symbol_for_qname(callee)
        normalized = table.normalize_qname(callee)
        if normalized and not symbol:
            symbol = table.symbol_for_qname(normalized)
        if not symbol:
            short = callee.split("::")[-1]
            candidates = _dedupe_symbols(table.by_short.get(short, []))
            if normalized_subject and "::" in normalized_subject:
                namespace = normalized_subject.rsplit("::", 2)[0]
                scoped = [c for c in candidates if c.qualified_name.startswith(namespace + "::")]
                if scoped:
                    candidates = scoped
            definitions = [c for c in candidates if c.declaration_or_definition == "definition"]
            if definitions:
                candidates = definitions
            if candidates:
                # Prefer a single stable candidate after namespace filtering.  If more than
                # one remains, use the first sorted qname but keep the relation semantic
                # rather than pretending this is a stronger call edge.
                symbol = sorted(candidates, key=lambda c: (c.qualified_name, c.path, c.start_line))[0]
        if symbol:
            payload["operation_callee"] = symbol.qualified_name
            payload["callee_qualified_name"] = symbol.qualified_name
            payload["callee_symbol_id"] = symbol.symbol_id
            payload["callee_definition_path"] = symbol.path
            payload["callee_definition_line"] = symbol.start_line
            payload["resolution_status"] = "resolved"
            payload["resolution_scope"] = str(payload.get("relation_kind") or "semantic_operation_relation")
            obj = symbol.qualified_name
        else:
            if normalized:
                payload["operation_callee"] = normalized
                payload["callee_qualified_name"] = normalized
                obj = normalized
            payload.setdefault("resolution_status", "unresolved")
    else:
        payload.setdefault("resolution_status", "semantic_relation")
    return replace(
        fact,
        subject=subject,
        object=obj,
        confidence="high" if payload.get("resolution_status") == "resolved" else fact.confidence,
        payload=payload,
    )

def _resolve_command_dispatch_relation_fact(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    handler = payload.get("handler_qualified_name") or fact.object
    dispatcher = payload.get("dispatcher_qualified_name")
    handler_symbol = table.symbol_for_qname(str(handler) if handler else None)
    dispatcher_symbol = table.symbol_for_qname(str(dispatcher) if dispatcher else None)
    if handler_symbol:
        payload["handler_qualified_name"] = handler_symbol.qualified_name
        payload["handler_symbol_id"] = handler_symbol.symbol_id
        payload["handler_definition_path"] = handler_symbol.path
        payload["handler_definition_line"] = handler_symbol.start_line
        payload["resolution_status"] = "resolved"
        obj = handler_symbol.qualified_name
    else:
        normalized_handler = table.normalize_qname(str(handler)) if handler else None
        if normalized_handler:
            payload["handler_qualified_name"] = normalized_handler
            obj = normalized_handler
        else:
            obj = fact.object
        payload.setdefault("resolution_status", "unresolved")
    if dispatcher_symbol:
        payload["dispatcher_qualified_name"] = dispatcher_symbol.qualified_name
        payload["dispatcher_symbol_id"] = dispatcher_symbol.symbol_id
    else:
        normalized_dispatcher = table.normalize_qname(str(dispatcher)) if dispatcher else None
        if normalized_dispatcher:
            payload["dispatcher_qualified_name"] = normalized_dispatcher
    payload.setdefault("resolution_scope", "command_dispatch_table")
    return replace(fact, object=obj, confidence="high" if handler_symbol else fact.confidence, payload=payload)

def _with_normalized_caller(fact: CodeFact, payload: dict, normalized_caller: str | None) -> CodeFact:
    if not normalized_caller or normalized_caller == payload.get("caller_qualified_name"):
        return fact
    payload = dict(payload)
    payload["caller_qualified_name"] = normalized_caller
    caller = fact.caller
    subject = fact.subject
    if caller and "::" in caller:
        caller = normalized_caller
    if subject and "::" in subject:
        subject = normalized_caller
    return replace(fact, caller=caller, subject=subject, payload=payload)

def _resolve_reference_fact(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    if payload.get("resolution_status") == "resolved" and payload.get("callee_symbol_id"):
        return fact
    # Reuse call-like fields from the duplicate call reference payload.
    pseudo = CodeFact(
        fact_type="call",
        path=fact.path,
        start_line=fact.start_line,
        end_line=fact.end_line,
        caller=str(fact.subject or ""),
        callee=str(fact.object or fact.symbol or ""),
        call_kind=str(payload.get("call_kind", "direct")),
        subject=fact.subject,
        predicate=fact.predicate,
        object=fact.object,
        payload=payload,
    )
    resolved = _resolve_call_fact(pseudo, table)
    if resolved.payload is payload or resolved.payload == payload:
        return fact
    new_payload = dict(resolved.payload)
    qname = new_payload.get("callee_qualified_name")
    return replace(fact, qualified_name=str(qname) if qname else fact.qualified_name, confidence=resolved.confidence, payload=new_payload)


def _enrich_candidate_set(fact: CodeFact, table: GlobalSymbolTable) -> CodeFact:
    payload = dict(fact.payload)
    candidate_names = list(payload.get("candidate_qualified_names") or [])
    candidate_ids = list(payload.get("candidate_symbol_ids") or [])
    enriched_names = set(candidate_names)
    enriched_ids = set(candidate_ids)
    for name in candidate_names:
        for candidate in table._qualified_candidates(str(name)) or table.by_short.get(str(name).split("::")[-1], []):
            enriched_names.add(candidate.qualified_name)
            if candidate.symbol_id:
                enriched_ids.add(candidate.symbol_id)
    if enriched_names != set(candidate_names) or enriched_ids != set(candidate_ids):
        payload["candidate_qualified_names"] = sorted(enriched_names)
        payload["candidate_symbol_ids"] = sorted(enriched_ids)
        payload["resolution_scope"] = "global_symbol_table_candidate_enrichment"
        return replace(fact, payload=payload)
    return fact


def _select_global_candidate(fact: CodeFact, candidates: list[GlobalSymbol]) -> tuple[GlobalSymbol | None, str, str | None]:
    candidates = _dedupe_symbols(candidates)
    if not candidates:
        return None, "unresolved", "unresolved_call_target"
    arg_count = fact.payload.get("argument_count")
    if arg_count is not None:
        count_matches = [c for c in candidates if c.argument_count == int(arg_count)]
        if count_matches:
            candidates = count_matches
    hints = list(fact.payload.get("argument_type_hints") or [])
    if hints:
        hinted = [c for c in candidates if _signature_matches_hints(c.signature, hints)]
        if hinted:
            candidates = hinted
    defs = [c for c in candidates if c.declaration_or_definition == "definition"]
    if defs:
        candidates = defs
    candidates = _dedupe_symbols(candidates)
    qnames = {c.qualified_name for c in candidates}
    signatures = {c.signature for c in candidates}
    if len(candidates) == 1:
        return candidates[0], "resolved", None
    if len(qnames) == 1 and len(signatures) > 1:
        return None, "ambiguous", "ambiguous_overload_resolution"
    return None, "ambiguous", "ambiguous_symbol_resolution"


def _dedupe_symbols(candidates: list[GlobalSymbol]) -> list[GlobalSymbol]:
    by_key: dict[tuple[str, str], GlobalSymbol] = {}
    for candidate in candidates:
        key = (candidate.qualified_name, candidate.signature)
        current = by_key.get(key)
        if current is None or (current.declaration_or_definition != "definition" and candidate.declaration_or_definition == "definition"):
            by_key[key] = candidate
    return list(by_key.values())


def _signature_matches_hints(signature: str, hints: list[str]) -> bool:
    params = [p.strip() for p in signature.split(",")] if signature else []
    if len(params) != len(hints):
        return False
    for param, hint in zip(params, hints):
        p = param.replace("const ", "")
        if hint == "int" and not any(tok in p for tok in ["int", "short", "long", "size_t", "uint", "int"]):
            return False
        if hint == "bool" and "bool" not in p:
            return False
        if hint == "string" and not ("char" in p or "string" in p):
            return False
        if hint == "nullptr" and "*" not in p:
            return False
    return True


def _strip_type_suffix(type_name: object) -> str | None:
    if not isinstance(type_name, str) or not type_name:
        return None
    return type_name.replace("*", "").replace("&", "").strip()


def _caller_namespace(fact: CodeFact, table: GlobalSymbolTable) -> str | None:
    qname = fact.payload.get("caller_qualified_name")
    symbol = table.symbol_for_qname(str(qname) if qname else None)
    if symbol:
        return symbol.namespace
    if isinstance(qname, str) and "::" in qname:
        parts = qname.split("::")[:-1]
        if len(parts) >= 2 and parts[-1][:1].isupper():
            parts = parts[:-1]
        return "::".join(parts) if parts else None
    return None


def _resolution_scope(fact: CodeFact, selected: GlobalSymbol) -> str:
    if selected.path != fact.path:
        return "cross_translation_unit"
    if Path(selected.path).suffix.lower() in CPP_SOURCE_EXTENSIONS:
        return "translation_unit"
    return "global_symbol_table"


def _symbol_table_relation_facts(table: GlobalSymbolTable) -> list[CodeFact]:
    facts: list[CodeFact] = []
    definitions_by_qsig = {
        (s.qualified_name, s.signature): s
        for s in table.symbols
        if s.declaration_or_definition == "definition"
    }
    for symbol in table.symbols:
        if symbol.declaration_or_definition != "declaration":
            continue
        definition = definitions_by_qsig.get((symbol.qualified_name, symbol.signature))
        if not definition or definition.path == symbol.path:
            continue
        facts.append(
            CodeFact(
                fact_type="relation",
                path=symbol.path,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                subject=f"{symbol.qualified_name}({symbol.signature})",
                predicate="declared_symbol_resolves_to_definition",
                object=f"{definition.qualified_name}({definition.signature})",
                confidence="medium",
                source="cross_tu_symbol_table",
                payload={
                    "relation_kind": "cross_tu_declaration_definition_binding",
                    "symbol_id": symbol.symbol_id,
                    "definition_symbol_id": definition.symbol_id,
                    "definition_path": definition.path,
                    "definition_line": definition.start_line,
                    "resolution_scope": "cross_translation_unit",
                    "semantic_phase": "phase3_cross_tu",
                },
            )
        )
    return facts
