from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_:$.\-]*$")
_SPLIT_IMPORTS_RE = re.compile(r"[,\s]+")


@dataclass(slots=True)
class TreeSitterDefinition:
    kind: str
    name: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class TreeSitterDependency:
    target: str
    kind: str
    line: int


_PARSER_CANDIDATES: dict[str, tuple[str, ...]] = {
    "python": ("python",),
    "javascript": ("javascript",),
    "typescript": ("typescript", "tsx", "javascript"),
    "tsx": ("tsx", "typescript", "javascript"),
    "java": ("java",),
    "csharp": ("c_sharp", "c-sharp", "csharp"),
    "cpp": ("cpp", "c"),
    "c": ("c",),
    "go": ("go",),
    "rust": ("rust",),
    "php": ("php",),
    "kotlin": ("kotlin",),
    "swift": ("swift",),
    "sql": ("sql",),
    "shell": ("bash", "shell"),
    "powershell": ("powershell",),
    "perl": ("perl",),
}

_DEFINITION_KEYWORDS = (
    "function",
    "method",
    "class",
    "interface",
    "enum",
    "struct",
    "trait",
    "impl",
    "module",
    "package",
    "namespace",
    "subroutine",
    "declaration",
)
_DEFINITION_EXCLUDE = (
    "parameter",
    "argument",
    "expression",
    "call",
    "import",
    "include",
)

_DEPENDENCY_NODE_HINTS = ("import", "include", "require", "using", "use", "source")

_LANGUAGE_DEFINITION_NODE_TYPES: dict[str, tuple[str, ...]] = {
    "python": ("function_definition", "class_definition"),
    "javascript": (
        "function_declaration",
        "method_definition",
        "class_declaration",
        "lexical_declaration",
        "variable_declaration",
    ),
    "typescript": (
        "function_declaration",
        "method_definition",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "lexical_declaration",
        "variable_declaration",
    ),
    "java": (
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "record_declaration",
    ),
    "csharp": (
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "enum_declaration",
        "record_declaration",
    ),
    "cpp": (
        "function_definition",
        "class_specifier",
        "struct_specifier",
        "namespace_definition",
        "enum_specifier",
    ),
    "c": ("function_definition", "struct_specifier", "enum_specifier"),
    "go": ("function_declaration", "method_declaration", "type_declaration"),
    "rust": (
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "mod_item",
    ),
    "php": (
        "function_definition",
        "method_declaration",
        "class_declaration",
        "interface_declaration",
        "trait_declaration",
        "enum_declaration",
    ),
    "kotlin": (
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "object_declaration",
        "enum_class_body",
    ),
    "swift": (
        "function_declaration",
        "class_declaration",
        "struct_declaration",
        "protocol_declaration",
        "enum_declaration",
    ),
    "sql": ("create_table_statement", "create_view_statement", "create_function_statement"),
    "shell": ("function_definition",),
    "powershell": ("function_definition",),
    "perl": ("subroutine_definition", "package_statement"),
}

_LANGUAGE_NAME_FIELDS: dict[str, tuple[str, ...]] = {
    "python": ("name",),
    "javascript": ("name", "declarator"),
    "typescript": ("name", "declarator"),
    "java": ("name",),
    "csharp": ("name",),
    "cpp": ("declarator", "name"),
    "c": ("declarator", "name"),
    "go": ("name",),
    "rust": ("name",),
    "php": ("name", "declarator"),
    "kotlin": ("name",),
    "swift": ("name",),
    "sql": ("name", "identifier"),
    "shell": ("name",),
    "powershell": ("name",),
    "perl": ("name", "package", "module"),
}

