from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Iterable

from repoanalyzer.core.models import CodeFact

_CONTROL_WORDS = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "alignof",
    "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "decltype",
}
_DECL_PREFIX_WORDS = {"virtual", "static", "inline", "constexpr", "extern", "friend", "explicit"}
_QUALIFIER_WORDS = _DECL_PREFIX_WORDS | {"const", "override", "final", "noexcept"}
_BUILTIN_TYPES = {"void", "int", "char", "short", "long", "bool", "float", "double", "signed", "unsigned", "size_t"}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")
_MACRO_WRAPPED_FUNCTIONS = {
    # FreeRTOS task-function declaration/definition helpers.
    # Both macros expand to a regular function with signature
    # `void name( void * parameter )`, but source-level extractors see the
    # unexpanded macro invocation.  Normalize them as functions while preserving
    # the macro provenance in symbol payloads.
    "portTASK_FUNCTION": "definition_or_declaration",
    "portTASK_FUNCTION_PROTO": "declaration",
}


@dataclass(frozen=True)
class Scope:
    kind: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    bases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Parameter:
    name: str | None
    type: str


@dataclass(frozen=True)
class FunctionInfo:
    name: str
    qualified_name: str
    kind: str
    path: str
    start_line: int
    end_line: int
    body_start_line: int | None
    declaration_or_definition: str
    return_type: str | None
    parameters: tuple[Parameter, ...]
    qualifiers: tuple[str, ...]
    scope: str | None
    namespace: str | None
    owner_type: str | None
    macro_wrapped_function: bool = False
    macro_name: str | None = None

    @property
    def signature(self) -> str:
        return ", ".join(p.type for p in self.parameters)

    @property
    def display_name(self) -> str:
        if "::" in self.qualified_name:
            return self.qualified_name
        return self.name

    @property
    def symbol_id(self) -> str:
        raw = "|".join([self.kind, self.qualified_name, self.signature, self.path, str(self.start_line)])
        return "sym_" + hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass(frozen=True)
class FieldInfo:
    name: str
    owner_type: str
    type_name: str | None
    path: str
    start_line: int
    end_line: int
    is_pointer: bool = False


@dataclass(frozen=True)
class SemanticModel:
    scopes: tuple[Scope, ...]
    functions: tuple[FunctionInfo, ...]
    fields: tuple[FieldInfo, ...]
    type_facts: tuple[CodeFact, ...]
    relation_facts: tuple[CodeFact, ...]
    type_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Binding:
    name: str
    type_name: str | None = None
    is_pointer: bool = False
    is_function_pointer: bool = False
    candidates: tuple[str, ...] = ()


def analyze_cpp_semantics(path: str, text: str) -> list[CodeFact]:
    model = build_semantic_model(path, text)
    symbol_facts = _annotate_template_symbols([_function_fact(fn) for fn in model.functions], text)
    execution_context_facts = _execution_context_relation_facts(path, model.functions)
    port_boundary_facts = _port_boundary_definition_facts(path, model.functions)
    call_facts = _extract_calls_and_references(path, text, model)
    template_facts = _template_diagnostic_facts(path, text)
    resource_facts = _resource_ui_binding_relations(path, text)
    kernel_object_macro_facts = _kernel_object_macro_relations(path, text)
    tinyusb_descriptor_facts = _tinyusb_descriptor_macro_facts(path, text)
    tinyusb_callback_facts = _tinyusb_callback_definition_facts(path, text, model)
    tinyusb_driver_dispatch_facts = _tinyusb_driver_dispatch_facts(path, text, model)
    tinyusb_device_runtime_facts = _tinyusb_device_runtime_facts(path, text, model)
    tinyusb_host_runtime_facts = _tinyusb_host_runtime_facts(path, text, model)
    tinyusb_class_protocol_facts = _tinyusb_class_protocol_facts(path, text, model)
    tinyusb_typec_pd_facts = _tinyusb_typec_pd_facts(path, text, model)
    return [
        *model.type_facts,
        *model.relation_facts,
        *symbol_facts,
        *execution_context_facts,
        *port_boundary_facts,
        *call_facts,
        *kernel_object_macro_facts,
        *template_facts,
        *resource_facts,
        *tinyusb_descriptor_facts,
        *tinyusb_callback_facts,
        *tinyusb_driver_dispatch_facts,
        *tinyusb_device_runtime_facts,
        *tinyusb_host_runtime_facts,
        *tinyusb_class_protocol_facts,
        *tinyusb_typec_pd_facts,
    ]


def build_semantic_model(path: str, text: str) -> SemanticModel:
    masked = mask_comments_and_strings(text)
    lines = masked.splitlines()
    scopes = _extract_scopes(path, masked)
    type_facts, type_relations = _type_and_inheritance_facts(path, scopes)
    alias_facts, type_aliases = _type_alias_facts(path, masked, scopes)
    field_facts, fields = _field_facts(path, masked, scopes, type_aliases)
    functions = tuple(_extract_functions(path, text, masked, scopes))
    return SemanticModel(
        scopes=tuple(scopes),
        functions=functions,
        fields=tuple(fields),
        type_facts=tuple([*type_facts, *alias_facts]),
        relation_facts=tuple([*type_relations, *field_facts]),
        type_aliases=type_aliases,
    )


def mask_comments_and_strings(text: str) -> str:
    """Replace comments and literal contents with spaces while preserving line/column shape."""
    out: list[str] = []
    i = 0
    n = len(text)
    state = "code"
    quote = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "/":
                out.append(" ")
                out.append(" ")
                i += 2
                state = "line_comment"
                continue
            if ch == "/" and nxt == "*":
                out.append(" ")
                out.append(" ")
                i += 2
                state = "block_comment"
                continue
            if ch in {'"', "'"}:
                quote = ch
                out.append(ch)
                i += 1
                state = "string"
                continue
            out.append(ch)
            i += 1
            continue
        if state == "line_comment":
            if ch == "\n":
                out.append("\n")
                state = "code"
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block_comment":
            if ch == "*" and nxt == "/":
                out.append(" ")
                out.append(" ")
                i += 2
                state = "code"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if state == "string":
            if ch == "\\" and i + 1 < n:
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            if ch == quote:
                out.append(ch)
                i += 1
                state = "code"
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
    return "".join(out)


def _extract_scopes(path: str, masked: str) -> list[Scope]:
    lines = masked.splitlines()
    raw_scopes: list[tuple[str, str, int, int, tuple[str, ...]]] = []
    for i, line in enumerate(lines):
        start_line = i + 1
        for m in re.finditer(r"\bnamespace\s+((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\{", line):
            raw_scopes.append(("namespace", m.group(1), start_line, _find_block_end(lines, i), ()))
        for m in re.finditer(r"\b(class|struct)\s+([A-Za-z_]\w*)\s*(?::\s*([^\{]+))?\{", line):
            bases = _parse_bases(m.group(3) or "")
            raw_scopes.append((m.group(1), m.group(2), start_line, _find_block_end(lines, i), tuple(bases)))

    scopes: list[Scope] = []
    for kind, name, start, end, bases in sorted(raw_scopes, key=lambda x: (x[2], -(x[3] - x[2]))):
        parent = _innermost_scope_at(scopes, start, exclude_kinds={"function"})
        if kind == "namespace" and "::" in name:
            qname = name
        elif parent and parent.qualified_name:
            qname = f"{parent.qualified_name}::{name}"
        else:
            qname = name
        scopes.append(Scope(kind=kind, name=name.split("::")[-1], qualified_name=qname, start_line=start, end_line=end, bases=bases))
    return scopes


def _parse_bases(text: str) -> list[str]:
    bases: list[str] = []
    for part in _split_top_level_commas(text):
        part = re.sub(r"\b(public|protected|private|virtual)\b", " ", part).strip()
        m = re.search(r"((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)", part)
        if m:
            bases.append(m.group(1))
    return bases


def _find_block_end(lines: list[str], start_index: int) -> int:
    depth = 0
    seen = False
    for j in range(start_index, len(lines)):
        for ch in lines[j]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
                if seen and depth <= 0:
                    return j + 1
    return len(lines)


def _innermost_scope_at(scopes: Iterable[Scope], line: int, *, exclude_kinds: set[str] | None = None) -> Scope | None:
    exclude_kinds = exclude_kinds or set()
    candidates = [s for s in scopes if s.kind not in exclude_kinds and s.start_line <= line <= s.end_line]
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: (s.end_line - s.start_line, -s.start_line))[0]


def _scopes_at(scopes: Iterable[Scope], line: int) -> list[Scope]:
    return sorted([s for s in scopes if s.start_line <= line <= s.end_line], key=lambda s: (s.start_line, -(s.end_line - s.start_line)))



def _type_alias_facts(path: str, masked: str, scopes: list[Scope]) -> tuple[list[CodeFact], dict[str, str]]:
    facts: list[CodeFact] = []
    aliases: dict[str, str] = {}
    type_scopes = [s for s in scopes if s.kind in {"class", "struct"}]
    lines = masked.splitlines()
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        namespace = _namespace_for_scope(scopes, index)
        matches: list[tuple[str, str, str]] = []
        m = re.match(r"using\s+(?P<alias>[A-Za-z_]\w*)\s*=\s*(?P<target>[^;]+);", stripped)
        if m:
            matches.append(("using", m.group("alias"), m.group("target")))
        m = re.match(r"typedef\s+(?P<target>.+?)\s+(?P<alias>[A-Za-z_]\w*)\s*;", stripped)
        if m and "(" not in m.group("target"):
            matches.append(("typedef", m.group("alias"), m.group("target")))
        for alias_kind, alias, target in matches:
            target_norm = _normalize_type(target)
            target_norm = re.sub(r"\b(const|volatile)\b", " ", target_norm).strip()
            pointer_suffix = "*" if "*" in target_norm else ""
            reference_suffix = "&" if "&" in target_norm else ""
            target_base = target_norm.replace("*", "").replace("&", "").strip()
            qualified_target = _qualify_type_name(target_base, namespace, type_scopes)
            if qualified_target and qualified_target not in _BUILTIN_TYPES:
                qualified_target = qualified_target + pointer_suffix + reference_suffix
            qualified_alias = f"{namespace}::{alias}" if namespace else alias
            aliases[alias] = qualified_target
            aliases[qualified_alias] = qualified_target
            facts.append(
                CodeFact(
                    fact_type="type",
                    path=path,
                    start_line=index,
                    end_line=index,
                    symbol=alias,
                    qualified_name=qualified_alias,
                    kind="type_alias",
                    subject=qualified_alias,
                    predicate="aliases",
                    object=qualified_target,
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload={
                        "alias_kind": alias_kind,
                        "alias_target": qualified_target,
                        "alias_target_raw": target.strip(),
                        "namespace": namespace,
                        "semantic_phase": "phase3_mvp",
                    },
                )
            )
    return facts, aliases

def _type_and_inheritance_facts(path: str, scopes: list[Scope]) -> tuple[list[CodeFact], list[CodeFact]]:
    type_facts: list[CodeFact] = []
    relation_facts: list[CodeFact] = []
    for scope in scopes:
        if scope.kind not in {"class", "struct"}:
            continue
        namespace = _namespace_for_scope(scopes, scope.start_line)
        symbol_id = "type_" + hashlib.sha1(f"{scope.kind}|{scope.qualified_name}|{path}|{scope.start_line}".encode()).hexdigest()[:16]
        type_facts.append(
            CodeFact(
                fact_type="type",
                path=path,
                start_line=scope.start_line,
                end_line=scope.end_line,
                symbol=scope.name,
                qualified_name=scope.qualified_name,
                kind=scope.kind,
                subject=scope.qualified_name,
                predicate="definition",
                object=scope.kind,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={"symbol_id": symbol_id, "namespace": namespace, "scope": namespace, "bases": list(scope.bases)},
            )
        )
        for base in scope.bases:
            qualified_base = _qualify_type_name(base, namespace, [s for s in scopes if s.kind in {"class", "struct"}])
            relation_facts.append(
                CodeFact(
                    fact_type="relation",
                    path=path,
                    start_line=scope.start_line,
                    end_line=scope.start_line,
                    subject=scope.qualified_name,
                    predicate="inherits",
                    object=qualified_base,
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload={"relation_kind": "inheritance", "base": qualified_base, "derived": scope.qualified_name},
                )
            )
    return type_facts, relation_facts



def _field_facts(path: str, masked: str, scopes: list[Scope], aliases: dict[str, str]) -> tuple[list[CodeFact], list[FieldInfo]]:
    """Extract shallow class/struct data-member declarations.

    This is intentionally conservative. It records plain field declarations such as
    `CLayoutMgr m_cLayoutMgr;`, `Outer* ptr;`, and `const Device& ref;` so member-chain
    calls can be resolved later. Method declarations, function pointer members, and
    complex template declarations are left to safe-unknown paths.
    """
    facts: list[CodeFact] = []
    fields: list[FieldInfo] = []
    lines = masked.splitlines()
    type_scopes = [s for s in scopes if s.kind in {"class", "struct"}]
    for scope in type_scopes:
        namespace = _namespace_for_scope(scopes, scope.start_line)
        for lineno in range(scope.start_line + 1, min(scope.end_line, len(lines)) + 1):
            stripped = lines[lineno - 1].strip()
            if not stripped or stripped.startswith("#") or stripped in {"public:", "private:", "protected:"}:
                continue
            if "(" in stripped or ")" in stripped:
                continue
            # Do not scan nested class bodies as fields of the outer class.
            inner = _innermost_scope_at(type_scopes, lineno)
            if inner and inner.qualified_name != scope.qualified_name:
                continue
            m = re.match(
                r"(?P<type>(?:(?:const|volatile|mutable|static)\s+)*(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\s*<[^;{}()]*>)?\s*(?:[*&]\s*)?)"
                r"(?P<name>[A-Za-z_]\w*)\s*(?:[;=\{])",
                stripped,
            )
            if not m:
                continue
            raw_type = m.group("type").strip()
            name = m.group("name")
            if raw_type.split()[0] in _CONTROL_WORDS or raw_type in _BUILTIN_TYPES:
                continue
            type_name, is_pointer = _normalize_declared_type(raw_type, namespace, type_scopes, aliases)
            if not type_name:
                continue
            field = FieldInfo(
                name=name,
                owner_type=scope.qualified_name,
                type_name=type_name,
                path=path,
                start_line=lineno,
                end_line=lineno,
                is_pointer=is_pointer,
            )
            fields.append(field)
            facts.append(
                CodeFact(
                    fact_type="relation",
                    path=path,
                    start_line=lineno,
                    end_line=lineno,
                    symbol=name,
                    subject=scope.qualified_name,
                    predicate="has_field",
                    object=type_name,
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload={
                        "relation_kind": "type_field",
                        "owner_type": scope.qualified_name,
                        "field_name": name,
                        "field_type": type_name,
                        "is_pointer": is_pointer,
                        "semantic_phase": "phase3_sakura_chain",
                    },
                )
            )
    return facts, fields


def _normalize_declared_type(
    type_text: str,
    namespace: str | None,
    type_scopes: list[Scope],
    aliases: dict[str, str],
) -> tuple[str | None, bool]:
    clean = type_text.strip()
    is_pointer = "*" in clean
    clean = re.sub(r"\b(const|volatile|static|extern|mutable)\b", " ", clean)
    clean = clean.replace("*", " ").replace("&", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean or clean in _BUILTIN_TYPES:
        return None, is_pointer
    if "<" in clean and ">" in clean:
        inner = clean[clean.find("<") + 1: clean.rfind(">")].strip()
        first_inner = _split_top_level_commas(inner)[0] if inner else ""
        if first_inner:
            clean = first_inner.replace("*", " ").replace("&", " ").strip()
    qualified = _normalize_alias_type(_qualify_type_name(clean, namespace, type_scopes), aliases)
    return qualified, is_pointer

def _namespace_for_scope(scopes: Iterable[Scope], line: int) -> str | None:
    namespaces = [s.qualified_name for s in _scopes_at(scopes, line) if s.kind == "namespace"]
    return namespaces[-1] if namespaces else None


def _extract_functions(path: str, original_text: str, masked: str, scopes: list[Scope]) -> list[FunctionInfo]:
    lines = masked.splitlines()
    original_lines = original_text.splitlines()
    functions: list[FunctionInfo] = []
    covered_body_lines: set[int] = set()
    i = 0
    while i < len(lines):
        line_no = i + 1
        if line_no in covered_body_lines:
            i += 1
            continue
        if not _could_start_function(lines[i]):
            i += 1
            continue
        statement, end_index = _collect_declarator(lines, i)
        if not statement or "(" not in statement or ")" not in statement:
            i += 1
            continue
        info = _parse_function_statement(path, statement, i + 1, end_index + 1, scopes)
        if info is None:
            i += 1
            continue
        if info.declaration_or_definition == "definition":
            body_start = _find_body_start_line(lines, i, end_index)
            end_line = _find_block_end(lines, body_start - 1 if body_start else end_index)
            info = FunctionInfo(**{**info.__dict__, "end_line": end_line, "body_start_line": body_start})
            for ln in range(info.start_line + 1, info.end_line + 1):
                covered_body_lines.add(ln)
            i = max(i + 1, end_line)
        else:
            i = end_index + 1
        functions.append(info)
    return functions


def _could_start_function(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return False
    first = stripped.split(None, 1)[0].split("(", 1)[0]
    if first in _CONTROL_WORDS or first in {"class", "struct", "namespace", "using", "typedef", "return"}:
        return False
    if stripped.endswith((";", "}")) and "(" not in stripped:
        return False
    # Multi-line signatures often begin with only a return type, e.g. `void`
    # followed by `Device::start(...)` on the next line. Let the bounded
    # declarator collector decide whether it really is a function.
    return bool(re.match(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:[<*&\s:].*)?$", stripped)) or "(" in stripped or re.search(r"\b(?:virtual|static|inline|constexpr|extern|explicit)\b", stripped) is not None


def _collect_declarator(lines: list[str], start: int) -> tuple[str, int]:
    parts: list[str] = []
    paren = 0
    for j in range(start, min(len(lines), start + 20)):
        line = lines[j]
        parts.append(line.strip())
        paren += line.count("(") - line.count(")")
        joined = " ".join(parts)
        if paren <= 0 and ("{" in line or ";" in line):
            return joined, j
    return " ".join(parts), min(len(lines) - 1, start)


def _parse_function_statement(path: str, statement: str, start_line: int, end_line: int, scopes: list[Scope]) -> FunctionInfo | None:
    compact = re.sub(r"\s+", " ", statement.strip())
    if not compact or compact.startswith(("if ", "for ", "while ", "switch ", "catch ", "return ")):
        return None
    macro_info = _parse_macro_wrapped_function_statement(path, compact, start_line, end_line, scopes)
    if macro_info is not None:
        return macro_info

    # Remove pure virtual/default/delete markers after parameter list for parsing.
    head = compact.split("{", 1)[0].rsplit(";", 1)[0].strip()
    m = re.match(r"(?P<prefix>.*?)\b(?P<name>(?:[A-Za-z_]\w*::)*~?[A-Za-z_]\w*)\s*\((?P<params>.*)\)\s*(?P<suffix>.*)$", head)
    if not m:
        return None
    name_token = m.group("name")
    short_name = name_token.split("::")[-1]
    if short_name in _CONTROL_WORDS:
        return None
    prefix = m.group("prefix").strip()
    params_text = m.group("params").strip()
    suffix = m.group("suffix").strip()
    if "=" in prefix or prefix.endswith(".") or prefix.endswith("->"):
        return None

    class_scope = _innermost_scope_at([s for s in scopes if s.kind in {"class", "struct"}], start_line)
    namespace = _namespace_for_scope(scopes, start_line)
    owner_type = _owner_from_name_or_scope(name_token, class_scope, namespace, scopes)
    unqualified_owner = owner_type.split("::")[-1] if owner_type else None
    bare_name = short_name.lstrip("~")
    is_constructor = unqualified_owner is not None and bare_name == unqualified_owner and not short_name.startswith("~")
    is_destructor = unqualified_owner is not None and short_name == f"~{unqualified_owner}"

    return_type = _normalize_return_type(prefix)
    if not return_type and not (is_constructor or is_destructor):
        # A call or variable declaration with parentheses, not a function declaration.
        return None
    if prefix and re.search(r"\b(new|return|if|for|while|switch)\b", prefix):
        return None

    declaration_or_definition = "definition" if "{" in statement else "declaration"
    kind = "function"
    if is_constructor:
        kind = "constructor"
    elif is_destructor:
        kind = "destructor"
    elif owner_type:
        kind = "method"

    qualified_name = _qualify_function_name(name_token, namespace, owner_type, scopes)
    parameters = tuple(_parse_parameters(params_text))
    qualifiers = tuple(sorted(_extract_qualifiers(prefix, suffix)))
    scope_name = owner_type or namespace
    return FunctionInfo(
        name=short_name,
        qualified_name=qualified_name,
        kind=kind,
        path=path,
        start_line=start_line,
        end_line=end_line,
        body_start_line=None,
        declaration_or_definition=declaration_or_definition,
        return_type=None if kind in {"constructor", "destructor"} else return_type,
        parameters=parameters,
        qualifiers=qualifiers,
        scope=scope_name,
        namespace=namespace,
        owner_type=owner_type,
    )



def _parse_macro_wrapped_function_statement(path: str, compact: str, start_line: int, end_line: int, scopes: list[Scope]) -> FunctionInfo | None:
    """Normalize known macro-wrapped function declarations/definitions.

    FreeRTOS ports commonly define task entry functions as::

        static portTASK_FUNCTION( prvTimerTask, pvParameters )
        {
            ...
        }

    Before preprocessing this does not look like a C function declaration to the
    lightweight parser, but after macro expansion it is equivalent to
    `static void prvTimerTask( void * pvParameters )`.  Treat the known macro as
    a function while keeping macro provenance so evidence consumers know this was
    recovered from a source-level macro pattern rather than a direct signature.
    """
    head = compact.split("{", 1)[0].rsplit(";", 1)[0].strip()
    m = re.match(
        r"(?P<prefix>.*?)\b(?P<macro>portTASK_FUNCTION|portTASK_FUNCTION_PROTO)\s*\(\s*"
        r"(?P<name>[A-Za-z_]\w*)\s*,\s*(?P<param>[A-Za-z_]\w*)\s*\)\s*(?P<suffix>.*)$",
        head,
    )
    if not m:
        return None
    prefix = m.group("prefix").strip()
    if prefix and re.search(r"\b(new|return|if|for|while|switch)\b", prefix):
        return None
    macro_name = m.group("macro")
    name = m.group("name")
    param = m.group("param")
    namespace = _namespace_for_scope(scopes, start_line)
    qualified_name = f"{namespace}::{name}" if namespace else name
    declaration_or_definition = "definition" if "{" in compact else "declaration"
    if macro_name == "portTASK_FUNCTION_PROTO":
        declaration_or_definition = "declaration" if "{" not in compact else "definition"
    return FunctionInfo(
        name=name,
        qualified_name=qualified_name,
        kind="function",
        path=path,
        start_line=start_line,
        end_line=end_line,
        body_start_line=None,
        declaration_or_definition=declaration_or_definition,
        return_type="void",
        parameters=(Parameter(name=param, type="void*"),),
        qualifiers=tuple(sorted(_extract_qualifiers(prefix, m.group("suffix").strip()))),
        scope=namespace,
        namespace=namespace,
        owner_type=None,
        macro_wrapped_function=True,
        macro_name=macro_name,
    )

def _owner_from_name_or_scope(name_token: str, class_scope: Scope | None, namespace: str | None, scopes: list[Scope]) -> str | None:
    if "::" in name_token:
        owner = "::".join(name_token.split("::")[:-1])
        return _qualify_type_name(owner, namespace, [s for s in scopes if s.kind in {"class", "struct"}])
    if class_scope:
        return class_scope.qualified_name
    return None


def _qualify_function_name(name_token: str, namespace: str | None, owner_type: str | None, scopes: list[Scope]) -> str:
    short = name_token.split("::")[-1]
    if owner_type:
        return f"{owner_type}::{short}"
    if "::" in name_token:
        if name_token.startswith("::"):
            return name_token[2:]
        if namespace and not name_token.startswith(namespace + "::"):
            # For namespace-local out-of-class definitions like Device::start.
            owner = "::".join(name_token.split("::")[:-1])
            if any(s.qualified_name == f"{namespace}::{owner}" for s in scopes):
                return f"{namespace}::{name_token}"
        return name_token
    return f"{namespace}::{short}" if namespace else short


def _qualify_type_name(type_name: str, namespace: str | None, type_scopes: list[Scope]) -> str:
    clean = type_name.strip().strip("&*")
    if not clean or clean in _BUILTIN_TYPES or "::" in clean:
        if namespace and clean and "::" not in clean and any(s.qualified_name == f"{namespace}::{clean}" for s in type_scopes):
            return f"{namespace}::{clean}"
        return clean
    if namespace and any(s.qualified_name == f"{namespace}::{clean}" for s in type_scopes):
        return f"{namespace}::{clean}"
    matches = [s.qualified_name for s in type_scopes if s.name == clean]
    return matches[0] if len(matches) == 1 else clean


def _normalize_return_type(prefix: str) -> str | None:
    text = prefix.strip()
    if not text:
        return None
    words = [w for w in text.split() if w not in _DECL_PREFIX_WORDS]
    if not words:
        return None
    return _normalize_type(" ".join(words))


def _extract_qualifiers(prefix: str, suffix: str) -> list[str]:
    found: list[str] = []
    for word in _QUALIFIER_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", prefix) or re.search(rf"\b{re.escape(word)}\b", suffix):
            found.append(word)
    return found


def _parse_parameters(params_text: str) -> list[Parameter]:
    if not params_text or params_text == "void":
        return []
    params: list[Parameter] = []
    for raw in _split_top_level_commas(params_text):
        raw = raw.split("=", 1)[0].strip()
        if not raw:
            continue
        # Drop parameter name if present.
        m = re.match(r"(?P<type>.*?)(?:\s+|(?=[*&]))(?P<name>[A-Za-z_]\w*)\s*$", raw)
        if m and m.group("type") and m.group("name") not in {"const", "volatile"}:
            type_part = m.group("type").strip()
            name = m.group("name")
            # If the type part is empty or just qualifiers, keep raw as type.
            if type_part and type_part not in _QUALIFIER_WORDS:
                params.append(Parameter(name=name, type=_normalize_type(type_part)))
                continue
        params.append(Parameter(name=None, type=_normalize_type(raw)))
    return params


def _normalize_type(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" *", "*").replace("* ", "*")
    text = text.replace(" &", "&").replace("& ", "&")
    return text


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "(<[":
            depth += 1
        elif ch in ")>]" and depth > 0:
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    last = text[start:].strip()
    if last:
        parts.append(last)
    return parts


def _find_body_start_line(lines: list[str], start_index: int, end_index: int) -> int | None:
    for j in range(start_index, end_index + 1):
        if "{" in lines[j]:
            return j + 1
    return None



def _execution_context_for_name(name: str, macro_name: str | None = None) -> tuple[str | None, str | None]:
    """Conservatively infer FreeRTOS-style task/ISR context from naming and macros.

    This is not a proof that the function always runs in that context; it is an
    evidence annotation that lets downstream answer contracts distinguish
    task-context APIs from ISR-context handlers/APIs.
    """
    short = name.split("::")[-1]
    if short.endswith("FromISR") or "FromISR" in short:
        return "isr", "freertos_from_isr_suffix"
    if re.search(r"(?:ISR|IRQHandler|SysTickHandler|PendSVHandler|SVCHandler)$", short):
        return "isr", "interrupt_handler_name"
    if macro_name in {"portTASK_FUNCTION", "portTASK_FUNCTION_PROTO"}:
        return "task", "freertos_task_function_macro"
    if short.startswith(("xQueue", "vQueue", "xTimer", "vTimer")):
        return "task", "freertos_task_context_api_name"
    if short in {"xTaskCreate", "vTaskStartScheduler"}:
        return "task", "freertos_task_context_api_name"
    return None, None


def _execution_context_payload_for_function(fn: FunctionInfo, *, prefix: str = "") -> dict[str, str]:
    context, basis = _execution_context_for_name(fn.name, fn.macro_name)
    if not context:
        return {}
    if prefix:
        return {
            f"{prefix}_execution_context": context,
            f"{prefix}_execution_context_basis": basis or "heuristic",
        }
    return {
        "execution_context": context,
        "execution_context_basis": basis or "heuristic",
    }


def _execution_context_payload_for_name(name: str, *, prefix: str = "") -> dict[str, str]:
    context, basis = _execution_context_for_name(name)
    if not context:
        return {}
    if prefix:
        return {
            f"{prefix}_execution_context": context,
            f"{prefix}_execution_context_basis": basis or "heuristic",
        }
    return {
        "execution_context": context,
        "execution_context_basis": basis or "heuristic",
    }


def _execution_context_relation_facts(path: str, functions: tuple[FunctionInfo, ...]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    seen: set[tuple[str, str]] = set()
    for fn in functions:
        if fn.declaration_or_definition != "definition":
            continue
        context, basis = _execution_context_for_name(fn.name, fn.macro_name)
        if not context:
            continue
        key = (fn.display_name, context)
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.display_name,
                predicate="has_execution_context",
                object=context,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "execution_context_annotation",
                    "execution_context": context,
                    "execution_context_basis": basis,
                    "function_qualified_name": fn.qualified_name,
                    "function_symbol_id": fn.symbol_id,
                    "resolution_status": "semantic_relation",
                    "semantic_phase": "phase7_execution_context",
                    **({
                        "macro_wrapped_function": True,
                        "macro_name": fn.macro_name,
                    } if fn.macro_wrapped_function else {}),
                },
            )
        )
    return facts

def _function_fact(fn: FunctionInfo) -> CodeFact:
    return CodeFact(
        fact_type="symbol",
        path=fn.path,
        start_line=fn.start_line,
        end_line=fn.end_line,
        symbol=fn.name,
        qualified_name=fn.qualified_name,
        kind=fn.kind,
        subject=f"{fn.qualified_name}({fn.signature})",
        predicate=fn.declaration_or_definition,
        object=fn.kind,
        confidence="high" if fn.declaration_or_definition == "definition" else "medium",
        source="semantic_cpp_lightweight",
        payload={
            "symbol_id": fn.symbol_id,
            "signature": fn.signature,
            "qualified_signature": f"{fn.qualified_name}({fn.signature})",
            "return_type": fn.return_type,
            "owner_type": fn.owner_type,
            "namespace": fn.namespace,
            "scope": fn.scope,
            "qualifiers": list(fn.qualifiers),
            "parameters": [{"name": p.name, "type": p.type} for p in fn.parameters],
            "argument_count": len(fn.parameters),
            "declaration_or_definition": fn.declaration_or_definition,
            "semantic_phase": "phase3",
            **_execution_context_payload_for_function(fn),
            **({
                "macro_wrapped_function": True,
                "macro_name": fn.macro_name,
                "definition_source": "macro_wrapped_function",
            } if fn.macro_wrapped_function else {}),
        },
    )


def _extract_calls_and_references(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    masked = mask_comments_and_strings(text)
    lines = masked.splitlines()
    original_lines = text.splitlines()
    facts: list[CodeFact] = []
    function_by_line: dict[int, FunctionInfo] = {}
    definition_start_lines = {fn.start_line for fn in model.functions}
    all_symbols = list(model.functions)
    type_names = {scope.name: scope.qualified_name for scope in model.scopes if scope.kind in {"class", "struct"}}
    type_names.update({scope.qualified_name: scope.qualified_name for scope in model.scopes if scope.kind in {"class", "struct"}})
    type_names.update({alias.split("::")[-1]: target for alias, target in model.type_aliases.items()})
    type_names.update(model.type_aliases)

    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        for ln in range(fn.start_line, fn.end_line + 1):
            function_by_line[ln] = fn

    callback_candidates_by_var: dict[str, set[str]] = {}

    for fn in [f for f in model.functions if f.declaration_or_definition == "definition"]:
        bindings = _extract_bindings(fn, lines, model, callback_candidates_by_var)
        body_range = range(fn.start_line, fn.end_line + 1)
        for lineno in body_range:
            if lineno in definition_start_lines or lineno == fn.body_start_line:
                # Still allow one-line function bodies after the opening brace.
                # Multi-line declarations may start on an access-label line; in that
                # case the actual opening brace is on body_start_line rather than
                # start_line, so handle both locations as signature/body boundary.
                line_for_calls = _after_open_brace(lines[lineno - 1])
                original_line_for_args = _after_open_brace(original_lines[lineno - 1]) if lineno <= len(original_lines) else line_for_calls
            else:
                if lineno < 1 or lineno > len(lines):
                    continue
                line_for_calls = lines[lineno - 1]
                original_line_for_args = original_lines[lineno - 1] if lineno <= len(original_lines) else line_for_calls
            if not line_for_calls.strip():
                continue
            line_facts = _calls_from_line(path, fn, lineno, line_for_calls, original_line_for_args, all_symbols, model, bindings, callback_candidates_by_var, type_names)
            facts.extend(line_facts)
            facts.extend(_edit_operation_relations_from_calls(path, fn, lineno, line_facts))
            facts.extend(_file_io_encoding_relations_from_calls(path, fn, lineno, line_facts))
            facts.extend(_config_profile_relations_from_calls(path, fn, lineno, line_facts))
            facts.extend(_windows_message_relations_from_calls(path, fn, lineno, line_facts, line_for_calls, all_symbols))
            facts.extend(_ui_resource_relations_from_calls(path, fn, lineno, line_facts, line_for_calls))
            facts.extend(_extension_execution_relations_from_calls(path, fn, lineno, line_facts, line_for_calls))
            facts.extend(_undo_operation_block_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_file_io_encoding_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_config_profile_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_windows_message_relations_from_line(path, fn, lineno, line_for_calls, all_symbols))
            facts.extend(_ui_resource_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_extension_execution_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_callback_relations_from_line(path, fn, lineno, line_for_calls, all_symbols))
            facts.extend(_callback_storage_and_invocation_relations_from_line(path, fn, lineno, line_for_calls, all_symbols))
            facts.extend(_task_entry_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_scheduler_semantic_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_task_state_transition_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_kernel_object_semantic_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_hook_assert_trace_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_heap_allocator_semantic_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_port_advanced_semantic_relations_from_line(path, fn, lineno, line_for_calls))
            facts.extend(_port_boundary_relations_from_calls(path, fn, lineno, line_facts))
            _update_function_pointer_assignments(line_for_calls, all_symbols, callback_candidates_by_var)
    facts.extend(_callback_dataflow_relations(path, facts))
    facts.extend(_task_entry_dataflow_relations(path, facts))
    facts.extend(_callback_table_relations(path, lines, all_symbols))
    facts.extend(_command_dispatch_relations(path, lines, all_symbols))
    facts.extend(_toolbar_command_binding_relations(path, lines))
    facts.extend(_macro_function_binding_relations(path, original_lines))
    return facts


def _annotate_template_symbols(facts: list[CodeFact], text: str) -> list[CodeFact]:
    lines = text.splitlines()
    marked: list[CodeFact] = []
    for fact in facts:
        if fact.fact_type != "symbol":
            marked.append(fact)
            continue
        current = lines[fact.start_line - 1].strip() if 0 <= fact.start_line - 1 < len(lines) else ""
        prev = fact.start_line - 2
        found_template = current.startswith("template") or current.startswith("template<") or str(fact.payload.get("return_type", "")).startswith("template")
        while not found_template and prev >= 0 and prev >= fact.start_line - 5:
            stripped = lines[prev].strip()
            if not stripped:
                prev -= 1
                continue
            found_template = stripped.startswith("template") or stripped.startswith("template<")
            break
        if not found_template:
            marked.append(fact)
            continue
        payload = dict(fact.payload)
        payload["template_declaration"] = True
        payload["unknown_type"] = "unsupported_cpp_construct"
        payload["unsupported_cpp_construct_kind"] = "template_declaration"
        marked.append(replace(fact, confidence="medium", payload=payload))
    return marked


def _template_diagnostic_facts(path: str, text: str) -> list[CodeFact]:
    facts: list[CodeFact] = []
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        if not re.search(r"\btemplate\s*<", line):
            continue
        target = "template"
        for next_line in lines[index:min(index + 4, len(lines))]:
            m = re.search(r"((?:[A-Za-z_]\w*::)*[~A-Za-z_]\w*)\s*\(", next_line)
            if m:
                target = m.group(1).split("::")[-1]
                break
            m = re.search(r"\b(class|struct)\s+([A-Za-z_]\w*)", next_line)
            if m:
                target = m.group(2)
                break
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=index,
                end_line=index,
                subject=target,
                predicate="uses_unsupported_cpp_construct",
                object="template_declaration",
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "unsupported_cpp_construct",
                    "unknown_type": "unsupported_cpp_construct",
                    "unsupported_cpp_construct_kind": "template_declaration",
                    "semantic_phase": "phase3_mvp",
                },
            )
        )
    return facts


