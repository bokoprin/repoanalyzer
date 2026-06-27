from __future__ import annotations

import re
from pathlib import Path

from repoanalyzer.v2.core.models import BuildContext

_DEFINED_RE = re.compile(r"defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
_SYMBOL_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SIMPLE_NOT_DEFINED_RE = re.compile(
    r"^!\s*defined\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*$"
)
_TOKEN_RE = re.compile(
    r"""
    (?P<and>&&)|
    (?P<or>\|\|)|
    (?P<neq>!=)|
    (?P<eq>==)|
    (?P<not>!)|
    (?P<lparen>\()|
    (?P<rparen>\))|
    (?P<number>\d+)|
    (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


def resolve_build_guard(repo_path: Path, path: str, line: int) -> tuple[str, str]:
    details = extract_build_guard_details(repo_path, path, line)
    return str(details["state"]), str(details["note"])


def resolve_build_guard_details(repo_path: Path, path: str, line: int) -> dict[str, object]:
    return extract_build_guard_details(repo_path, path, line)


def extract_build_guard_details(repo_path: Path, path: str, line: int) -> dict[str, object]:
    file_path = repo_path / Path(path)
    if not file_path.exists():
        return _unknown("file_missing")
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return _unknown("empty_file")
    stack: list[dict[str, object]] = []
    branches: list[str] = []
    upper = min(line, len(lines))
    for current_line in range(1, upper + 1):
        text = lines[current_line - 1].strip()
        if text.startswith(("#if", "#ifdef", "#ifndef")):
            block = {
                "expr": text,
                "symbols": _extract_symbols(text),
                "start_line": current_line,
                "branches": [text],
            }
            stack.append(block)
            branches = _string_list(block.get("branches"))
        elif text.startswith(("#elif", "#else")) and stack:
            stack[-1]["branches"] = [*_string_list(stack[-1].get("branches")), text]
            stack[-1]["expr"] = text
            stack[-1]["symbols"] = sorted(
                {
                    *_string_list(stack[-1].get("symbols")),
                    *_extract_symbols(text),
                }
            )
            branches = _string_list(stack[-1].get("branches"))
        elif text.startswith("#endif") and stack:
            stack.pop()
            branches = _string_list(stack[-1].get("branches")) if stack else []
    if not stack:
        return {
            "state": "none",
            "note": "",
            "symbols": [],
            "active_expr": "",
            "branches": [],
            "file_path": str(path),
        }
    active = stack[-1]
    expr = str(active.get("expr") or "")
    symbols = [
        symbol
        for symbol in _string_list(active.get("symbols"))
        if symbol not in _pp_keywords()
    ]
    if len(stack) == 1 and _is_header_include_guard_block(file_path=file_path, block=active):
        return {
            "state": "none",
            "note": "header_include_guard_ignored",
            "symbols": [],
            "active_expr": "",
            "branches": branches,
            "file_path": str(path),
        }
    return {
        "state": "conditional",
        "note": f"guarded_by {expr}; build context unspecified",
        "symbols": symbols,
        "active_expr": expr,
        "branches": branches,
        "file_path": str(path),
    }


def evaluate_build_guard(
    details: dict[str, object], build_context: BuildContext | None
) -> dict[str, object]:
    state = str(details.get("state") or "unknown")
    summary = build_context.summary() if build_context is not None else "unspecified"
    if state == "none":
        return {
            "evaluation": "not_guarded",
            "matched_guards": [],
            "unmatched_guards": [],
            "unresolved_guards": [],
            "build_context_summary": summary,
            "reason": "",
        }
    if build_context is None or build_context.is_empty():
        return {
            "evaluation": "unresolved",
            "matched_guards": [],
            "unmatched_guards": [],
            "unresolved_guards": _string_list(details.get("symbols")),
            "build_context_summary": summary,
            "reason": str(details.get("note") or "build context unspecified"),
        }
    expr = str(details.get("active_expr") or "")
    matched, unmatched, unresolved = _evaluate_expr(expr, build_context)
    if unmatched and not matched and not unresolved:
        evaluation = "unmatched"
        reason = f"filtered_by_build_context {', '.join(unmatched)}"
    elif matched and not unmatched and not unresolved:
        evaluation = "matched"
        reason = f"build_context_matched {', '.join(matched)}"
    elif matched and unmatched and not unresolved:
        evaluation = "partially_matched"
        reason = "matched=" + ",".join(matched) + "; unmatched=" + ",".join(unmatched)
    elif unresolved and (matched or unmatched):
        evaluation = "partially_matched"
        fragments: list[str] = []
        if matched:
            fragments.append("matched=" + ",".join(matched))
        if unmatched:
            fragments.append("unmatched=" + ",".join(unmatched))
        fragments.append("unresolved=" + ",".join(unresolved))
        reason = "; ".join(fragments)
    else:
        evaluation = "unresolved"
        fragments: list[str] = []
        if matched:
            fragments.append("matched=" + ",".join(matched))
        if unmatched:
            fragments.append("unmatched=" + ",".join(unmatched))
        if unresolved:
            fragments.append("unresolved=" + ",".join(unresolved))
        reason = "; ".join(fragments) if fragments else "build_context_unresolved"
    return {
        "evaluation": evaluation,
        "matched_guards": matched,
        "unmatched_guards": unmatched,
        "unresolved_guards": unresolved,
        "build_context_summary": summary,
        "reason": reason,
    }


def _evaluate_expr(
    expr: str, build_context: BuildContext
) -> tuple[list[str], list[str], list[str]]:
    normalized = expr.strip()
    if not normalized:
        return [], [], []
    macros = {item.upper() for item in build_context.defined_macros}
    features = {item.upper() for item in build_context.feature_flags}
    available = macros | features
    if normalized.startswith("#else"):
        return [], [], ["else_branch"]
    if normalized.startswith("#ifdef"):
        symbol = normalized.removeprefix("#ifdef").strip()
        return _match_symbol(symbol, available)
    if normalized.startswith("#ifndef"):
        symbol = normalized.removeprefix("#ifndef").strip()
        if symbol.upper() in available:
            return [], [symbol], []
        return [symbol], [], []
    if normalized.startswith("#elif"):
        normalized = "#if " + normalized.removeprefix("#elif").strip()
    if normalized.startswith("#if"):
        expr_body = normalized.removeprefix("#if").strip()
        evaluation = _evaluate_if_expression(expr_body, available)
        return (
            list(evaluation["matched"]),
            list(evaluation["unmatched"]),
            list(evaluation["unresolved"]),
        )
    return [], [], ["expr_not_supported"]


def _evaluate_if_expression(expr_body: str, available: set[str]) -> dict[str, set[str]]:
    parsed_tokens = _tokenize_expr(expr_body)
    if parsed_tokens is None:
        return {"matched": set(), "unmatched": set(), "unresolved": {"expr_not_supported"}}
    parser = _ExprParser(parsed_tokens)
    node = parser.parse_expression()
    if node is None or not parser.at_end():
        return {"matched": set(), "unmatched": set(), "unresolved": {"expr_parse_failed"}}
    value, matched, unmatched, unresolved = _eval_node(node=node, available=available)
    if value is None and not unresolved:
        unresolved.add("expr_unresolved")
    return {
        "matched": matched,
        "unmatched": unmatched,
        "unresolved": unresolved,
    }


def _tokenize_expr(expr: str) -> list[str] | None:
    normalized = _normalize_defined_calls(expr)
    tokens: list[str] = []
    cursor = 0
    while cursor < len(normalized):
        char = normalized[cursor]
        if char.isspace():
            cursor += 1
            continue
        match = _TOKEN_RE.match(normalized, cursor)
        if not match:
            return None
        token = match.group(0)
        tokens.append(token)
        cursor = match.end()
    return tokens


def _normalize_defined_calls(expr: str) -> str:
    return _DEFINED_RE.sub(lambda m: f"DEFINED_{m.group(1)}", expr)


class _ExprParser:
    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.index = 0

    def at_end(self) -> bool:
        return self.index >= len(self.tokens)

    def parse_expression(self):
        return self._parse_or()

    def _parse_or(self):
        node = self._parse_and()
        while self._peek("||"):
            self._consume("||")
            rhs = self._parse_and()
            if rhs is None:
                return None
            node = ("or", node, rhs)
        return node

    def _parse_and(self):
        node = self._parse_not()
        while self._peek("&&"):
            self._consume("&&")
            rhs = self._parse_not()
            if rhs is None:
                return None
            node = ("and", node, rhs)
        return node

    def _parse_not(self):
        if self._peek("!"):
            self._consume("!")
            inner = self._parse_not()
            if inner is None:
                return None
            return ("not", inner)
        return self._parse_primary()

    def _parse_primary(self):
        if self._peek("("):
            self._consume("(")
            node = self._parse_or()
            if node is None or not self._consume(")"):
                return None
            return node
        token = self._next_token()
        if token is None:
            return None
        if token.isdigit():
            return ("num", token)
        if _is_identifier(token):
            if self._peek("==") or self._peek("!="):
                op = self._next_token()
                rhs = self._next_token()
                if op is None or rhs is None or not rhs.isdigit():
                    return None
                return ("cmp", op, token, rhs)
            return ("id", token)
        return None

    def _peek(self, value: str) -> bool:
        return self.index < len(self.tokens) and self.tokens[self.index] == value

    def _consume(self, value: str) -> bool:
        if not self._peek(value):
            return False
        self.index += 1
        return True

    def _next_token(self) -> str | None:
        if self.index >= len(self.tokens):
            return None
        token = self.tokens[self.index]
        self.index += 1
        return token


def _is_identifier(token: str) -> bool:
    return bool(_SYMBOL_RE.fullmatch(token))


def _eval_node(
    *,
    node,
    available: set[str],
) -> tuple[bool | None, set[str], set[str], set[str]]:
    kind = node[0]
    if kind == "num":
        value = str(node[1]) != "0"
        return value, set(), set(), set()
    if kind == "id":
        return _eval_symbol(str(node[1]), available=available)
    if kind == "cmp":
        _, op, left, right = node
        value, matched, unmatched, unresolved = _eval_symbol(str(left), available=available)
        if value is None:
            unresolved.add(str(left))
            return None, matched, unmatched, unresolved
        rhs_value = str(right) != "0"
        if op == "==":
            out = value == rhs_value
        else:
            out = value != rhs_value
        return out, matched, unmatched, unresolved
    if kind == "not":
        value, matched, unmatched, unresolved = _eval_node(node=node[1], available=available)
        if value is None:
            return None, matched, unmatched, unresolved
        return (not value), matched, unmatched, unresolved
    if kind in {"and", "or"}:
        left_value, left_matched, left_unmatched, left_unresolved = _eval_node(
            node=node[1], available=available
        )
        right_value, right_matched, right_unmatched, right_unresolved = _eval_node(
            node=node[2], available=available
        )
        matched = left_matched | right_matched
        unmatched = left_unmatched | right_unmatched
        unresolved = left_unresolved | right_unresolved
        if left_value is None or right_value is None:
            return None, matched, unmatched, unresolved
        if kind == "and":
            return left_value and right_value, matched, unmatched, unresolved
        return left_value or right_value, matched, unmatched, unresolved
    return None, set(), set(), {"expr_not_supported"}


def _eval_symbol(symbol: str, *, available: set[str]) -> tuple[bool, set[str], set[str], set[str]]:
    clean = symbol.replace("DEFINED_", "")
    if not clean:
        return False, set(), set(), {"expr_symbol_empty"}
    present = clean.upper() in available
    if present:
        return True, {clean}, set(), set()
    return False, set(), {clean}, set()


def _match_symbol(symbol: str, available: set[str]) -> tuple[list[str], list[str], list[str]]:
    clean = symbol.strip()
    if not clean:
        return [], [], ["expr_not_supported"]
    if clean.upper() in available:
        return [clean], [], []
    return [], [clean], []


def _extract_symbols(text: str) -> list[str]:
    return [token for token in _SYMBOL_RE.findall(text) if token.isupper()]


def _is_header_include_guard_block(*, file_path: Path, block: dict[str, object]) -> bool:
    suffix = file_path.suffix.lower()
    if suffix not in {".h", ".hh", ".hpp", ".hxx"}:
        return False
    start_line = int(block.get("start_line") or 0)
    if start_line > 6:
        return False
    expr = str(block.get("expr") or "").strip()
    symbol = _extract_guard_symbol(expr)
    if not symbol:
        return False
    return _is_probable_include_guard_name(symbol)


def _extract_guard_symbol(expr: str) -> str:
    text = expr.strip()
    if text.startswith("#ifndef"):
        return text.removeprefix("#ifndef").strip()
    if text.startswith("#if"):
        body = text.removeprefix("#if").strip()
        match = _SIMPLE_NOT_DEFINED_RE.fullmatch(body)
        if match:
            return match.group(1).strip()
    return ""


def _is_probable_include_guard_name(symbol: str) -> bool:
    upper = symbol.strip().upper()
    if not upper:
        return False
    if upper.startswith("__") and upper.endswith("__"):
        return True
    return upper.endswith(("_H", "_H_", "_HPP", "_HPP_", "_HH", "_HH_"))


def _pp_keywords() -> set[str]:
    return {"IF", "IFDEF", "IFNDEF", "ELIF", "ELSE", "DEFINED"}


def _unknown(reason: str) -> dict[str, object]:
    return {
        "state": "unknown",
        "note": reason,
        "symbols": [],
        "active_expr": "",
        "branches": [],
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return []