_NAME_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "javascript": (
        re.compile(r"\b(?:function|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_$]*)"),
        re.compile(
            r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:function|\()",
        ),
    ),
    "typescript": (
        re.compile(r"\b(?:function|class|interface|type|enum)\s+([A-Za-z_][A-Za-z0-9_$]*)"),
        re.compile(
            r"\b(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:function|\()",
        ),
    ),
    "python": (
        re.compile(r"\b(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "java": (
        re.compile(r"\b(?:class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    ),
    "csharp": (
        re.compile(r"\b(?:class|interface|enum|struct|record)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    ),
    "cpp": (
        re.compile(r"\b(?:class|struct|enum|namespace)\s+([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"\b([A-Za-z_][A-Za-z0-9_:]*)\s*\("),
    ),
    "go": (
        re.compile(r"\b(?:func|type)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "rust": (
        re.compile(r"\b(?:fn|struct|enum|trait|mod|impl)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "php": (
        re.compile(r"\b(?:function|class|interface|trait|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "kotlin": (
        re.compile(r"\b(?:fun|class|interface|object|enum)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "swift": (
        re.compile(r"\b(?:func|class|struct|enum|protocol|actor)\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "sql": (
        re.compile(
            r"\b(?:create\s+(?:or\s+replace\s+)?(?:view|table|function|procedure))\s+"
            r"([A-Za-z_][A-Za-z0-9_.]*)",
            re.IGNORECASE,
        ),
    ),
    "shell": (
        re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", re.MULTILINE),
    ),
    "powershell": (
        re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_\-]*)", re.IGNORECASE),
    ),
}

_DEPENDENCY_PATTERNS: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    "python": (
        (re.compile(r"^\s*import\s+([A-Za-z0-9_.,\s]+)", re.MULTILINE), "python-import"),
        (re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+", re.MULTILINE), "python-from"),
    ),
    "javascript": (
        (re.compile(r"\bimport\s+(?:[^;]*?\s+from\s+)?['\"]([^'\"]+)['\"]"), "js-import"),
        (re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"), "js-require"),
    ),
    "typescript": (
        (re.compile(r"\bimport\s+(?:[^;]*?\s+from\s+)?['\"]([^'\"]+)['\"]"), "ts-import"),
        (re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"), "ts-require"),
    ),
    "java": (
        (re.compile(r"^\s*import\s+([A-Za-z0-9_.*]+)\s*;", re.MULTILINE), "java-import"),
    ),
    "csharp": (
        (re.compile(r"^\s*using\s+([A-Za-z0-9_.]+)\s*;", re.MULTILINE), "csharp-using"),
    ),
    "cpp": (
        (re.compile(r"^\s*#include\s+[<\"]([^\">]+)[>\"]", re.MULTILINE), "c-include"),
    ),
    "c": (
        (re.compile(r"^\s*#include\s+[<\"]([^\">]+)[>\"]", re.MULTILINE), "c-include"),
    ),
    "go": (
        (re.compile(r"^\s*import\s+\"([^\"]+)\"", re.MULTILINE), "go-import"),
        (re.compile(r"^\s*\"([^\"]+)\"\s*$", re.MULTILINE), "go-import"),
    ),
    "rust": (
        (re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)", re.MULTILINE), "rust-use"),
        (re.compile(r"^\s*mod\s+([A-Za-z0-9_]+)", re.MULTILINE), "rust-mod"),
    ),
    "php": (
        (re.compile(r"^\s*use\s+([A-Za-z0-9_\\]+)", re.MULTILINE), "php-use"),
        (re.compile(r"\b(?:require|include)(?:_once)?\s*[('\"\s]+([^'\"\)\s;]+)"), "php-require"),
    ),
    "kotlin": (
        (re.compile(r"^\s*import\s+([A-Za-z0-9_.*]+)", re.MULTILINE), "kotlin-import"),
    ),
    "swift": (
        (re.compile(r"^\s*import\s+([A-Za-z0-9_]+)", re.MULTILINE), "swift-import"),
    ),
    "sql": (
        (re.compile(r"\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE), "sql-from"),
        (re.compile(r"\bjoin\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE), "sql-join"),
    ),
    "shell": (
        (re.compile(r"^\s*(?:source|\. )\s+([^\s;]+)", re.MULTILINE), "shell-source"),
    ),
    "powershell": (
        (re.compile(r"^\s*Import-Module\s+([A-Za-z0-9_.-]+)", re.MULTILINE), "powershell-import"),
    ),
}


def extract_definitions_with_tree_sitter(text: str, language: str) -> list[TreeSitterDefinition]:
    if not text.strip():
        return []
    parser = get_parser_for_language(language)
    if parser is None:
        return []
    source = text.encode("utf-8")
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    lines = text.splitlines()
    if not lines:
        return []
    root_node = getattr(tree, "root_node", None)
    if root_node is None:
        return []

    definitions: list[TreeSitterDefinition] = []
    for node in _iter_nodes(root_node):
        node_type = str(getattr(node, "type", "")).lower()
        if not _is_definition_node(node_type=node_type, language=language):
            continue
        start_line = int(getattr(node, "start_point", (0, 0))[0]) + 1
        end_line = int(getattr(node, "end_point", (0, 0))[0]) + 1
        if start_line <= 0 or end_line < start_line:
            continue
        end_line = min(end_line, len(lines))
        snippet = _node_text(node, source, max_chars=320)
        if not snippet:
            continue
        name = _extract_definition_name(
            language=language,
            node=node,
            snippet=snippet,
            source=source,
        )
        if not name:
            continue
        kind = _infer_kind(node_type=node_type, snippet=snippet)
        definitions.append(
            TreeSitterDefinition(
                kind=kind,
                name=name,
                start_line=start_line,
                end_line=end_line,
            )
        )

    unique: dict[tuple[str, str, int, int], TreeSitterDefinition] = {}
    for item in definitions:
        unique[(item.kind, item.name, item.start_line, item.end_line)] = item
    return sorted(
        unique.values(),
        key=lambda value: (value.start_line, value.end_line, value.kind, value.name),
    )


def extract_dependencies_with_tree_sitter(text: str, language: str) -> list[TreeSitterDependency]:
    if not text.strip():
        return []
    parser = get_parser_for_language(language)
    if parser is None:
        return []
    source = text.encode("utf-8")
    try:
        tree = parser.parse(source)
    except Exception:
        return []

    root_node = getattr(tree, "root_node", None)
    if root_node is None:
        return []
    patterns = _DEPENDENCY_PATTERNS.get(language, ())
    if not patterns:
        return []

    results: list[TreeSitterDependency] = []
    for node in _iter_nodes(root_node):
        node_type = str(getattr(node, "type", "")).lower()
        if not any(hint in node_type for hint in _DEPENDENCY_NODE_HINTS):
            continue
        snippet = _node_text(node, source, max_chars=800)
        if not snippet:
            continue
        line = int(getattr(node, "start_point", (0, 0))[0]) + 1
        for pattern, kind in patterns:
            for match in pattern.finditer(snippet):
                target = match.group(1).strip()
                if not target:
                    continue
                if kind == "python-import":
                    for module in _split_python_import_targets(target):
                        results.append(TreeSitterDependency(target=module, kind=kind, line=line))
                else:
                    results.append(TreeSitterDependency(target=target, kind=kind, line=line))

    unique: dict[tuple[str, str, int], TreeSitterDependency] = {}
    for item in results:
        unique[(item.target, item.kind, item.line)] = item
    return sorted(unique.values(), key=lambda value: (value.line, value.kind, value.target))


def get_parser_for_language(language: str) -> Any | None:
    normalized = language.strip().lower()
    if not normalized:
        return None
    for candidate in _candidate_languages(normalized):
        parser = _load_parser(candidate)
        if parser is not None:
            return parser
    return None


@lru_cache(maxsize=64)
def _load_parser(language: str) -> Any | None:
    try:
        from tree_sitter_language_pack import get_parser
    except Exception:
        return None
    try:
        return get_parser(cast(Any, language))
    except Exception:
        return None


def _candidate_languages(language: str) -> list[str]:
    candidates = [language, *_PARSER_CANDIDATES.get(language, ())]
    unique: list[str] = []
    for value in candidates:
        if value not in unique:
            unique.append(value)
    return unique


def _iter_nodes(root_node: Any):
    stack = [root_node]
    while stack:
        node = stack.pop()
        yield node
        for child in reversed(list(getattr(node, "children", ()))):
            stack.append(child)


def _is_definition_node(node_type: str, language: str) -> bool:
    if not node_type:
        return False
    language_specific = _LANGUAGE_DEFINITION_NODE_TYPES.get(language, ())
    if language_specific:
        if any(token in node_type for token in language_specific):
            return True
        return False
    if any(excluded in node_type for excluded in _DEFINITION_EXCLUDE):
        return False
    return any(keyword in node_type for keyword in _DEFINITION_KEYWORDS)


def _extract_definition_name(language: str, node: Any, snippet: str, source: bytes) -> str:
    for field in _LANGUAGE_NAME_FIELDS.get(language, ("name", "declarator", "module", "alias")):
        name_node = _child_by_field(node, field)
        if name_node is None:
            continue
        name = _node_text(name_node, source, max_chars=120).strip().strip("(){};,")
        if _looks_like_name(name):
            return name

    for pattern in _NAME_PATTERNS.get(language, ()):
        match = pattern.search(snippet)
        if match:
            name = match.group(1).strip()
            if _looks_like_name(name):
                return name

    for pattern in _NAME_PATTERNS.get("javascript", ()):
        match = pattern.search(snippet)
        if match:
            name = match.group(1).strip()
            if _looks_like_name(name):
                return name
    return ""


def _child_by_field(node: Any, field: str) -> Any | None:
    accessor = getattr(node, "child_by_field_name", None)
    if accessor is None:
        return None
    try:
        return accessor(field)
    except Exception:
        return None


def _looks_like_name(name: str) -> bool:
    normalized = name.strip()
    if not normalized:
        return False
    return bool(_IDENTIFIER_RE.match(normalized))


def _node_text(node: Any, source: bytes, max_chars: int = 400) -> str:
    start_byte = int(getattr(node, "start_byte", 0))
    end_byte = int(getattr(node, "end_byte", 0))
    if end_byte <= start_byte or start_byte < 0:
        return ""
    text = source[start_byte:end_byte].decode("utf-8", errors="ignore")
    return text[:max_chars]


def _split_python_import_targets(raw: str) -> list[str]:
    modules = [token.strip() for token in _SPLIT_IMPORTS_RE.split(raw) if token.strip()]
    return [module for module in modules if module not in {"as"}]


def _infer_kind(node_type: str, snippet: str) -> str:
    lowered = f"{node_type} {snippet[:80]}".lower()
    if "class" in lowered:
        return "class"
    if "interface" in lowered:
        return "interface"
    if "enum" in lowered:
        return "enum"
    if "struct" in lowered or "record" in lowered or "type " in lowered:
        return "type"
    if "module" in lowered or "namespace" in lowered or "package" in lowered:
        return "module"
    return "function"