def _after_open_brace(line: str) -> str:
    return line.split("{", 1)[1] if "{" in line else ""


def _normalize_alias_type(type_name: str | None, aliases: dict[str, str]) -> str | None:
    if not type_name:
        return type_name
    suffix = ""
    base = type_name.strip()
    while base.endswith("*") or base.endswith("&"):
        suffix = base[-1] + suffix
        base = base[:-1].strip()
    target = aliases.get(base)
    if target is None and "::" in base:
        target = aliases.get(base.split("::")[-1])
    if target is None:
        return type_name
    return target + suffix


def _extract_bindings(fn: FunctionInfo, lines: list[str], model: SemanticModel, fp_candidates: dict[str, set[str]]) -> dict[str, Binding]:
    bindings: dict[str, Binding] = {}
    type_scopes = [s for s in model.scopes if s.kind in {"class", "struct"}]

    def normalize_declared_type(type_text: str) -> tuple[str | None, bool]:
        return _normalize_declared_type(type_text, fn.namespace, type_scopes, model.type_aliases)

    for p in fn.parameters:
        if p.name:
            typename, is_pointer = normalize_declared_type(p.type)
            bindings[p.name] = Binding(p.name, typename, is_pointer=is_pointer or "*" in p.type)
    for lineno in range(fn.start_line, fn.end_line + 1):
        if lineno < 1 or lineno > len(lines):
            continue
        line = lines[lineno - 1]
        # Function pointer declarations and assignments.
        for m in re.finditer(r"(?:void|int|bool|char|long|short|float|double)\s*\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\([^)]*\)\s*(?:=\s*&?(?P<target>[A-Za-z_]\w*))?", line):
            name = m.group("name")
            target = m.group("target")
            if target:
                fp_candidates.setdefault(name, set()).add(target)
            bindings[name] = Binding(name, None, is_function_pointer=True, candidates=tuple(sorted(fp_candidates.get(name, set()))))
        # Declarations such as `Alias dev;`, `const Alias& ref = ...`, `Alias* ptr = ...`, `Alias dev{};`.
        for m in re.finditer(
            r"\b(?P<type>(?:(?:const|volatile)\s+)?(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*(?:\s*<[^;{}()]*>)?\s*(?:[*&]\s*)?)"
            r"(?P<name>[A-Za-z_]\w*)\s*(?:[;=({])",
            line,
        ):
            type_name = m.group("type")
            if type_name.split()[0] in _CONTROL_WORDS or type_name.strip() in {"return", "auto"}:
                continue
            name = m.group("name")
            typename, is_pointer = normalize_declared_type(type_name)
            if typename:
                bindings[name] = Binding(name, typename, is_pointer=is_pointer)
        # Limited `auto var = Type{...};` / `auto var = Type(...);` inference.
        for m in re.finditer(r"\bauto\s+(?P<ptr>[*&]?)\s*(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<type>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*(?:\{|\()", line):
            typename, is_pointer = normalize_declared_type(m.group("type") + m.group("ptr"))
            if typename:
                bindings[m.group("name")] = Binding(m.group("name"), typename, is_pointer=is_pointer or bool(m.group("ptr")))
    return bindings


def _parse_receiver_chain(expr: str) -> dict | None:
    expr = re.sub(r"\s+", "", expr.strip())
    ident = r"[A-Za-z_]\w*"
    qident = rf"{ident}(?:::{ident})*"
    m = re.match(
        rf"(?:(?P<root_qname>{qident})\((?P<root_qargs>[^()]*)\)|(?P<root>{ident})(?:\((?P<root_args>[^()]*)\))?)(?P<rest>(?:(?:->|\.){ident}(?:\([^()]*\))?)+)$",
        expr,
    )
    if not m:
        return None
    root_name = m.group("root_qname") or m.group("root")
    raw_root_args = m.group("root_qargs") if m.group("root_qname") else m.group("root_args")
    root_args = _split_top_level_commas(raw_root_args or "") if raw_root_args is not None else []
    steps = []
    for sm in re.finditer(rf"(?P<op>->|\.)(?P<name>{ident})(?:\((?P<args>[^()]*)\))?", m.group("rest")):
        has_args = sm.group("args") is not None
        steps.append({
            "op": sm.group("op"),
            "name": sm.group("name"),
            "args": _split_top_level_commas(sm.group("args") or "") if has_args else [],
            "step_kind": "method_return" if has_args else "field",
        })
    root_kind = "function_return" if raw_root_args is not None else "variable"
    # Plain obj.method(...) is handled by the simpler member-call path.  Treat
    # function-return chains such as CEditWnd::getInstance()->GetHwnd() as
    # chains even with a single terminal step.
    if len(steps) < 2 and root_kind != "function_return":
        return None
    if not steps:
        return None
    return {"root_kind": root_kind, "root_name": root_name, "root_args": root_args, "steps": steps}


def _strip_pointer_suffix(type_name: str | None) -> str | None:
    if not type_name:
        return None
    return type_name.replace("*", "").replace("&", "").strip()


def _field_type_for(owner_type: str | None, field_name: str, model: SemanticModel) -> tuple[str | None, bool]:
    owner = _strip_pointer_suffix(_normalize_alias_type(owner_type, model.type_aliases) if owner_type else owner_type)
    if not owner:
        return None, False
    for field in model.fields:
        if field.owner_type == owner and field.name == field_name:
            return field.type_name, field.is_pointer
    return None, False


def _return_type_for_call_root(name: str, args: list[str], caller: FunctionInfo, symbols: list[FunctionInfo], model: SemanticModel) -> str | None:
    candidates = []
    if "::" not in name and caller.owner_type:
        candidates.extend([s for s in symbols if s.owner_type == caller.owner_type and s.name == name])
    candidates.extend(_candidate_functions(symbols, name=name, caller_namespace=caller.namespace))
    resolved, status, _unknown = _resolve_overload(candidates, args)
    selected = resolved if status == "resolved" else (_dedupe_candidates(candidates)[0] if len(_dedupe_candidates(candidates)) == 1 else None)
    if not selected or not selected.return_type:
        return None
    return _normalize_alias_type(selected.return_type, model.type_aliases)



def _temporary_object_type_for_root(name: str, caller: FunctionInfo, model: SemanticModel) -> str | None:
    """Resolve `Type().method()` receiver roots as temporary objects.

    Sakura Editor uses patterns such as `CDocTypeManager().GetTypeConfigMini(...)`.
    They look syntactically like a function-return receiver, but the root is actually
    a temporary object construction. Treat this conservatively only when the root
    name maps to a known class/struct or alias in the indexed TU.
    """
    clean = name.strip()
    if not clean or "::" in clean and clean.endswith("::"):
        return None
    type_scopes = [s for s in model.scopes if s.kind in {"class", "struct"}]
    qualified = _normalize_alias_type(_qualify_type_name(clean, caller.namespace, type_scopes), model.type_aliases)
    known = {s.qualified_name for s in type_scopes}
    known.update(model.type_aliases.values())
    known.add(clean)
    if qualified and _strip_pointer_suffix(qualified) in {_strip_pointer_suffix(k) for k in known}:
        return qualified
    matches = [s.qualified_name for s in type_scopes if s.name == clean]
    if len(matches) == 1:
        return matches[0]
    return None

def _return_type_for_member_step(owner_type: str | None, method: str, args: list[str], symbols: list[FunctionInfo], model: SemanticModel) -> tuple[str | None, FunctionInfo | None, str]:
    owner = _strip_pointer_suffix(_normalize_alias_type(owner_type, model.type_aliases) if owner_type else owner_type)
    if not owner:
        return None, None, "missing_owner_type"
    candidates = [s for s in symbols if s.owner_type == owner and s.name == method]
    resolved, status, _unknown = _resolve_overload(candidates, args)
    selected = resolved if status == "resolved" else (_dedupe_candidates(candidates)[0] if len(_dedupe_candidates(candidates)) == 1 else None)
    if not selected or not selected.return_type:
        return None, selected, status
    return _normalize_alias_type(selected.return_type, model.type_aliases), selected, status


def _resolve_receiver_chain_type(
    chain: dict,
    caller: FunctionInfo,
    symbols: list[FunctionInfo],
    model: SemanticModel,
    bindings: dict[str, Binding],
) -> tuple[str | None, list[dict], str | None]:
    trace: list[dict] = []
    root_name = str(chain["root_name"])
    current_type: str | None = None
    if chain["root_kind"] == "variable":
        binding = bindings.get(root_name)
        if binding and binding.type_name:
            current_type = binding.type_name
            trace.append({"kind": "local_variable", "name": root_name, "type": binding.type_name, "is_pointer": binding.is_pointer})
        elif caller.owner_type:
            field_type, is_pointer = _field_type_for(caller.owner_type, root_name, model)
            if field_type:
                current_type = field_type
                trace.append({"kind": "implicit_this_field", "name": root_name, "owner_type": caller.owner_type, "type": field_type, "is_pointer": is_pointer})
            else:
                trace.append({"kind": "variable", "name": root_name, "type": None})
                return None, trace, root_name
        else:
            trace.append({"kind": "variable", "name": root_name, "type": None})
            return None, trace, root_name
    else:
        current_type = _return_type_for_call_root(root_name, list(chain.get("root_args") or []), caller, symbols, model)
        if current_type:
            trace.append({"kind": "function_return", "name": root_name, "args": list(chain.get("root_args") or []), "type": current_type})
        else:
            current_type = _temporary_object_type_for_root(root_name, caller, model)
            trace.append({"kind": "temporary_object", "name": root_name, "args": list(chain.get("root_args") or []), "type": current_type})
        if not current_type:
            return None, trace, root_name

    for step in list(chain["steps"][:-1]):
        owner = _strip_pointer_suffix(current_type)
        if step.get("step_kind") == "method_return":
            return_type, selected, status = _return_type_for_member_step(owner, str(step["name"]), list(step.get("args") or []), symbols, model)
            trace.append({
                "kind": "method_return",
                "op": step["op"],
                "name": step["name"],
                "args": list(step.get("args") or []),
                "owner_type": owner,
                "type": return_type,
                "resolution_status": status,
                "callee_qualified_name": selected.qualified_name if selected else None,
            })
            if not return_type:
                return None, trace, str(step["name"])
            current_type = return_type
            continue
        field_type, is_pointer = _field_type_for(owner, str(step["name"]), model)
        trace.append({"kind": "field", "op": step["op"], "name": step["name"], "owner_type": owner, "type": field_type, "is_pointer": is_pointer})
        if not field_type:
            return None, trace, str(step["name"])
        current_type = field_type + ("*" if is_pointer and not field_type.endswith("*") else "")
    return current_type, trace, None


def _make_chained_member_call(
    path: str,
    lineno: int,
    caller: FunctionInfo,
    chain_expr: str,
    args: list[str],
    symbols: list[FunctionInfo],
    model: SemanticModel,
    bindings: dict[str, Binding],
) -> list[CodeFact]:
    chain = _parse_receiver_chain(chain_expr)
    if not chain:
        return []
    final_step = chain["steps"][-1]
    method = str(final_step["name"])
    receiver_expr = chain_expr.rsplit(final_step["op"] + method, 1)[0]
    receiver_type, trace, unresolved_at = _resolve_receiver_chain_type(chain, caller, symbols, model, bindings)
    base_payload = {
        "receiver_expr": receiver_expr,
        "receiver_chain_expr": chain_expr,
        "receiver_chain": trace,
        "receiver_chain_root_kind": chain["root_kind"],
        "receiver_chain_root_name": chain["root_name"],
        "receiver_chain_steps": list(chain["steps"]),
        "member_name": method,
        "terminal_op": final_step["op"],
        "argument_count": len(args),
        "argument_type_hints": [_literal_type_hint(arg) for arg in args],
        "resolution_basis": "receiver_chain",
    }
    if not receiver_type:
        payload = dict(base_payload)
        payload.update({"resolution_status": "unresolved", "unknown_type": "unresolved_member_receiver_type"})
        if unresolved_at:
            payload["receiver_chain_unresolved_at"] = unresolved_at
        return _make_call_fact(path, lineno, caller, method, "member_unresolved", confidence="low", payload=payload)
    owner = _strip_pointer_suffix(receiver_type) or receiver_type
    candidates = [s for s in symbols if s.owner_type == owner and s.name == method]
    resolved, status, unknown = _resolve_overload(candidates, args)
    payload = _resolution_payload(resolved, candidates, args, status, unknown)
    payload.update(base_payload)
    payload.update({"receiver_type": receiver_type, "receiver_type_resolved": owner, "resolution_basis": "receiver_chain_local"})
    return _make_call_fact(
        path,
        lineno,
        caller,
        _display_for_target(resolved, owner + "::" + method),
        "member_direct" if status == "resolved" else "member_unresolved",
        confidence="high" if status == "resolved" else "low",
        payload=payload,
    )

def _calls_from_line(
    path: str,
    caller: FunctionInfo,
    lineno: int,
    line: str,
    original_line: str,
    symbols: list[FunctionInfo],
    model: SemanticModel,
    bindings: dict[str, Binding],
    fp_candidates: dict[str, set[str]],
    type_names: dict[str, str],
) -> list[CodeFact]:
    facts: list[CodeFact] = []
    spans: list[tuple[int, int]] = []

    def overlapped(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in spans)

    # chained member calls: GetDocument()->m_cLayoutMgr.SearchWord(...),
    # CEditWnd::getInstance()->SetDrawSwitchOfAllViews(...),
    # pcEditView->GetCommander().Command_ADDTAIL(...).
    chain_root = r"(?:[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*\s*\([^()]*\)|[A-Za-z_]\w*)"
    chain_mid = r"(?:\s*(?:->|\.)\s*[A-Za-z_]\w*(?:\s*\([^()]*\))?)"
    chain_terminal = r"(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)"
    for m in re.finditer(rf"(?<![A-Za-z_0-9])(?=(?P<chain>{chain_root}{chain_mid}*{chain_terminal})\s*\()", line):
        chain_start = m.start("chain")
        chain_end = m.end("chain")
        open_index = chain_end
        while open_index < len(line) and line[open_index].isspace():
            open_index += 1
        if open_index >= len(line) or line[open_index] != "(":
            continue
        close_index = _matching_paren_index(line, open_index)
        if close_index is None:
            continue
        if overlapped(chain_start, close_index + 1):
            continue
        args_text = line[open_index + 1:close_index]
        args = _split_top_level_commas(args_text) if args_text.strip() else []
        chain_facts = _make_chained_member_call(path, lineno, caller, m.group("chain"), args, symbols, model, bindings)
        if not chain_facts:
            continue
        spans.append((chain_start, close_index + 1))
        facts.extend(chain_facts)

    # member dot/arrow calls
    for m in re.finditer(r"\b(?P<recv>[A-Za-z_]\w*)\s*(?P<op>\.|->)\s*(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)", line):
        if overlapped(*m.span()):
            continue
        spans.append(m.span())
        recv = m.group("recv")
        method = m.group("name")
        args = _args_from_original(original_line, m.group("args"))
        facts.extend(_make_member_call(path, lineno, caller, recv, method, m.group("op"), args, symbols, model, bindings))

    # static or namespace-qualified calls
    for m in re.finditer(r"(?<![A-Za-z_0-9])(?P<qual>(?:[A-Za-z_]\w*::)+)(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)", line):
        if overlapped(*m.span()):
            continue
        spans.append(m.span())
        qname = (m.group("qual") + m.group("name")).rstrip(":")
        args = _split_top_level_commas(m.group("args")) if m.group("args").strip() else []
        facts.extend(_make_qualified_call(path, lineno, caller, qname, args, symbols, model))

    # new Type(...) constructor
    for m in re.finditer(r"\bnew\s+(?P<type>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)", line):
        if overlapped(*m.span()):
            continue
        spans.append(m.span())
        facts.extend(_make_constructor_call(path, lineno, caller, m.group("type"), _split_top_level_commas(m.group("args")), symbols, model))

    # variable constructor Type var(...)
    for m in re.finditer(r"\b(?P<type>[A-Z][A-Za-z_]\w*)\s+(?P<var>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)", line):
        if overlapped(*m.span()):
            continue
        if m.group("type") not in type_names:
            continue
        spans.append(m.span())
        facts.extend(_make_constructor_call(path, lineno, caller, m.group("type"), _split_top_level_commas(m.group("args")), symbols, model))

    # free/function pointer calls
    for m in re.finditer(r"\b(?P<name>[A-Za-z_]\w*)\s*\((?P<args>[^()]*)\)", line):
        if overlapped(*m.span()):
            continue
        name = m.group("name")
        if name in _CONTROL_WORDS or name in _BUILTIN_TYPES:
            continue
        before = line[max(0, m.start() - 3):m.start()]
        if before.endswith("::") or before.endswith("->") or before.endswith("."):
            continue
        args = _split_top_level_commas(m.group("args")) if m.group("args").strip() else []
        if name in bindings and (bindings[name].is_function_pointer or name in fp_candidates):
            facts.extend(_make_function_pointer_call(path, lineno, caller, name, fp_candidates.get(name, set()) or set(bindings[name].candidates), symbols))
        else:
            facts.extend(_make_free_call(path, lineno, caller, name, args, symbols))
    return facts


def _matching_paren_index(text: str, open_index: int) -> int | None:
    depth = 0
    for i in range(open_index, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _args_from_original(original_line: str, fallback_args: str) -> list[str]:
    return _split_top_level_commas(fallback_args) if fallback_args.strip() else []


def _make_call_fact(
    path: str,
    lineno: int,
    caller: FunctionInfo,
    callee_display: str,
    call_kind: str,
    *,
    confidence: str = "high",
    payload: dict | None = None,
) -> list[CodeFact]:
    payload = dict(payload or {})
    payload.setdefault("caller_qualified_name", caller.qualified_name)
    payload.setdefault("caller_symbol_id", caller.symbol_id)
    caller_ctx = _execution_context_payload_for_function(caller, prefix="caller")
    payload.update({k: v for k, v in caller_ctx.items() if k not in payload})
    if "caller_execution_context" in payload:
        payload.setdefault("execution_context", payload["caller_execution_context"])
        payload.setdefault("execution_context_basis", payload.get("caller_execution_context_basis"))
    callee_ctx = _execution_context_payload_for_name(callee_display, prefix="callee")
    payload.update({k: v for k, v in callee_ctx.items() if k not in payload})
    payload.setdefault("semantic_phase", "phase3")
    call = CodeFact(
        fact_type="call",
        path=path,
        start_line=lineno,
        end_line=lineno,
        caller=caller.display_name,
        callee=callee_display,
        call_kind=call_kind,
        subject=caller.display_name,
        predicate="calls",
        object=callee_display,
        confidence=confidence,
        source="semantic_cpp_lightweight",
        payload=payload,
    )
    ref = CodeFact(
        fact_type="reference",
        path=path,
        start_line=lineno,
        end_line=lineno,
        symbol=_short_name(callee_display),
        qualified_name=payload.get("callee_qualified_name") or (callee_display if "::" in callee_display else None),
        subject=caller.display_name,
        predicate="references",
        object=callee_display,
        confidence="medium" if confidence == "high" else "low",
        source="semantic_cpp_lightweight",
        payload={"reference_kind": "call", **payload},
    )
    return [call, ref]


def _make_free_call(path: str, lineno: int, caller: FunctionInfo, name: str, args: list[str], symbols: list[FunctionInfo]) -> list[CodeFact]:
    candidates = _candidate_functions(symbols, name=name, caller_namespace=caller.namespace)
    resolved, status, unknown = _resolve_overload(candidates, args)
    # Free functions are often declared in headers or other TUs that the lightweight
    # per-file resolver has not loaded yet. Keep the edge queryable but avoid turning
    # every cross-TU call into a semantic unknown.
    if status == "unresolved":
        unknown = None
    payload = _resolution_payload(resolved, candidates, args, status, unknown)
    callee = _display_for_target(resolved, name)
    confidence = "high" if status == "resolved" else "low"
    return _make_call_fact(path, lineno, caller, callee, "direct", confidence=confidence, payload=payload)


def _make_qualified_call(path: str, lineno: int, caller: FunctionInfo, qname: str, args: list[str], symbols: list[FunctionInfo], model: SemanticModel) -> list[CodeFact]:
    # If the prefix is a known type, this is a static member call.
    owner = "::".join(qname.split("::")[:-1])
    type_qnames = {s.qualified_name for s in model.scopes if s.kind in {"class", "struct"}}
    if caller.namespace and f"{caller.namespace}::{owner}" in type_qnames:
        qname = f"{caller.namespace}::{qname}"
        owner = f"{caller.namespace}::{owner}"
    candidates = [s for s in symbols if s.qualified_name == qname or s.qualified_name.endswith("::" + qname)]
    resolved, status, unknown = _resolve_overload(candidates, args)
    payload = _resolution_payload(resolved, candidates, args, status, unknown)
    if owner in type_qnames or any(s.owner_type == owner for s in candidates):
        payload["resolution_basis"] = "qualified_owner_type"
        return _make_call_fact(path, lineno, caller, _display_for_target(resolved, qname), "static_member", confidence="high" if status == "resolved" else "low", payload=payload)
    payload["resolution_basis"] = "qualified_name"
    return _make_call_fact(path, lineno, caller, _display_for_target(resolved, qname), "direct", confidence="high" if status == "resolved" else "low", payload=payload)


def _make_member_call(path: str, lineno: int, caller: FunctionInfo, recv: str, method: str, op: str, args: list[str], symbols: list[FunctionInfo], model: SemanticModel, bindings: dict[str, Binding]) -> list[CodeFact]:
    binding = bindings.get(recv)
    receiver_basis = "local_variable_type"
    receiver_trace: list[dict] = []
    if not binding or not binding.type_name:
        field_type, is_pointer = _field_type_for(caller.owner_type, recv, model)
        if field_type:
            binding = Binding(recv, field_type, is_pointer=is_pointer or op == "->")
            receiver_basis = "implicit_this_field"
            receiver_trace.append({"kind": "implicit_this_field", "name": recv, "owner_type": caller.owner_type, "type": field_type, "is_pointer": is_pointer})
        else:
            payload = {
                "receiver_expr": recv,
                "member_name": method,
                "resolution_status": "unresolved",
                "unknown_type": "unresolved_member_receiver_type",
                "argument_count": len(args),
            }
            return _make_call_fact(path, lineno, caller, method, "member_unresolved", confidence="low", payload=payload)
    owner = binding.type_name
    candidates = [s for s in symbols if s.owner_type == owner and s.name == method]
    resolved, status, unknown = _resolve_overload(candidates, args)
    virtual_candidates = _virtual_candidates(owner, method, symbols, model)
    if virtual_candidates:
        payload = _resolution_payload(resolved, virtual_candidates, args, "candidate_set", "virtual_dispatch_candidates")
        payload.update({"receiver_expr": recv, "receiver_type": owner + ("*" if binding.is_pointer or op == "->" else ""), "resolution_basis": receiver_basis})
        if receiver_trace:
            payload["receiver_chain"] = receiver_trace
        return _make_call_fact(path, lineno, caller, owner + "::" + method, "virtual_candidate", confidence="medium", payload=payload)
    payload = _resolution_payload(resolved, candidates, args, status, unknown)
    payload.update({"receiver_expr": recv, "receiver_type": owner + ("*" if binding.is_pointer or op == "->" else ""), "resolution_basis": receiver_basis})
    if receiver_trace:
        payload["receiver_chain"] = receiver_trace
    return _make_call_fact(path, lineno, caller, _display_for_target(resolved, owner + "::" + method), "member_direct", confidence="high" if status == "resolved" else "low", payload=payload)


def _make_constructor_call(path: str, lineno: int, caller: FunctionInfo, type_name: str, args: list[str], symbols: list[FunctionInfo], model: SemanticModel) -> list[CodeFact]:
    type_scopes = [s for s in model.scopes if s.kind in {"class", "struct"}]
    owner = _normalize_alias_type(_qualify_type_name(type_name, caller.namespace, type_scopes), model.type_aliases) or type_name
    short = owner.split("::")[-1]
    candidates = [s for s in symbols if s.owner_type == owner and s.kind == "constructor"]
    resolved, status, unknown = _resolve_overload(candidates, args)
    payload = _resolution_payload(resolved, candidates, args, status, unknown)
    payload.update({"constructed_type": owner, "resolution_basis": "constructor_syntax"})
    return _make_call_fact(path, lineno, caller, _display_for_target(resolved, owner + "::" + short), "constructor", confidence="high" if status == "resolved" else "medium", payload=payload)


def _make_function_pointer_call(path: str, lineno: int, caller: FunctionInfo, name: str, candidates: set[str], symbols: list[FunctionInfo]) -> list[CodeFact]:
    candidate_symbols = []
    candidate_qnames = []
    for cand in sorted(candidates):
        matches = _candidate_functions(symbols, name=cand, caller_namespace=caller.namespace)
        if matches:
            for match in matches:
                candidate_symbols.append(match.symbol_id)
                candidate_qnames.append(match.qualified_name)
        else:
            candidate_qnames.append(cand)
    payload = {
        "resolution_status": "candidate_set" if candidate_qnames else "unresolved",
        "unknown_type": "indirect_call_unresolved",
        "function_pointer_variable": name,
        "candidate_symbol_ids": candidate_symbols,
        "candidate_qualified_names": candidate_qnames,
    }
    return _make_call_fact(path, lineno, caller, name, "function_pointer", confidence="low", payload=payload)


def _candidate_functions(symbols: list[FunctionInfo], *, name: str, caller_namespace: str | None) -> list[FunctionInfo]:
    if "::" in name:
        return [s for s in symbols if s.qualified_name == name or s.qualified_name.endswith("::" + name)]
    candidates = [s for s in symbols if s.name == name]
    if caller_namespace:
        ns_candidates = [s for s in candidates if s.namespace == caller_namespace or not s.namespace]
        if ns_candidates:
            return ns_candidates
    return candidates


def _resolve_overload(candidates: list[FunctionInfo], args: list[str]) -> tuple[FunctionInfo | None, str, str | None]:
    candidates = _dedupe_candidates(candidates)
    if not candidates:
        return None, "unresolved", "unresolved_call_target"
    by_count = [c for c in candidates if len(c.parameters) == len(args)]
    candidates = _dedupe_candidates(by_count or candidates)
    hints = [_literal_type_hint(arg) for arg in args]
    if any(hints):
        typed = [c for c in candidates if _parameters_match_hints(c.parameters, hints)]
        if typed:
            candidates = _dedupe_candidates(typed)
    if len(candidates) == 1:
        return candidates[0], "resolved", None
    return None, "ambiguous", "ambiguous_overload_resolution"


def _dedupe_candidates(candidates: list[FunctionInfo]) -> list[FunctionInfo]:
    by_key: dict[tuple[str, str], FunctionInfo] = {}
    for candidate in candidates:
        key = (candidate.qualified_name, candidate.signature)
        current = by_key.get(key)
        if current is None or (current.declaration_or_definition != "definition" and candidate.declaration_or_definition == "definition"):
            by_key[key] = candidate
    return list(by_key.values())


def _literal_type_hint(arg: str) -> str | None:
    arg = arg.strip()
    if not arg:
        return None
    if arg.startswith('"') or arg.startswith("L\""):
        return "string"
    if arg in {"true", "false"}:
        return "bool"
    if arg == "nullptr" or arg == "NULL":
        return "nullptr"
    if re.fullmatch(r"[-+]?0x[0-9A-Fa-f]+", arg) or re.fullmatch(r"[-+]?\d+", arg):
        return "int"
    return None


def _parameters_match_hints(params: tuple[Parameter, ...], hints: list[str | None]) -> bool:
    if len(params) != len(hints):
        return False
    for param, hint in zip(params, hints):
        if hint is None:
            continue
        p = param.type.replace("const ", "")
        if hint == "int" and not re.search(r"\b(int|short|long|size_t|uint\w*|int\w*)\b", p):
            return False
        if hint == "bool" and "bool" not in p:
            return False
        if hint == "string" and not ("char" in p or "string" in p):
            return False
        if hint == "nullptr" and "*" not in p:
            return False
    return True


def _resolution_payload(resolved: FunctionInfo | None, candidates: list[FunctionInfo], args: list[str], status: str, unknown: str | None) -> dict:
    payload = {
        "resolution_status": status,
        "argument_count": len(args),
        "argument_expressions": list(args),
        "argument_type_hints": [h for h in (_literal_type_hint(arg) for arg in args) if h],
        "candidate_symbol_ids": [c.symbol_id for c in candidates],
        "candidate_qualified_names": [c.qualified_name for c in candidates],
    }
    if resolved:
        payload.update({"callee_symbol_id": resolved.symbol_id, "callee_qualified_name": resolved.qualified_name, "callee_signature": resolved.signature})
    if unknown:
        payload["unknown_type"] = unknown
    return payload


def _display_for_target(resolved: FunctionInfo | None, fallback: str) -> str:
    if resolved:
        return resolved.display_name
    return fallback


def _short_name(name: str) -> str:
    return name.split("::")[-1]


def _virtual_candidates(owner: str, method: str, symbols: list[FunctionInfo], model: SemanticModel) -> list[FunctionInfo]:
    owner_methods = [s for s in symbols if s.owner_type == owner and s.name == method]
    derived_types = [rel.subject for rel in model.relation_facts if rel.predicate == "inherits" and rel.object == owner]
    derived_methods: list[FunctionInfo] = []
    for derived in derived_types:
        derived_methods.extend([s for s in symbols if s.owner_type == derived and s.name == method])
    if not owner_methods or not derived_methods:
        return []
    if any("virtual" in s.qualifiers for s in owner_methods) or derived_methods:
        return _dedupe_candidates([*owner_methods, *derived_methods])
    return []




_EDIT_OPERATION_KINDS: dict[str, tuple[str, str]] = {
    "InsertData_CEditView": ("performs_edit_operation", "insert_text"),
    "DeleteData": ("performs_edit_operation", "delete_text"),
    "ReplaceData_CEditView3": ("performs_edit_operation", "replace_text"),
    "ReplaceData_CEditView": ("performs_edit_operation", "replace_text"),
    "SetModified": ("updates_document_modified_state", "set_modified"),
    "SetUndoBuffer": ("updates_undo_buffer", "flush_or_prepare_undo_buffer"),
    "DoUndo": ("consumes_undo_history", "undo_history_pop"),
    "DoRedo": ("consumes_redo_history", "redo_history_pop"),
    "GetOpe": ("iterates_operation_block", "operation_block_item"),
    "GetNum": ("inspects_operation_block", "operation_block_count"),
    "SetOpeBlk": ("uses_undo_operation_block", "set_operation_block"),
    "GetOpeBlk": ("uses_undo_operation_block", "get_operation_block"),
    "SetRefCount": ("uses_undo_operation_block", "operation_block_refcount"),
    "AddRef": ("uses_undo_operation_block", "operation_block_refcount"),
    "Release": ("uses_undo_operation_block", "operation_block_refcount"),
}

_EDIT_OPERATION_RELATION_KIND = {
    "performs_edit_operation": "edit_buffer_mutation",
    "updates_document_modified_state": "document_modified_state",
    "updates_undo_buffer": "undo_buffer_update",
    "consumes_undo_history": "undo_redo_history_access",
    "consumes_redo_history": "undo_redo_history_access",
    "iterates_operation_block": "undo_operation_block_iteration",
    "inspects_operation_block": "undo_operation_block_iteration",
    "uses_undo_operation_block": "undo_operation_block_lifecycle",
}


_FILE_IO_ENCODING_OPERATION_KINDS: dict[str, tuple[str, str, str]] = {
    "FileOpen": ("opens_file", "open_file", "file_open"),
    "CreateFile": ("opens_file", "win32_create_file", "file_open"),
    "GetFileSize": ("reads_file_size", "win32_get_file_size", "file_metadata"),
    "CreateFileMapping": ("maps_file_buffer", "create_file_mapping", "file_mapping"),
    "MapViewOfFile": ("maps_file_buffer", "map_view_of_file", "file_mapping"),
    "CheckKanjiCode": ("detects_character_encoding", "detect_encoding_from_buffer", "encoding_detection"),
    "CheckKanjiCodeOfFile": ("detects_character_encoding", "detect_encoding_from_file", "encoding_detection"),
    "Detect": ("uses_encoding_detector", "charset_detector", "encoding_detection"),
    "CreateCodeBase": ("creates_encoding_converter", "create_code_base", "encoding_converter_factory"),
    "GetEncodingTrait": ("determines_encoding_trait", "encoding_trait_lookup", "encoding_metadata"),
    "FileToImpl": ("converts_file_to_internal_encoding", "file_to_internal_conversion", "encoding_conversion"),
    "ReadLine": ("reads_file_line", "read_logical_line", "line_read"),
    "ReadLine_core": ("reads_file_line", "read_line_core", "line_read"),
    "GetNextLineCharCode": ("scans_line_boundary", "scan_line_boundary_by_encoding", "line_boundary_scan"),
    "GetEol": ("configures_eol_detection", "configure_encoded_eol", "eol_detection"),
    "FileClose": ("closes_file", "close_file", "file_close"),
}

_FILE_IO_ENCODING_RELATION_KIND = {
    "opens_file": "file_open",
    "reads_file_size": "file_metadata",
    "maps_file_buffer": "file_mapping",
    "detects_character_encoding": "encoding_detection",
    "uses_encoding_detector": "encoding_detection",
    "creates_encoding_converter": "encoding_converter_factory",
    "determines_encoding_trait": "encoding_metadata",
    "converts_file_to_internal_encoding": "encoding_conversion",
    "reads_file_line": "line_read",
    "scans_line_boundary": "line_boundary_scan",
    "configures_eol_detection": "eol_detection",
    "closes_file": "file_close",
}


_CONFIG_PROFILE_OPERATION_KINDS: dict[str, tuple[str, str, str]] = {
    "LoadShareData": ("loads_shared_settings", "load_share_data_entry", "settings_lifecycle"),
    "SaveShareData": ("saves_shared_settings", "save_share_data_entry", "settings_lifecycle"),
    "ShareData_IO_2": ("runs_profile_io", "shared_settings_io_core", "profile_io_core"),
    "GetIniFileNameForIO": ("resolves_ini_path", "select_ini_path", "ini_path_resolution"),
    "SetReadingMode": ("selects_profile_mode", "profile_reading_mode", "profile_mode"),
    "SetWritingMode": ("selects_profile_mode", "profile_writing_mode", "profile_mode"),
    "ReadProfile": ("reads_profile", "read_ini_profile", "profile_file_io"),
    "WriteProfile": ("writes_profile", "write_ini_profile", "profile_file_io"),
    "IOProfileData": ("maps_profile_key", "read_or_write_profile_key", "profile_key_mapping"),
    "IsReadingMode": ("checks_profile_mode", "is_reading_mode", "profile_mode"),
    "GetDllShareData": ("accesses_shared_data", "get_dll_share_data", "shared_data_access"),
    "RefreshString": ("refreshes_shared_strings", "refresh_localized_strings", "shared_data_refresh"),
    "ChangeLang": ("applies_language_setting", "change_language", "language_setting"),
    "ConvertLangValues": ("applies_language_setting", "convert_language_values", "language_setting"),
    "CopyFile": ("backs_up_ini_file", "backup_ini_file", "ini_backup"),
}

_CONFIG_PROFILE_RELATION_KIND = {
    "loads_shared_settings": "settings_lifecycle",
    "saves_shared_settings": "settings_lifecycle",
    "runs_profile_io": "profile_io_core",
    "resolves_ini_path": "ini_path_resolution",
    "selects_profile_mode": "profile_mode",
    "reads_profile": "profile_file_io",
    "writes_profile": "profile_file_io",
    "maps_profile_key": "profile_key_mapping",
    "checks_profile_mode": "profile_mode",
    "accesses_shared_data": "shared_data_access",
    "refreshes_shared_strings": "shared_data_refresh",
    "applies_language_setting": "language_setting",
    "backs_up_ini_file": "ini_backup",
    "loads_config_section": "config_section_io",
    "saves_config_section": "config_section_io",
    "accesses_common_setting": "common_setting_access",
}


def _config_profile_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact]) -> list[CodeFact]:
    """Derive settings/profile/INI semantic relations from calls.

    Sakura Editor's settings persistence is centered around CShareData_IO,
    CDataProfile, GetDllShareData(), and section helpers.  These relations
    expose configuration roles without pretending every edge is an
    unconditional runtime call.
    """
    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, int]] = set()
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        if not callee:
            continue
        short = _short_name(callee)
        if short.startswith("ShareData_IO_") and short not in {"ShareData_IO_2"}:
            predicate, operation_kind, relation_kind = ("loads_config_section", short, "config_section_io")
        elif short not in _CONFIG_PROFILE_OPERATION_KINDS:
            continue
        else:
            predicate, operation_kind, relation_kind = _CONFIG_PROFILE_OPERATION_KINDS[short]
        key = (caller.qualified_name, predicate, callee, lineno)
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=callee,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "operation_callee": callee,
                    "operation_callee_short": short,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "call_kind": fact.call_kind,
                    "call_resolution_status": fact.payload.get("resolution_status"),
                    "callee_qualified_name": fact.payload.get("callee_qualified_name") or callee,
                    "callee_symbol_id": fact.payload.get("callee_symbol_id"),
                    "edge_status": "semantic_config_profile_relation",
                    "semantic_phase": "sakura_config_profile_io",
                },
            )
        )
    return relations


