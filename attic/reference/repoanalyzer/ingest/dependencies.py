from __future__ import annotations

import ast
import re

from repoanalyzer.ingest.tree_sitter_common import extract_dependencies_with_tree_sitter
from repoanalyzer.models import DependencyRecord, ScannedFile

_PY_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_.,\s]+)")
_PY_FROM_RE = re.compile(r"^\s*from\s+([A-Za-z0-9_\.]+)\s+import\s+")
_JS_IMPORT_RE = re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]")
_JS_REQUIRE_RE = re.compile(r"require\(['\"]([^'\"]+)['\"]\)")
_TS_IMPORT_RE = re.compile(r"^\s*import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]")
_C_INCLUDE_RE = re.compile(r"^\s*#include\s+[<\"]([^\">]+)[>\"]")
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_.*]+)\s*;")
_CSHARP_USING_RE = re.compile(r"^\s*using\s+([A-Za-z0-9_.]+)\s*;")
_GO_IMPORT_RE = re.compile(r"^\s*import\s+\"([^\"]+)\"")
_RUST_USE_RE = re.compile(r"^\s*use\s+([A-Za-z0-9_:]+)")
_PHP_USE_RE = re.compile(r"^\s*use\s+([A-Za-z0-9_\\]+)")
_KOTLIN_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_.*]+)")
_SWIFT_IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z0-9_]+)")
_SQL_FROM_RE = re.compile(r"\bfrom\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
_SQL_JOIN_RE = re.compile(r"\bjoin\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)
_SHELL_SOURCE_RE = re.compile(r"^\s*(?:source|\. )\s+([^\s;]+)")
_POWERSHELL_IMPORT_RE = re.compile(r"^\s*Import-Module\s+([A-Za-z0-9_.-]+)")
_PERL_USE_RE = re.compile(r"^\s*use\s+([A-Za-z_][A-Za-z0-9_:]*)\b")
_PERL_REQUIRE_MODULE_RE = re.compile(r"^\s*require\s+([A-Za-z_][A-Za-z0-9_:]*)\b")
_PERL_REQUIRE_FILE_RE = re.compile(r"^\s*require\s+['\"]([^'\"]+)['\"]")
_TREE_SITTER_DEP_LANGUAGES = {
    "javascript",
    "typescript",
    "java",
    "csharp",
    "cpp",
    "c",
    "go",
    "rust",
    "php",
    "kotlin",
    "swift",
    "sql",
    "shell",
    "powershell",
}


def extract_dependencies(scanned_file: ScannedFile) -> list[DependencyRecord]:
    lines = scanned_file.text.splitlines()
    dependencies: list[DependencyRecord] = []

    for line_number, line in enumerate(lines, start=1):
        if scanned_file.language == "perl":
            dependencies.extend(_extract_perl(scanned_file.relative_path, line, line_number))
            continue
        dependencies.extend(_extract_python(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_javascript(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_typescript(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_c_cpp(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_java(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_csharp(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_go(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_rust(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_php(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_kotlin(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_swift(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_sql(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_shell(scanned_file.relative_path, line, line_number))
        dependencies.extend(_extract_powershell(scanned_file.relative_path, line, line_number))

    if scanned_file.language == "python":
        dependencies.extend(_extract_python_ast(scanned_file))
    if scanned_file.language in _TREE_SITTER_DEP_LANGUAGES:
        dependencies.extend(_extract_by_tree_sitter(scanned_file))

    unique: dict[tuple[str, str, int], DependencyRecord] = {}
    for dep in dependencies:
        unique[(dep.target, dep.kind, dep.line)] = dep
    return sorted(unique.values(), key=lambda item: (item.line, item.kind, item.target))


def _extract_python_ast(scanned_file: ScannedFile) -> list[DependencyRecord]:
    try:
        module = ast.parse(scanned_file.text)
    except SyntaxError:
        return []
    results: list[DependencyRecord] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    results.append(
                        DependencyRecord(
                            path=scanned_file.relative_path,
                            target=alias.name,
                            kind="python-import",
                            line=int(getattr(node, "lineno", 1)),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            if module_name:
                results.append(
                    DependencyRecord(
                        path=scanned_file.relative_path,
                        target=module_name,
                        kind="python-from",
                        line=int(getattr(node, "lineno", 1)),
                    )
                )
    return results


def _extract_by_tree_sitter(scanned_file: ScannedFile) -> list[DependencyRecord]:
    dependencies = extract_dependencies_with_tree_sitter(
        text=scanned_file.text,
        language=scanned_file.language,
    )
    return [
        DependencyRecord(
            path=scanned_file.relative_path,
            target=item.target,
            kind=item.kind,
            line=item.line,
        )
        for item in dependencies
    ]


def _extract_typescript(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _TS_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="ts-import",
            line=line_number,
        )
    ]


def _extract_java(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _JAVA_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="java-import",
            line=line_number,
        )
    ]


def _extract_csharp(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    using_match = _CSHARP_USING_RE.match(line)
    if not using_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=using_match.group(1),
            kind="csharp-using",
            line=line_number,
        )
    ]


def _extract_go(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _GO_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="go-import",
            line=line_number,
        )
    ]


def _extract_rust(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    use_match = _RUST_USE_RE.match(line)
    if not use_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=use_match.group(1),
            kind="rust-use",
            line=line_number,
        )
    ]


def _extract_php(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    use_match = _PHP_USE_RE.match(line)
    if not use_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=use_match.group(1),
            kind="php-use",
            line=line_number,
        )
    ]


def _extract_kotlin(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _KOTLIN_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="kotlin-import",
            line=line_number,
        )
    ]


def _extract_swift(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _SWIFT_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="swift-import",
            line=line_number,
        )
    ]


def _extract_sql(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    results: list[DependencyRecord] = []
    for pattern, kind in ((_SQL_FROM_RE, "sql-from"), (_SQL_JOIN_RE, "sql-join")):
        for match in pattern.finditer(line):
            results.append(
                DependencyRecord(
                    path=path,
                    target=match.group(1),
                    kind=kind,
                    line=line_number,
                )
            )
    return results


def _extract_shell(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    source_match = _SHELL_SOURCE_RE.match(line)
    if not source_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=source_match.group(1),
            kind="shell-source",
            line=line_number,
        )
    ]


def _extract_powershell(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    import_match = _POWERSHELL_IMPORT_RE.match(line)
    if not import_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=import_match.group(1),
            kind="powershell-import",
            line=line_number,
        )
    ]


def _extract_python(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    results: list[DependencyRecord] = []
    import_match = _PY_IMPORT_RE.match(line)
    if import_match:
        modules = [token.strip() for token in import_match.group(1).split(",")]
        for module in modules:
            if module:
                results.append(
                    DependencyRecord(
                        path=path,
                        target=module,
                        kind="python-import",
                        line=line_number,
                    )
                )
    from_match = _PY_FROM_RE.match(line)
    if from_match:
        results.append(
            DependencyRecord(
                path=path,
                target=from_match.group(1),
                kind="python-from",
                line=line_number,
            )
        )
    return results


def _extract_javascript(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    results: list[DependencyRecord] = []
    import_match = _JS_IMPORT_RE.match(line)
    if import_match:
        results.append(
            DependencyRecord(
                path=path,
                target=import_match.group(1),
                kind="js-import",
                line=line_number,
            )
        )
    for match in _JS_REQUIRE_RE.finditer(line):
        results.append(
            DependencyRecord(
                path=path,
                target=match.group(1),
                kind="js-require",
                line=line_number,
            )
        )
    return results


def _extract_c_cpp(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    include_match = _C_INCLUDE_RE.match(line)
    if not include_match:
        return []
    return [
        DependencyRecord(
            path=path,
            target=include_match.group(1),
            kind="c-include",
            line=line_number,
        )
    ]


def _extract_perl(path: str, line: str, line_number: int) -> list[DependencyRecord]:
    results: list[DependencyRecord] = []
    use_match = _PERL_USE_RE.match(line)
    if use_match:
        results.append(
            DependencyRecord(
                path=path,
                target=use_match.group(1),
                kind="perl-use",
                line=line_number,
            )
        )
    require_module_match = _PERL_REQUIRE_MODULE_RE.match(line)
    if require_module_match:
        results.append(
            DependencyRecord(
                path=path,
                target=require_module_match.group(1),
                kind="perl-require",
                line=line_number,
            )
        )
    require_file_match = _PERL_REQUIRE_FILE_RE.match(line)
    if require_file_match:
        results.append(
            DependencyRecord(
                path=path,
                target=require_file_match.group(1),
                kind="perl-require",
                line=line_number,
            )
        )
    return results