def _config_profile_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Detect settings markers that are field accesses or mode branches."""
    relations: list[CodeFact] = []
    markers: list[tuple[str, str, str, str]] = []
    if re.search(r"\bbRead\b", line) and re.search(r"SetReadingMode|ReadProfile|IsReadingMode", line):
        markers.append(("selects_profile_mode", "bRead", "read_mode_branch", "profile_mode"))
    if re.search(r"\bbRead\b", line) and re.search(r"SetWritingMode|WriteProfile|!\s*bRead", line):
        markers.append(("selects_profile_mode", "bRead", "write_mode_branch", "profile_mode"))
    if re.search(r"\bm_Common\b", line):
        markers.append(("accesses_common_setting", "DLLSHAREDATA::m_Common", "common_setting_tree", "common_setting_access"))
    if re.search(r"\bm_sHistory\b", line):
        markers.append(("accesses_shared_data", "DLLSHAREDATA::m_sHistory", "history_setting_tree", "shared_data_access"))
    if re.search(r"\bm_sFlags\b", line):
        markers.append(("accesses_shared_data", "DLLSHAREDATA::m_sFlags", "flags_setting_tree", "shared_data_access"))
    if re.search(r"\.ini\b|szIniFileName|iniPath|GetIniFileName", line):
        markers.append(("resolves_ini_path", "sakura.ini", "ini_path_marker", "ini_path_resolution"))
    for predicate, obj, operation_kind, relation_kind in markers:
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=obj,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_config_profile_relation",
                    "semantic_phase": "sakura_config_profile_io",
                },
            )
        )
    return relations


_WINDOWS_MESSAGE_API_KINDS: dict[str, tuple[str, str, str]] = {
    "DialogBoxParam": ("creates_dialog", "modal_dialog_create", "dialog_lifecycle"),
    "DialogBox": ("creates_dialog", "modal_dialog_create", "dialog_lifecycle"),
    "CreateDialogParam": ("creates_dialog", "modeless_dialog_create", "dialog_lifecycle"),
    "CreateDialog": ("creates_dialog", "modeless_dialog_create", "dialog_lifecycle"),
    "SendMessage": ("sends_windows_message", "send_window_message", "message_send"),
    "SendMessageCmd": ("sends_windows_message", "send_command_message", "message_send"),
    "PostMessage": ("posts_windows_message", "post_window_message", "message_send"),
    "PostMessageCmd": ("posts_windows_message", "post_command_message", "message_send"),
    "DispatchMessage": ("dispatches_windows_message", "dispatch_message_loop", "message_loop"),
    "TranslateMessage": ("translates_windows_message", "translate_message_loop", "message_loop"),
    "EndDialog": ("closes_dialog", "end_dialog", "dialog_lifecycle"),
    "SetWindowSubclass": ("registers_window_subclass_callback", "set_window_subclass", "subclass_callback_registration"),
    "RemoveWindowSubclass": ("removes_window_subclass_callback", "remove_window_subclass", "subclass_callback_registration"),
}

_WINDOWS_MESSAGE_RELATION_KIND = {
    "creates_dialog": "dialog_lifecycle",
    "registers_dialog_callback": "dialog_callback_registration",
    "handles_windows_message": "message_dispatch",
    "handles_control_command": "control_command_dispatch",
    "sends_windows_message": "message_send",
    "posts_windows_message": "message_send",
    "dispatches_windows_message": "message_loop",
    "translates_windows_message": "message_loop",
    "closes_dialog": "dialog_lifecycle",
    "registers_window_subclass_callback": "subclass_callback_registration",
    "removes_window_subclass_callback": "subclass_callback_registration",
}


def _windows_message_relations_from_calls(
    path: str,
    caller: FunctionInfo,
    lineno: int,
    call_facts: list[CodeFact],
    line: str,
    symbols: list[FunctionInfo],
) -> list[CodeFact]:
    """Derive Windows message / dialog callback semantic relations from calls.

    Dialog APIs such as DialogBoxParam register a callback that Windows calls later;
    SendMessage/PostMessage bridge to message dispatch rather than acting as normal
    application call edges.  Keep these as explicit semantic relations so LLMs can
    qualify them as event/callback edges.
    """
    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, int]] = set()
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        if not callee:
            continue
        short = _short_name(callee)
        if short not in _WINDOWS_MESSAGE_API_KINDS:
            continue
        predicate, operation_kind, relation_kind = _WINDOWS_MESSAGE_API_KINDS[short]
        message_id = _first_message_id(line)
        command_id = _first_command_or_control_id(line)
        object_name = message_id or command_id or callee
        key = (caller.qualified_name, predicate, object_name, lineno)
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=object_name,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "operation_callee": callee,
                    "operation_callee_short": short,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "call_kind": fact.call_kind,
                    "call_resolution_status": fact.payload.get("resolution_status"),
                    "callee_qualified_name": fact.payload.get("callee_qualified_name") or callee,
                    "callee_symbol_id": fact.payload.get("callee_symbol_id"),
                    "message_id": message_id,
                    "command_or_control_id": command_id,
                    "edge_status": "semantic_windows_message_relation",
                    "unknown_type": "message_relation_not_unconditional_call",
                    "semantic_phase": "sakura_windows_message_dialog_callback",
                },
            )
        )
        if short in {"DialogBoxParam", "DialogBox", "CreateDialogParam", "CreateDialog"}:
            relations.extend(_dialog_callback_registration_relations(path, caller, lineno, line, short, symbols))
        if short == "SetWindowSubclass":
            relations.extend(_subclass_callback_registration_relations(path, caller, lineno, line, symbols))
    return relations


def _windows_message_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str, symbols: list[FunctionInfo]) -> list[CodeFact]:
    """Detect switch-case message/control handlers and dialog callback markers."""
    relations: list[CodeFact] = []
    if _looks_like_dialog_proc(caller):
        for m in re.finditer(r"\bcase\s+(WM_[A-Za-z0-9_]+)\s*:", line):
            message_id = m.group(1)
            relations.append(_windows_message_relation(
                path, caller, lineno,
                predicate="handles_windows_message",
                obj=message_id,
                operation_kind=f"handle_{message_id.lower()}",
                relation_kind="message_dispatch",
                extra={"message_id": message_id, "callback_kind": "dialog_proc"},
            ))
        for m in re.finditer(r"\bcase\s+((?:IDC|IDOK|IDCANCEL|ID|F)_[A-Za-z0-9_]+|IDOK|IDCANCEL)\s*:", line):
            command_id = m.group(1)
            # F_* cases in HandleCommand are handled by command dispatch; here keep
            # dialog/control handlers and command IDs sent through WM_COMMAND.
            relations.append(_windows_message_relation(
                path, caller, lineno,
                predicate="handles_control_command",
                obj=command_id,
                operation_kind=f"handle_control_{command_id.lower()}",
                relation_kind="control_command_dispatch",
                extra={"command_or_control_id": command_id, "callback_kind": "dialog_proc"},
            ))
    if re.search(r"\b(WM_INITDIALOG|WM_COMMAND|WM_NOTIFY|WM_DESTROY|WM_CLOSE)\b", line) and _looks_like_dialog_proc(caller):
        message_id = _first_message_id(line)
        if message_id:
            relations.append(_windows_message_relation(
                path, caller, lineno,
                predicate="handles_windows_message",
                obj=message_id,
                operation_kind=f"inspect_{message_id.lower()}",
                relation_kind="message_dispatch",
                extra={"message_id": message_id, "callback_kind": "dialog_proc", "marker_kind": "message_reference"},
            ))
    for api_name, predicate, operation_kind in [
        ("SendMessage", "sends_windows_message", "send_window_message"),
        ("SendMessageCmd", "sends_windows_message", "send_command_message"),
        ("PostMessage", "posts_windows_message", "post_window_message"),
        ("PostMessageCmd", "posts_windows_message", "post_command_message"),
    ]:
        if re.search(rf"\b{api_name}\s*\(", line):
            message_id = _first_message_id(line) or api_name
            relations.append(_windows_message_relation(
                path, caller, lineno,
                predicate=predicate,
                obj=message_id,
                operation_kind=operation_kind,
                relation_kind="message_send",
                extra={
                    "api_name": api_name,
                    "message_id": _first_message_id(line),
                    "command_or_control_id": _first_command_or_control_id(line),
                },
            ))
    if re.search(r"\bEndDialog\s*\(", line):
        relations.append(_windows_message_relation(
            path, caller, lineno,
            predicate="closes_dialog",
            obj=_first_command_or_control_id(line) or "EndDialog",
            operation_kind="end_dialog",
            relation_kind="dialog_lifecycle",
            extra={"api_name": "EndDialog", "command_or_control_id": _first_command_or_control_id(line)},
        ))
    return _dedupe_relation_facts(relations)


def _dialog_callback_registration_relations(path: str, caller: FunctionInfo, lineno: int, line: str, api_name: str, symbols: list[FunctionInfo]) -> list[CodeFact]:
    args = _arguments_for_call(line, api_name)
    if not args:
        return []
    candidates: list[str] = []
    # Win32 dialog APIs normally take the DLGPROC near the end.  Search all args
    # to support wrapper macros and class-qualified callback names.
    for arg in args:
        token = arg.strip().lstrip("&")
        token = re.sub(r"\b(?:DLGPROC|WNDPROC)\s*\(?\s*", "", token).strip().strip(")")
        if re.fullmatch(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*", token) and ("Proc" in token or "Dlg" in token or "Dialog" in token):
            candidates.append(token)
    facts: list[CodeFact] = []
    for callback in candidates:
        matches = _resolve_callback_symbols(callback, symbols)
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate="registers_dialog_callback",
                object=matches[0].qualified_name if len(matches) == 1 else callback,
                confidence="high" if len(matches) == 1 else "medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "dialog_callback_registration",
                    "operation_kind": "register_dialog_proc",
                    "api_name": api_name,
                    "callback_symbol": callback,
                    "callback_qualified_name": matches[0].qualified_name if len(matches) == 1 else callback,
                    "candidate_qualified_names": [s.qualified_name for s in matches] or [callback],
                    "candidate_symbol_ids": [s.symbol_id for s in matches],
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_windows_message_relation",
                    "unknown_type": "dialog_callback_not_direct_call",
                    "semantic_phase": "sakura_windows_message_dialog_callback",
                },
            )
        )
    return facts


def _subclass_callback_registration_relations(path: str, caller: FunctionInfo, lineno: int, line: str, symbols: list[FunctionInfo]) -> list[CodeFact]:
    args = _arguments_for_call(line, "SetWindowSubclass")
    if len(args) < 2:
        return []
    callback = args[1].strip().lstrip("&")
    if not re.fullmatch(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*", callback):
        return []
    matches = _resolve_callback_symbols(callback, symbols)
    return [
        CodeFact(
            fact_type="relation",
            path=path,
            start_line=lineno,
            end_line=lineno,
            subject=caller.qualified_name,
            predicate="registers_window_subclass_callback",
            object=matches[0].qualified_name if len(matches) == 1 else callback,
            confidence="high" if len(matches) == 1 else "medium",
            source="semantic_cpp_lightweight",
            payload={
                "relation_kind": "subclass_callback_registration",
                "operation_kind": "set_window_subclass_callback",
                "api_name": "SetWindowSubclass",
                "callback_symbol": callback,
                "callback_qualified_name": matches[0].qualified_name if len(matches) == 1 else callback,
                "candidate_qualified_names": [s.qualified_name for s in matches] or [callback],
                "candidate_symbol_ids": [s.symbol_id for s in matches],
                "caller_qualified_name": caller.qualified_name,
                "caller_symbol_id": caller.symbol_id,
                "edge_status": "semantic_windows_message_relation",
                "unknown_type": "subclass_callback_not_direct_call",
                "semantic_phase": "sakura_windows_message_dialog_callback",
            },
        )
    ]


def _windows_message_relation(
    path: str,
    caller: FunctionInfo,
    lineno: int,
    *,
    predicate: str,
    obj: str,
    operation_kind: str,
    relation_kind: str,
    extra: dict[str, object] | None = None,
) -> CodeFact:
    payload = {
        "relation_kind": relation_kind,
        "operation_kind": operation_kind,
        "caller_qualified_name": caller.qualified_name,
        "caller_symbol_id": caller.symbol_id,
        "edge_status": "semantic_windows_message_relation",
        "unknown_type": "message_relation_not_unconditional_call",
        "semantic_phase": "sakura_windows_message_dialog_callback",
    }
    if extra:
        payload.update(extra)
    return CodeFact(
        fact_type="relation",
        path=path,
        start_line=lineno,
        end_line=lineno,
        subject=caller.qualified_name,
        predicate=predicate,
        object=obj,
        confidence="medium",
        source="semantic_cpp_lightweight",
        payload=payload,
    )


def _looks_like_dialog_proc(fn: FunctionInfo) -> bool:
    if re.search(r"(DlgProc|DialogProc|WndProc|SubclassProc)$", fn.name):
        return True
    return any(p.type in {"HWND", "UINT", "WPARAM", "LPARAM"} for p in fn.parameters) and ("Proc" in fn.name or "Dialog" in fn.name)


def _arguments_for_call(line: str, name: str) -> list[str]:
    m = re.search(rf"\b{re.escape(name)}\s*\(", line)
    if not m:
        return []
    start = m.end()
    depth = 1
    i = start
    while i < len(line):
        ch = line[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return _split_top_level_commas(line[start:i])
        i += 1
    return []


def _resolve_callback_symbols(name: str, symbols: list[FunctionInfo]) -> list[FunctionInfo]:
    return [s for s in symbols if s.name == name or s.qualified_name == name or s.qualified_name.endswith("::" + name)]


def _first_message_id(line: str) -> str | None:
    m = re.search(r"\b(WM_[A-Za-z0-9_]+)\b", line)
    return m.group(1) if m else None


def _first_command_or_control_id(line: str) -> str | None:
    m = re.search(r"\b((?:IDC|ID|F)_[A-Za-z0-9_]+|IDOK|IDCANCEL)\b", line)
    return m.group(1) if m else None


def _dedupe_relation_facts(facts: list[CodeFact]) -> list[CodeFact]:
    seen: set[tuple[str | None, str | None, str | None, int]] = set()
    out: list[CodeFact] = []
    for fact in facts:
        key = (fact.subject, fact.predicate, fact.object, fact.start_line)
        if key in seen:
            continue
        seen.add(key)
        out.append(fact)
    return out



_EXTENSION_EXECUTION_CALLS = {
    "Append": ("records_macro_command", "record_key_macro_command", "macro_recording"),
    "Exec": ("executes_macro", "execute_macro_buffer_or_file", "macro_execution"),
    "ExecKeyMacro2": ("executes_macro", "execute_loaded_macro", "macro_execution"),
    "Load": ("loads_macro", "load_macro_entry", "macro_loading"),
    "LoadKeyMacro": ("loads_macro", "load_macro_file", "macro_loading"),
    "LoadKeyMacroStr": ("loads_macro", "load_macro_string", "macro_loading"),
    "Save": ("saves_macro", "save_macro_entry", "macro_persistence"),
    "SaveKeyMacro": ("saves_macro", "save_key_macro", "macro_persistence"),
    "Create": ("creates_macro_manager", "macro_factory_create", "macro_loading"),
    "RegisterPlug": ("registers_plugin_hook", "register_plugin_to_jack", "plugin_registration"),
    "UnRegisterPlug": ("unregisters_plugin_hook", "unregister_plugin_from_jack", "plugin_registration"),
    "GetUsablePlug": ("enumerates_plugin_hook", "get_usable_plugin_hooks", "plugin_lookup"),
    "Invoke": ("invokes_plugin_hook", "invoke_plugin_object", "plugin_execution"),
    "InvokePlugins": ("invokes_plugin_hook", "invoke_plugins_for_jack", "plugin_execution"),
    "GetCommandCode": ("maps_plugin_command_id", "plugin_command_index_to_function_code", "plugin_command_mapping"),
    "GetCommandById": ("maps_plugin_command_id", "plugin_command_id_to_plugin", "plugin_command_mapping"),
    "GetPluginFunctionCode": ("maps_plugin_command_id", "plugin_function_code_mapping", "plugin_command_mapping"),
    "ShellExecute": ("launches_external_process", "shell_execute_external_target", "external_process"),
    "ShellExecuteW": ("launches_external_process", "shell_execute_external_target", "external_process"),
    "ShellExecuteEx": ("launches_external_process", "shell_execute_external_target", "external_process"),
    "ShellExecuteExW": ("launches_external_process", "shell_execute_external_target", "external_process"),
    "CreateProcess": ("launches_external_process", "create_process_external_command", "external_process"),
    "CreateProcessW": ("launches_external_process", "create_process_external_command", "external_process"),
    "WinExec": ("launches_external_process", "winexec_external_command", "external_process"),
    "OpenNewEditor": ("launches_external_process", "open_new_editor_process_or_window", "external_process"),
}

_EXTENSION_EXECUTION_PREDICATE_KIND = {
    "records_macro_command": "macro_recording",
    "executes_macro": "macro_execution",
    "loads_macro": "macro_loading",
    "saves_macro": "macro_persistence",
    "creates_macro_manager": "macro_loading",
    "maps_macro_function": "macro_function_mapping",
    "registers_plugin_hook": "plugin_registration",
    "unregisters_plugin_hook": "plugin_registration",
    "enumerates_plugin_hook": "plugin_lookup",
    "invokes_plugin_hook": "plugin_execution",
    "maps_plugin_command_id": "plugin_command_mapping",
    "launches_external_process": "external_process",
}


def _extension_execution_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact], line: str) -> list[CodeFact]:
    """Derive macro/plugin/external-process semantic relations from calls.

    These are intentionally not unconditional call-path claims.  A macro Exec
    runs a loaded script/key macro, plugin Invoke enters a dynamically registered
    extension, and ShellExecute/CreateProcess cross the process boundary.
    """
    relations: list[CodeFact] = []
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        short = _short_name(callee)
        rule = _EXTENSION_EXECUTION_CALLS.get(short)
        if not rule:
            # Chained calls can be captured as the outer API name in object/callee.
            for api_name, candidate_rule in _EXTENSION_EXECUTION_CALLS.items():
                if re.search(rf"\b{re.escape(api_name)}\s*\(", line):
                    short = api_name
                    rule = candidate_rule
                    break
        if not rule:
            continue
        predicate, operation_kind, category = rule
        if short == "Create" and "CMacroFactory" not in line and "macro" not in caller.qualified_name.lower():
            continue
        relations.append(_extension_execution_relation(
            path,
            lineno,
            subject=caller.qualified_name,
            predicate=predicate,
            obj=callee or short,
            operation_kind=operation_kind,
            category=category,
            extra={
                "caller_qualified_name": caller.qualified_name,
                "callee_qualified_name": callee,
                "api_name": short,
            },
        ))
    return relations


def _extension_execution_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    relations: list[CodeFact] = []

    # Sakura records commands into key macros through CSMacroMgr::Append and
    # later replays them through Exec/ExecKeyMacro2.  Receiver resolution may be
    # incomplete for member fields such as m_pcSMacroMgr, so keep lexical markers.
    if re.search(r"\b(?:m_pcSMacroMgr|CSMacroMgr::getInstance\s*\(\)|CSMacroMgr)\s*(?:->|\.|::)\s*Append\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="records_macro_command",
            obj="CSMacroMgr::Append",
            operation_kind="record_key_macro_command",
            category="macro_recording",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if re.search(r"\b(?:m_pcSMacroMgr|CSMacroMgr::getInstance\s*\(\)|CSMacroMgr)\s*(?:->|\.|::)\s*Exec\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="executes_macro",
            obj="CSMacroMgr::Exec",
            operation_kind="execute_macro_from_command",
            category="macro_execution",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if "BeReloadWhenExecuteMacro" in line or "GetMacroFilename" in line:
        operation = "check_macro_reload_policy" if "BeReloadWhenExecuteMacro" in line else "resolve_macro_filename"
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="loads_macro",
            obj="CShareData::macro_configuration",
            operation_kind=operation,
            category="macro_loading",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if re.search(r"\bCMacroFactory::getInstance\s*\(\)\s*->\s*Create\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="creates_macro_manager",
            obj="CMacroFactory::Create",
            operation_kind="macro_factory_create",
            category="macro_loading",
            extra={"caller_qualified_name": caller.qualified_name},
        ))

    # Plugin jack manager patterns: plugins are registered into jacks and later
    # discovered/invoked by event category or plugin command id.
    if re.search(r"\bRegisterPlug\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="registers_plugin_hook",
            obj="CJackManager::RegisterPlug",
            operation_kind="register_plugin_to_jack",
            category="plugin_registration",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if "CJackManager::RegisterPlug" in caller.qualified_name and ("plugs.push_back" in line or "plugs.insert" in line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="registers_plugin_hook",
            obj="CJackManager::RegisterPlug",
            operation_kind="register_plugin_to_jack",
            category="plugin_registration",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if re.search(r"\bGetUsablePlug\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="enumerates_plugin_hook",
            obj="CJackManager::GetUsablePlug",
            operation_kind="get_usable_plugin_hooks",
            category="plugin_lookup",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if re.search(r"(?:->|\.)\s*Invoke\s*\(", line) or re.search(r"\bInvokePlugins\s*\(", line):
        relations.append(_extension_execution_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="invokes_plugin_hook",
            obj="CPlug::Invoke",
            operation_kind="invoke_plugin_object",
            category="plugin_execution",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    if "PP_COMMAND" in line or "GetCommandCode" in line or "GetCommandById" in line or "GetPluginFunctionCode" in line or ("CJackManager" in caller.qualified_name and "GetFunctionCode" in line):
        if re.search(r"\b(GetCommandCode|GetCommandById|GetPluginFunctionCode|GetFunctionCode)\s*\(", line) or "PP_COMMAND" in line:
            relations.append(_extension_execution_relation(
                path, lineno,
                subject=caller.qualified_name,
                predicate="maps_plugin_command_id",
                obj="plugin_command_function_code",
                operation_kind="plugin_command_id_mapping",
                category="plugin_command_mapping",
                extra={"caller_qualified_name": caller.qualified_name},
            ))

    for api_name, operation_kind in [
        ("ShellExecute", "shell_execute_external_target"),
        ("ShellExecuteW", "shell_execute_external_target"),
        ("ShellExecuteEx", "shell_execute_external_target"),
        ("ShellExecuteExW", "shell_execute_external_target"),
        ("CreateProcess", "create_process_external_command"),
        ("CreateProcessW", "create_process_external_command"),
        ("WinExec", "winexec_external_command"),
        ("OpenNewEditor", "open_new_editor_process_or_window"),
    ]:
        if re.search(rf"\b{re.escape(api_name)}\s*\(", line):
            relations.append(_extension_execution_relation(
                path, lineno,
                subject=caller.qualified_name,
                predicate="launches_external_process",
                obj=api_name,
                operation_kind=operation_kind,
                category="external_process",
                extra={"caller_qualified_name": caller.qualified_name, "api_name": api_name},
            ))
    return relations


def _macro_function_binding_relations(path: str, lines: list[str]) -> list[CodeFact]:
    """Extract Sakura CSMacroMgr's F_* -> macro function-name table entries."""
    facts: list[CodeFact] = []
    in_macro_table = False
    for lineno, line in enumerate(lines, start=1):
        if "MacroFuncInfo" in line and "m_MacroFuncInfo" in line and "[]" in line:
            in_macro_table = True
            continue
        if in_macro_table and re.match(r"\s*};", line):
            in_macro_table = False
            continue
        if not in_macro_table:
            continue
        m = re.search(r"\{\s*(F_[A-Za-z0-9_]+)\s*,\s*L\"([^\"]+)\"", line)
        if not m:
            continue
        command_id, macro_name = m.group(1), m.group(2)
        facts.append(_extension_execution_relation(
            path,
            lineno,
            subject=command_id,
            predicate="maps_macro_function",
            obj=macro_name,
            operation_kind="macro_function_table_binding",
            category="macro_function_mapping",
            extra={"command_id": command_id, "macro_function_name": macro_name, "resource_table": "CSMacroMgr::m_MacroFuncInfoCommandArr"},
        ))
    return facts


def _extension_execution_relation(
    path: str,
    lineno: int,
    *,
    subject: str,
    predicate: str,
    obj: str,
    operation_kind: str,
    category: str,
    extra: dict | None = None,
) -> CodeFact:
    payload = {
        "relation_kind": _EXTENSION_EXECUTION_PREDICATE_KIND.get(predicate, category),
        "operation_kind": operation_kind,
        "execution_category": category,
        "edge_status": "semantic_extension_execution_relation",
        "unknown_type": "extension_execution_not_unconditional_direct_call",
        "semantic_phase": "sakura_extension_execution",
    }
    if extra:
        payload.update(extra)
    return CodeFact(
        fact_type="relation",
        path=path,
        start_line=lineno,
        end_line=lineno,
        subject=subject,
        predicate=predicate,
        object=obj,
        confidence="medium",
        source="semantic_cpp_lightweight",
        payload=payload,
    )

_TINYUSB_DESCRIPTOR_MACROS: dict[str, dict[str, object]] = {
    "TUD_CONFIG_DESCRIPTOR": {
        "descriptor_kind": "configuration",
        "predicate": "defines_configuration_descriptor",
        "arg_names": ("config_num", "interface_count", "string_index", "total_length", "attributes", "power_ma"),
    },
    "TUD_CDC_DESCRIPTOR": {
        "descriptor_kind": "interface",
        "usb_class": "CDC",
        "predicate": "defines_class_interface_descriptor",
        "arg_names": ("interface_number", "string_index", "endpoint_notification", "endpoint_notification_size", "endpoint_out", "endpoint_in", "endpoint_size"),
        "interface_arg_names": ("interface_number",),
        "endpoint_arg_names": ("endpoint_notification", "endpoint_out", "endpoint_in"),
    },
    "TUD_MSC_DESCRIPTOR": {
        "descriptor_kind": "interface",
        "usb_class": "MSC",
        "predicate": "defines_class_interface_descriptor",
        "arg_names": ("interface_number", "string_index", "endpoint_out", "endpoint_in", "endpoint_size"),
        "interface_arg_names": ("interface_number",),
        "endpoint_arg_names": ("endpoint_out", "endpoint_in"),
    },
    "TUD_HID_DESCRIPTOR": {
        "descriptor_kind": "interface",
        "usb_class": "HID",
        "predicate": "defines_class_interface_descriptor",
        "arg_names": ("interface_number", "string_index", "protocol", "report_descriptor_len", "endpoint_in", "endpoint_size", "polling_interval"),
        "interface_arg_names": ("interface_number",),
        "endpoint_arg_names": ("endpoint_in",),
    },
    "TUD_HID_REPORT_DESC_KEYBOARD": {
        "descriptor_kind": "hid_report",
        "usb_class": "HID",
        "predicate": "defines_hid_report_descriptor_item",
        "arg_names": ("report_id",),
        "report_kind": "keyboard",
    },
    "TUD_HID_REPORT_DESC_MOUSE": {
        "descriptor_kind": "hid_report",
        "usb_class": "HID",
        "predicate": "defines_hid_report_descriptor_item",
        "arg_names": ("report_id",),
        "report_kind": "mouse",
    },
    "TUD_HID_REPORT_DESC_CONSUMER": {
        "descriptor_kind": "hid_report",
        "usb_class": "HID",
        "predicate": "defines_hid_report_descriptor_item",
        "arg_names": ("report_id",),
        "report_kind": "consumer",
    },
    "TUD_HID_REPORT_DESC_GAMEPAD": {
        "descriptor_kind": "hid_report",
        "usb_class": "HID",
        "predicate": "defines_hid_report_descriptor_item",
        "arg_names": ("report_id",),
        "report_kind": "gamepad",
    },
    "TUD_HID_REPORT_DESC_STYLUS_PEN": {
        "descriptor_kind": "hid_report",
        "usb_class": "HID",
        "predicate": "defines_hid_report_descriptor_item",
        "arg_names": ("report_id",),
        "report_kind": "stylus_pen",
    },
}

_TINYUSB_DESCRIPTOR_CALLBACK_KINDS = {
    "tud_descriptor_device_cb": "device",
    "tud_descriptor_configuration_cb": "configuration",
    "tud_descriptor_string_cb": "string",
    "tud_descriptor_bos_cb": "bos",
    "tud_descriptor_hid_report_cb": "hid_report",
    "tud_hid_descriptor_report_cb": "hid_report",
    "tud_descriptor_device_qualifier_cb": "device_qualifier",
}



_TINYUSB_CALLBACK_LIFECYCLE_NAMES = {
    "tud_mount_cb": "mount",
    "tud_umount_cb": "umount",
    "tud_suspend_cb": "suspend",
    "tud_resume_cb": "resume",
}



_TINYUSB_USBD_DRIVER_TABLES = {"_usbd_driver"}
_TINYUSB_DRIVER_FIELD_FALLBACK = ("name", "init", "open", "xfer_cb")
_TINYUSB_DRIVER_CLASS_TO_CFG = {
    "CDC": "CFG_TUD_CDC",
    "MSC": "CFG_TUD_MSC",
    "HID": "CFG_TUD_HID",
    "MIDI": "CFG_TUD_MIDI",
    "VENDOR": "CFG_TUD_VENDOR",
    "AUDIO": "CFG_TUD_AUDIO",
    "VIDEO": "CFG_TUD_VIDEO",
    "DFU": "CFG_TUD_DFU",
    "ECM_RNDIS": "CFG_TUD_ECM_RNDIS",
    "NCM": "CFG_TUD_NCM",
}

_TINYUSB_HOST_DRIVER_CLASS_TO_CFG = {
    "CDC": "CFG_TUH_CDC",
    "MSC": "CFG_TUH_MSC",
    "HID": "CFG_TUH_HID",
    "HUB": "CFG_TUH_HUB",
    "MIDI": "CFG_TUH_MIDI",
    "MIDI2": "CFG_TUH_MIDI2",
    "VENDOR": "CFG_TUH_VENDOR",
}


def _tinyusb_driver_dispatch_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract TinyUSB device class-driver dispatch and endpoint binding evidence.

    TinyUSB routes descriptors and transfer-complete events through a class-driver
    table rather than direct calls.  These facts deliberately describe semantic
    bindings and possible dispatch targets; they are not proof that a particular
    USB runtime event occurs on every path.
    """
    # Keep this extractor scoped to the device stack. Host files also use
    # itf2drv/ep2drv/get_driver, but their dispatch model is emitted as
    # tinyusb_host_runtime evidence to avoid mixing tud/usbd and tuh/usbh roles.
    if "_usbd_driver" not in text:
        return []
    lines = text.splitlines()
    facts: list[CodeFact] = []
    driver_entries = _tinyusb_usbd_driver_entries(path, text, model)
    facts.extend(driver_entries)
    facts.extend(_tinyusb_driver_callback_binding_facts(path, driver_entries, model))
    facts.extend(_tinyusb_endpoint_interface_map_facts(path, lines))
    facts.extend(_tinyusb_endpoint_interface_bind_call_facts(path, text, model))
    facts.extend(_tinyusb_indirect_driver_dispatch_facts(path, lines, model))
    return facts


def _tinyusb_usbd_driver_entries(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    table = _tinyusb_find_initializer_block(text, "_usbd_driver")
    if table is None:
        return []
    start, end = table
    table_text = text[start:end]
    field_order = _tinyusb_driver_struct_field_order(text) or list(_TINYUSB_DRIVER_FIELD_FALLBACK)
    facts: list[CodeFact] = []
    seen: set[tuple[str, int]] = set()
    for rel_start, rel_end, body in _tinyusb_initializer_entries(table_text):
        entry_start = start + rel_start
        entry_end = start + rel_end
        start_line = text.count("\n", 0, entry_start) + 1
        end_line = text.count("\n", 0, entry_end) + 1
        callbacks, driver_class = _tinyusb_parse_driver_entry_body(body, field_order)
        if not driver_class:
            continue
        key = (driver_class, start_line)
        if key in seen:
            continue
        seen.add(key)
        config_macro = _tinyusb_driver_config_macro(driver_class, text, entry_start)
        callback_symbols = [name for field, name in callbacks.items() if field != "name" and _tinyusb_is_callback_symbol(name)]
        payload = {
            "relation_kind": "tinyusb_class_driver_table_entry",
            "semantic_phase": "phase7_tinyusb_class_driver_dispatch_semantics",
            "driver_table": "_usbd_driver",
            "usb_role": "device",
            "driver_class": driver_class,
            "usb_class": driver_class,
            "class_name": driver_class,
            "config_macro": config_macro,
            "callbacks": callbacks,
            "callback_fields": [field for field, value in callbacks.items() if field != "name" and _tinyusb_is_callback_symbol(value)],
            "callback_symbols": callback_symbols,
            "resolution_status": "semantic_relation",
            "dispatch_model": "class_driver_table",
            "unknown_type": "class_driver_entry_runtime_selection_depends_on_descriptor",
            "response_constraint": "TinyUSB class-driver table evidence maps enabled classes to callback function pointers; descriptor parsing and runtime USB events determine which callbacks execute.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_driver_dispatch",
                path=path,
                start_line=start_line,
                end_line=end_line,
                subject=driver_class,
                predicate="declares_class_driver_entry",
                object="_usbd_driver",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _tinyusb_find_initializer_block(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(rf"\b{name}\s*\[\s*\]\s*=\s*\{{", text)
    if not match:
        return None
    open_brace = text.find("{", match.start())
    if open_brace < 0:
        return None
    depth = 0
    for i in range(open_brace, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return open_brace + 1, i
    return None


def _tinyusb_initializer_entries(table_text: str) -> list[tuple[int, int, str]]:
    entries: list[tuple[int, int, str]] = []
    depth = 0
    entry_start: int | None = None
    for i, ch in enumerate(table_text):
        if ch == "{":
            depth += 1
            if depth == 1:
                entry_start = i
        elif ch == "}":
            if depth == 1 and entry_start is not None:
                entries.append((entry_start, i + 1, table_text[entry_start + 1:i]))
                entry_start = None
            if depth > 0:
                depth -= 1
    return entries


def _tinyusb_driver_struct_field_order(text: str) -> list[str]:
    m = re.search(r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*usbd_class_driver_t\s*;", text, flags=re.DOTALL)
    if not m:
        return list(_TINYUSB_DRIVER_FIELD_FALLBACK)
    fields: list[str] = []
    for raw_line in m.group("body").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        fp = re.search(r"\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\(", line)
        if fp:
            fields.append(fp.group("name"))
            continue
        normal = re.search(r"\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;", line)
        if normal:
            fields.append(normal.group("name"))
    return fields or list(_TINYUSB_DRIVER_FIELD_FALLBACK)


def _tinyusb_parse_driver_entry_body(body: str, field_order: list[str]) -> tuple[dict[str, str], str | None]:
    callbacks: dict[str, str] = {}
    designated = list(re.finditer(r"\.(?P<field>[A-Za-z_]\w*)\s*=\s*(?P<value>[^,}\n]+)", body))
    if designated:
        for m in designated:
            callbacks[m.group("field")] = _tinyusb_clean_driver_value(m.group("value"))
    else:
        values = [_tinyusb_clean_driver_value(value) for value in _split_top_level_commas(body)]
        for field, value in zip(field_order, values):
            callbacks[field] = value
    driver_class = _tinyusb_driver_class_from_callbacks(callbacks)
    return callbacks, driver_class


def _tinyusb_clean_driver_value(value: str) -> str:
    value = value.strip().rstrip(",")
    value = re.sub(r"/\*.*?\*/", "", value).strip()
    m = re.match(r'DRIVER_NAME\s*\(\s*"(?P<name>[^"]+)"\s*\)', value)
    if m:
        return m.group("name")
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value.lstrip("&").strip()


def _tinyusb_driver_class_from_callbacks(callbacks: dict[str, str]) -> str | None:
    name = callbacks.get("name") or callbacks.get("driver")
    if name and name not in {"NULL", "0"}:
        return name.upper()
    for value in callbacks.values():
        m = re.match(r"(?P<prefix>[a-z]+)d?_", value)
        if not m:
            continue
        prefix = m.group("prefix")
        if prefix.startswith("cdc"):
            return "CDC"
        if prefix.startswith("msc"):
            return "MSC"
        if prefix.startswith("hid"):
            return "HID"
    return None


def _tinyusb_driver_config_macro(driver_class: str, text: str, entry_start: int) -> str | None:
    mapped = _TINYUSB_DRIVER_CLASS_TO_CFG.get(driver_class.upper())
    if mapped:
        return mapped
    prefix = text[max(0, entry_start - 250):entry_start]
    matches = re.findall(r"#\s*if\s+(CFG_TUD_[A-Za-z0-9_]+)", prefix)
    return matches[-1] if matches else None


def _tinyusb_is_callback_symbol(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.fullmatch(r"[A-Za-z_]\w*", value)) and value not in {"NULL", "null", "nullptr", "0", "true", "false"}


def _tinyusb_driver_callback_binding_facts(path: str, driver_entries: list[CodeFact], model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    symbol_by_name: dict[str, list[FunctionInfo]] = {}
    for fn in model.functions:
        symbol_by_name.setdefault(fn.name, []).append(fn)
    for entry in driver_entries:
        callbacks = dict(entry.payload.get("callbacks") or {})
        driver_class = str(entry.payload.get("driver_class") or entry.subject or "")
        for field, symbol in callbacks.items():
            if field == "name" or not _tinyusb_is_callback_symbol(symbol):
                continue
            candidates = symbol_by_name.get(symbol, [])
            payload = {
                "relation_kind": "tinyusb_driver_callback_binding",
                "semantic_phase": "phase7_tinyusb_class_driver_dispatch_semantics",
                "driver_table": entry.payload.get("driver_table") or "_usbd_driver",
                "usb_role": "device",
                "driver_class": driver_class,
                "usb_class": driver_class,
                "class_name": driver_class,
                "config_macro": entry.payload.get("config_macro"),
                "callback_field": field,
                "callback_symbol": symbol,
                "callback_qualified_name": candidates[0].qualified_name if len(candidates) == 1 else symbol,
                "candidate_qualified_names": [fn.qualified_name for fn in candidates] or [symbol],
                "candidate_symbol_ids": [fn.symbol_id for fn in candidates],
                "driver_entry_line": entry.start_line,
                "resolution_status": "resolved" if len(candidates) == 1 else ("candidate_set" if candidates else "unresolved"),
                "dispatch_model": "class_driver_table",
                "unknown_type": "function_pointer_dispatch_not_direct_call",
                "response_constraint": "TinyUSB driver callback bindings are function-pointer targets selected through the class-driver table, not unconditional direct calls.",
            }
            facts.append(
                CodeFact(
                    fact_type="tinyusb_driver_dispatch",
                    path=path,
                    start_line=entry.start_line,
                    end_line=entry.end_line,
                    subject=driver_class,
                    predicate="binds_driver_callback",
                    object=symbol,
                    confidence="high" if candidates else "medium",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                )
            )
    return facts


def _tinyusb_endpoint_interface_map_facts(path: str, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for lineno, line in enumerate(lines, start=1):
        for map_name, map_kind, predicate in (
            ("itf2drv", "interface_to_driver_map", "declares_interface_driver_map"),
            ("ep2drv", "endpoint_to_driver_map", "declares_endpoint_driver_map"),
        ):
            if not re.search(rf"^\s*uint8_t\s+{map_name}\s*\[", line):
                continue
            payload = {
                "relation_kind": "tinyusb_endpoint_interface_driver_map",
                "semantic_phase": "phase7_tinyusb_class_driver_dispatch_semantics",
                "map_name": map_name,
                "map_kind": map_kind,
                "usb_role": "device",
                "resolution_status": "semantic_relation",
                "dispatch_model": "endpoint_interface_driver_lookup",
                "unknown_type": "map_contents_runtime_descriptor_dependent",
                "response_constraint": "TinyUSB interface/endpoint maps identify dispatch lookup storage; actual entries depend on descriptor parsing and runtime configuration.",
            }
            facts.append(
                CodeFact(
                    fact_type="tinyusb_driver_dispatch",
                    path=path,
                    start_line=lineno,
                    end_line=lineno,
                    subject=map_name,
                    predicate=predicate,
                    object=map_kind,
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload=payload,
                )
            )
    return facts


def _tinyusb_endpoint_interface_bind_call_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for match in re.finditer(r"tu_bind_driver_to_ep_itf\s*\(", text):
        args, end_pos = _tinyusb_call_args_at(text, match.end() - 1)
        if args is None:
            continue
        start_line = text.count("\n", 0, match.start()) + 1
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.start())
        if line_end < 0:
            line_end = len(text)
        current_line = text[line_start:line_end]
        trailer = text[end_pos + 1: min(len(text), end_pos + 8)]
        if re.search(r"^\s*(?:static\s+)?(?:bool|void|uint(?:8|16|32)_t|int)\b", current_line) and "{" in trailer:
            continue
        end_line = text.count("\n", 0, end_pos) + 1
        caller = _tinyusb_function_at_line(model, start_line)
        endpoint_map = _tinyusb_arg_containing(args, "ep2drv")
        interface_map = _tinyusb_arg_containing(args, "itf2drv")
        descriptor_arg = args[4] if len(args) > 4 else None
        length_arg = args[5] if len(args) > 5 else None
        payload = {
            "relation_kind": "tinyusb_endpoint_interface_binding",
            "semantic_phase": "phase7_tinyusb_class_driver_dispatch_semantics",
            "binding_api": "tu_bind_driver_to_ep_itf",
            "caller": caller.display_name if caller else None,
            "caller_qualified_name": caller.qualified_name if caller else None,
            "driver_id_arg": args[0] if args else None,
            "endpoint_map": endpoint_map,
            "interface_map": interface_map,
            "max_interface_arg": args[3] if len(args) > 3 else None,
            "descriptor_arg": descriptor_arg,
            "descriptor_length_arg": length_arg,
            "argument_expressions": args,
            "binds_endpoint_map": bool(endpoint_map),
            "binds_interface_map": bool(interface_map),
            "usb_role": "device",
            "resolution_status": "semantic_relation",
            "dispatch_model": "descriptor_open_binds_driver_to_endpoint_interface",
            "unknown_type": "descriptor_parse_runtime_path_dependent",
            "response_constraint": "tu_bind_driver_to_ep_itf evidence links an opened class driver id to endpoint/interface maps, but descriptor content and runtime enumeration determine concrete map values.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_driver_dispatch",
                path=path,
                start_line=start_line,
                end_line=end_line,
                subject=args[0] if args else "driver_id",
                predicate="binds_driver_to_endpoint_interface_maps",
                object="tu_bind_driver_to_ep_itf",
                confidence="high" if endpoint_map and interface_map else "medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _tinyusb_call_args_at(text: str, open_paren_pos: int) -> tuple[list[str] | None, int]:
    if open_paren_pos < 0 or open_paren_pos >= len(text) or text[open_paren_pos] != "(":
        return None, open_paren_pos
    depth = 0
    for i in range(open_paren_pos, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return _split_top_level_commas(text[open_paren_pos + 1:i]), i
    return None, open_paren_pos


def _tinyusb_arg_containing(args: list[str], token: str) -> str | None:
    for arg in args:
        if token in arg:
            return arg.strip()
    return None


def _tinyusb_function_at_line(model: SemanticModel, line: int) -> FunctionInfo | None:
    for fn in model.functions:
        if fn.start_line <= line <= fn.end_line:
            return fn
    return None


def _tinyusb_indirect_driver_dispatch_facts(path: str, lines: list[str], model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = "\n".join(lines[max(fn.start_line - 1, 0):fn.end_line])
        if "get_driver" not in fn_text and "->" not in fn_text:
            continue
        for rel_index, line in enumerate(lines[max(fn.start_line - 1, 0):fn.end_line], start=fn.start_line):
            for m in re.finditer(r"(?P<receiver>[A-Za-z_]\w*)\s*->\s*(?P<field>[A-Za-z_]\w*)\s*\(", line):
                field = m.group("field")
                if field not in {"open", "xfer_cb", "control_xfer_cb", "init", "deinit", "reset", "sof", "xfer_isr"}:
                    continue
                context_lines = lines[max(fn.start_line - 1, rel_index - 3):rel_index]
                context = "\n".join(context_lines + [line])
                map_kind = None
                map_name = None
                if "ep2drv" in context:
                    map_kind = "endpoint_to_driver_map"
                    map_name = "ep2drv"
                elif "itf2drv" in context:
                    map_kind = "interface_to_driver_map"
                    map_name = "itf2drv"
                payload = {
                    "relation_kind": "tinyusb_indirect_driver_dispatch",
                    "semantic_phase": "phase7_tinyusb_class_driver_dispatch_semantics",
                    "dispatch_function": fn.display_name,
                    "dispatch_function_qualified_name": fn.qualified_name,
                    "dispatch_receiver": m.group("receiver"),
                    "callback_field": field,
                    "via_function": "get_driver" if "get_driver" in context or "get_driver" in fn_text else None,
                    "map_name": map_name,
                    "map_kind": map_kind,
                    "uses_endpoint_map": map_name == "ep2drv",
                    "uses_interface_map": map_name == "itf2drv",
                    "usb_role": "device",
                    "resolution_status": "indirect_dispatch_site",
                    "dispatch_model": "get_driver_table_lookup_then_function_pointer_call",
                    "unknown_type": "function_pointer_dispatch_target_depends_on_runtime_driver_id",
                    "response_constraint": "Indirect TinyUSB driver dispatch evidence identifies a callback field call through get_driver(); it is not a direct call to every concrete class callback.",
                }
                facts.append(
                    CodeFact(
                        fact_type="tinyusb_driver_dispatch",
                        path=path,
                        start_line=rel_index,
                        end_line=rel_index,
                        subject=fn.display_name,
                        predicate="indirect_dispatches_to_driver_callback",
                        object=field,
                        confidence="high" if payload.get("via_function") else "medium",
                        source="semantic_cpp_lightweight",
                        payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                    )
                )
    return facts


_TINYUSB_ENDPOINT_RUNTIME_APIS = {
    "usbd_edpt_claim": ("endpoint_claim", "claim"),
    "usbd_edpt_release": ("endpoint_release", "release"),
    "usbd_edpt_busy": ("endpoint_busy_check", "busy_check"),
    "usbd_edpt_xfer": ("endpoint_transfer_submit", "submit"),
    "usbd_edpt_stall": ("endpoint_stall_state", "stall"),
    "usbd_edpt_clear_stall": ("endpoint_stall_state", "clear_stall"),
}

_TINYUSB_DCD_RUNTIME_APIS = {
    "dcd_edpt_xfer": ("dcd_transfer_submit_boundary", "submit"),
    "dcd_edpt_stall": ("dcd_endpoint_stall_boundary", "stall"),
    "dcd_edpt_clear_stall": ("dcd_endpoint_clear_stall_boundary", "clear_stall"),
    "dcd_edpt_open": ("dcd_endpoint_open_boundary", "open"),
    "dcd_event_handler": ("dcd_event_producer", "event_submit"),
    "dcd_event_xfer_complete": ("endpoint_transfer_complete_event", "complete"),
}

_TINYUSB_OSAL_QUEUE_APIS = {
    "osal_queue_send": ("osal_queue_send", "producer"),
    "osal_queue_receive": ("osal_queue_receive", "consumer"),
}


def _tinyusb_device_runtime_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract TinyUSB device runtime, event queue, OSAL, and DCD boundary evidence.

    Batch 5 intentionally stays on the device-side runtime path.  These facts
    describe semantic stages such as async endpoint transfer submit, hardware
    controller boundary calls, ISR/event deferral through OSAL queues, and
    ``tud_task`` event consumption.  They are not full USB protocol proofs.
    """
    if not any(token in text for token in ("usbd_edpt_", "dcd_edpt_", "dcd_event_", "osal_queue_", "OSAL_QUEUE", "tud_task")):
        return []
    lines = text.splitlines()
    facts: list[CodeFact] = []
    facts.extend(_tinyusb_endpoint_runtime_api_facts(path, text, model, lines))
    facts.extend(_tinyusb_dcd_runtime_boundary_facts(path, text, model, lines))
    facts.extend(_tinyusb_osal_queue_facts(path, text, model, lines))
    facts.extend(_tinyusb_device_event_task_facts(path, text, model, lines))
    return facts


def _tinyusb_function_text(lines: list[str], fn: FunctionInfo) -> str:
    return "\n".join(lines[max(fn.start_line - 1, 0):fn.end_line])


def _tinyusb_endpoint_runtime_api_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in _TINYUSB_ENDPOINT_RUNTIME_APIS:
            continue
        predicate, stage = _TINYUSB_ENDPOINT_RUNTIME_APIS[fn.name]
        fn_text = _tinyusb_function_text(lines, fn)
        calls_dcd_xfer = "dcd_edpt_xfer" in fn_text
        calls_dcd = sorted(set(re.findall(r"\b(dcd_edpt_[A-Za-z_0-9]+)\s*\(", fn_text)))
        payload = {
            "relation_kind": "tinyusb_endpoint_runtime_api",
            "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
            "runtime_model": "device_endpoint_async_transfer_lifecycle",
            "usb_role": "device",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "transfer_lifecycle_stage": stage,
            "endpoint_state_operation": stage,
            "calls_dcd_api": bool(calls_dcd),
            "dcd_api_calls": calls_dcd,
            "dcd_transfer_api": "dcd_edpt_xfer" if calls_dcd_xfer else None,
            "is_async_transfer_submit": fn.name == "usbd_edpt_xfer",
            "resolution_status": "semantic_relation",
            "unknown_type": "usb_transfer_completion_depends_on_dcd_event",
            "response_constraint": "TinyUSB usbd_edpt_* evidence describes core endpoint runtime intent; transfer completion is asynchronous and depends on later DCD events.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_device_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate=predicate,
                object="async_transfer_request" if fn.name == "usbd_edpt_xfer" else "endpoint_state",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _tinyusb_dcd_runtime_boundary_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in _TINYUSB_DCD_RUNTIME_APIS:
            continue
        predicate, stage = _TINYUSB_DCD_RUNTIME_APIS[fn.name]
        fn_text = _tinyusb_function_text(lines, fn)
        calls_osal_send = "osal_queue_send" in fn_text
        dispatches_xfer_cb = "xfer_cb" in fn_text and "get_driver" in fn_text
        payload = {
            "relation_kind": "tinyusb_dcd_runtime_boundary",
            "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
            "runtime_model": "dcd_event_and_controller_boundary",
            "usb_role": "device",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "transfer_lifecycle_stage": stage,
            "hardware_boundary": fn.name.startswith("dcd_edpt_"),
            "controller_port_path": _tinyusb_controller_port_path(path),
            "selected_controller_port": _tinyusb_controller_port_path(path),
            "event_queue_api": "osal_queue_send" if calls_osal_send else None,
            "queues_event": calls_osal_send,
            "dispatches_class_xfer_callback": dispatches_xfer_cb,
            "resolution_status": "semantic_relation",
            "unknown_type": "hardware_register_semantics_unknown" if fn.name.startswith("dcd_edpt_") else "event_runtime_order_depends_on_usb_interrupts",
            "response_constraint": "DCD evidence marks the portable USB-controller boundary; register-level behavior and interrupt timing remain target-specific.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_device_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate=predicate,
                object="hardware_controller_boundary" if fn.name.startswith("dcd_edpt_") else "event_queue",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _tinyusb_osal_queue_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        m = re.search(r"\bOSAL_QUEUE_DEF\s*\(\s*(?P<name>[A-Za-z_]\w*)", line)
        if not m:
            m = re.search(r"\bosal_queue_t\s+(?P<name>[A-Za-z_]\w*)\b", line)
        if not m:
            continue
        queue_name = m.group("name")
        payload = {
            "relation_kind": "tinyusb_osal_queue_definition",
            "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
            "runtime_model": "device_event_queue",
            "usb_role": "device",
            "queue_name": queue_name,
            "osal_profile": _tinyusb_osal_profile(path, text),
            "config_macro": "CFG_TUSB_OS",
            "resolution_status": "semantic_relation",
            "unknown_type": "osal_backend_semantics_depend_on_cfg_tusb_os",
            "response_constraint": "TinyUSB OSAL queue evidence is scoped to the selected CFG_TUSB_OS backend; scheduling behavior differs across OSAL implementations.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_device_runtime",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=queue_name,
                predicate="declares_osal_event_queue",
                object="osal_queue",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload=payload,
            )
        )
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in _TINYUSB_OSAL_QUEUE_APIS:
            continue
        predicate, role = _TINYUSB_OSAL_QUEUE_APIS[fn.name]
        payload = {
            "relation_kind": "tinyusb_osal_queue_api",
            "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
            "runtime_model": "device_event_queue",
            "usb_role": "device",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "queue_operation": role,
            "osal_profile": _tinyusb_osal_profile(path, text),
            "config_macro": "CFG_TUSB_OS",
            "resolution_status": "semantic_relation",
            "unknown_type": "osal_backend_semantics_depend_on_cfg_tusb_os",
            "response_constraint": "OSAL queue API evidence marks producer/consumer roles but not exact scheduler timing for every backend.",
        }
        facts.append(
            CodeFact(
                fact_type="tinyusb_device_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate=predicate,
                object="event_queue",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload=payload,
            )
        )
    return facts


def _tinyusb_device_event_task_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        if fn.name in {"tud_task", "tud_task_ext"} and "osal_queue_receive" in fn_text:
            payload = {
                "relation_kind": "tinyusb_device_event_task",
                "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
                "runtime_model": "dcd_event_queue_to_tud_task_dispatch",
                "usb_role": "device",
                "task_function": fn.name,
                "queue_api": "osal_queue_receive",
                "consumes_event_queue": True,
                "dispatches_transfer_complete": "dcd_event_xfer_complete" in fn_text,
                "event_dispatch_model": "queued_dcd_events_consumed_by_tud_task",
                "resolution_status": "semantic_relation",
                "unknown_type": "event_order_depends_on_runtime_usb_events",
                "response_constraint": "tud_task evidence shows queued event consumption; concrete event ordering depends on runtime USB interrupts and application polling/scheduling.",
            }
            facts.append(
                CodeFact(
                    fact_type="tinyusb_device_runtime",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject=fn.name,
                    predicate="consumes_dcd_event_queue",
                    object="osal_queue_receive",
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload=payload,
                )
            )
        if fn.name == "dcd_event_handler" and "osal_queue_send" in fn_text:
            payload = {
                "relation_kind": "tinyusb_dcd_event_defer",
                "semantic_phase": "phase7_tinyusb_device_runtime_semantics",
                "runtime_model": "isr_to_task_event_defer",
                "usb_role": "device",
                "event_source": "dcd_event_handler",
                "queue_api": "osal_queue_send",
                "defer_model": "dcd_event_handler_enqueues_for_tud_task",
                "isr_safe_arg_detected": "in_isr" in fn_text,
                "resolution_status": "semantic_relation",
                "unknown_type": "isr_context_depends_on_dcd_caller",
                "response_constraint": "dcd_event_handler evidence shows event deferral into the OSAL queue; whether a given call is ISR context depends on the DCD caller and in_isr argument.",
            }
            facts.append(
                CodeFact(
                    fact_type="tinyusb_device_runtime",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject="dcd_event_handler",
                    predicate="defers_dcd_event_to_task_queue",
                    object="osal_queue_send",
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload=payload,
                )
            )
    return facts


def _tinyusb_controller_port_path(path: str) -> str | None:
    normalized = path.replace("\\", "/")
    m = re.search(r"(src/portable/[^/]+/[^/]+)", normalized)
    return m.group(1) if m else None


def _tinyusb_osal_profile(path: str, text: str) -> str:
    if "osal_none" in path.replace("\\", "/") or "osal_none.h" in text:
        return "none"
    if "OPT_OS_NONE" in text or "CFG_TUSB_OS=OPT_OS_NONE" in text:
        return "none"
    if "OPT_OS_FREERTOS" in text:
        return "freertos"
    if "OPT_OS_PICO" in text:
        return "pico"
    if "OPT_OS_ZEPHYR" in text:
        return "zephyr"
    return "unknown"



def _tinyusb_host_runtime_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract TinyUSB host-stack enumeration, HCD, queue, and class dispatch evidence.

    The host stack has a different runtime model from the device stack: HCD
    events are queued for ``tuh_task()``, enumeration is a control-transfer
    state machine, and class dispatch goes through ``usbh_class_drivers[]`` plus
    per-device ``itf2drv``/``ep2drv`` maps.  These facts intentionally describe
    possible semantic routes for the selected host target, not proof that a
    physical device is attached at runtime.
    """
    if not any(token in text for token in (
        "usbh_class_drivers", "tuh_task", "hcd_event_handler", "process_enumeration",
        "enum_new_device", "hcd_edpt_xfer", "hcd_init", "_usbh_q",
    )):
        return []
    lines = text.splitlines()
    facts: list[CodeFact] = []
    host_entries = _tinyusb_host_class_driver_entries(path, text, model)
    facts.extend(host_entries)
    facts.extend(_tinyusb_host_driver_callback_binding_facts(path, host_entries, model))
    facts.extend(_tinyusb_host_endpoint_interface_map_facts(path, lines))
    facts.extend(_tinyusb_host_endpoint_interface_bind_call_facts(path, text, model))
    facts.extend(_tinyusb_host_event_queue_facts(path, text, model, lines))
    facts.extend(_tinyusb_host_hcd_boundary_facts(path, text, model, lines))
    facts.extend(_tinyusb_host_task_dispatch_facts(path, text, model, lines))
    facts.extend(_tinyusb_host_enumeration_facts(path, text, model, lines))
    return facts


def _tinyusb_host_class_driver_entries(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    table = _tinyusb_find_initializer_block(text, "usbh_class_drivers")
    if table is None:
        return []
    start, end = table
    table_text = text[start:end]
    field_order = _tinyusb_host_driver_struct_field_order(text) or [
        "name", "init", "deinit", "open", "set_config", "xfer_cb", "close",
    ]
    facts: list[CodeFact] = []
    seen: set[tuple[str, int]] = set()
    for rel_start, rel_end, body in _tinyusb_initializer_entries(table_text):
        entry_start = start + rel_start
        entry_end = start + rel_end
        start_line = text.count("\n", 0, entry_start) + 1
        end_line = text.count("\n", 0, entry_end) + 1
        callbacks, driver_class = _tinyusb_parse_driver_entry_body(body, field_order)
        if not driver_class:
            continue
        key = (driver_class, start_line)
        if key in seen:
            continue
        seen.add(key)
        config_macro = _TINYUSB_HOST_DRIVER_CLASS_TO_CFG.get(driver_class.upper())
        callback_symbols = [name for field, name in callbacks.items() if field != "name" and _tinyusb_is_callback_symbol(name)]
        payload = {
            "relation_kind": "tinyusb_host_class_driver_table_entry",
            "semantic_phase": "phase7_tinyusb_host_stack_semantics",
            "driver_table": "usbh_class_drivers",
            "usb_role": "host",
            "driver_class": driver_class,
            "usb_class": driver_class,
            "class_name": driver_class,
            "config_macro": config_macro,
            "callbacks": callbacks,
            "callback_fields": [field for field, value in callbacks.items() if field != "name" and _tinyusb_is_callback_symbol(value)],
            "callback_symbols": callback_symbols,
            "resolution_status": "semantic_relation",
            "dispatch_model": "host_class_driver_table",
            "unknown_type": "host_class_driver_runtime_selection_depends_on_connected_device_descriptor",
            "response_constraint": "TinyUSB host class-driver table evidence maps enabled host classes to callback function pointers; runtime enumeration determines which callbacks execute.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_host_runtime",
            path=path,
            start_line=start_line,
            end_line=end_line,
            subject=driver_class,
            predicate="declares_host_class_driver_entry",
            object="usbh_class_drivers",
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_host_driver_struct_field_order(text: str) -> list[str]:
    m = re.search(r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*usbh_class_driver_t\s*;", text, flags=re.DOTALL)
    if not m:
        return []
    fields: list[str] = []
    for raw_line in m.group("body").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        fp = re.search(r"\(\s*\*\s*(?P<name>[A-Za-z_]\w*)\s*\)\s*\(", line)
        if fp:
            fields.append(fp.group("name"))
            continue
        normal = re.search(r"\b(?P<name>[A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*;", line)
        if normal:
            fields.append(normal.group("name"))
    return fields


def _tinyusb_host_driver_callback_binding_facts(path: str, host_entries: list[CodeFact], model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    symbol_by_name: dict[str, list[FunctionInfo]] = {}
    for fn in model.functions:
        symbol_by_name.setdefault(fn.name, []).append(fn)
    for entry in host_entries:
        callbacks = dict(entry.payload.get("callbacks") or {})
        driver_class = str(entry.payload.get("driver_class") or entry.subject or "")
        for field, symbol in callbacks.items():
            if field == "name" or not _tinyusb_is_callback_symbol(symbol):
                continue
            candidates = symbol_by_name.get(symbol, [])
            payload = {
                "relation_kind": "tinyusb_host_driver_callback_binding",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "driver_table": "usbh_class_drivers",
                "usb_role": "host",
                "driver_class": driver_class,
                "usb_class": driver_class,
                "class_name": driver_class,
                "config_macro": entry.payload.get("config_macro"),
                "callback_field": field,
                "callback_symbol": symbol,
                "callback_qualified_name": candidates[0].qualified_name if len(candidates) == 1 else symbol,
                "candidate_qualified_names": [fn.qualified_name for fn in candidates] or [symbol],
                "candidate_symbol_ids": [fn.symbol_id for fn in candidates],
                "driver_entry_line": entry.start_line,
                "resolution_status": "resolved" if len(candidates) == 1 else "semantic_relation",
                "dispatch_model": "host_class_driver_table",
                "unknown_type": "host_function_pointer_dispatch_not_direct_call",
                "response_constraint": "Treat host class-driver callback bindings as possible dispatch targets selected during enumeration or transfer-complete handling.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=entry.start_line,
                end_line=entry.end_line,
                subject=driver_class,
                predicate="binds_host_driver_callback",
                object=symbol,
                confidence="high" if candidates else "medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
    return facts


def _tinyusb_host_endpoint_interface_map_facts(path: str, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    patterns = [
        ("itf2drv", "interface_to_driver_map", "declares_host_interface_driver_map"),
        ("ep2drv", "endpoint_to_driver_map", "declares_host_endpoint_driver_map"),
    ]
    for idx, line in enumerate(lines, start=1):
        for token, map_kind, predicate in patterns:
            if token not in line or "[" not in line:
                continue
            payload = {
                "relation_kind": "tinyusb_host_endpoint_interface_driver_map",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "map_name": token,
                "map_kind": map_kind,
                "declaration_text": line.strip(),
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=idx,
                end_line=idx,
                subject=token,
                predicate=predicate,
                object=map_kind,
                confidence="high",
                source="semantic_cpp_lightweight",
                payload=payload,
            ))
    return facts


def _tinyusb_host_endpoint_interface_bind_call_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for match in re.finditer(r"\btu_bind_driver_to_ep_itf\s*\(", text):
        args, end_pos = _tinyusb_call_args_at(text, match.end() - 1)
        if not args:
            continue
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = text.count("\n", 0, end_pos) + 1
        caller = _tinyusb_function_at_line(model, start_line)
        endpoint_map = _tinyusb_arg_containing(args, "ep2drv")
        interface_map = _tinyusb_arg_containing(args, "itf2drv")
        payload = {
            "relation_kind": "tinyusb_host_endpoint_interface_binding",
            "semantic_phase": "phase7_tinyusb_host_stack_semantics",
            "usb_role": "host",
            "bind_api": "tu_bind_driver_to_ep_itf",
            "caller_function": caller.name if caller else None,
            "caller_qualified_name": caller.qualified_name if caller else None,
            "driver_id_expression": args[0].strip() if args else None,
            "endpoint_map": endpoint_map,
            "interface_map": interface_map,
            "binds_endpoint_map": endpoint_map is not None,
            "binds_interface_map": interface_map is not None,
            "descriptor_context": "host_configuration_descriptor_parse",
            "resolution_status": "semantic_relation",
            "unknown_type": "host_driver_binding_depends_on_connected_device_descriptor",
            "response_constraint": "Host endpoint/interface binding is created only after enumeration parses a connected device's configuration descriptor.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_host_runtime",
            path=path,
            start_line=start_line,
            end_line=end_line,
            subject=(args[0].strip() if args else "driver_id"),
            predicate="binds_host_driver_to_endpoint_interface_maps",
            object="tu_bind_driver_to_ep_itf",
            confidence="high" if endpoint_map and interface_map else "medium",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_host_event_queue_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for idx, line in enumerate(lines, start=1):
        for match in re.finditer(r"\b(?:OSAL_QUEUE_DEF|osal_queue_def_t)\s*\(?\s*(?P<name>_usbh_[A-Za-z0-9_]*q(?:def)?)", line):
            name = match.group("name")
            queue_name = "_usbh_q" if name == "_usbh_qdef" else name
            payload = {
                "relation_kind": "tinyusb_host_osal_queue_definition",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "queue_name": queue_name,
                "queue_def": name,
                "queue_role": "hcd_event_queue",
                "osal_profile": _tinyusb_osal_profile(path, text),
                "config_macro": "CFG_TUSB_OS",
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=idx,
                end_line=idx,
                subject=queue_name,
                predicate="declares_host_osal_event_queue",
                object="osal_queue",
                confidence="medium" if path.endswith(".h") else "high",
                source="semantic_cpp_lightweight",
                payload=payload,
            ))
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        if fn.name == "hcd_event_handler" and "osal_queue_send" in fn_text:
            payload = {
                "relation_kind": "tinyusb_host_hcd_event_defer",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "event_source": "HCD",
                "queue_api": "osal_queue_send",
                "queue_name": "_usbh_q" if "_usbh_q" in fn_text else None,
                "defer_model": "hcd_event_handler_enqueues_for_tuh_task",
                "queues_event": True,
                "isr_safe_arg_detected": "in_isr" in fn_text,
                "runtime_model": "hcd_event_queue_to_tuh_task_dispatch",
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject="hcd_event_handler",
                predicate="defers_hcd_event_to_host_queue",
                object="osal_queue_send",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
        if fn.name in {"tuh_task", "tuh_task_ext"} and "osal_queue_receive" in fn_text:
            payload = {
                "relation_kind": "tinyusb_host_task_event_dispatch",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "task_function": fn.name,
                "queue_api": "osal_queue_receive",
                "queue_name": "_usbh_q" if "_usbh_q" in fn_text else None,
                "consumes_event_queue": True,
                "handles_device_attach": "HCD_EVENT_DEVICE_ATTACH" in fn_text,
                "handles_transfer_complete": "HCD_EVENT_XFER_COMPLETE" in fn_text,
                "dispatches_enumeration": "enum_new_device" in fn_text,
                "dispatches_class_xfer_callback": "driver->xfer_cb" in fn_text,
                "runtime_model": "hcd_event_queue_to_tuh_task_dispatch",
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="consumes_hcd_event_queue",
                object="osal_queue_receive",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
    return facts


def _tinyusb_host_hcd_boundary_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    api_meta = {
        "hcd_init": ("hcd_init_boundary", "init"),
        "hcd_deinit": ("hcd_deinit_boundary", "deinit"),
        "hcd_int_enable": ("hcd_interrupt_enable_boundary", "interrupt_enable"),
        "hcd_int_disable": ("hcd_interrupt_disable_boundary", "interrupt_disable"),
        "hcd_port_reset": ("hcd_port_reset_boundary", "port_reset"),
        "hcd_edpt_open": ("hcd_endpoint_open_boundary", "endpoint_open"),
        "hcd_edpt_xfer": ("hcd_transfer_submit_boundary", "submit"),
        "tuh_edpt_xfer": ("host_endpoint_transfer_submit", "submit"),
    }
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in api_meta:
            continue
        predicate, stage = api_meta[fn.name]
        fn_text = _tinyusb_function_text(lines, fn)
        dcd_calls = sorted(set(re.findall(r"\b(hcd_[A-Za-z_]\w*)\s*\(", fn_text)))
        payload = {
            "relation_kind": "tinyusb_host_hcd_runtime_boundary" if fn.name.startswith("hcd_") else "tinyusb_host_endpoint_runtime_api",
            "semantic_phase": "phase7_tinyusb_host_stack_semantics",
            "usb_role": "host",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "transfer_lifecycle_stage": stage,
            "hcd_transfer_api": "hcd_edpt_xfer" if fn.name == "tuh_edpt_xfer" else fn.name,
            "hcd_api_calls": dcd_calls,
            "hardware_boundary": fn.name.startswith("hcd_"),
            "controller_port_path": _tinyusb_controller_port_path(path) if fn.name.startswith("hcd_") else None,
            "selected_controller_port": _tinyusb_controller_port_path(path) if fn.name.startswith("hcd_") else None,
            "runtime_model": "host_controller_boundary" if fn.name.startswith("hcd_") else "host_endpoint_async_transfer",
            "resolution_status": "semantic_relation",
            "unknown_type": "host_controller_register_semantics_unknown" if fn.name.startswith("hcd_") else "host_transfer_completion_depends_on_hcd_event",
            "response_constraint": "Host controller operations cross into the selected HCD port; register-level behavior is target-specific." if fn.name.startswith("hcd_") else "Host endpoint transfer submit is asynchronous; completion is reported later as HCD_EVENT_XFER_COMPLETE.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_host_runtime",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate=predicate,
            object="host_controller_boundary" if fn.name.startswith("hcd_") else "async_host_transfer_request",
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_host_task_dispatch_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        if fn.name in {"tuh_task", "tuh_task_ext"} and "driver->xfer_cb" in fn_text:
            payload = {
                "relation_kind": "tinyusb_host_indirect_driver_dispatch",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "dispatch_function": fn.name,
                "dispatch_function_qualified_name": fn.qualified_name,
                "callback_field": "xfer_cb",
                "callback_expression": "driver->xfer_cb",
                "via_function": "get_driver" if "get_driver" in fn_text else None,
                "map_name": "ep2drv" if "ep2drv" in fn_text else None,
                "map_kind": "endpoint_to_driver_map" if "ep2drv" in fn_text else None,
                "uses_endpoint_map": "ep2drv" in fn_text,
                "event_id": "HCD_EVENT_XFER_COMPLETE",
                "dispatches_class_xfer_callback": True,
                "runtime_model": "host_hcd_event_xfer_complete_to_class_driver_callback",
                "resolution_status": "semantic_relation",
                "unknown_type": "host_indirect_dispatch_depends_on_endpoint_binding_and_runtime_event",
                "response_constraint": "Host transfer-complete dispatch is indirect through the endpoint-to-driver map populated during enumeration.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="host_indirect_dispatches_to_driver_callback",
                object="xfer_cb",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
    return facts


def _tinyusb_host_enumeration_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    stage_apis = [
        ("tuh_descriptor_get_device", "get_device_descriptor"),
        ("tuh_address_set", "set_address"),
        ("tuh_descriptor_get_configuration", "get_configuration_descriptor"),
        ("tuh_configuration_set", "set_configuration"),
        ("enum_parse_configuration_desc", "parse_configuration_descriptor"),
        ("usbh_driver_set_config_complete", "configure_class_drivers"),
        ("tuh_mount_cb", "mount_callback"),
    ]
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        if fn.name == "enum_new_device":
            payload = {
                "relation_kind": "tinyusb_host_enumeration_entry",
                "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                "usb_role": "host",
                "enumeration_stage": "new_device_attach",
                "entry_event": "HCD_EVENT_DEVICE_ATTACH",
                "next_state_function": "process_enumeration" if "process_enumeration" in text else None,
                "runtime_model": "host_enumeration_state_machine",
                "resolution_status": "semantic_relation",
                "unknown_type": "host_enumeration_requires_runtime_device_attach",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_host_runtime",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject="enum_new_device",
                predicate="starts_host_enumeration",
                object="HCD_EVENT_DEVICE_ATTACH",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
        if fn.name in {"process_enumeration", "usbh_driver_set_config_complete"}:
            present = [(api, stage) for api, stage in stage_apis if api in fn_text]
            for api, stage in present:
                payload = {
                    "relation_kind": "tinyusb_host_enumeration_stage",
                    "semantic_phase": "phase7_tinyusb_host_stack_semantics",
                    "usb_role": "host",
                    "state_machine_function": fn.name,
                    "enumeration_stage": stage,
                    "stage_api": api,
                    "continuation_callback": "process_enumeration" if "process_enumeration" in fn_text else None,
                    "runtime_model": "host_enumeration_state_machine",
                    "resolution_status": "semantic_relation",
                    "unknown_type": "host_enumeration_stage_depends_on_control_transfer_result",
                    "response_constraint": "Host enumeration stage evidence identifies the state-machine step; success/failure depends on runtime USB control transfers.",
                }
                facts.append(CodeFact(
                    fact_type="tinyusb_host_runtime",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject=api,
                    predicate="host_enumeration_stage",
                    object=stage,
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                ))
    return facts



def _tinyusb_class_protocol_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract CDC/MSC/HID class-specific protocol evidence.

    Batch 7 keeps this as a layer above generic descriptor/runtime evidence:
    CDC stream/line-state APIs, MSC SCSI callbacks, and HID report descriptor
    and report/control callbacks are class-protocol facts rather than proof of
    a concrete USB transaction occurring at runtime.
    """
    if not any(token in text for token in ("tud_cdc", "tud_msc", "tud_hid", "TUD_HID", "REPORT_ID_", "SCSI", "read10", "write10")):
        return []
    lines = text.splitlines()
    facts: list[CodeFact] = []
    facts.extend(_tinyusb_cdc_class_protocol_facts(path, text, model))
    facts.extend(_tinyusb_msc_class_protocol_facts(path, text, model))
    facts.extend(_tinyusb_hid_class_protocol_facts(path, text, model, lines))
    return facts


_TINYUSB_CDC_PROTOCOL_APIS = {
    "tud_cdc_available": ("cdc_rx_available", "rx"),
    "tud_cdc_read": ("cdc_read", "out"),
    "tud_cdc_write": ("cdc_write", "in"),
    "tud_cdc_write_flush": ("cdc_write_flush", "in"),
    "tud_cdc_line_state_cb": ("cdc_line_state", "control"),
    "tud_cdc_line_coding_cb": ("cdc_line_coding", "control"),
    "tud_cdc_rx_cb": ("cdc_rx_callback", "out"),
    "tud_cdc_tx_complete_cb": ("cdc_tx_complete", "in"),
}


def _tinyusb_cdc_class_protocol_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in _TINYUSB_CDC_PROTOCOL_APIS:
            continue
        operation, direction = _TINYUSB_CDC_PROTOCOL_APIS[fn.name]
        is_callback = fn.name.endswith("_cb")
        payload = {
            "relation_kind": "tinyusb_cdc_class_protocol",
            "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
            "usb_class": "CDC",
            "class_name": "CDC",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "callback_name": fn.name if is_callback else None,
            "callback_qualified_name": fn.qualified_name if is_callback else None,
            "protocol_operation": operation,
            "protocol_stage": "callback" if is_callback else "application_api",
            "transfer_direction": direction,
            "line_state_semantics": fn.name == "tud_cdc_line_state_cb",
            "line_coding_semantics": fn.name == "tud_cdc_line_coding_cb",
            "stream_api": not is_callback,
            "resolution_status": "semantic_relation",
            "unknown_type": "cdc_class_protocol_runtime_depends_on_host_control_or_data_transfer",
            "response_constraint": "CDC class-protocol evidence identifies stream APIs and line-state/line-coding callbacks; host control requests and endpoint traffic determine when they run.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_class_protocol",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate="declares_cdc_callback" if is_callback else "declares_cdc_stream_api",
            object=operation,
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


_TINYUSB_MSC_CALLBACKS = {
    "tud_msc_read10_cb": ("READ10", "read", "out_to_host"),
    "tud_msc_write10_cb": ("WRITE10", "write", "host_to_device"),
    "tud_msc_scsi_cb": ("SCSI", "vendor_scsi", "bidirectional"),
    "tud_msc_inquiry_cb": ("INQUIRY", "inquiry", "device_to_host"),
    "tud_msc_test_unit_ready_cb": ("TEST_UNIT_READY", "ready_check", "control"),
    "tud_msc_capacity_cb": ("READ_CAPACITY", "capacity", "device_to_host"),
    "tud_msc_start_stop_cb": ("START_STOP_UNIT", "start_stop", "control"),
}


def _tinyusb_msc_class_protocol_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition" or fn.name not in _TINYUSB_MSC_CALLBACKS:
            continue
        scsi_command, operation, direction = _TINYUSB_MSC_CALLBACKS[fn.name]
        payload = {
            "relation_kind": "tinyusb_msc_class_protocol",
            "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
            "usb_class": "MSC",
            "class_name": "MSC",
            "callback_name": fn.name,
            "callback_qualified_name": fn.qualified_name,
            "protocol_operation": operation,
            "protocol_stage": "class_callback",
            "scsi_command": scsi_command,
            "transfer_direction": direction,
            "block_storage_callback": True,
            "resolution_status": "semantic_relation",
            "unknown_type": "msc_scsi_command_execution_depends_on_host_bot_transaction",
            "response_constraint": "MSC class-protocol evidence maps callbacks to SCSI/BOT command roles; it does not prove a host issues that command at runtime.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_class_protocol",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate="declares_msc_scsi_callback",
            object=scsi_command,
            confidence="high",
            source="semantic_cpp_lightweight",
            payload=payload,
        ))
    return facts


_TINYUSB_HID_REPORT_API_KINDS = {
    "tud_hid_report": "generic",
    "tud_hid_n_report": "generic",
    "tud_hid_keyboard_report": "keyboard",
    "tud_hid_n_keyboard_report": "keyboard",
    "tud_hid_mouse_report": "mouse",
    "tud_hid_n_mouse_report": "mouse",
    "tud_hid_abs_mouse_report": "abs_mouse",
    "tud_hid_n_abs_mouse_report": "abs_mouse",
    "tud_hid_gamepad_report": "gamepad",
    "tud_hid_n_gamepad_report": "gamepad",
    "tud_hid_stylus_report": "stylus_pen",
    "tud_hid_n_stylus_report": "stylus_pen",
}

_TINYUSB_HID_CONTROL_CALLBACKS = {
    "tud_hid_descriptor_report_cb": ("hid_report_descriptor", "descriptor"),
    "tud_hid_get_report_cb": ("get_report", "control_in"),
    "tud_hid_set_report_cb": ("set_report", "control_out"),
    "tud_hid_report_complete_cb": ("report_complete", "in_complete"),
    "tud_hid_report_failed_cb": ("report_failed", "transfer_error"),
    "tud_hid_set_protocol_cb": ("set_protocol", "control_out"),
    "tud_hid_set_idle_cb": ("set_idle", "control_out"),
}


def _tinyusb_hid_class_protocol_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    report_ids = _tinyusb_hid_report_ids(lines)
    report_kinds_by_line = _tinyusb_hid_report_descriptor_items(lines)
    if report_kinds_by_line:
        first_line = min((line for line, _, _ in report_kinds_by_line), default=1)
        payload = {
            "relation_kind": "tinyusb_hid_report_descriptor_map",
            "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
            "usb_class": "HID",
            "class_name": "HID",
            "descriptor_kind": "hid_report",
            "report_ids": list(report_ids.keys()),
            "resolved_report_ids": report_ids,
            "report_kinds": [kind for _, kind, _ in report_kinds_by_line],
            "resolution_status": "semantic_relation",
            "unknown_type": "hid_report_descriptor_byte_layout_not_fully_validated",
            "response_constraint": "HID report descriptor evidence identifies report IDs and macro-level report kinds, but it is not a full HID report descriptor validator.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_class_protocol",
            path=path,
            start_line=first_line,
            end_line=first_line,
            subject="HID",
            predicate="declares_hid_report_descriptor_map",
            object="hid_report_descriptor",
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    for lineno, kind, report_id in report_kinds_by_line:
        payload = {
            "relation_kind": "tinyusb_hid_report_descriptor_item",
            "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
            "usb_class": "HID",
            "class_name": "HID",
            "descriptor_kind": "hid_report",
            "report_kind": kind,
            "report_id": report_id,
            "resolved_report_id": report_ids.get(report_id),
            "protocol_operation": "report_descriptor_item",
            "resolution_status": "semantic_relation",
            "unknown_type": "hid_report_descriptor_byte_layout_not_fully_validated",
            "response_constraint": "HID report descriptor item evidence preserves report kind/report-id intent without validating the final byte sequence.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_class_protocol",
            path=path,
            start_line=lineno,
            end_line=lineno,
            subject=report_id or kind,
            predicate="declares_hid_report_descriptor_item",
            object=kind,
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        if fn.name in _TINYUSB_HID_REPORT_API_KINDS:
            report_kind = _TINYUSB_HID_REPORT_API_KINDS[fn.name]
            fn_text = _tinyusb_function_text(lines, fn)
            calls_xfer = "usbd_edpt_xfer" in fn_text or "tud_hid_n_report" in fn_text
            payload = {
                "relation_kind": "tinyusb_hid_report_api",
                "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
                "usb_class": "HID",
                "class_name": "HID",
                "api_name": fn.name,
                "api_qualified_name": fn.qualified_name,
                "protocol_operation": "submit_report",
                "protocol_stage": "application_api",
                "report_kind": report_kind,
                "transfer_direction": "in",
                "calls_endpoint_transfer": calls_xfer,
                "protocol_apis": sorted(set(re.findall(r"\b(tud_hid_[A-Za-z_]\w*)\s*\(", fn_text))),
                "resolution_status": "semantic_relation",
                "unknown_type": "hid_report_submit_depends_on_device_ready_and_endpoint_state",
                "response_constraint": "HID report API evidence describes report submission intent; actual transfer depends on device readiness and endpoint state.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_class_protocol",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="declares_hid_report_api",
                object=report_kind,
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
        if fn.name in _TINYUSB_HID_CONTROL_CALLBACKS:
            operation, direction = _TINYUSB_HID_CONTROL_CALLBACKS[fn.name]
            payload = {
                "relation_kind": "tinyusb_hid_control_callback",
                "semantic_phase": "phase7_tinyusb_class_protocol_semantics",
                "usb_class": "HID",
                "class_name": "HID",
                "callback_name": fn.name,
                "callback_qualified_name": fn.qualified_name,
                "protocol_operation": operation,
                "protocol_stage": "class_callback",
                "transfer_direction": direction,
                "descriptor_kind": "hid_report" if operation == "hid_report_descriptor" else None,
                "resolution_status": "semantic_relation",
                "unknown_type": "hid_control_callback_depends_on_host_request_or_transfer_completion",
                "response_constraint": "HID callback evidence identifies host-control/transfer-complete hooks; it does not prove a host requests each report at runtime.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_class_protocol",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="declares_hid_control_callback",
                object=operation,
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
    return facts


def _tinyusb_hid_report_ids(lines: list[str]) -> dict[str, int]:
    values = _tinyusb_descriptor_symbol_values(lines)
    return {name: value for name, value in values.items() if name.startswith("REPORT_ID_") and isinstance(value, int)}


def _tinyusb_hid_report_descriptor_items(lines: list[str]) -> list[tuple[int, str, str | None]]:
    items: list[tuple[int, str, str | None]] = []
    kind_by_macro = {
        "TUD_HID_REPORT_DESC_KEYBOARD": "keyboard",
        "TUD_HID_REPORT_DESC_MOUSE": "mouse",
        "TUD_HID_REPORT_DESC_CONSUMER": "consumer",
        "TUD_HID_REPORT_DESC_GAMEPAD": "gamepad",
        "TUD_HID_REPORT_DESC_STYLUS_PEN": "stylus_pen",
    }
    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        for macro, kind in kind_by_macro.items():
            for args_text in _macro_invocation_arg_texts(line, macro):
                report_id = None
                m = re.search(r"\b(REPORT_ID_[A-Za-z0-9_]+)\b", args_text)
                if m:
                    report_id = m.group(1)
                items.append((lineno, kind, report_id))
    return items


_TINYUSB_TCD_BOUNDARY_APIS = {
    "tcd_init": ("tcd_init_boundary", "init"),
    "tcd_int_enable": ("tcd_interrupt_enable_boundary", "interrupt_enable"),
    "tcd_int_disable": ("tcd_interrupt_disable_boundary", "interrupt_disable"),
    "tcd_connect": ("tcd_connect_boundary", "connect"),
    "tcd_disconnect": ("tcd_disconnect_boundary", "disconnect"),
    "tcd_msg_receive": ("tcd_message_receive_boundary", "receive"),
    "tcd_msg_send": ("tcd_message_send_boundary", "send"),
}

_TINYUSB_TUC_APIS = {
    "tuc_init": ("typec_stack_init", "init"),
    "tuc_connect": ("typec_port_connect", "connect"),
    "tuc_disconnect": ("typec_port_disconnect", "disconnect"),
    "tuc_msg_request": ("builds_pd_request_message", "request"),
    "usbc_msg_send": ("pd_message_send", "send"),
}

_TINYUSB_TCD_EVENTS = {
    "TCD_EVENT_CC_CHANGED": "cc_changed",
    "TCD_EVENT_RX_COMPLETE": "rx_complete",
    "TCD_EVENT_TX_COMPLETE": "tx_complete",
}


def _tinyusb_typec_pd_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract TinyUSB Type-C / USB-PD stack evidence.

    Batch 8 keeps Type-C/PD separate from device/host/class evidence.  These
    facts describe the Type-C controller boundary (TCD), USBC event queue/task,
    PD message parsing/building, and application policy callbacks.  They are
    intentionally not a full USB-PD policy-engine proof.
    """
    if not any(token in text for token in ("tuc_", "usbc_", "tcd_", "TCD_EVENT", "PD_DATA_", "PD_CTRL_", "pd_header_t")):
        return []
    lines = text.splitlines()
    facts: list[CodeFact] = []
    facts.extend(_tinyusb_typec_api_facts(path, text, model, lines))
    facts.extend(_tinyusb_tcd_boundary_facts(path, text, model, lines))
    facts.extend(_tinyusb_typec_event_queue_facts(path, text, model, lines))
    facts.extend(_tinyusb_pd_message_policy_facts(path, text, model, lines))
    facts.extend(_tinyusb_tcd_event_api_facts(path, text, model, lines))
    return facts


def _tinyusb_function_has_prefix(lines: list[str], fn: FunctionInfo, token: str) -> bool:
    for lineno in range(max(fn.start_line - 3, 1), fn.start_line + 1):
        if 1 <= lineno <= len(lines) and token in lines[lineno - 1]:
            return True
    return False


def _tinyusb_typec_api_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.name not in _TINYUSB_TUC_APIS:
            continue
        if fn.declaration_or_definition != "definition":
            continue
        predicate, stage = _TINYUSB_TUC_APIS[fn.name]
        fn_text = _tinyusb_function_text(lines, fn)
        tcd_calls = sorted(set(re.findall(r"\b(tcd_[A-Za-z_]\w*)\s*\(", fn_text)))
        pd_header = _tinyusb_pd_header_initializer(fn_text)
        payload = {
            "relation_kind": "tinyusb_typec_stack_api",
            "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
            "usb_role": "typec_pd",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "protocol_stage": stage,
            "runtime_model": "typec_usbc_stack_to_tcd_boundary",
            "tcd_api_calls": tcd_calls,
            "uses_osal_queue": "osal_queue_create" in fn_text,
            "calls_tcd_init": "tcd_init" in tcd_calls,
            "calls_tcd_interrupt_enable": "tcd_int_enable" in tcd_calls,
            "calls_tcd_connect": "tcd_connect" in tcd_calls,
            "calls_tcd_disconnect": "tcd_disconnect" in tcd_calls,
            "calls_tcd_msg_send": "tcd_msg_send" in tcd_calls,
            "pd_header_fields": pd_header,
            "pd_message_type": pd_header.get("msg_type") if pd_header else None,
            "power_role": pd_header.get("power_role") if pd_header else None,
            "data_role": pd_header.get("data_role") if pd_header else None,
            "spec_revision": pd_header.get("specs_rev") if pd_header else None,
            "data_object_count": pd_header.get("n_data_obj") if pd_header else None,
            "resolution_status": "semantic_relation",
            "unknown_type": "typec_pd_policy_depends_on_runtime_partner" if fn.name.startswith("tuc_msg") else "typec_controller_behavior_depends_on_tcd_port",
            "response_constraint": "TinyUSB Type-C/PD API evidence identifies stack intent and TCD boundary calls; negotiated power/data roles depend on the runtime PD partner and controller port.",
        }
        obj = payload.get("pd_message_type") or (tcd_calls[0] if tcd_calls else stage)
        facts.append(CodeFact(
            fact_type="tinyusb_typec_pd",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate=predicate,
            object=str(obj),
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_tcd_boundary_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.name not in _TINYUSB_TCD_BOUNDARY_APIS:
            continue
        # TCD boundary evidence is strongest at definitions in the selected
        # controller port or weak fallback definitions.  Declarations in tcd.h
        # are intentionally skipped here to avoid downgrading active port
        # support to conditional when a matching definition is available.
        if fn.declaration_or_definition != "definition":
            continue
        predicate, stage = _TINYUSB_TCD_BOUNDARY_APIS[fn.name]
        payload = {
            "relation_kind": "tinyusb_typec_tcd_boundary",
            "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
            "usb_role": "typec_pd",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "protocol_stage": stage,
            "declaration_or_definition": fn.declaration_or_definition,
            "hardware_boundary": True,
            "controller_port_path": _tinyusb_controller_port_path(path),
            "selected_controller_port": _tinyusb_controller_port_path(path),
            "runtime_model": "typec_controller_driver_boundary",
            "resolution_status": "semantic_relation",
            "unknown_type": "typec_controller_register_semantics_unknown",
            "response_constraint": "TCD evidence marks the Type-C controller-driver boundary; CC/PD PHY behavior and registers are target-specific.",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_typec_pd",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate=predicate,
            object="typec_controller_boundary",
            confidence="high" if fn.declaration_or_definition == "definition" else "medium",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_typec_event_queue_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for lineno, line in enumerate(lines, start=1):
        if "OSAL_QUEUE_DEF" in line and "tcd_event_t" in line:
            qname = "_usbc_q"
            m = re.search(r"OSAL_QUEUE_DEF\s*\([^,]+,\s*([^,]+),\s*[^,]+,\s*([A-Za-z_]\w*)", line)
            qdef = m.group(1).strip() if m else "_usbc_qdef"
            event_type = m.group(2).strip() if m else "tcd_event_t"
            payload = {
                "relation_kind": "tinyusb_typec_event_queue",
                "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                "usb_role": "typec_pd",
                "queue_name": qname,
                "queue_definition": qdef,
                "event_type": event_type,
                "event_source": "tcd_event_handler",
                "event_consumer": "tuc_task_ext",
                "runtime_model": "tcd_event_queue_to_tuc_task",
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_typec_pd",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=qname,
                predicate="declares_typec_event_queue",
                object=event_type,
                confidence="high",
                source="semantic_cpp_lightweight",
                payload=payload,
            ))
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        if fn.name == "tcd_event_handler" and "osal_queue_send" in fn_text:
            payload = {
                "relation_kind": "tinyusb_tcd_event_defer",
                "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                "usb_role": "typec_pd",
                "producer_function": fn.name,
                "queue_api": "osal_queue_send",
                "event_ids": sorted([eid for eid in _TINYUSB_TCD_EVENTS if eid in fn_text]),
                "starts_receive_on_cc_attach": "TCD_EVENT_CC_CHANGED" in fn_text and "tcd_msg_receive" in fn_text,
                "defer_model": "tcd_event_handler_enqueues_for_tuc_task",
                "runtime_model": "tcd_event_queue_to_tuc_task",
                "resolution_status": "semantic_relation",
                "unknown_type": "typec_event_order_depends_on_controller_interrupts",
                "response_constraint": "TCD event ordering depends on runtime Type-C controller interrupts; static evidence only proves queue deferral sites.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_typec_pd",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="defers_tcd_event_to_typec_queue",
                object="osal_queue_send",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
        if fn.name in {"tuc_task", "tuc_task_ext"} and "osal_queue_receive" in fn_text:
            event_ids = sorted([eid for eid in _TINYUSB_TCD_EVENTS if eid in fn_text])
            payload = {
                "relation_kind": "tinyusb_typec_task_consumer",
                "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                "usb_role": "typec_pd",
                "consumer_function": fn.name,
                "queue_api": "osal_queue_receive",
                "event_ids": event_ids,
                "handles_rx_complete": "TCD_EVENT_RX_COMPLETE" in event_ids,
                "handles_tx_complete": "TCD_EVENT_TX_COMPLETE" in event_ids,
                "handles_cc_changed": "TCD_EVENT_CC_CHANGED" in event_ids,
                "dispatches_pd_data_parser": "parse_msg_data" in fn_text,
                "dispatches_pd_control_parser": "parse_msg_control" in fn_text,
                "rearms_message_receive": "tcd_msg_receive" in fn_text,
                "runtime_model": "tcd_event_queue_to_pd_message_parser",
                "resolution_status": "semantic_relation",
                "unknown_type": "pd_message_parse_path_depends_on_runtime_header",
                "response_constraint": "tuc_task_ext evidence identifies event handling and parser dispatch; concrete PD message type depends on the received header at runtime.",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_typec_pd",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="consumes_typec_event_queue",
                object="osal_queue_receive",
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
            for event_id in event_ids:
                facts.append(CodeFact(
                    fact_type="tinyusb_typec_pd",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject=event_id,
                    predicate="handles_typec_event",
                    object=_TINYUSB_TCD_EVENTS[event_id],
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload={
                        "relation_kind": "tinyusb_typec_event_handler_case",
                        "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                        "usb_role": "typec_pd",
                        "consumer_function": fn.name,
                        "event_id": event_id,
                        "event_kind": _TINYUSB_TCD_EVENTS[event_id],
                        "runtime_model": "tcd_event_queue_to_tuc_task",
                    },
                ))
    return facts


def _tinyusb_pd_message_policy_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        weak = _tinyusb_function_has_prefix(lines, fn, "TU_ATTR_WEAK")
        if fn.name in {"tuc_pd_data_received_cb", "tuc_pd_control_received_cb"}:
            payload = {
                "relation_kind": "tinyusb_pd_policy_callback",
                "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                "usb_role": "typec_pd",
                "callback_name": fn.name,
                "callback_qualified_name": fn.qualified_name,
                "callback_family": "pd_data" if "data" in fn.name else "pd_control",
                "implementation_kind": "weak_default" if weak else "application_callback",
                "linkage": "weak" if weak else "strong",
                "application_path": _tinyusb_is_application_path(path),
                "runtime_model": "application_pd_policy_callback",
                "resolution_status": "semantic_relation",
            }
            facts.append(CodeFact(
                fact_type="tinyusb_typec_pd",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate="declares_pd_policy_callback",
                object=payload["callback_family"],
                confidence="high",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            ))
        if fn.name == "parse_msg_data" and "tuc_pd_data_received_cb" in fn_text:
            facts.append(_tinyusb_pd_dispatch_fact(path, fn, "dispatches_pd_data_message_callback", "tuc_pd_data_received_cb", "PD data message", "data_message"))
        if fn.name == "parse_msg_control" and "tuc_pd_control_received_cb" in fn_text:
            facts.append(_tinyusb_pd_dispatch_fact(path, fn, "dispatches_pd_control_message_callback", "tuc_pd_control_received_cb", "PD control message", "control_message"))
        if fn.name == "tuc_pd_data_received_cb":
            for msg in sorted(set(re.findall(r"\b(PD_DATA_[A-Z0-9_]+)\b", fn_text))):
                payload = {
                    "relation_kind": "tinyusb_pd_data_policy_handler",
                    "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                    "usb_role": "typec_pd",
                    "callback_name": fn.name,
                    "pd_message_type": msg,
                    "message_category": "data",
                    "pdo_types": sorted(set(re.findall(r"\b(PD_PDO_TYPE_[A-Z0-9_]+)\b", fn_text))),
                    "builds_request": "tuc_msg_request" in fn_text,
                    "policy_action": "select_pdo_and_send_request" if msg == "PD_DATA_SOURCE_CAP" and "tuc_msg_request" in fn_text else "application_data_policy",
                    "runtime_model": "application_pd_data_policy",
                    "resolution_status": "semantic_relation",
                    "unknown_type": "pd_policy_outcome_depends_on_source_capabilities",
                    "response_constraint": "Application PD data policy evidence identifies handled message types and request construction; selected PDO depends on runtime Source_Capabilities.",
                }
                facts.append(CodeFact(
                    fact_type="tinyusb_typec_pd",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject=fn.name,
                    predicate="handles_pd_data_message",
                    object=msg,
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                ))
        if fn.name == "tuc_pd_control_received_cb":
            for msg in sorted(set(re.findall(r"\b(PD_CTRL_[A-Z0-9_]+)\b", fn_text))):
                payload = {
                    "relation_kind": "tinyusb_pd_control_policy_handler",
                    "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
                    "usb_role": "typec_pd",
                    "callback_name": fn.name,
                    "pd_message_type": msg,
                    "message_category": "control",
                    "policy_action": _tinyusb_pd_control_policy_action(msg),
                    "runtime_model": "application_pd_control_policy",
                    "resolution_status": "semantic_relation",
                }
                facts.append(CodeFact(
                    fact_type="tinyusb_typec_pd",
                    path=path,
                    start_line=fn.start_line,
                    end_line=fn.end_line,
                    subject=fn.name,
                    predicate="handles_pd_control_message",
                    object=msg,
                    confidence="high",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                ))
    return [fact for fact in facts if fact is not None]


def _tinyusb_pd_dispatch_fact(path: str, fn: FunctionInfo, predicate: str, callback: str, object_name: str, category: str) -> CodeFact:
    return CodeFact(
        fact_type="tinyusb_typec_pd",
        path=path,
        start_line=fn.start_line,
        end_line=fn.end_line,
        subject=fn.name,
        predicate=predicate,
        object=callback,
        confidence="high",
        source="semantic_cpp_lightweight",
        payload={
            "relation_kind": "tinyusb_pd_message_callback_dispatch",
            "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
            "usb_role": "typec_pd",
            "parser_function": fn.name,
            "callback_name": callback,
            "message_category": category,
            "protocol_operation": object_name,
            "runtime_model": "pd_parser_to_application_policy_callback",
            "resolution_status": "semantic_relation",
            "unknown_type": "pd_message_content_depends_on_runtime_packet",
        },
    )


def _tinyusb_tcd_event_api_facts(path: str, text: str, model: SemanticModel, lines: list[str]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for fn in model.functions:
        if fn.name not in {"tcd_event_cc_changed", "tcd_event_rx_complete", "tcd_event_tx_complete"}:
            continue
        fn_text = _tinyusb_function_text(lines, fn)
        event_ids = [eid for eid in _TINYUSB_TCD_EVENTS if eid in fn_text]
        event_id = event_ids[0] if event_ids else None
        payload = {
            "relation_kind": "tinyusb_tcd_event_api",
            "semantic_phase": "phase7_tinyusb_typec_pd_semantics",
            "usb_role": "typec_pd",
            "api_name": fn.name,
            "api_qualified_name": fn.qualified_name,
            "event_id": event_id,
            "event_kind": _TINYUSB_TCD_EVENTS.get(event_id or ""),
            "calls_event_handler": "tcd_event_handler" in fn_text,
            "runtime_model": "tcd_inline_event_api_to_usbc_event_handler",
            "resolution_status": "semantic_relation",
        }
        facts.append(CodeFact(
            fact_type="tinyusb_typec_pd",
            path=path,
            start_line=fn.start_line,
            end_line=fn.end_line,
            subject=fn.name,
            predicate="declares_tcd_event_api",
            object=event_id or "tcd_event_handler",
            confidence="high",
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))
    return facts


def _tinyusb_pd_header_initializer(fn_text: str) -> dict[str, str]:
    m = re.search(r"pd_header_t\s+const\s+\w+\s*=\s*\{(?P<body>.*?)\};", fn_text, re.S)
    if not m:
        return {}
    body = m.group("body")
    fields: dict[str, str] = {}
    for field, value in re.findall(r"\.([A-Za-z_]\w*)\s*=\s*([^,}\n]+)", body):
        fields[field.strip()] = value.strip()
    return fields


def _tinyusb_pd_control_policy_action(message: str) -> str:
    return {
        "PD_CTRL_ACCEPT": "request_accepted",
        "PD_CTRL_REJECT": "request_rejected",
        "PD_CTRL_PS_READY": "power_supply_ready",
    }.get(message, "application_control_policy")



def _tinyusb_callback_definition_facts(path: str, text: str, model: SemanticModel) -> list[CodeFact]:
    """Extract TinyUSB callback definitions and weak defaults.

    TinyUSB relies on application-provided ``tud_*_cb`` / ``tuh_*_cb`` functions
    and weak defaults in the stack.  Source-level evidence must keep those
    distinct: a weak default is a fallback hook, while a same-named strong
    application definition overrides it at link time.  Cross-translation-unit
    override edges are added later in ``cross_tu`` once all active definitions
    are available.
    """
    if "_cb" not in text and "TU_ATTR_WEAK" not in text:
        return []
    facts: list[CodeFact] = []
    original_lines = text.splitlines()
    for fn in model.functions:
        if fn.declaration_or_definition != "definition":
            continue
        if not _is_tinyusb_callback_name(fn.name):
            continue
        first_line = original_lines[fn.start_line - 1] if 0 <= fn.start_line - 1 < len(original_lines) else ""
        return_type = fn.return_type or ""
        weak = "TU_ATTR_WEAK" in return_type or "TU_ATTR_WEAK" in first_line
        family = _tinyusb_callback_family(fn.name)
        role = _tinyusb_callback_role(fn.name, family)
        implementation_kind = "weak_default" if weak else "application_callback"
        predicate = "declares_weak_callback_default" if weak else "declares_tinyusb_callback_implementation"
        payload = {
            "relation_kind": "tinyusb_callback_definition",
            "callback_name": fn.name,
            "callback_qualified_name": fn.qualified_name,
            "callback_family": family,
            "callback_role": role,
            "callback_requirement": _tinyusb_callback_requirement(fn.name, weak),
            "implementation_kind": implementation_kind,
            "linkage": "weak" if weak else "strong",
            "weak_default": weak,
            "application_callback": not weak,
            "application_path": _tinyusb_is_application_path(path),
            "return_type": return_type.replace("TU_ATTR_WEAK", "").strip() if weak else return_type,
            "raw_return_type": return_type,
            "signature": fn.signature,
            "argument_count": len(fn.parameters),
            "parameters": [{"name": p.name, "type": p.type} for p in fn.parameters],
            "symbol_id": fn.symbol_id,
            "semantic_phase": "phase7_tinyusb_weak_callback_semantics",
            "resolution_status": "semantic_relation",
            "build_status": "active",
            "response_constraint": "TinyUSB callback evidence distinguishes weak defaults from strong application definitions; it does not prove callback execution on every runtime path.",
        }
        if weak:
            payload["override_status"] = "weak_default_may_be_overridden"
            payload["unknown_type"] = "weak_callback_override_requires_link_resolution"
        elif fn.name.startswith("tud_descriptor_"):
            payload["provider_kind"] = "descriptor_callback_provider"
        payload = {key: value for key, value in payload.items() if value not in (None, [], {})}
        facts.append(
            CodeFact(
                fact_type="tinyusb_callback",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.name,
                predicate=predicate,
                object=implementation_kind,
                confidence="high" if weak or _tinyusb_is_application_path(path) else "medium",
                source="semantic_cpp_lightweight",
                payload=payload,
            )
        )
    return facts


def _is_tinyusb_callback_name(name: str) -> bool:
    return bool(re.fullmatch(r"tu[dhc]_[A-Za-z0-9_]+_cb", name))


def _tinyusb_is_application_path(path: str) -> bool:
    norm = path.replace("\\", "/")
    return norm.startswith("examples/") or "/examples/" in norm


def _tinyusb_callback_family(name: str) -> str:
    if name.startswith("tud_descriptor_"):
        return "descriptor"
    if name in _TINYUSB_CALLBACK_LIFECYCLE_NAMES:
        return "device_lifecycle"
    for prefix, family in (
        ("tud_cdc_", "cdc"),
        ("tud_msc_", "msc"),
        ("tud_hid_", "hid"),
        ("tud_vendor_", "vendor"),
        ("tud_audio_", "audio"),
        ("tud_video_", "video"),
        ("tuh_cdc_", "host_cdc"),
        ("tuh_msc_", "host_msc"),
        ("tuh_hid_", "host_hid"),
        ("tuc_pd_", "typec_pd"),
    ):
        if name.startswith(prefix):
            return family
    if name.startswith("tud_"):
        return "device"
    if name.startswith("tuh_"):
        return "host"
    if name.startswith("tuc_"):
        return "typec"
    return "tinyusb"


def _tinyusb_callback_role(name: str, family: str) -> str:
    if name in _TINYUSB_CALLBACK_LIFECYCLE_NAMES:
        return _TINYUSB_CALLBACK_LIFECYCLE_NAMES[name]
    if name.startswith("tud_descriptor_"):
        role = name[len("tud_descriptor_") : -len("_cb")]
        return role or "descriptor"
    prefixes = {
        "cdc": "tud_cdc_",
        "msc": "tud_msc_",
        "hid": "tud_hid_",
        "vendor": "tud_vendor_",
        "audio": "tud_audio_",
        "video": "tud_video_",
        "host_cdc": "tuh_cdc_",
        "host_msc": "tuh_msc_",
        "host_hid": "tuh_hid_",
        "typec_pd": "tuc_pd_",
    }
    prefix = prefixes.get(family)
    if prefix and name.startswith(prefix):
        return name[len(prefix) : -len("_cb")]
    return name[:-len("_cb")] if name.endswith("_cb") else name


def _tinyusb_callback_requirement(name: str, weak: bool) -> str:
    if weak:
        return "optional_weak_default"
    if name.startswith("tud_descriptor_"):
        return "application_descriptor_provider"
    if name.startswith("tud_msc_"):
        return "application_class_callback"
    if name.startswith("tuc_pd_"):
        return "application_pd_policy_callback"
    if name in _TINYUSB_CALLBACK_LIFECYCLE_NAMES:
        return "optional_application_override"
    return "application_callback"

def _tinyusb_descriptor_macro_facts(path: str, text: str) -> list[CodeFact]:
    """Extract TinyUSB descriptor macro semantics.

    TinyUSB examples encode device configuration through macro invocations such
    as ``TUD_CDC_DESCRIPTOR(...)`` inside descriptor byte arrays.  Treat those
    invocations as USB-domain evidence rather than ordinary preprocessor noise:
    the fact records which class/interface/endpoint a descriptor macro declares,
    while leaving byte-level USB spec validation out of scope.
    """
    if "TUD_" not in text and "tud_descriptor_" not in text:
        return []
    facts: list[CodeFact] = []
    lines = text.splitlines()
    symbol_values = _tinyusb_descriptor_symbol_values(lines)
    descriptor_arrays = _tinyusb_descriptor_arrays(lines)
    descriptor_arrays_by_line: dict[int, str] = {}
    for array_name, span in descriptor_arrays.items():
        for lineno in range(span[0], span[1] + 1):
            descriptor_arrays_by_line[lineno] = array_name
        facts.append(_tinyusb_descriptor_array_fact(path, array_name, span, symbol_values))

    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        for macro_name, meta in _TINYUSB_DESCRIPTOR_MACROS.items():
            for args_text in _macro_invocation_arg_texts(line, macro_name):
                args = _split_top_level_commas(args_text)
                facts.append(_tinyusb_descriptor_macro_fact(path, lineno, macro_name, args, meta, descriptor_arrays_by_line.get(lineno), symbol_values))

    facts.extend(_tinyusb_descriptor_callback_facts(path, text, descriptor_arrays, symbol_values))
    return facts


def _tinyusb_descriptor_array_fact(path: str, array_name: str, span: tuple[int, int], symbol_values: dict[str, object]) -> CodeFact:
    array_kind = _tinyusb_descriptor_array_kind(array_name)
    payload = {
        "relation_kind": "tinyusb_descriptor_array",
        "descriptor_array": array_name,
        "descriptor_kind": array_kind,
        "descriptor_symbols": {k: v for k, v in symbol_values.items() if k.startswith(("ITF_", "EPNUM_", "CONFIG_", "TUD_", "CFG_TUD_"))},
        "semantic_phase": "phase7_tinyusb_descriptor_macro_semantics",
        "resolution_status": "semantic_relation",
        "build_status": "active",
        "response_constraint": "Descriptor-array evidence identifies the source-level TinyUSB descriptor object, but it is not a full USB byte-level validator.",
    }
    return CodeFact(
        fact_type="usb_descriptor",
        path=path,
        start_line=span[0],
        end_line=span[1],
        subject=array_name,
        predicate="declares_descriptor_array",
        object=array_kind,
        confidence="medium",
        source="semantic_cpp_lightweight",
        payload=payload,
    )


def _tinyusb_descriptor_macro_fact(path: str, lineno: int, macro_name: str, args: list[str], meta: dict[str, object], descriptor_array: str | None, symbol_values: dict[str, object]) -> CodeFact:
    arg_names = tuple(meta.get("arg_names") or ())
    named_args = {name: args[index] for index, name in enumerate(arg_names) if index < len(args)}
    resolved_args = {name: _resolve_tinyusb_descriptor_arg(value, symbol_values) for name, value in named_args.items()}
    interface_arg_names = tuple(meta.get("interface_arg_names") or ())
    endpoint_arg_names = tuple(meta.get("endpoint_arg_names") or ())
    interface_symbols = [named_args[name] for name in interface_arg_names if name in named_args]
    endpoint_symbols = [named_args[name] for name in endpoint_arg_names if name in named_args]
    usb_class = str(meta.get("usb_class") or "")
    descriptor_kind = str(meta.get("descriptor_kind") or "unknown")
    subject = usb_class or macro_name
    obj = descriptor_array or descriptor_kind
    payload = {
        "relation_kind": "tinyusb_descriptor_macro",
        "descriptor_macro": macro_name,
        "descriptor_kind": descriptor_kind,
        "usb_class": usb_class or None,
        "descriptor_array": descriptor_array,
        "argument_names": list(arg_names),
        "argument_expressions": list(args),
        "named_arguments": named_args,
        "resolved_arguments": resolved_args,
        "interface_symbols": interface_symbols,
        "endpoint_symbols": endpoint_symbols,
        "interface_symbol": interface_symbols[0] if interface_symbols else None,
        "endpoint_symbol": endpoint_symbols[0] if endpoint_symbols else None,
        "endpoint_directions": _tinyusb_endpoint_directions(endpoint_symbols, symbol_values),
        "report_kind": meta.get("report_kind"),
        "report_id": named_args.get("report_id"),
        "semantic_phase": "phase7_tinyusb_descriptor_macro_semantics",
        "resolution_status": "semantic_relation",
        "build_status": "active",
        "unknown_type": "descriptor_byte_layout_not_fully_validated",
        "response_constraint": "TinyUSB descriptor macro evidence preserves class/interface/endpoint intent, but does not prove the final USB byte layout is spec-valid.",
    }
    payload = {key: value for key, value in payload.items() if value not in (None, [], {})}
    return CodeFact(
        fact_type="usb_descriptor",
        path=path,
        start_line=lineno,
        end_line=lineno,
        subject=subject,
        predicate=str(meta.get("predicate") or "defines_descriptor"),
        object=obj,
        confidence="medium",
        source="semantic_cpp_lightweight",
        payload=payload,
    )


def _tinyusb_descriptor_callback_facts(path: str, text: str, descriptor_arrays: dict[str, tuple[int, int]], symbol_values: dict[str, object]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for m in re.finditer(
        r"(?P<ret>(?:[A-Za-z_][\w\s\*]+?)?)\b(?P<name>tud_(?:descriptor_[A-Za-z0-9_]+|hid_descriptor_report)_cb)\s*\([^)]*\)\s*\{(?P<body>.*?)\}",
        text,
        re.DOTALL,
    ):
        name = m.group("name")
        body = m.group("body")
        return_match = re.search(r"\breturn\s+(?P<target>[A-Za-z_]\w*)\s*;", body)
        if not return_match:
            continue
        returned = return_match.group("target")
        start_line = text.count("\n", 0, m.start()) + 1
        end_line = text.count("\n", 0, m.end()) + 1
        descriptor_kind = _TINYUSB_DESCRIPTOR_CALLBACK_KINDS.get(name) or _tinyusb_descriptor_array_kind(returned)
        payload = {
            "relation_kind": "tinyusb_descriptor_callback_provider",
            "callback_kind": "descriptor_callback_provider",
            "callback_name": name,
            "descriptor_kind": descriptor_kind,
            "returned_descriptor": returned,
            "descriptor_array": returned if returned in descriptor_arrays else None,
            "descriptor_array_span": list(descriptor_arrays[returned]) if returned in descriptor_arrays else None,
            "descriptor_symbols": {k: v for k, v in symbol_values.items() if k.startswith(("ITF_", "EPNUM_", "CONFIG_", "TUD_", "CFG_TUD_"))},
            "semantic_phase": "phase7_tinyusb_descriptor_macro_semantics",
            "resolution_status": "semantic_relation",
            "build_status": "active",
            "response_constraint": "Descriptor callback evidence shows which source array is returned; runtime USB host requests still determine when the callback is invoked.",
        }
        payload = {key: value for key, value in payload.items() if value not in (None, [], {})}
        facts.append(
            CodeFact(
                fact_type="usb_descriptor",
                path=path,
                start_line=start_line,
                end_line=end_line,
                subject=name,
                predicate="provides_descriptor_callback",
                object=returned,
                confidence="high",
                source="semantic_cpp_lightweight",
                payload=payload,
            )
        )
    return facts


def _tinyusb_descriptor_arrays(lines: list[str]) -> dict[str, tuple[int, int]]:
    arrays: dict[str, tuple[int, int]] = {}
    current_name: str | None = None
    current_start: int | None = None
    brace_depth = 0
    for lineno, line in enumerate(lines, start=1):
        if current_name is None:
            m = re.search(r"\b(?P<name>desc_[A-Za-z0-9_]+|[A-Za-z_]*descriptor[A-Za-z0-9_]*)\s*\[\s*\]\s*=\s*\{", line)
            if not m:
                continue
            current_name = m.group("name")
            current_start = lineno
            brace_depth = line.count("{") - line.count("}")
            if brace_depth <= 0:
                arrays[current_name] = (current_start, lineno)
                current_name = None
                current_start = None
            continue
        brace_depth += line.count("{") - line.count("}")
        if brace_depth <= 0:
            arrays[current_name] = (current_start or lineno, lineno)
            current_name = None
            current_start = None
    return arrays


def _tinyusb_descriptor_array_kind(array_name: str) -> str:
    lowered = array_name.lower()
    if "configuration" in lowered or "config" in lowered:
        return "configuration"
    if "device" in lowered:
        return "device"
    if "string" in lowered:
        return "string"
    if "bos" in lowered:
        return "bos"
    if "hid" in lowered and "report" in lowered:
        return "hid_report"
    return "descriptor"


def _tinyusb_descriptor_symbol_values(lines: list[str]) -> dict[str, object]:
    values: dict[str, object] = {}
    enum_depth = 0
    enum_next = 0
    for line in lines:
        stripped = line.strip()
        m_define = re.match(r"#\s*define\s+(?P<name>[A-Za-z_]\w*)(?P<rest>.*?)(?://.*)?$", stripped)
        if m_define:
            rest_raw = m_define.group("rest") or ""
            # Function-like macros have no whitespace between the name and '('.
            # Object-like descriptor constants may legitimately be parenthesized,
            # e.g. '#define CONFIG_TOTAL_LEN (A + B + C)'.
            function_like = rest_raw.startswith("(")
            rest = rest_raw.strip()
            if rest and not function_like:
                value_text = rest
                resolved = _eval_tinyusb_descriptor_value(value_text, values)
                values[m_define.group("name")] = resolved if resolved is not None else value_text
        if re.match(r"\benum\b", stripped) and "{" in stripped:
            enum_depth = 1
            enum_next = 0
            stripped = stripped.split("{", 1)[1]
        if enum_depth:
            enum_depth += stripped.count("{") - stripped.count("}")
            enum_part = stripped.split("}", 1)[0]
            for item in _split_top_level_commas(enum_part):
                item = item.strip().rstrip(",")
                if not item or item.startswith("enum"):
                    continue
                m_item = re.match(r"(?P<name>[A-Za-z_]\w*)\s*(?:=\s*(?P<value>.+))?$", item)
                if not m_item:
                    continue
                name = m_item.group("name")
                value_expr = m_item.group("value")
                if value_expr is not None:
                    resolved = _eval_tinyusb_descriptor_value(value_expr, values)
                    if isinstance(resolved, int):
                        enum_next = resolved
                    values[name] = resolved if resolved is not None else value_expr.strip()
                else:
                    values[name] = enum_next
                enum_next += 1
    return values


def _eval_tinyusb_descriptor_value(expr: str, values: dict[str, object]) -> object | None:
    clean = expr.strip().strip("()")
    clean = re.sub(r"\b([0-9]+|0[xX][0-9A-Fa-f]+)[uUlL]+\b", r"\1", clean)
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", clean):
        try:
            return int(clean, 16)
        except ValueError:
            return None
    if re.fullmatch(r"[+-]?\d+", clean):
        try:
            return int(clean, 10)
        except ValueError:
            return None
    if clean in values:
        return values[clean]
    if re.fullmatch(r"[A-Za-z_]\w*", clean):
        return None
    # Support simple additive descriptor length expressions such as
    # ``TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_MSC_DESC_LEN``.
    if re.fullmatch(r"(?:[A-Za-z_][\w]*|0[xX][0-9A-Fa-f]+|\d+)(?:\s*[+\-]\s*(?:[A-Za-z_][\w]*|0[xX][0-9A-Fa-f]+|\d+))+", clean):
        total = 0
        sign = 1
        tokens = re.split(r"(\+|\-)", clean)
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if token == "+":
                sign = 1
                continue
            if token == "-":
                sign = -1
                continue
            value = values.get(token)
            if value is None:
                value = _eval_tinyusb_descriptor_value(token, values)
            if not isinstance(value, int):
                return None
            total += sign * value
        return total
    return None


def _resolve_tinyusb_descriptor_arg(value: str, symbol_values: dict[str, object]) -> object:
    stripped = value.strip()
    if stripped in symbol_values:
        return symbol_values[stripped]
    resolved = _eval_tinyusb_descriptor_value(stripped, symbol_values)
    return resolved if resolved is not None else stripped


def _tinyusb_endpoint_directions(endpoint_symbols: list[str], symbol_values: dict[str, object]) -> dict[str, str]:
    directions: dict[str, str] = {}
    for symbol in endpoint_symbols:
        value = _resolve_tinyusb_descriptor_arg(symbol, symbol_values)
        if isinstance(value, int):
            directions[symbol] = "in" if value & 0x80 else "out"
        else:
            lower = symbol.lower()
            if lower.endswith("_in") or "_in" in lower:
                directions[symbol] = "in"
            elif lower.endswith("_out") or "_out" in lower:
                directions[symbol] = "out"
            elif "notif" in lower or "int" in lower:
                directions[symbol] = "in"
    return directions


def _macro_invocation_arg_texts(line: str, macro_name: str) -> list[str]:
    out: list[str] = []
    start = 0
    needle = macro_name
    while True:
        idx = line.find(needle, start)
        if idx < 0:
            break
        before = line[idx - 1] if idx > 0 else ""
        after_index = idx + len(needle)
        after = line[after_index] if after_index < len(line) else ""
        if (before and (before.isalnum() or before == "_")) or (after and (after.isalnum() or after == "_")):
            start = after_index
            continue
        pos = after_index
        while pos < len(line) and line[pos].isspace():
            pos += 1
        if pos >= len(line) or line[pos] != "(":
            start = after_index
            continue
        end = _matching_paren_index(line, pos)
        if end is None:
            start = pos + 1
            continue
        out.append(line[pos + 1:end])
        start = end + 1
    return out


def _matching_paren_index(text: str, open_index: int) -> int | None:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


_UI_RESOURCE_RELATION_PREDICATES = {
    "binds_menu_item_to_command",
    "binds_accelerator_to_command",
    "binds_toolbar_button_to_command",
    "creates_accelerator_table",
    "translates_accelerator_to_command",
    "looks_up_accelerator_command",
    "routes_resource_command_to_handler",
}


def _resource_ui_binding_relations(path: str, text: str) -> list[CodeFact]:
    """Extract static Windows .rc menu/accelerator resource bindings.

    RC files are not C++ execution, but they are critical evidence for GUI entry
    points.  A MENUITEM or ACCELERATORS entry binds a resource/control gesture to
    a command id; it does not call the handler by itself.
    """
    facts: list[CodeFact] = []
    section_stack: list[str] = []
    current_menu: str | None = None
    current_accel: str | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        menu_start = re.match(r"(?P<id>[A-Za-z_][A-Za-z0-9_]*)\s+MENU\b", line)
        accel_start = re.match(r"(?P<id>[A-Za-z_][A-Za-z0-9_]*)\s+ACCELERATORS\b", line)
        if menu_start:
            current_menu = menu_start.group("id")
            section_stack.append("menu")
            continue
        if accel_start:
            current_accel = accel_start.group("id")
            section_stack.append("accelerator")
            continue
        if line == "END":
            if section_stack:
                kind = section_stack.pop()
                if kind == "menu" and "menu" not in section_stack:
                    current_menu = None
                if kind == "accelerator" and "accelerator" not in section_stack:
                    current_accel = None
            continue
        if line == "BEGIN":
            continue
        if current_menu:
            m = re.match(r'MENUITEM\s+"(?P<label>(?:[^"]|"")*)"\s*,\s*(?P<cmd>F_[A-Za-z0-9_]+|ID_[A-Za-z0-9_]+|IDOK|IDCANCEL)\b', line)
            if m:
                label = m.group("label").replace('""', '"')
                cmd = m.group("cmd")
                facts.append(_ui_resource_relation(
                    path, lineno,
                    subject=f"{current_menu}:{label}",
                    predicate="binds_menu_item_to_command",
                    obj=cmd,
                    relation_kind="menu_resource_binding",
                    operation_kind="menu_item_command_binding",
                    extra={"resource_id": current_menu, "menu_label": label, "command_id": cmd},
                ))
        if current_accel:
            m = re.match(r'(?P<key>"[^"]+"|VK_[A-Za-z0-9_]+|[A-Za-z0-9_]+)\s*,\s*(?P<cmd>F_[A-Za-z0-9_]+|ID_[A-Za-z0-9_]+|IDOK|IDCANCEL)\b(?P<flags>.*)', line)
            if m:
                key = m.group("key").strip('"')
                cmd = m.group("cmd")
                flags = m.group("flags").strip(" ,")
                facts.append(_ui_resource_relation(
                    path, lineno,
                    subject=f"{current_accel}:{key}",
                    predicate="binds_accelerator_to_command",
                    obj=cmd,
                    relation_kind="accelerator_resource_binding",
                    operation_kind="accelerator_resource_command_binding",
                    extra={"resource_id": current_accel, "accelerator_key": key, "accelerator_flags": flags, "command_id": cmd},
                ))
    facts.extend(_toolbar_command_binding_relations(path, text.splitlines()))
    return facts


def _toolbar_command_binding_relations(path: str, lines: list[str]) -> list[CodeFact]:
    """Extract Sakura-style toolbar table slots from CMenuDrawer's tbd[] array."""
    facts: list[CodeFact] = []
    in_tbd = False
    for lineno, line in enumerate(lines, start=1):
        if re.search(r"\bstatic\s+const\s+int\s+tbd\s*\[\s*\]\s*=\s*\{", line):
            in_tbd = True
            continue
        if in_tbd and "};" in line:
            in_tbd = False
            continue
        if not in_tbd:
            continue
        m = re.search(r"/\*\s*(?P<slot>\d+)\s*\*/\s*(?P<cmd>F_[A-Za-z0-9_]+)", line)
        if not m:
            continue
        cmd = m.group("cmd")
        if cmd == "F_DISABLE":
            # F_DISABLE entries may be dummy slots or carry disabled legacy names in comments.
            continue
        slot = m.group("slot")
        facts.append(_ui_resource_relation(
            path, lineno,
            subject=f"toolbar_slot_{slot}",
            predicate="binds_toolbar_button_to_command",
            obj=cmd,
            relation_kind="toolbar_resource_binding",
            operation_kind="toolbar_button_command_binding",
            extra={"toolbar_slot": int(slot), "command_id": cmd, "resource_table": "CMenuDrawer::tbd"},
        ))
    return facts


def _ui_resource_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact], line: str) -> list[CodeFact]:
    relations: list[CodeFact] = []
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        short = _short_name(callee)
        if short == "CreateAcceleratorTable":
            relations.append(_ui_resource_relation(
                path, lineno,
                subject=caller.qualified_name,
                predicate="creates_accelerator_table",
                obj="CreateAcceleratorTable",
                relation_kind="accelerator_runtime_binding",
                operation_kind="create_accelerator_table",
                extra={"caller_qualified_name": caller.qualified_name, "callee_qualified_name": callee},
            ))
        elif short == "GetFuncCodeAt":
            relations.append(_ui_resource_relation(
                path, lineno,
                subject=caller.qualified_name,
                predicate="looks_up_accelerator_command",
                obj="GetFuncCodeAt",
                relation_kind="accelerator_runtime_binding",
                operation_kind="lookup_key_function_code",
                extra={"caller_qualified_name": caller.qualified_name, "callee_qualified_name": callee},
            ))
    # pAccelArr[k].cmd = pKeyNameArr[i].m_nKeyCode | (((WORD)j)<<8)
    if re.search(r"\bpAccelArr\s*\[.*?\]\s*\.\s*cmd\s*=", line):
        relations.append(_ui_resource_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="binds_accelerator_to_command",
            obj="ACCEL.cmd",
            relation_kind="accelerator_runtime_binding",
            operation_kind="set_accelerator_command_id",
            extra={"caller_qualified_name": caller.qualified_name, "runtime_binding": "ACCEL.cmd"},
        ))
    if re.search(r"\breturn\s+GetFuncCodeAt\s*\(", line):
        relations.append(_ui_resource_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="translates_accelerator_to_command",
            obj="EFunctionCode",
            relation_kind="accelerator_runtime_binding",
            operation_kind="translate_accelerator_to_function_code",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    return relations


def _ui_resource_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    relations: list[CodeFact] = []
    # LOWORD(wParam) or nCommand coming from WM_COMMAND is an entry point from
    # resource/menu/toolbar/accelerator IDs into the command dispatcher.
    if re.search(r"\b(LOWORD\s*\(\s*wParam\s*\)|WM_COMMAND|HandleCommand\s*\()", line) and ("F_" in line or "nCommand" in line or "wParam" in line):
        relations.append(_ui_resource_relation(
            path, lineno,
            subject=caller.qualified_name,
            predicate="routes_resource_command_to_handler",
            obj="CViewCommander::HandleCommand",
            relation_kind="resource_command_routing",
            operation_kind="route_wm_command_or_resource_id",
            extra={"caller_qualified_name": caller.qualified_name},
        ))
    return relations


def _ui_resource_relation(
    path: str,
    lineno: int,
    *,
    subject: str,
    predicate: str,
    obj: str,
    relation_kind: str,
    operation_kind: str,
    extra: dict | None = None,
) -> CodeFact:
    payload = {
        "relation_kind": relation_kind,
        "operation_kind": operation_kind,
        "edge_status": "semantic_ui_resource_relation",
        "unknown_type": "resource_binding_not_unconditional_call",
        "semantic_phase": "sakura_ui_resource_command_binding",
    }
    if extra:
        payload.update(extra)
    return CodeFact(
        fact_type="relation",
        path=path,
        start_line=lineno,
        end_line=lineno,
        subject=subject,
        predicate=predicate,
        object=obj,
        confidence="medium",
        source="semantic_cpp_lightweight",
        payload=payload,
    )

def _file_io_encoding_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact]) -> list[CodeFact]:
    """Derive file-load / encoding-detection semantic relations from calls.

    Sakura Editor's file loading flow mixes Win32 file mapping, encoding auto
    detection, code-base factory creation, EOL setup, and per-line conversion.
    These are semantic roles rather than plain unconditional answer text, so we
    expose them as evidence relations that can be combined into safe traces.
    """
    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, int]] = set()
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        if not callee:
            continue
        short = _short_name(callee)
        if short not in _FILE_IO_ENCODING_OPERATION_KINDS:
            continue
        predicate, operation_kind, relation_kind = _FILE_IO_ENCODING_OPERATION_KINDS[short]
        key = (caller.qualified_name, predicate, callee, lineno)
        if key in seen:
            continue
        seen.add(key)
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=callee,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "operation_callee": callee,
                    "operation_callee_short": short,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "call_kind": fact.call_kind,
                    "call_resolution_status": fact.payload.get("resolution_status"),
                    "callee_qualified_name": fact.payload.get("callee_qualified_name") or callee,
                    "callee_symbol_id": fact.payload.get("callee_symbol_id"),
                    "edge_status": "semantic_file_io_relation",
                    "semantic_phase": "sakura_file_loading_encoding",
                },
            )
        )
    return relations


def _file_io_encoding_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Detect encoding-flow markers that are assignments/branches rather than calls."""
    relations: list[CodeFact] = []
    markers: list[tuple[str, str, str, str]] = []
    if re.search(r"\bCharCode\s*==\s*CODE_AUTODETECT\b", line):
        markers.append(("checks_autodetect_requested", "CODE_AUTODETECT", "autodetect_branch", "encoding_detection"))
    if re.search(r"\bm_CharCode\s*=\s*CharCode\b", line):
        markers.append(("stores_detected_encoding", "m_CharCode", "store_detected_encoding", "encoding_metadata"))
    if re.search(r"\bm_bBomExist\s*=\s*true\b", line) or re.search(r"\*\s*pbBomExist\s*=\s*true\b", line):
        markers.append(("tracks_bom_status", "BOM", "bom_detected", "bom_detection"))
    if re.search(r"\*\s*pbBomExist\s*=\s*false\b", line):
        markers.append(("tracks_bom_status", "BOM", "bom_not_detected", "bom_detection"))
    for predicate, obj, operation_kind, relation_kind in markers:
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=obj,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_file_io_relation",
                    "semantic_phase": "sakura_file_loading_encoding",
                },
            )
        )
    return relations


def _edit_operation_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact]) -> list[CodeFact]:
    """Derive edit/undo semantic relations from resolved or unresolved calls.

    Sakura Editor's editing flow is not just a plain call path: commands mutate the
    edit buffer, prepare/flush undo buffers, then Undo/Redo replays operation blocks.
    These relations keep those roles explicit so an LLM can say which edge is an
    edit operation and which edge is undo bookkeeping without inventing semantics.
    """
    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, int]] = set()
    for fact in call_facts:
        if fact.fact_type != "call":
            continue
        callee = str(fact.payload.get("callee_qualified_name") or fact.callee or fact.object or "")
        if not callee:
            continue
        short = _short_name(callee)
        if short not in _EDIT_OPERATION_KINDS:
            continue
        predicate, operation_kind = _EDIT_OPERATION_KINDS[short]
        key = (caller.qualified_name, predicate, callee, lineno)
        if key in seen:
            continue
        seen.add(key)
        relation_kind = _EDIT_OPERATION_RELATION_KIND[predicate]
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate=predicate,
                object=callee,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": relation_kind,
                    "operation_kind": operation_kind,
                    "operation_callee": callee,
                    "operation_callee_short": short,
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "call_kind": fact.call_kind,
                    "call_resolution_status": fact.payload.get("resolution_status"),
                    "callee_qualified_name": fact.payload.get("callee_qualified_name") or callee,
                    "callee_symbol_id": fact.payload.get("callee_symbol_id"),
                    "edge_status": "semantic_operation_relation",
                    "semantic_phase": "sakura_undo_edit_tracking",
                },
            )
        )
    return relations


def _undo_operation_block_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Detect operation-block lifecycle markers that are not always normal calls.

    `SetOpeBlk(new COpeBlk())` is already partly visible as a constructor call, but
    recording an explicit relation makes the Undo/Redo setup visible even when the
    receiver type of SetOpeBlk is only partially known.
    """
    relations: list[CodeFact] = []
    if "new COpeBlk" in line or "new COpeBlk()" in line:
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate="creates_undo_operation_block",
                object="COpeBlk",
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "undo_operation_block_lifecycle",
                    "operation_kind": "create_operation_block",
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_operation_relation",
                    "semantic_phase": "sakura_undo_edit_tracking",
                },
            )
        )
    if re.search(r"\bm_bDoing_UndoRedo\s*=\s*true", line):
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate="marks_undo_redo_execution",
                object="m_bDoing_UndoRedo",
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "undo_redo_state_flag",
                    "operation_kind": "enter_undo_redo_execution",
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_operation_relation",
                    "semantic_phase": "sakura_undo_edit_tracking",
                },
            )
        )
    if re.search(r"\bm_bDoing_UndoRedo\s*=\s*false", line):
        relations.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.qualified_name,
                predicate="marks_undo_redo_execution",
                object="m_bDoing_UndoRedo",
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={
                    "relation_kind": "undo_redo_state_flag",
                    "operation_kind": "leave_undo_redo_execution",
                    "caller_qualified_name": caller.qualified_name,
                    "caller_symbol_id": caller.symbol_id,
                    "edge_status": "semantic_operation_relation",
                    "semantic_phase": "sakura_undo_edit_tracking",
                },
            )
        )
    return relations

def _command_dispatch_relations(path: str, lines: list[str], symbols: list[FunctionInfo]) -> list[CodeFact]:
    """Extract switch-case command dispatcher bindings such as Sakura Editor's HandleCommand.

    This is intentionally represented as a relation, not as an unconditional call:
    `case F_SEARCH_NEXT: Command_SEARCH_NEXT(...)` means the command id is bound to
    a handler when that case is selected.  The handler call itself is still emitted
    by the normal call extractor when it appears in code.
    """
    facts: list[CodeFact] = []
    symbol_by_qname = {s.qualified_name: s for s in symbols}
    symbols_by_short: dict[str, list[FunctionInfo]] = {}
    for symbol in symbols:
        symbols_by_short.setdefault(symbol.name, []).append(symbol)

    for fn in [f for f in symbols if f.declaration_or_definition == "definition"]:
        if fn.start_line < 1 or fn.end_line > len(lines):
            continue
        active_command: str | None = None
        active_case_line: int | None = None
        for lineno in range(fn.start_line, fn.end_line + 1):
            line = lines[lineno - 1]
            case_match = re.search(r"\bcase\s+(?P<command>[A-Za-z_]\w*)\s*:", line)
            if case_match:
                active_command = case_match.group("command")
                active_case_line = lineno
                # Only treat command-like case labels as dispatch ids.  This keeps
                # ordinary enum switches out of the command-dispatch model.
                if not active_command.startswith(("F_", "ID_", "WM_")):
                    active_command = None
                    active_case_line = None
            if not active_command:
                continue

            for handler_match in re.finditer(r"(?:(?:this|self)\s*->\s*)?(?P<handler>Command_[A-Za-z_]\w*)\s*\(", line):
                handler = handler_match.group("handler")
                handler_qname = _resolve_dispatch_handler_qname(handler, fn, symbols_by_short, symbol_by_qname)
                handler_symbol = symbol_by_qname.get(handler_qname)
                payload = {
                    "relation_kind": "command_dispatch",
                    "dispatch_kind": "switch_case",
                    "command_id": active_command,
                    "command_case_line": active_case_line,
                    "dispatcher_qualified_name": fn.qualified_name,
                    "dispatcher_symbol_id": fn.symbol_id,
                    "handler_name": handler,
                    "handler_qualified_name": handler_qname,
                    "handler_symbol_id": handler_symbol.symbol_id if handler_symbol else None,
                    "edge_status": "conditional_dispatch",
                    "unknown_type": "dispatch_relation_not_unconditional_call",
                    "semantic_phase": "sakura_command_dispatch",
                }
                facts.append(
                    CodeFact(
                        fact_type="relation",
                        path=path,
                        start_line=lineno,
                        end_line=lineno,
                        subject=active_command,
                        predicate="dispatches_to",
                        object=handler_qname,
                        confidence="high" if handler_symbol else "medium",
                        source="semantic_cpp_lightweight",
                        payload={k: v for k, v in payload.items() if v is not None},
                    )
                )
            if re.search(r"\b(break|return)\b", line):
                active_command = None
                active_case_line = None
    return facts


def _resolve_dispatch_handler_qname(
    handler: str,
    dispatcher: FunctionInfo,
    symbols_by_short: dict[str, list[FunctionInfo]],
    symbol_by_qname: dict[str, FunctionInfo],
) -> str:
    if dispatcher.owner_type:
        candidate = f"{dispatcher.owner_type}::{handler}"
        if candidate in symbol_by_qname:
            return candidate
    matches = symbols_by_short.get(handler, [])
    if len(matches) == 1:
        return matches[0].qualified_name
    if dispatcher.namespace:
        candidate = f"{dispatcher.namespace}::{handler}"
        if candidate in symbol_by_qname:
            return candidate
    return handler

def _callback_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str, symbols: list[FunctionInfo]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    symbol_names = {s.name for s in symbols}
    for m in re.finditer(r"\b(?P<api>[A-Za-z_]\w*(?:register|Register|callback|Callback)[A-Za-z_]*)\s*\((?P<args>[^()]*)\)", line):
        args = _split_top_level_commas(m.group("args")) if m.group("args").strip() else []
        for arg in args:
            name = arg.strip().lstrip("&")
            if not re.fullmatch(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*", name):
                continue
            if name in _CONTROL_WORDS or name in _BUILTIN_TYPES:
                continue
            local_matches = [s for s in symbols if s.name == name or s.qualified_name == name]
            payload = {
                "relation_kind": "callback_registration",
                "api_name": m.group("api"),
                "callback_symbol": name,
                "caller": caller.display_name,
                "unknown_type": "callback_relation_not_execution",
                "resolution_status": "candidate_set" if local_matches else "unresolved",
                "candidate_qualified_names": [s.qualified_name for s in local_matches] or [name],
                "candidate_symbol_ids": [s.symbol_id for s in local_matches],
            }
            facts.append(
                CodeFact(
                    fact_type="relation",
                    path=path,
                    start_line=lineno,
                    end_line=lineno,
                    subject=m.group("api"),
                    predicate="registers_callback",
                    object=name,
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload=payload,
                )
            )
    return facts




def _callback_dataflow_relations(path: str, facts: list[CodeFact]) -> list[CodeFact]:
    """Link callback argument passing, storage, and later function-pointer invocation.

    This is intentionally a semantic dataflow trace, not proof that a concrete
    user callback executes on all paths.  It captures the common embedded C shape:

    * creator() calls init(..., callback_arg)
    * init() stores callback_arg into obj->callbackField
    * worker() invokes obj->callbackField(...)

    The concrete runtime object identity and final callback target remain unknown.
    """
    call_facts = [f for f in facts if f.fact_type == "call"]
    storage_facts = [f for f in facts if f.fact_type == "relation" and f.predicate == "stores_callback"]
    invocation_facts = [f for f in facts if f.fact_type == "relation" and f.predicate == "invokes_callback"]
    if not call_facts or not storage_facts or not invocation_facts:
        return []

    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for call in call_facts:
        caller = call.caller or call.subject
        callee = call.callee or call.object
        if not caller or not callee:
            continue
        args = [str(arg).strip().lstrip("&") for arg in (call.payload.get("argument_expressions") or []) if str(arg).strip()]
        if not args:
            continue
        for storage in storage_facts:
            storage_fn = storage.subject
            callback_symbol = str(storage.object or storage.payload.get("callback_symbol") or "").strip()
            callback_field = str(storage.payload.get("callback_field") or "").strip()
            if not storage_fn or not callback_symbol or not callback_field:
                continue
            if not _names_match_semantic(callee, storage_fn):
                continue
            if not any(_names_match_semantic(arg, callback_symbol) for arg in args):
                continue
            for invocation in invocation_facts:
                invocation_fn = invocation.subject
                invocation_field = str(invocation.payload.get("callback_field") or invocation.object or "").strip()
                if not invocation_fn or not invocation_field:
                    continue
                if not _names_match_semantic(callback_field, invocation_field):
                    continue
                key = (str(caller), str(storage_fn), str(invocation_fn), callback_symbol, callback_field)
                if key in seen:
                    continue
                seen.add(key)
                steps = [
                    {
                        "kind": "passes_callback_argument",
                        "function": caller,
                        "callee": callee,
                        "callback_symbol": callback_symbol,
                        "argument_expressions": args,
                        "line": call.start_line,
                    },
                    {
                        "kind": "stores_callback",
                        "function": storage_fn,
                        "callback_symbol": callback_symbol,
                        "storage_expr": storage.payload.get("storage_expr"),
                        "callback_field": callback_field,
                        "line": storage.start_line,
                    },
                    {
                        "kind": "invokes_callback",
                        "function": invocation_fn,
                        "callback_symbol": callback_symbol,
                        "callback_storage_expr": invocation.payload.get("callback_storage_expr"),
                        "callback_field": invocation_field,
                        "line": invocation.start_line,
                    },
                ]
                payload = {
                    "relation_kind": "callback_dataflow_trace",
                    "callback_symbol": callback_symbol,
                    "callback_field": callback_field,
                    "creator_function": caller,
                    "storage_function": storage_fn,
                    "invocation_function": invocation_fn,
                    "creator_execution_context": call.payload.get("execution_context") or call.payload.get("caller_execution_context"),
                    "storage_execution_context": storage.payload.get("execution_context") or storage.payload.get("caller_execution_context"),
                    "invocation_execution_context": invocation.payload.get("execution_context") or invocation.payload.get("caller_execution_context"),
                    "storage_expr": storage.payload.get("storage_expr"),
                    "callback_storage_expr": invocation.payload.get("callback_storage_expr"),
                    "pass_call_line": call.start_line,
                    "storage_line": storage.start_line,
                    "invocation_line": invocation.start_line,
                    "dataflow_steps": steps,
                    "call_fact_span": call.span.to_dict(),
                    "storage_fact_span": storage.span.to_dict(),
                    "invocation_fact_span": invocation.span.to_dict(),
                    "callback_resolution_status": "linked_storage_and_invocation_target_unknown",
                    "resolution_status": "semantic_relation",
                    "unknown_type": "callback_target_unknown",
                    "semantic_phase": "phase7_freertos_callback_dataflow",
                    "response_constraint": "Callback dataflow evidence links argument passing, storage, and invocation site, but does not resolve the concrete runtime callback target or prove execution on every path.",
                }
                relations.append(
                    CodeFact(
                        fact_type="relation",
                        path=path,
                        start_line=call.start_line,
                        end_line=invocation.end_line,
                        subject=str(caller),
                        predicate="callback_dataflows_to",
                        object=str(invocation_fn),
                        confidence="medium",
                        source="semantic_cpp_lightweight",
                        payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                    )
                )
    return relations


def _names_match_semantic(left: str, right: str) -> bool:
    left = left.strip().lstrip("&")
    right = right.strip().lstrip("&")
    return left == right or left.split("::")[-1] == right.split("::")[-1]


def _task_entry_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS-like task-entry function-pointer relations.

    These relations are deliberately not direct-call evidence.  A task entry
    argument such as ``pxTaskCode`` is stored in a TCB and/or passed into a port
    stack initializer; the task executes later via scheduler/context-switch
    machinery that is outside a normal C call edge.
    """
    facts: list[CodeFact] = []
    task_entry_params = {
        p.name
        for p in caller.parameters
        if p.name and ("TaskFunction_t" in p.type or re.search(r"task(code|function)|px(code|taskcode)", p.name, re.IGNORECASE))
    }

    def is_task_entry_symbol(name: str) -> bool:
        clean = name.strip().lstrip("&")
        return clean in task_entry_params or bool(re.search(r"task(code|function)|px(code|taskcode)", clean, re.IGNORECASE))

    # Store task entry in a TCB-like field, e.g. ``pxNewTCB->pxTaskCode = pxTaskCode;``.
    for m in re.finditer(
        r"(?P<storage>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*\s*(?:->|\.)\s*(?:pxTaskCode|pxTaskFunction|taskEntry|pxCode))\s*=\s*&?(?P<entry>[A-Za-z_]\w*)\s*(?:;|,)?",
        line,
        re.IGNORECASE,
    ):
        entry = m.group("entry")
        if not is_task_entry_symbol(entry):
            continue
        storage_expr = re.sub(r"\s+", "", m.group("storage"))
        field_name = re.split(r"->|\.", storage_expr)[-1]
        payload = {
            "relation_kind": "task_entry_storage",
            "task_entry_symbol": entry,
            "storage_expr": storage_expr,
            "task_entry_field": field_name,
            "deferred_execution": True,
            "scheduler_dependent_execution": True,
            "resolution_status": "semantic_relation",
            "unknown_type": "task_entry_execution_deferred",
            "semantic_phase": "phase7_freertos_task_entry_dataflow",
            "response_constraint": "Task-entry storage is not a direct call; execution is deferred until scheduler/context-switch machinery runs the task.",
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.display_name,
                predicate="stores_task_entry",
                object=entry,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )

    # Pass task entry into a port stack initializer, e.g.
    # ``pxPortInitialiseStack( ..., pxTaskCode, pvParameters )``.
    for m in re.finditer(r"(?P<stack>pxPortInitialiseStack|[A-Za-z_]\w*PortInitialiseStack)\s*\((?P<args>[^()]*)\)", line):
        args = _split_top_level_commas(m.group("args")) if m.group("args").strip() else []
        for arg in args:
            entry = arg.strip().lstrip("&")
            if not is_task_entry_symbol(entry):
                continue
            payload = {
                "relation_kind": "task_entry_stack_initialisation",
                "task_entry_symbol": entry,
                "stack_initialiser": m.group("stack"),
                "argument_expressions": list(args),
                "task_entry_argument_index": args.index(arg),
                "deferred_execution": True,
                "scheduler_dependent_execution": True,
                "resolution_status": "semantic_relation",
                "unknown_type": "task_entry_execution_deferred",
                "semantic_phase": "phase7_freertos_task_entry_dataflow",
                "response_constraint": "Passing a task entry to a stack initializer prepares deferred scheduler execution; it is not a direct function call to the task entry.",
                **_execution_context_payload_for_function(caller),
                **_execution_context_payload_for_function(caller, prefix="caller"),
            }
            facts.append(
                CodeFact(
                    fact_type="relation",
                    path=path,
                    start_line=lineno,
                    end_line=lineno,
                    subject=caller.display_name,
                    predicate="initializes_stack_with_task_entry",
                    object=m.group("stack"),
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                )
            )
            break
    return facts


def _task_entry_dataflow_relations(path: str, facts: list[CodeFact]) -> list[CodeFact]:
    """Link task-entry argument passing to TCB/stack initialisation.

    This FreeRTOS-oriented trace intentionally models deferred task entry
    registration rather than a direct call.  It links shapes such as:

    * xTaskCreate(..., pxTaskCode, ...) -> prvCreateTask(..., pxTaskCode, ...)
    * prvCreateTask(..., pxTaskCode, ...) -> prvInitialiseNewTask(..., pxTaskCode, ...)
    * prvInitialiseNewTask stores pxTaskCode and passes it to pxPortInitialiseStack
    """
    call_facts = [f for f in facts if f.fact_type == "call"]
    stack_facts = [f for f in facts if f.fact_type == "relation" and f.predicate == "initializes_stack_with_task_entry"]
    storage_facts = [f for f in facts if f.fact_type == "relation" and f.predicate == "stores_task_entry"]
    if not call_facts or not stack_facts:
        return []

    def call_args(fact: CodeFact) -> list[str]:
        return [str(arg).strip().lstrip("&") for arg in (fact.payload.get("argument_expressions") or []) if str(arg).strip()]

    relations: list[CodeFact] = []
    seen: set[tuple[str, str, str, str]] = set()
    for stack in stack_facts:
        storage_fn = str(stack.subject or "")
        entry_symbol = str(stack.payload.get("task_entry_symbol") or "").strip()
        stack_initialiser = str(stack.payload.get("stack_initialiser") or stack.object or "").strip()
        if not storage_fn or not entry_symbol or not stack_initialiser:
            continue
        matching_storage = [
            s for s in storage_facts
            if _names_match_semantic(str(s.subject or ""), storage_fn)
            and _names_match_semantic(str(s.object or s.payload.get("task_entry_symbol") or ""), entry_symbol)
        ]

        # Direct creator -> storage function, or creator -> factory -> storage function.
        for inbound in call_facts:
            inbound_caller = str(inbound.caller or inbound.subject or "")
            inbound_callee = str(inbound.callee or inbound.object or "")
            if not inbound_caller or not inbound_callee:
                continue
            if not any(_names_match_semantic(arg, entry_symbol) for arg in call_args(inbound)):
                continue

            factory_fn: str | None = None
            pass_call = inbound
            if _names_match_semantic(inbound_callee, storage_fn):
                creator_fn = inbound_caller
            else:
                # Look for factory -> storage forwarding of the same task-entry symbol.
                forwarded = None
                for candidate in call_facts:
                    if not _names_match_semantic(str(candidate.caller or candidate.subject or ""), inbound_callee):
                        continue
                    if not _names_match_semantic(str(candidate.callee or candidate.object or ""), storage_fn):
                        continue
                    if not any(_names_match_semantic(arg, entry_symbol) for arg in call_args(candidate)):
                        continue
                    forwarded = candidate
                    break
                if forwarded is None:
                    continue
                creator_fn = inbound_caller
                factory_fn = inbound_callee
                pass_call = forwarded

            if not re.search(r"TaskCreate|CreateTask|Task", creator_fn):
                # Avoid inventing task-entry traces for unrelated functions that happen
                # to pass a variable named pxTaskCode.
                continue
            key = (creator_fn, storage_fn, stack_initialiser, entry_symbol)
            if key in seen:
                continue
            seen.add(key)
            dataflow_steps = [
                {
                    "kind": "passes_task_entry_argument",
                    "function": creator_fn,
                    "callee": inbound_callee,
                    "task_entry_symbol": entry_symbol,
                    "argument_expressions": call_args(inbound),
                    "line": inbound.start_line,
                }
            ]
            if factory_fn:
                dataflow_steps.append(
                    {
                        "kind": "forwards_task_entry_argument",
                        "function": factory_fn,
                        "callee": storage_fn,
                        "task_entry_symbol": entry_symbol,
                        "argument_expressions": call_args(pass_call),
                        "line": pass_call.start_line,
                    }
                )
            if matching_storage:
                dataflow_steps.append(
                    {
                        "kind": "stores_task_entry",
                        "function": storage_fn,
                        "task_entry_symbol": entry_symbol,
                        "storage_expr": matching_storage[0].payload.get("storage_expr"),
                        "task_entry_field": matching_storage[0].payload.get("task_entry_field"),
                        "line": matching_storage[0].start_line,
                    }
                )
            dataflow_steps.append(
                {
                    "kind": "initializes_stack_with_task_entry",
                    "function": storage_fn,
                    "stack_initialiser": stack_initialiser,
                    "task_entry_symbol": entry_symbol,
                    "argument_expressions": stack.payload.get("argument_expressions") or [],
                    "line": stack.start_line,
                }
            )
            payload = {
                "relation_kind": "task_entry_dataflow_trace",
                "task_entry_symbol": entry_symbol,
                "creator_function": creator_fn,
                "factory_function": factory_fn,
                "storage_function": storage_fn,
                "stack_initialiser": stack_initialiser,
                "creator_execution_context": inbound.payload.get("execution_context") or inbound.payload.get("caller_execution_context"),
                "factory_execution_context": pass_call.payload.get("execution_context") or pass_call.payload.get("caller_execution_context"),
                "storage_execution_context": stack.payload.get("execution_context") or stack.payload.get("caller_execution_context"),
                "storage_expr": matching_storage[0].payload.get("storage_expr") if matching_storage else None,
                "task_entry_field": matching_storage[0].payload.get("task_entry_field") if matching_storage else None,
                "pass_call_line": inbound.start_line,
                "forward_call_line": pass_call.start_line if factory_fn else None,
                "storage_line": matching_storage[0].start_line if matching_storage else None,
                "stack_initialiser_line": stack.start_line,
                "dataflow_steps": dataflow_steps,
                "call_fact_span": inbound.span.to_dict(),
                "forward_call_fact_span": pass_call.span.to_dict() if factory_fn else None,
                "storage_fact_span": matching_storage[0].span.to_dict() if matching_storage else None,
                "stack_fact_span": stack.span.to_dict(),
                "task_entry_resolution_status": "linked_to_stack_initialiser_target_execution_deferred",
                "resolution_status": "semantic_relation",
                "unknown_type": "task_entry_execution_deferred",
                "deferred_execution": True,
                "scheduler_dependent_execution": True,
                "semantic_phase": "phase7_freertos_task_entry_dataflow",
                "response_constraint": "Task-entry dataflow links argument passing, optional TCB storage, and stack initialisation, but it is not a direct call and does not prove the concrete task function executes on every path.",
            }
            relations.append(
                CodeFact(
                    fact_type="relation",
                    path=path,
                    start_line=inbound.start_line,
                    end_line=inbound.end_line,
                    subject=creator_fn,
                    predicate="task_entry_dataflows_to",
                    object=stack_initialiser,
                    confidence="medium",
                    source="semantic_cpp_lightweight",
                    payload={k: v for k, v in payload.items() if v not in (None, [], {})},
                )
            )
    return relations





def _short_symbol_name(name: str | None) -> str:
    if not name:
        return ""
    return str(name).split("::")[-1]


def _is_freertos_port_symbol(name: str | None) -> bool:
    """Return true for FreeRTOS port-layer entry points and port hooks.

    The predicate is intentionally heuristic: repoanalyzer is not proving the
    complete port implementation.  It marks the point where common kernel code
    crosses into target/architecture-specific code so later answers keep the
    port/assembly/vector-table uncertainty explicit.
    """
    short = _short_symbol_name(name)
    if not short:
        return False
    if re.match(r"^(?:x|v|px|pv|ul|ux)Port[A-Za-z0-9_]*", short):
        return True
    return short in {
        "SVC_Handler",
        "PendSV_Handler",
        "SysTick_Handler",
        "vPortSVCHandler",
        "xPortPendSVHandler",
        "xPortSysTickHandler",
    }


def _port_boundary_kind(name: str | None, path: str = "") -> tuple[str, list[str]]:
    short = _short_symbol_name(name)
    unknowns = ["port_layer_boundary"]
    kind = "port_layer"
    if short in {"xPortStartScheduler", "vPortStartScheduler"}:
        kind = "scheduler_start_boundary"
        unknowns.extend(["assembly_boundary_unverified", "startup_file_missing"])
    elif short in {"pxPortInitialiseStack", "vPortInitialiseStack"}:
        kind = "task_stack_initialisation_boundary"
        unknowns.extend(["port_stack_layout_target_specific", "assembly_boundary_unverified"])
    elif re.search(r"(?:SysTick|PendSV|SVC|Handler)", short):
        kind = "exception_vector_boundary"
        unknowns.extend(["vector_table_unverified", "assembly_boundary_unverified"])
    elif "/portable/" in path.replace("\\", "/") or path.replace("\\", "/").startswith("portable/"):
        kind = "portable_source_boundary"
    return kind, _dedupe_strings(unknowns)


def _port_boundary_response_constraint(caller: str | None, callee: str | None, kind: str) -> str:
    if callee:
        return (
            f"{caller} reaches FreeRTOS port-layer boundary {callee}; C-source evidence stops at this boundary and "
            "target-specific port code, assembly/startup/vector-table evidence may still be required."
        )
    return (
        f"{caller} is FreeRTOS port-layer boundary evidence; do not treat it as fully verified beyond the "
        "selected port source without startup/assembly/vector-table evidence."
    )


def _port_boundary_definition_facts(path: str, functions: tuple[FunctionInfo, ...]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    normalized_path = path.replace("\\", "/")
    for fn in functions:
        if fn.declaration_or_definition != "definition":
            continue
        if not (_is_freertos_port_symbol(fn.name) or "/portable/" in f"/{normalized_path}"):
            continue
        kind, unknowns = _port_boundary_kind(fn.name, normalized_path)
        payload = {
            "relation_kind": "port_boundary_definition",
            "port_boundary_kind": kind,
            "port_function": fn.display_name,
            "port_function_qualified_name": fn.qualified_name,
            "port_function_symbol_id": fn.symbol_id,
            "unknown_type": unknowns[0] if unknowns else "port_layer_boundary",
            "unknown_types": unknowns,
            "semantic_phase": "phase7_freertos_port_boundary",
            "resolution_status": "semantic_relation",
            "response_constraint": _port_boundary_response_constraint(fn.display_name, None, kind),
            **_execution_context_payload_for_function(fn),
            **_execution_context_payload_for_function(fn, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=fn.start_line,
                end_line=fn.end_line,
                subject=fn.display_name,
                predicate="has_port_boundary",
                object="port_layer",
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _port_boundary_relations_from_calls(path: str, caller: FunctionInfo, lineno: int, call_facts: list[CodeFact]) -> list[CodeFact]:
    facts: list[CodeFact] = []
    for call in call_facts:
        if call.fact_type != "call" or call.predicate != "calls":
            continue
        callee = call.callee or call.object
        if not _is_freertos_port_symbol(callee):
            continue
        kind, unknowns = _port_boundary_kind(callee, path)
        payload = {
            "relation_kind": "port_boundary_crossing",
            "port_boundary_kind": kind,
            "caller": caller.display_name,
            "callee": callee,
            "port_api": callee,
            "call_kind": call.call_kind,
            "call_fact_span": call.span.to_dict(),
            "unknown_type": unknowns[0] if unknowns else "port_layer_boundary",
            "unknown_types": unknowns,
            "semantic_phase": "phase7_freertos_port_boundary",
            "resolution_status": "semantic_relation",
            "response_constraint": _port_boundary_response_constraint(caller.display_name, callee, kind),
            **{k: v for k, v in (call.payload or {}).items() if k.endswith("execution_context") or k.endswith("execution_context_basis")},
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.display_name,
                predicate="crosses_port_boundary",
                object=str(callee),
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


_APPLICATION_HOOK_APIS: dict[str, tuple[str, str]] = {
    "vApplicationMallocFailedHook": ("malloc_failed_hook", "application_malloc_failed_hook"),
    "vApplicationStackOverflowHook": ("stack_overflow_hook", "application_stack_overflow_hook"),
    "vApplicationIdleHook": ("idle_hook", "application_idle_hook"),
    "vApplicationTickHook": ("tick_hook", "application_tick_hook"),
    "vApplicationDaemonTaskStartupHook": ("daemon_task_startup_hook", "application_daemon_task_startup_hook"),
    "vApplicationGetIdleTaskMemory": ("idle_task_memory_hook", "application_static_memory_hook"),
    "vApplicationGetTimerTaskMemory": ("timer_task_memory_hook", "application_static_memory_hook"),
}


def _hook_assert_trace_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS hook/assert/trace semantics.

    Trace macros, configASSERT and application hooks are deliberately not
    ordinary control-flow proof.  They expose extension/diagnostic boundaries:
    application code may provide hook bodies, trace macros may be compiled out,
    and assert behavior depends on the user's FreeRTOSConfig.h definition.
    Capture those facts so final answers keep the target/application-defined
    nature of the evidence instead of treating them as normal direct calls.
    """
    facts: list[CodeFact] = []
    line_clean = re.sub(r"\s+", " ", line.strip())
    if not line_clean:
        return facts
    caller_name = caller.display_name

    def add(
        predicate: str,
        obj: str,
        *,
        api_name: str,
        operation_kind: str,
        trigger_expr: str,
        unknown_type: str,
        category: str,
        confidence: str = "medium",
    ) -> None:
        payload = {
            "relation_kind": "freertos_hook_assert_trace_semantic",
            "hook_assert_trace_category": category,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "trigger_expr": trigger_expr,
            "semantic_predicate": predicate,
            "caller": caller_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "resolution_status": "semantic_relation",
            "unknown_type": unknown_type,
            "semantic_phase": "phase7_freertos_hook_assert_trace_semantics",
            "response_constraint": _hook_assert_trace_response_constraint(predicate, api_name, caller_name),
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller_name,
                predicate=predicate,
                object=obj,
                confidence=confidence,
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )

    # FreeRTOS trace macros follow a trace* naming convention.  Treat them as
    # instrumentation hook evidence, not as direct calls into a concrete trace
    # implementation, because applications may define them as no-ops or route
    # them through a trace recorder.
    for m in re.finditer(r"\b(trace[A-Za-z0-9_]+)\s*\(", line_clean):
        api = m.group(1)
        add(
            "invokes_trace_hook",
            api,
            api_name=api,
            operation_kind="trace_hook_invocation",
            trigger_expr=line_clean,
            unknown_type="trace_hook_target_unknown",
            category="trace_hook",
        )

    if re.search(r"\bconfigASSERT\s*\(", line_clean):
        add(
            "invokes_assert_handler",
            "configASSERT",
            api_name="configASSERT",
            operation_kind="assert_check",
            trigger_expr=line_clean,
            unknown_type="assert_handler_config_dependent",
            category="assert",
        )

    if re.search(r"\bmtCOVERAGE_TEST_MARKER\s*\(", line_clean):
        add(
            "coverage_marker",
            "mtCOVERAGE_TEST_MARKER",
            api_name="mtCOVERAGE_TEST_MARKER",
            operation_kind="coverage_marker",
            trigger_expr=line_clean,
            unknown_type="coverage_marker_not_runtime_behavior",
            category="coverage",
        )

    for api, (obj, operation_kind) in _APPLICATION_HOOK_APIS.items():
        if not re.search(rf"\b{re.escape(api)}\s*\(", line_clean):
            continue
        add(
            "invokes_application_hook",
            obj,
            api_name=api,
            operation_kind=operation_kind,
            trigger_expr=line_clean,
            unknown_type="application_defined_hook_target_unknown",
            category="application_hook",
        )

    return _dedupe_relation_facts(facts)


def _hook_assert_trace_response_constraint(predicate: str, api_name: str, caller: str) -> str:
    if predicate == "invokes_trace_hook":
        return f"{caller} invokes FreeRTOS trace hook {api_name}; treat it as instrumentation/configurable trace evidence, not guaranteed application behavior."
    if predicate == "invokes_assert_handler":
        return f"{caller} uses configASSERT; qualify assert behavior by the application's FreeRTOSConfig.h definition."
    if predicate == "invokes_application_hook":
        return f"{caller} invokes application hook {api_name}; the hook body is application-defined and may be absent from the analyzed source."
    if predicate == "coverage_marker":
        return f"{caller} reaches mtCOVERAGE_TEST_MARKER; describe it as coverage/test marker evidence, not runtime kernel behavior."
    return f"{caller} has FreeRTOS hook/assert/trace semantic evidence."


_HEAP_ALLOCATOR_SEMANTICS: dict[str, tuple[str, str, str, str, str]] = {
    # predicate: (object, category, operation_kind, unknown_type, response noun)
    "allocates_heap_memory": ("heap_memory", "heap_allocation", "heap_allocate", "heap_runtime_state_unknown", "heap allocation"),
    "frees_heap_memory": ("heap_memory", "heap_free", "heap_free", "heap_runtime_state_unknown", "heap free"),
    "coalesces_free_blocks": ("free_block_list", "heap_coalescing", "free_block_coalescing", "heap_coalescing_path_dependent", "free-block coalescing"),
    "uses_libc_allocator": ("libc_allocator", "libc_heap_wrapper", "libc_allocator_use", "external_allocator_behavior_unknown", "libc allocator wrapper"),
    "uses_multiple_heap_regions": ("heap_regions", "multi_region_heap", "multiple_heap_regions", "heap_region_configuration_required", "multiple heap regions"),
    "does_not_support_free": ("heap_memory", "no_free_allocator", "no_free_supported", "heap_free_not_supported", "no-free allocator"),
}

_HEAP_FUNCTION_PREDICATES: dict[str, tuple[str, ...]] = {
    "pvPortMalloc": ("allocates_heap_memory",),
    "vPortFree": ("frees_heap_memory",),
    "prvInsertBlockIntoFreeList": ("coalesces_free_blocks",),
    "vPortDefineHeapRegions": ("uses_multiple_heap_regions",),
}


def _heap_allocator_name_from_path(path: str) -> str | None:
    m = re.search(r"(?:^|/)heap_(\d+)\.c$", path.replace("\\", "/"))
    if not m:
        return None
    return f"heap_{m.group(1)}"


def _heap_allocator_semantic_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS heap allocator semantics.

    FreeRTOS ships multiple heap implementations with deliberately different
    behavior. Capture those allocator-level facts as semantic evidence so an
    answer can say, for example, that heap_3 delegates to libc malloc/free, or
    heap_4 coalesces free blocks, instead of reducing everything to a generic
    pvPortMalloc/vPortFree call edge.
    """
    allocator = _heap_allocator_name_from_path(path)
    if not allocator:
        return []
    line_clean = re.sub(r"\s+", " ", line.strip())
    if not line_clean:
        return []
    facts: list[CodeFact] = []
    caller_name = caller.display_name
    short = caller.name

    def add(predicate: str, *, api_name: str, trigger_expr: str, confidence: str = "medium") -> None:
        obj, category, operation_kind, unknown_type, noun = _HEAP_ALLOCATOR_SEMANTICS[predicate]
        payload = {
            "relation_kind": "freertos_heap_allocator_semantic",
            "heap_allocator": allocator,
            "heap_allocator_category": category,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "trigger_expr": trigger_expr,
            "semantic_predicate": predicate,
            "state_object": obj,
            "caller": caller_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "resolution_status": "semantic_relation",
            "unknown_type": unknown_type,
            "semantic_phase": "phase7_freertos_heap_allocator_semantics",
            "response_constraint": _heap_allocator_response_constraint(predicate, caller_name, allocator, noun),
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(CodeFact(
            fact_type="relation",
            path=path,
            start_line=lineno,
            end_line=lineno,
            subject=caller_name,
            predicate=predicate,
            object=obj,
            confidence=confidence,
            source="semantic_cpp_lightweight",
            payload={k: v for k, v in payload.items() if v not in (None, [], {})},
        ))

    # Function-level semantics, conservatively gated on body content.  One-line
    # compact fixtures and real FreeRTOS sources both include these tokens.
    for predicate in _HEAP_FUNCTION_PREDICATES.get(short, ()):
        if predicate == "allocates_heap_memory" and re.search(r"\b(pvPortMalloc|malloc|ucHeap|xWantedSize|xWantedSize)\b", line_clean):
            add(predicate, api_name=short, trigger_expr=line_clean)
        elif predicate == "frees_heap_memory" and re.search(r"\b(vPortFree|free|prvInsertBlockIntoFreeList|pxLink|puc)\b", line_clean):
            add(predicate, api_name=short, trigger_expr=line_clean)
        elif predicate == "coalesces_free_blocks" and re.search(r"\b(prvInsertBlockIntoFreeList|xBlockSize|pxBlockToInsert|pxIterator|puc)\b", line_clean):
            add(predicate, api_name=short, trigger_expr=line_clean)
        elif predicate == "uses_multiple_heap_regions" and re.search(r"\b(vPortDefineHeapRegions|HeapRegion_t|pxHeapRegions|xDefinedRegions|heap_regions)\b", line_clean):
            add(predicate, api_name=short, trigger_expr=line_clean)

    # Implementation-specific semantic markers.
    if allocator == "heap_3":
        if re.search(r"\bmalloc\s*\(", line_clean):
            add("uses_libc_allocator", api_name="malloc", trigger_expr=line_clean)
        if re.search(r"\bfree\s*\(", line_clean):
            add("uses_libc_allocator", api_name="free", trigger_expr=line_clean)
    if allocator in {"heap_4", "heap_5"}:
        if "prvInsertBlockIntoFreeList" in line_clean or "pxBlockToInsert->xBlockSize" in line_clean:
            add("coalesces_free_blocks", api_name="prvInsertBlockIntoFreeList", trigger_expr=line_clean, confidence="medium")
    if allocator == "heap_5" and ("HeapRegion_t" in line_clean or "pxHeapRegions" in line_clean or short == "vPortDefineHeapRegions"):
        add("uses_multiple_heap_regions", api_name="vPortDefineHeapRegions", trigger_expr=line_clean, confidence="medium")
    if allocator == "heap_1" and short == "vPortFree" and "configASSERT" in line_clean:
        add("does_not_support_free", api_name="vPortFree", trigger_expr=line_clean, confidence="medium")

    return _dedupe_relation_facts(facts)


def _heap_allocator_response_constraint(predicate: str, function: str, allocator: str, noun: str) -> str:
    if predicate == "allocates_heap_memory":
        return f"{function} has FreeRTOS {allocator} allocation semantics; describe allocator behavior, not just a generic call edge."
    if predicate == "frees_heap_memory":
        return f"{function} has FreeRTOS {allocator} free semantics; qualify free behavior by the selected heap implementation."
    if predicate == "coalesces_free_blocks":
        return f"{function} has FreeRTOS {allocator} free-block coalescing evidence; do not imply all heap implementations coalesce."
    if predicate == "uses_libc_allocator":
        return f"{function} in FreeRTOS {allocator} delegates to the C library allocator; qualify behavior by external libc malloc/free."
    if predicate == "uses_multiple_heap_regions":
        return f"{function} has FreeRTOS {allocator} multi-region heap semantics; require heap-region configuration evidence for concrete memory layout claims."
    if predicate == "does_not_support_free":
        return f"{function} in FreeRTOS {allocator} indicates free is unsupported; do not claim ordinary deallocation behavior for this heap."
    return f"{function} has FreeRTOS heap allocator semantic evidence ({noun})."

def _scheduler_semantic_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS scheduler/yield/critical-section semantic relations.

    These are not ordinary direct-call facts.  FreeRTOS exposes many execution
    semantics through macros or port hooks: critical sections, scheduler
    suspension, and context-switch requests.  Capture those as meaning-level
    relations so answer contracts can preserve the distinction between a normal
    call and scheduler/interrupt side effects.
    """
    facts: list[CodeFact] = []
    patterns: list[tuple[str, str, str, str, str, str, str, str | None]] = [
        ("taskENTER_CRITICAL", "enters_critical_section", "critical_section", "critical_section", "task_or_kernel", "critical_section_enter", "phase7_freertos_scheduler_semantics", None),
        ("taskEXIT_CRITICAL", "exits_critical_section", "critical_section", "critical_section", "task_or_kernel", "critical_section_exit", "phase7_freertos_scheduler_semantics", None),
        ("vTaskSuspendAll", "suspends_scheduler", "scheduler", "scheduler_control", "task", "scheduler_suspend", "phase7_freertos_scheduler_semantics", None),
        ("xTaskResumeAll", "resumes_scheduler", "scheduler", "scheduler_control", "task", "scheduler_resume", "phase7_freertos_scheduler_semantics", None),
        ("portYIELD_FROM_ISR", "requests_context_switch", "context_switch", "yield_request", "isr", "yield_from_isr", "phase7_freertos_scheduler_semantics", "scheduler_dependent_execution"),
        ("portYIELD_WITHIN_API", "requests_context_switch", "context_switch", "yield_request", "task", "yield_within_api", "phase7_freertos_scheduler_semantics", "scheduler_dependent_execution"),
        ("portYIELD", "requests_context_switch", "context_switch", "yield_request", "task", "yield", "phase7_freertos_scheduler_semantics", "scheduler_dependent_execution"),
        ("taskYIELD", "requests_context_switch", "context_switch", "yield_request", "task", "task_yield", "phase7_freertos_scheduler_semantics", "scheduler_dependent_execution"),
        ("portSET_INTERRUPT_MASK_FROM_ISR", "masks_interrupts_from_isr", "interrupt_mask", "interrupt_masking", "isr", "set_interrupt_mask_from_isr", "phase7_freertos_scheduler_semantics", "interrupt_mask_state_deferred"),
        ("portCLEAR_INTERRUPT_MASK_FROM_ISR", "clears_interrupt_mask_from_isr", "interrupt_mask", "interrupt_masking", "isr", "clear_interrupt_mask_from_isr", "phase7_freertos_scheduler_semantics", "interrupt_mask_state_deferred"),
    ]
    for api_name, predicate, obj, relation_kind, context, operation_kind, semantic_phase, unknown_type in patterns:
        if not re.search(rf"\b{re.escape(api_name)}\s*\(", line):
            continue
        payload = {
            "relation_kind": relation_kind,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "execution_context": context,
            "execution_context_basis": "freertos_scheduler_semantic_api",
            "caller": caller.display_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "resolution_status": "semantic_relation",
            "semantic_phase": semantic_phase,
            "response_constraint": _scheduler_response_constraint(predicate, api_name, context),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        if unknown_type:
            payload["unknown_type"] = unknown_type
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.display_name,
                predicate=predicate,
                object=obj,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return facts


def _scheduler_response_constraint(predicate: str, api_name: str, context: str) -> str:
    if predicate == "requests_context_switch":
        return f"{api_name} is yield/context-switch request evidence, not proof that a context switch has already occurred on every path."
    if predicate in {"enters_critical_section", "exits_critical_section"}:
        return f"{api_name} is critical-section evidence; describe interrupt/scheduler protection semantics rather than a normal data-flow call."
    if predicate in {"suspends_scheduler", "resumes_scheduler"}:
        return f"{api_name} is scheduler-control evidence; preserve scheduler suspension/resumption semantics in the answer."
    if predicate in {"masks_interrupts_from_isr", "clears_interrupt_mask_from_isr"}:
        return f"{api_name} is ISR interrupt-mask evidence; preserve ISR masking/unmasking semantics."
    return f"{api_name} is FreeRTOS scheduler semantic evidence in {context} context."


def _task_state_transition_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS task/list state-transition semantics.

    The kernel represents task state through intrusive lists.  A raw call such
    as ``vListInsert`` or ``uxListRemove`` is useful, but it does not tell an LLM
    whether a task is being made ready, delayed, blocked on an event list, or
    unblocked from a queue/event wait.  Capture the common FreeRTOS idioms as
    meaning-level relations while preserving that these are list-state evidence,
    not proof of a complete scheduler state machine for every runtime path.
    """
    facts: list[CodeFact] = []
    line_clean = re.sub(r"\s+", " ", line.strip())
    caller_name = caller.display_name
    short = caller.name

    def add(predicate: str, obj: str, *, api_name: str, operation_kind: str, trigger_expr: str, confidence: str = "medium") -> None:
        payload = {
            "relation_kind": "freertos_task_state_transition",
            "operation_kind": operation_kind,
            "api_name": api_name,
            "trigger_expr": trigger_expr,
            "transition_predicate": predicate,
            "state_object": obj,
            "caller": caller_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "resolution_status": "semantic_relation",
            "unknown_type": "task_state_transition_semantic",
            "semantic_phase": "phase7_freertos_task_state_transition",
            "response_constraint": _task_state_transition_response_constraint(predicate, caller_name, obj),
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller_name,
                predicate=predicate,
                object=obj,
                confidence=confidence,
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )

    if re.search(r"\bprvAddTaskToReadyList\s*\(", line_clean) or re.search(r"\bvListInsertEnd\s*\([^;]*pxReadyTasksLists", line_clean):
        add(
            "moves_task_to_ready_list",
            "ready_list",
            api_name="prvAddTaskToReadyList" if "prvAddTaskToReadyList" in line_clean else "vListInsertEnd",
            operation_kind="move_task_to_ready_list",
            trigger_expr=line_clean,
        )
    elif short == "prvAddNewTaskToReadyList" and re.search(r"\(\s*void\s*\)\s*pxNewTCB", line_clean):
        add(
            "moves_task_to_ready_list",
            "ready_list",
            api_name="prvAddNewTaskToReadyList",
            operation_kind="move_new_task_to_ready_list",
            trigger_expr="function_name:prvAddNewTaskToReadyList",
        )

    if re.search(r"\bvTaskPlaceOnEventList\s*\(", line_clean) or re.search(r"\bvTaskPlaceOnEventListRestricted\s*\(", line_clean):
        add(
            "blocks_task_on_event_list",
            "event_list",
            api_name="vTaskPlaceOnEventListRestricted" if "vTaskPlaceOnEventListRestricted" in line_clean else "vTaskPlaceOnEventList",
            operation_kind="block_task_on_event_list",
            trigger_expr=line_clean,
        )
    elif short in {"vTaskPlaceOnEventList", "vTaskPlaceOnEventListRestricted"} and re.search(r"\bvListInsert(?:End)?\s*\(", line_clean):
        add(
            "blocks_task_on_event_list",
            "event_list",
            api_name="vListInsertEnd" if "vListInsertEnd" in line_clean else "vListInsert",
            operation_kind="insert_task_into_event_wait_list",
            trigger_expr=line_clean,
        )

    if re.search(r"\bxTaskRemoveFromEventList\s*\(", line_clean):
        add(
            "unblocks_task_from_event_list",
            "event_list",
            api_name="xTaskRemoveFromEventList",
            operation_kind="unblock_task_from_event_list",
            trigger_expr=line_clean,
        )

    if short == "xTaskRemoveFromEventList" and re.search(r"\bprvAddTaskToReadyList\s*\(", line_clean):
        add(
            "unblocks_task_from_event_list",
            "event_list",
            api_name="prvAddTaskToReadyList",
            operation_kind="unblock_task_from_event_list_to_ready",
            trigger_expr=line_clean,
        )

    if re.search(r"\bprvAddCurrentTaskToDelayedList\s*\(", line_clean):
        add(
            "moves_task_to_delayed_list",
            "delayed_list",
            api_name="prvAddCurrentTaskToDelayedList",
            operation_kind="move_current_task_to_delayed_list",
            trigger_expr=line_clean,
        )
    elif short == "prvAddCurrentTaskToDelayedList" and re.search(r"\bvListInsert\s*\(", line_clean) and re.search(r"DelayedList|pxDelayedList|pxOverflowDelayedList", line_clean):
        add(
            "moves_task_to_delayed_list",
            "delayed_list",
            api_name="vListInsert",
            operation_kind="insert_current_task_into_delayed_list",
            trigger_expr=line_clean,
        )

    if re.search(r"\buxListRemove\s*\(", line_clean):
        list_kind = "event_list" if "xEventListItem" in line_clean else "task_state_list" if "xStateListItem" in line_clean else "list"
        add(
            "removes_task_from_list",
            list_kind,
            api_name="uxListRemove",
            operation_kind="remove_task_from_list",
            trigger_expr=line_clean,
            confidence="low" if list_kind == "list" else "medium",
        )

    return _dedupe_relation_facts(facts)


def _task_state_transition_response_constraint(predicate: str, function: str, obj: str) -> str:
    if predicate == "moves_task_to_ready_list":
        return f"{function} has FreeRTOS ready-list transition evidence; describe it as task state/list movement, not merely a raw list helper call."
    if predicate == "moves_task_to_delayed_list":
        return f"{function} has delayed-list transition evidence; qualify it as scheduler/list-state evidence rather than direct task execution."
    if predicate == "blocks_task_on_event_list":
        return f"{function} places a task on an event/list wait path; describe this as blocking/wait-list state evidence, not as proof of wake-up."
    if predicate == "unblocks_task_from_event_list":
        return f"{function} removes/unblocks a task from an event-list wait path; describe this as unblocking-to-ready evidence when paired with ready-list insertion."
    if predicate == "removes_task_from_list":
        return f"{function} removes a task list item from {obj}; preserve list-state transition semantics instead of reducing it to a normal call."
    return f"{function} has FreeRTOS task/list state-transition evidence."


_PORT_ADVANCED_SEMANTICS: dict[str, tuple[str, str, str, str, str]] = {
    # predicate: (object, category, operation_kind, unknown_type, response noun)
    "uses_smp_scheduler": ("smp_scheduler", "smp", "smp_scheduler", "smp_runtime_interleaving_unknown", "SMP scheduler"),
    "uses_core_affinity": ("core_affinity", "smp", "core_affinity", "core_affinity_runtime_state_unknown", "core-affinity"),
    "uses_cross_core_yield": ("cross_core_yield", "smp", "cross_core_yield", "cross_core_yield_target_unknown", "cross-core yield"),
    "uses_smp_locking": ("smp_lock", "smp", "smp_locking", "smp_lock_order_runtime_unknown", "SMP lock"),
    "uses_mpu_wrappers": ("mpu_wrapper", "mpu", "mpu_wrapper", "mpu_port_configuration_required", "MPU wrapper"),
    "configures_mpu_regions": ("mpu_region", "mpu", "mpu_region_configuration", "mpu_region_layout_target_specific", "MPU region"),
    "checks_mpu_access": ("mpu_access_check", "mpu", "mpu_access_check", "mpu_access_policy_target_specific", "MPU access-check"),
    "crosses_privilege_boundary": ("privilege_boundary", "mpu", "privilege_boundary", "privilege_boundary_target_specific", "privilege boundary"),
    "uses_port_assembly": ("port_assembly", "port_advanced", "port_assembly", "assembly_boundary_unverified", "port assembly"),
    "uses_secure_context_boundary": ("secure_context", "port_advanced", "secure_context_boundary", "secure_context_boundary_unverified", "secure-context boundary"),
}


def _port_advanced_semantic_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS SMP/MPU/advanced-port semantics.

    These relations deliberately do not claim a complete runtime proof.  They
    mark places where kernel behavior depends on multi-core scheduling state,
    MPU configuration/privilege transitions, or assembly/startup/secure-context
    port code so downstream answers keep those boundaries qualified.
    """
    facts: list[CodeFact] = []
    line_clean = re.sub(r"\s+", " ", line.strip())
    if not line_clean:
        return facts
    caller_name = caller.display_name
    short = caller.name
    is_function_entry_line = lineno in {caller.start_line, caller.body_start_line}
    normalized_path = path.replace("\\", "/")

    def add(predicate: str, *, api_name: str, trigger_expr: str, confidence: str = "medium") -> None:
        obj, category, operation_kind, unknown_type, noun = _PORT_ADVANCED_SEMANTICS[predicate]
        unknown_types = [unknown_type, "port_advanced_target_specific"]
        if category == "smp":
            unknown_types.append("configNUMBER_OF_CORES_profile_dependent")
        if category == "mpu":
            unknown_types.append("mpu_wrapper_configuration_dependent")
        payload = {
            "relation_kind": "freertos_port_advanced_semantic",
            "port_advanced_category": category,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "trigger_expr": trigger_expr,
            "semantic_predicate": predicate,
            "state_object": obj,
            "caller": caller_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "path_category": _port_advanced_path_category(normalized_path),
            "resolution_status": "semantic_relation",
            "unknown_type": unknown_type,
            "unknown_types": _dedupe_strings(unknown_types),
            "semantic_phase": "phase7_freertos_port_advanced_semantics",
            "response_constraint": _port_advanced_response_constraint(predicate, caller_name, noun),
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller_name,
                predicate=predicate,
                object=obj,
                confidence=confidence,
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )

    if (short == "prvSelectHighestPriorityTask" and is_function_entry_line) or "configNUMBER_OF_CORES" in line_clean or "pxCurrentTCBs[" in line_clean or re.search(r"\bprvSelectHighestPriorityTask\s*\(", line_clean):
        add("uses_smp_scheduler", api_name="configNUMBER_OF_CORES" if "configNUMBER_OF_CORES" in line_clean else "prvSelectHighestPriorityTask", trigger_expr=line_clean or f"function_name:{short}")
    if "uxCoreAffinityMask" in line_clean or "configUSE_CORE_AFFINITY" in line_clean or (re.search(r"AffinitySet\b", short) and is_function_entry_line):
        add("uses_core_affinity", api_name="uxCoreAffinityMask" if "uxCoreAffinityMask" in line_clean else short, trigger_expr=line_clean or f"function_name:{short}")
    if (short == "prvYieldCore" and is_function_entry_line) or "portYIELD_CORE" in line_clean or re.search(r"\bprvYieldCore\s*\(", line_clean):
        add("uses_cross_core_yield", api_name="portYIELD_CORE" if "portYIELD_CORE" in line_clean else "prvYieldCore", trigger_expr=line_clean or f"function_name:{short}")
    if re.search(r"\bport(?:GET|RELEASE)_(?:TASK|ISR)_LOCK\s*\(", line_clean):
        lock = re.search(r"\b(port(?:GET|RELEASE)_(?:TASK|ISR)_LOCK)\s*\(", line_clean)
        add("uses_smp_locking", api_name=lock.group(1) if lock else "portSMP_LOCK", trigger_expr=line_clean)

    if "MPU_WRAPPERS_INCLUDED_FROM_API_FILE" in line_clean or "portUSING_MPU_WRAPPERS" in line_clean or (short.startswith("MPU_") and is_function_entry_line):
        add("uses_mpu_wrappers", api_name="MPU_WRAPPERS_INCLUDED_FROM_API_FILE" if "MPU_WRAPPERS_INCLUDED_FROM_API_FILE" in line_clean else short, trigger_expr=line_clean)
    if (short in {"xTaskCreateRestricted", "xTaskCreateRestrictedStatic", "vTaskAllocateMPURegions"} and is_function_entry_line) or re.search(r"\b(?:xTaskCreateRestricted(?:Static)?|vTaskAllocateMPURegions|vPortStoreTaskMPUSettings|prvSetupMPU)\s*\(", line_clean) or "xRegions" in line_clean or "xMPUSettings" in line_clean:
        m = re.search(r"\b(xTaskCreateRestrictedStatic|xTaskCreateRestricted|vTaskAllocateMPURegions|vPortStoreTaskMPUSettings|prvSetupMPU)\s*\(", line_clean)
        add("configures_mpu_regions", api_name=m.group(1) if m else short if short in {"xTaskCreateRestricted", "xTaskCreateRestrictedStatic", "vTaskAllocateMPURegions"} else "mpu_region_configuration", trigger_expr=line_clean or f"function_name:{short}")
    if (short in {"xPortIsAuthorizedToAccessBuffer", "xPortIsAuthorizedToAccessKernelObject", "xPortIsInsideInterrupt"} and (is_function_entry_line or "return" in line_clean or "pdTRUE" in line_clean or "pdFALSE" in line_clean)) or re.search(r"\b(?:xPortIsAuthorizedToAccessBuffer|xPortIsAuthorizedToAccessKernelObject|xPortIsInsideInterrupt)\s*\(", line_clean):
        m = re.search(r"\b(xPortIsAuthorizedToAccessBuffer|xPortIsAuthorizedToAccessKernelObject|xPortIsInsideInterrupt)\s*\(", line_clean)
        add("checks_mpu_access", api_name=m.group(1) if m else short, trigger_expr=line_clean or f"function_name:{short}")
    if (short.startswith("MPU_") and is_function_entry_line) or re.search(r"\b(?:MPU_[A-Za-z_]\w*|vRaisePrivilege|vResetPrivilege|portRAISE_PRIVILEGE|portRESET_PRIVILEGE|portSWITCH_TO_USER_MODE)\s*\(", line_clean):
        m = re.search(r"\b(MPU_[A-Za-z_]\w*|vRaisePrivilege|vResetPrivilege|portRAISE_PRIVILEGE|portRESET_PRIVILEGE|portSWITCH_TO_USER_MODE)\s*\(", line_clean)
        add("crosses_privilege_boundary", api_name=m.group(1) if m else short, trigger_expr=line_clean or f"function_name:{short}")

    if (short in {"vPortSVCHandler", "xPortPendSVHandler", "vPortYield", "prvPortStartFirstTask"} and (is_function_entry_line or "__asm" in line_clean or "asm" in line_clean)) or normalized_path.endswith(("portasm.c", "portasm.S", "portasm.s", "portASM.asm", "portasm.asm")) or re.search(r"\b(?:vPortSVCHandler|xPortPendSVHandler|vPortYield|prvPortStartFirstTask)\s*\(", line_clean):
        m = re.search(r"\b(vPortSVCHandler|xPortPendSVHandler|vPortYield|prvPortStartFirstTask)\s*\(", line_clean)
        add("uses_port_assembly", api_name=m.group(1) if m else short if short in {"vPortSVCHandler", "xPortPendSVHandler", "vPortYield", "prvPortStartFirstTask"} else "portasm", trigger_expr=line_clean or f"function_name:{short}")
    if ((short.startswith("SecureContext_") or short == "vPortAllocateSecureContext") and (is_function_entry_line or "__asm" in line_clean or "asm" in line_clean)) or "SecureContext" in line_clean or "secure_context" in normalized_path or re.search(r"\b(?:SecureContext_[A-Za-z_]\w*|vPortAllocateSecureContext)\s*\(", line_clean):
        m = re.search(r"\b(SecureContext_[A-Za-z_]\w*|vPortAllocateSecureContext)\s*\(", line_clean)
        add("uses_secure_context_boundary", api_name=m.group(1) if m else short if short.startswith("SecureContext_") or short == "vPortAllocateSecureContext" else "secure_context", trigger_expr=line_clean or f"function_name:{short}")

    return _dedupe_relation_facts(facts)


def _port_advanced_path_category(path: str) -> str:
    if "mpu" in path.lower():
        return "mpu_port"
    if "secure" in path.lower():
        return "secure_port"
    if "portable/" in path:
        return "portable_layer"
    return "kernel_common"


def _port_advanced_response_constraint(predicate: str, function: str, noun: str) -> str:
    if predicate in {"uses_smp_scheduler", "uses_core_affinity", "uses_cross_core_yield", "uses_smp_locking"}:
        return f"{function} has FreeRTOS {noun} evidence; qualify conclusions by configNUMBER_OF_CORES, core affinity, and runtime core scheduling state."
    if predicate in {"uses_mpu_wrappers", "configures_mpu_regions", "checks_mpu_access", "crosses_privilege_boundary"}:
        return f"{function} has FreeRTOS {noun} evidence; qualify it by MPU port configuration, privilege mode, and target memory-region setup."
    if predicate in {"uses_port_assembly", "uses_secure_context_boundary"}:
        return f"{function} crosses advanced port/assembly/secure-context evidence; do not claim behavior beyond C evidence without startup/assembly/secure-port verification."
    return f"{function} has FreeRTOS advanced port semantics evidence; qualify target-specific behavior."


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


_KERNEL_OBJECT_SEMANTICS: dict[str, tuple[str, str, str, str, str]] = {
    # predicate: (object, category, operation_kind, default_context, response noun)
    "sends_to_stream_buffer": ("stream_buffer", "stream_buffer", "send_stream_buffer", "task", "stream-buffer send"),
    "receives_from_stream_buffer": ("stream_buffer", "stream_buffer", "receive_stream_buffer", "task", "stream-buffer receive"),
    "sends_to_message_buffer": ("message_buffer", "message_buffer", "send_message_buffer", "task", "message-buffer send"),
    "receives_from_message_buffer": ("message_buffer", "message_buffer", "receive_message_buffer", "task", "message-buffer receive"),
    "sets_event_bits": ("event_group", "event_group", "set_event_bits", "task", "event-group set-bits"),
    "clears_event_bits": ("event_group", "event_group", "clear_event_bits", "task", "event-group clear-bits"),
    "waits_for_event_bits": ("event_group", "event_group", "wait_event_bits", "task", "event-group wait-bits"),
    "syncs_event_bits": ("event_group", "event_group", "sync_event_bits", "task", "event-group sync"),
    "notifies_task": ("task_notification", "task_notification", "notify_task", "task", "direct-to-task notification"),
    "waits_for_task_notification": ("task_notification", "task_notification", "wait_task_notification", "task", "task-notification wait"),
    "gives_semaphore": ("semaphore", "semaphore", "give_semaphore", "task", "semaphore give"),
    "takes_semaphore": ("semaphore", "semaphore", "take_semaphore", "task", "semaphore take"),
    "creates_semaphore": ("semaphore", "semaphore", "create_semaphore", "task", "semaphore create"),
    "gives_mutex": ("mutex", "mutex", "give_mutex", "task", "mutex give"),
    "takes_mutex": ("mutex", "mutex", "take_mutex", "task", "mutex take"),
    "creates_mutex": ("mutex", "mutex", "create_mutex", "task", "mutex create"),
}

_KERNEL_OBJECT_API_MAP: dict[str, str] = {
    "xStreamBufferSend": "sends_to_stream_buffer",
    "xStreamBufferSendFromISR": "sends_to_stream_buffer",
    "xStreamBufferReceive": "receives_from_stream_buffer",
    "xStreamBufferReceiveFromISR": "receives_from_stream_buffer",
    "xMessageBufferSend": "sends_to_message_buffer",
    "xMessageBufferSendFromISR": "sends_to_message_buffer",
    "xMessageBufferReceive": "receives_from_message_buffer",
    "xMessageBufferReceiveFromISR": "receives_from_message_buffer",
    "xEventGroupSetBits": "sets_event_bits",
    "xEventGroupSetBitsFromISR": "sets_event_bits",
    "vEventGroupSetBitsCallback": "sets_event_bits",
    "xEventGroupClearBits": "clears_event_bits",
    "xEventGroupClearBitsFromISR": "clears_event_bits",
    "vEventGroupClearBitsCallback": "clears_event_bits",
    "xEventGroupWaitBits": "waits_for_event_bits",
    "xEventGroupSync": "syncs_event_bits",
    "xTaskGenericNotify": "notifies_task",
    "xTaskGenericNotifyFromISR": "notifies_task",
    "xTaskNotifyIndexed": "notifies_task",
    "xTaskNotifyIndexedFromISR": "notifies_task",
    "vTaskGenericNotifyGiveFromISR": "notifies_task",
    "vTaskNotifyGiveFromISR": "notifies_task",
    "xTaskGenericNotifyWait": "waits_for_task_notification",
    "ulTaskGenericNotifyTake": "waits_for_task_notification",
    "xQueueGiveFromISR": "gives_semaphore",
    "xQueueSemaphoreTake": "takes_semaphore",
    "xQueueCreateCountingSemaphore": "creates_semaphore",
    "xQueueCreateCountingSemaphoreStatic": "creates_semaphore",
    "xQueueGiveMutexRecursive": "gives_mutex",
    "xQueueTakeMutexRecursive": "takes_mutex",
    "xQueueCreateMutex": "creates_mutex",
    "xQueueCreateMutexStatic": "creates_mutex",
    "xSemaphoreGive": "gives_semaphore",
    "xSemaphoreGiveFromISR": "gives_semaphore",
    "xSemaphoreTake": "takes_semaphore",
    "xSemaphoreTakeFromISR": "takes_semaphore",
    "xSemaphoreCreateBinary": "creates_semaphore",
    "xSemaphoreCreateBinaryStatic": "creates_semaphore",
    "xSemaphoreCreateCounting": "creates_semaphore",
    "xSemaphoreCreateCountingStatic": "creates_semaphore",
    "xSemaphoreGiveRecursive": "gives_mutex",
    "xSemaphoreTakeRecursive": "takes_mutex",
    "xSemaphoreCreateMutex": "creates_mutex",
    "xSemaphoreCreateMutexStatic": "creates_mutex",
}

_KERNEL_OBJECT_HELPER_MAP: list[tuple[str, str]] = [
    ("prvWriteBytesToBuffer", "sends_to_stream_buffer"),
    ("prvReadBytesFromBuffer", "receives_from_stream_buffer"),
    ("prvWriteMessageToBuffer", "sends_to_message_buffer"),
    ("prvReadMessageFromBuffer", "receives_from_message_buffer"),
    ("prvSEND_COMPLETED", "sends_to_stream_buffer"),
    ("prvSEND_COMPLETE_FROM_ISR", "sends_to_stream_buffer"),
    ("prvRECEIVE_COMPLETED", "receives_from_stream_buffer"),
    ("prvRECEIVE_COMPLETED_FROM_ISR", "receives_from_stream_buffer"),
]


def _kernel_object_semantic_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str) -> list[CodeFact]:
    """Extract FreeRTOS kernel-object semantics.

    Kernel object APIs (stream/message buffers, event groups, task notifications,
    semaphores and mutexes) are often implemented through shared queue/list/task
    helpers.  Capturing their object-level meaning prevents an LLM from reducing
    them to a generic call edge and losing the RTOS synchronization/communication
    semantics.
    """
    facts: list[CodeFact] = []
    line_clean = re.sub(r"\s+", " ", line.strip())
    caller_name = caller.display_name
    short = caller.name

    def add(predicate: str, *, api_name: str, trigger_expr: str, confidence: str = "medium") -> None:
        obj, category, operation_kind, default_context, noun = _KERNEL_OBJECT_SEMANTICS[predicate]
        context, basis = _execution_context_for_name(api_name)
        context = context or default_context
        basis = basis or "freertos_kernel_object_api"
        payload = {
            "relation_kind": "freertos_kernel_object_semantic",
            "kernel_object_category": category,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "trigger_expr": trigger_expr,
            "semantic_predicate": predicate,
            "state_object": obj,
            "caller": caller_name,
            "caller_qualified_name": caller.qualified_name,
            "caller_symbol_id": caller.symbol_id,
            "execution_context": context,
            "execution_context_basis": basis,
            "resolution_status": "semantic_relation",
            "unknown_type": "kernel_object_semantic",
            "semantic_phase": "phase7_freertos_kernel_object_semantics",
            "response_constraint": _kernel_object_response_constraint(predicate, caller_name, noun, context),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller_name,
                predicate=predicate,
                object=obj,
                confidence=confidence,
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )

    # API implementation or wrapper function names are themselves strong semantic
    # evidence. Gate them on likely body operations to avoid annotating empty
    # prototypes that slipped through as definitions.
    if short in _KERNEL_OBJECT_API_MAP:
        predicate = _KERNEL_OBJECT_API_MAP[short]
        if _kernel_object_line_supports_function_name(predicate, line_clean):
            add(predicate, api_name=short, trigger_expr=line_clean or f"function_name:{short}")

    # Calls to public APIs from wrappers or macros are also kernel-object evidence
    # for the caller.
    for api_name, predicate in _KERNEL_OBJECT_API_MAP.items():
        if re.search(rf"\b{re.escape(api_name)}\s*\(", line_clean):
            add(predicate, api_name=api_name, trigger_expr=line_clean)

    for helper, predicate in _KERNEL_OBJECT_HELPER_MAP:
        if re.search(rf"\b{re.escape(helper)}\s*\(", line_clean):
            add(predicate, api_name=helper, trigger_expr=line_clean, confidence="medium")

    # FreeRTOS message buffers are implemented by stream_buffer.c using the
    # sbTYPE_MESSAGE_BUFFER flag. Capture creation/typed buffer semantics where
    # wrappers expand away before C-source extraction.
    if "sbTYPE_MESSAGE_BUFFER" in line_clean:
        add("sends_to_message_buffer", api_name="sbTYPE_MESSAGE_BUFFER", trigger_expr=line_clean, confidence="low")

    return _dedupe_relation_facts(facts)


def _kernel_object_line_supports_function_name(predicate: str, line: str) -> bool:
    # A conservative trigger set. It intentionally allows returns and trace hooks
    # because compact fixtures often model the public API in a few lines.
    triggers_by_category = {
        "stream_buffer": ("StreamBuffer", "prvWrite", "prvRead", "SEND", "RECEIVE", "return"),
        "message_buffer": ("MessageBuffer", "sbTYPE_MESSAGE_BUFFER", "prvWriteMessage", "prvReadMessage", "return"),
        "event_group": ("EventGroup", "uxEventBits", "xEventBits", "prvTestWaitCondition", "return", "bits"),
        "task_notification": ("Notify", "Notification", "ucNotifyState", "ulNotifiedValue", "return"),
        "semaphore": ("Semaphore", "queueQUEUE_IS_MUTEX", "uxMessagesWaiting", "return"),
        "mutex": ("Mutex", "mutex", "pxMutexHolder", "uxRecursiveCallCount", "return"),
    }
    obj, category, *_ = _KERNEL_OBJECT_SEMANTICS[predicate]
    return any(token in line for token in triggers_by_category.get(category, ("return",)))


def _kernel_object_response_constraint(predicate: str, function: str, noun: str, context: str) -> str:
    if predicate.startswith("sends_to_"):
        return f"{function} has FreeRTOS {noun} evidence; describe it as kernel-object communication, not merely a helper call."
    if predicate.startswith("receives_from_"):
        return f"{function} has FreeRTOS {noun} evidence; preserve receive/wait semantics and do not present it as a plain memory copy."
    if predicate in {"sets_event_bits", "clears_event_bits", "waits_for_event_bits", "syncs_event_bits"}:
        return f"{function} has FreeRTOS event-group bit semantics; explain set/clear/wait/sync behavior at the event-bit level."
    if predicate in {"notifies_task", "waits_for_task_notification"}:
        return f"{function} has direct-to-task notification semantics; distinguish notification send/wait from generic task calls."
    if predicate in {"takes_semaphore", "gives_semaphore", "creates_semaphore"}:
        return f"{function} has FreeRTOS semaphore semantics in {context} context; do not conflate it with general queue send/receive behavior."
    if predicate in {"takes_mutex", "gives_mutex", "creates_mutex"}:
        return f"{function} has FreeRTOS mutex semantics; preserve ownership/recursive-mutex meaning instead of treating it as a generic queue operation."
    return f"{function} has FreeRTOS kernel-object semantic evidence."



def _kernel_object_macro_relations(path: str, text: str) -> list[CodeFact]:
    """Extract FreeRTOS public kernel-object APIs implemented as macros.

    Message buffers and semaphores are frequently exposed as `#define` wrappers
    around stream-buffer or queue primitives.  Without macro-level evidence an
    LLM would see only the underlying helper and lose the public API meaning.
    """
    facts: list[CodeFact] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = re.match(r"\s*#\s*define\s+(?P<name>[A-Za-z_]\w*)\s*\(", line)
        if not m:
            continue
        api_name = m.group("name")
        predicate = _KERNEL_OBJECT_API_MAP.get(api_name)
        if not predicate:
            continue
        obj, category, operation_kind, default_context, noun = _KERNEL_OBJECT_SEMANTICS[predicate]
        context, basis = _execution_context_for_name(api_name)
        context = context or default_context
        payload = {
            "relation_kind": "freertos_kernel_object_macro_semantic",
            "kernel_object_category": category,
            "operation_kind": operation_kind,
            "api_name": api_name,
            "macro_name": api_name,
            "trigger_expr": line.strip(),
            "semantic_predicate": predicate,
            "state_object": obj,
            "caller": api_name,
            "execution_context": context,
            "execution_context_basis": basis or "freertos_kernel_object_macro_api",
            "resolution_status": "semantic_relation",
            "unknown_type": "kernel_object_semantic",
            "semantic_phase": "phase7_freertos_kernel_object_semantics",
            "response_constraint": _kernel_object_response_constraint(predicate, api_name, noun, context),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=api_name,
                predicate=predicate,
                object=obj,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v not in (None, [], {})},
            )
        )
    return _dedupe_relation_facts(facts)

def _callback_storage_and_invocation_relations_from_line(path: str, caller: FunctionInfo, lineno: int, line: str, symbols: list[FunctionInfo]) -> list[CodeFact]:
    """Extract conservative function-pointer callback storage/invocation relations.

    These are semantic relations, not direct call edges.  They capture common
    embedded-C shapes such as FreeRTOS timer callbacks:

    * pxNewTimer->pxCallbackFunction = pxCallbackFunction;
    * pxTimer->pxCallbackFunction( ( TimerHandle_t ) pxTimer );

    The concrete runtime callback target is intentionally left unknown unless a
    separate registration/storage relation can prove it.
    """
    facts: list[CodeFact] = []
    symbol_by_name = {s.name: s for s in symbols}

    def callback_like(name: str) -> bool:
        return bool(re.search(r"callback|Callback|handler|Handler|function|Function", name))

    # Member/chain callback storage, e.g. `obj->pxCallbackFunction = cb;` or
    # `message.u.xCallbackParameters.pxCallbackFunction = xFunctionToPend;`.
    for m in re.finditer(
        r"(?P<storage>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+)\s*=\s*&?(?P<callback>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*(?:;|,)?",
        line,
    ):
        storage_expr = m.group("storage")
        callback_symbol = m.group("callback")
        callback_field = re.split(r"->|\.", storage_expr)[-1]
        if callback_symbol in _CONTROL_WORDS or callback_symbol in _BUILTIN_TYPES:
            continue
        if not (callback_like(callback_field) or callback_like(callback_symbol)):
            continue
        matches = _candidate_functions(symbols, name=callback_symbol, caller_namespace=caller.namespace)
        payload = {
            "relation_kind": "callback_storage",
            "storage_expr": storage_expr,
            "callback_field": callback_field,
            "callback_symbol": callback_symbol,
            "callback_qualified_name": matches[0].qualified_name if len(matches) == 1 else None,
            "candidate_qualified_names": [s.qualified_name for s in matches] or [callback_symbol],
            "candidate_symbol_ids": [s.symbol_id for s in matches],
            "callback_resolution_status": "resolved" if len(matches) == 1 else ("candidate_set" if matches else "unresolved"),
            "semantic_phase": "phase7_freertos_callback",
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.display_name,
                predicate="stores_callback",
                object=callback_symbol,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload={k: v for k, v in payload.items() if v is not None},
            )
        )

    # Member/chain callback invocation, e.g. `pxTimer->pxCallbackFunction(...)`.
    for m in re.finditer(
        r"(?P<storage>[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)+)\s*\(",
        line,
    ):
        storage_expr = m.group("storage")
        callback_field = re.split(r"->|\.", storage_expr)[-1]
        if not callback_like(callback_field):
            continue
        payload = {
            "relation_kind": "callback_invocation",
            "callback_storage_expr": storage_expr,
            "callback_field": callback_field,
            "callback_resolution_status": "unresolved",
            "unknown_type": "callback_target_unknown",
            "semantic_phase": "phase7_freertos_callback",
            **_execution_context_payload_for_function(caller),
            **_execution_context_payload_for_function(caller, prefix="caller"),
        }
        facts.append(
            CodeFact(
                fact_type="relation",
                path=path,
                start_line=lineno,
                end_line=lineno,
                subject=caller.display_name,
                predicate="invokes_callback",
                object=callback_field,
                confidence="medium",
                source="semantic_cpp_lightweight",
                payload=payload,
            )
        )
    return facts

def _update_function_pointer_assignments(line: str, symbols: list[FunctionInfo], fp_candidates: dict[str, set[str]]) -> None:
    for m in re.finditer(r"\b(?P<var>[A-Za-z_]\w*)\s*=\s*&?(?P<target>(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\s*;", line):
        target = m.group("target")
        if target not in _CONTROL_WORDS and target not in _BUILTIN_TYPES:
            fp_candidates.setdefault(m.group("var"), set()).add(target)


def _callback_table_relations(path: str, lines: list[str], symbols: list[FunctionInfo]) -> list[CodeFact]:
    symbol_names = {s.name for s in symbols}
    facts: list[CodeFact] = []
    for lineno, line in enumerate(lines, start=1):
        if "{" not in line or "}" not in line or "=" not in line:
            continue
        left, body = line.split("=", 1)
        var_match = re.search(r"\b(?P<var>[A-Za-z_]\w*)\s*$", left.strip())
        if not var_match:
            continue
        var = var_match.group("var")
        if "{" not in body or "}" not in body:
            continue
        inner = body.split("{", 1)[1].rsplit("}", 1)[0]
        for index, item in enumerate(_split_top_level_commas(inner)):
            item = item.strip()
            field = str(index)
            if item.startswith(".") and "=" in item:
                field, item = [p.strip() for p in item[1:].split("=", 1)]
            name = item.lstrip("&")
            if re.fullmatch(r"(?:[A-Za-z_]\w*::)*[A-Za-z_]\w*", name):
                local_matches = [s for s in symbols if s.name == name or s.qualified_name == name]
                facts.append(
                    CodeFact(
                        fact_type="relation",
                        path=path,
                        start_line=lineno,
                        end_line=lineno,
                        subject=f"{var}.{field}",
                        predicate="callback_candidate",
                        object=name,
                        confidence="medium",
                        source="semantic_cpp_lightweight",
                        payload={
                            "relation_kind": "callback_table_initializer",
                            "table": var,
                            "field": field,
                            "callback_symbol": name,
                            "unknown_type": "callback_relation_not_execution",
                            "resolution_status": "candidate_set" if local_matches else "unresolved",
                            "candidate_qualified_names": [s.qualified_name for s in local_matches] or [name],
                            "candidate_symbol_ids": [s.symbol_id for s in local_matches],
                        },
                    )
                )
    return facts
