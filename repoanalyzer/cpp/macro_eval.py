from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class MacroDefinition:
    name: str
    value: str | None = None


@dataclass(frozen=True)
class GuardEvaluation:
    status: str
    reason: str | None = None
    unsupported_kind: str | None = None
    unresolved_symbols: tuple[str, ...] = ()
    details: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status}
        if self.reason:
            payload["evaluation_reason"] = self.reason
        if self.unsupported_kind:
            payload["unsupported_kind"] = self.unsupported_kind
        if self.unresolved_symbols:
            payload["unresolved_symbols"] = list(self.unresolved_symbols)
        if self.details:
            payload["evaluation_details"] = list(self.details)
        return payload


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_]\w*$")
_INTEGER_RE = re.compile(r"^[+-]?(?:0[xX][0-9A-Fa-f]+|\d+)(?:[uUlL]*)$")
_HASH_DEFINE_RE = re.compile(r"^\s*#\s*define\s+(?P<name>[A-Za-z_]\w*)(?P<rest>.*?)(?://.*)?$")

_TOKEN_RE = re.compile(
    r"""
    \s*(?P<token>
        ==
        |!=
        |<=
        |>=
        |\|\|
        |&&
        |<<
        |>>
        |!
        |~
        |\+
        |-
        |\*
        |/
        |%
        |&
        |\|
        |\^
        |<
        |>
        |\(
        |\)
        |defined\b
        |[A-Za-z_]\w*
        |(?:0[xX][0-9A-Fa-f]+|\d+)(?:[uUlL]*)
    )
    """,
    re.VERBOSE,
)

TriBool = str
_TRUE: TriBool = "true"
_FALSE: TriBool = "false"
_UNKNOWN: TriBool = "unknown"


@dataclass(frozen=True)
class _EvalValue:
    int_value: int | None = None
    unknown: bool = False
    reason: str | None = None
    symbols: tuple[str, ...] = ()

    @classmethod
    def known(cls, value: int) -> "_EvalValue":
        return cls(int_value=value, unknown=False)

    @classmethod
    def unknown_value(cls, reason: str | None = None, symbols: tuple[str, ...] = ()) -> "_EvalValue":
        return cls(int_value=None, unknown=True, reason=reason, symbols=symbols)

    def to_bool(self) -> TriBool:
        if self.unknown or self.int_value is None:
            return _UNKNOWN
        return _TRUE if self.int_value != 0 else _FALSE

    def to_int(self) -> int | None:
        return None if self.unknown else self.int_value


def _bool_value(value: TriBool) -> _EvalValue:
    if value == _TRUE:
        return _EvalValue.known(1)
    if value == _FALSE:
        return _EvalValue.known(0)
    return _EvalValue.unknown_value()


def parse_macro_definition(raw: str) -> MacroDefinition | None:
    text = raw.strip()
    if text.startswith("-D"):
        text = text[2:].strip()
    if not text:
        return None
    if "=" in text:
        name, value = text.split("=", 1)
        name = name.strip()
        value = value.strip()
    else:
        name = text.strip()
        value = None
    if not _IDENTIFIER_RE.match(name):
        return None
    return MacroDefinition(name=name, value=value)


def parse_hash_define(line: str) -> MacroDefinition | None:
    """Parse a simple object-like ``#define`` line.

    Function-like macros are intentionally ignored because this lightweight
    build-context pass only needs object-like macro values for preprocessor
    guard evaluation.
    """
    m = _HASH_DEFINE_RE.match(line)
    if not m:
        return None
    name = m.group("name")
    rest = _strip_line_comment(m.group("rest") or "").rstrip()
    if rest.startswith("("):
        return None
    value = rest.strip() or None
    if not _IDENTIFIER_RE.match(name):
        return None
    return MacroDefinition(name=name, value=value)


def macro_map(macros: list[str] | tuple[str, ...]) -> dict[str, str | None]:
    parsed: dict[str, str | None] = {}
    for raw in macros:
        definition = parse_macro_definition(raw)
        if definition is not None:
            parsed[definition.name] = definition.value
    return parsed


def eval_guard(directive: str, expression: str, macros: Mapping[str, str | None]) -> str:
    """Evaluate a tiny safe subset of preprocessor guards.

    Returns one of: ``active``, ``inactive``, or ``conditional``.
    Anything outside the deterministic subset is intentionally left conditional.
    """
    return eval_guard_detailed(directive, expression, macros).status


def eval_guard_detailed(directive: str, expression: str, macros: Mapping[str, str | None]) -> GuardEvaluation:
    """Evaluate a guard and explain why a conditional result was produced."""
    expr = _strip_line_comment(expression).strip()
    if directive == "ifdef":
        name = _macro_name(_strip_outer_parens(expr))
        if name in macros:
            return GuardEvaluation("active")
        return GuardEvaluation("conditional", reason="unresolved_macro", unresolved_symbols=(name,) if name else ())
    if directive == "ifndef":
        name = _macro_name(_strip_outer_parens(expr))
        if name in macros:
            return GuardEvaluation("inactive")
        return GuardEvaluation("conditional", reason="unresolved_macro", unresolved_symbols=(name,) if name else ())
    if directive in {"if", "elif"}:
        return _eval_if_expression_detailed(expr, macros)
    return GuardEvaluation("conditional", reason="unsupported_preprocessor_directive", unsupported_kind=directive)


def _eval_if_expression(expression: str, macros: Mapping[str, str | None]) -> str:
    return _eval_if_expression_detailed(expression, macros).status


def _eval_if_expression_detailed(expression: str, macros: Mapping[str, str | None]) -> GuardEvaluation:
    expr = expression.strip()
    if not expr:
        return GuardEvaluation("conditional", reason="unsupported_preprocessor_expression", unsupported_kind="empty_expression")
    if "?" in expr or ":" in expr:
        return GuardEvaluation("conditional", reason="unsupported_preprocessor_expression", unsupported_kind="ternary_operator")
    tokens = _tokenize(expr)
    if tokens is None:
        return GuardEvaluation("conditional", reason="unsupported_preprocessor_expression", unsupported_kind="tokenization_failed")
    function_like = _detect_function_like_macro_call(tokens)
    if function_like is not None:
        return GuardEvaluation(
            "conditional",
            reason="unsupported_preprocessor_expression",
            unsupported_kind="function_like_macro_call",
            details=(function_like,),
        )
    parser = _ExprParser(tokens, macros)
    value = parser.parse_expression()
    if value is None or not parser.at_end():
        return GuardEvaluation("conditional", reason="unsupported_preprocessor_expression", unsupported_kind="expression_syntax")
    status = _tri_to_status(value)
    if status != "conditional":
        return GuardEvaluation(status)
    unresolved = _unresolved_identifiers(tokens, macros)
    if unresolved:
        return GuardEvaluation("conditional", reason="unresolved_macro", unresolved_symbols=tuple(unresolved))
    if value.reason:
        reason = "unsupported_preprocessor_expression" if value.reason in {"division_by_zero", "negative_shift", "unsupported_macro_value", "macro_alias_cycle"} else value.reason
        return GuardEvaluation("conditional", reason=reason, unsupported_kind=value.reason, details=value.symbols)
    return GuardEvaluation("conditional", reason="unsupported_preprocessor_expression", unsupported_kind="evaluation_unknown")


class _ExprParser:
    def __init__(self, tokens: list[str], macros: Mapping[str, str | None]):
        self._tokens = tokens
        self._macros = macros
        self._pos = 0

    def at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def parse_expression(self) -> _EvalValue | None:
        return self._parse_or()

    def _parse_or(self) -> _EvalValue | None:
        value = self._parse_and()
        if value is None:
            return None
        while self._match("||"):
            rhs = self._parse_and()
            if rhs is None:
                return None
            value = _bool_value(_tri_or(value.to_bool(), rhs.to_bool()))
        return value

    def _parse_and(self) -> _EvalValue | None:
        value = self._parse_bitwise_or()
        if value is None:
            return None
        while self._match("&&"):
            rhs = self._parse_bitwise_or()
            if rhs is None:
                return None
            value = _bool_value(_tri_and(value.to_bool(), rhs.to_bool()))
        return value

    def _parse_bitwise_or(self) -> _EvalValue | None:
        value = self._parse_bitwise_xor()
        if value is None:
            return None
        while self._match("|"):
            rhs = self._parse_bitwise_xor()
            if rhs is None:
                return None
            value = _apply_bitwise(value, "|", rhs)
        return value

    def _parse_bitwise_xor(self) -> _EvalValue | None:
        value = self._parse_bitwise_and()
        if value is None:
            return None
        while self._match("^"):
            rhs = self._parse_bitwise_and()
            if rhs is None:
                return None
            value = _apply_bitwise(value, "^", rhs)
        return value

    def _parse_bitwise_and(self) -> _EvalValue | None:
        value = self._parse_comparison()
        if value is None:
            return None
        while self._match("&"):
            rhs = self._parse_comparison()
            if rhs is None:
                return None
            value = _apply_bitwise(value, "&", rhs)
        return value

    def _parse_comparison(self) -> _EvalValue | None:
        lhs = self._parse_shift()
        if lhs is None:
            return None
        op = self._peek()
        if op not in {"==", "!=", "<", "<=", ">", ">="}:
            return lhs
        self._pos += 1
        rhs = self._parse_shift()
        if rhs is None:
            return None
        compared = _compare_values(lhs, op, rhs)
        return _bool_value(compared)

    def _parse_shift(self) -> _EvalValue | None:
        value = self._parse_additive()
        if value is None:
            return None
        while True:
            op = self._peek()
            if op not in {"<<", ">>"}:
                return value
            self._pos += 1
            rhs = self._parse_additive()
            if rhs is None:
                return None
            value = _apply_shift(value, op, rhs)

    def _parse_additive(self) -> _EvalValue | None:
        value = self._parse_multiplicative()
        if value is None:
            return None
        while True:
            op = self._peek()
            if op not in {"+", "-"}:
                return value
            self._pos += 1
            rhs = self._parse_multiplicative()
            if rhs is None:
                return None
            value = _apply_arithmetic(value, op, rhs)

    def _parse_multiplicative(self) -> _EvalValue | None:
        value = self._parse_unary()
        if value is None:
            return None
        while True:
            op = self._peek()
            if op not in {"*", "/", "%"}:
                return value
            self._pos += 1
            rhs = self._parse_unary()
            if rhs is None:
                return None
            value = _apply_arithmetic(value, op, rhs)

    def _parse_unary(self) -> _EvalValue | None:
        if self._match("!"):
            value = self._parse_unary()
            if value is None:
                return None
            return _bool_value(_tri_not(value.to_bool()))
        if self._match("+"):
            return self._parse_unary()
        if self._match("-"):
            value = self._parse_unary()
            if value is None:
                return None
            int_value = value.to_int()
            if int_value is None:
                return _EvalValue.unknown_value()
            return _EvalValue.known(-int_value)
        if self._match("~"):
            value = self._parse_unary()
            if value is None:
                return None
            int_value = value.to_int()
            if int_value is None:
                return _EvalValue.unknown_value()
            return _EvalValue.known(~int_value)
        return self._parse_primary()

    def _parse_primary(self) -> _EvalValue | None:
        token = self._peek()
        if token is None:
            return None
        if token == "(":
            self._pos += 1
            value = self.parse_expression()
            if value is None or not self._match(")"):
                return None
            return value
        if token == "defined":
            self._pos += 1
            name = self._parse_defined_name()
            if name is None:
                return None
            return _EvalValue.known(1) if name in self._macros else _EvalValue.unknown_value()
        integer = _parse_int(token)
        if integer is not None:
            self._pos += 1
            return _EvalValue.known(integer)
        if _IDENTIFIER_RE.match(token):
            self._pos += 1
            return _macro_value(token, self._macros)
        return None

    def _parse_defined_name(self) -> str | None:
        if self._match("("):
            token = self._peek()
            if token is None or not _IDENTIFIER_RE.match(token):
                return None
            self._pos += 1
            if not self._match(")"):
                return None
            return token
        token = self._peek()
        if token is not None and _IDENTIFIER_RE.match(token):
            self._pos += 1
            return token
        return None

    def _peek(self) -> str | None:
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]

    def _match(self, expected: str) -> bool:
        if self._peek() == expected:
            self._pos += 1
            return True
        return False


def _tokenize(expression: str) -> list[str] | None:
    tokens: list[str] = []
    pos = 0
    while pos < len(expression):
        m = _TOKEN_RE.match(expression, pos)
        if not m:
            if expression[pos:].strip() == "":
                break
            return None
        token = m.group("token")
        tokens.append(token)
        pos = m.end()
    return tokens




def _detect_function_like_macro_call(tokens: list[str]) -> str | None:
    for idx, token in enumerate(tokens[:-1]):
        if token == "defined":
            continue
        if _IDENTIFIER_RE.match(token) and tokens[idx + 1] == "(":
            return token
    return None


def _unresolved_identifiers(tokens: list[str], macros: Mapping[str, str | None]) -> list[str]:
    unresolved: list[str] = []
    skip_next_defined_name = False
    in_defined_parens = False
    for idx, token in enumerate(tokens):
        if token == "defined":
            skip_next_defined_name = True
            continue
        if skip_next_defined_name and token == "(":
            in_defined_parens = True
            continue
        if _IDENTIFIER_RE.match(token):
            if token not in macros and token not in unresolved:
                unresolved.append(token)
            if skip_next_defined_name and not in_defined_parens:
                skip_next_defined_name = False
            continue
        if in_defined_parens and token == ")":
            in_defined_parens = False
            skip_next_defined_name = False
    return unresolved

def _macro_value(name: str, macros: Mapping[str, str | None]) -> _EvalValue:
    return _macro_value_resolved(name, macros, seen=frozenset())


def _macro_value_resolved(
    name: str,
    macros: Mapping[str, str | None],
    *,
    seen: frozenset[str],
) -> _EvalValue:
    if name not in macros:
        return _EvalValue.unknown_value()
    if name in seen:
        return _EvalValue.unknown_value()
    value = macros[name]
    if value is None or value == "":
        # In C/C++, -DNAME behaves like NAME=1 for #if NAME in practice.
        return _EvalValue.known(1)

    value_expr = _strip_outer_parens(str(value).strip())
    integer_value = _parse_int(value_expr)
    if integer_value is not None:
        return _EvalValue.known(integer_value)

    # Support the common config-header pattern where one object-like macro is a
    # simple alias of another: ``#define ACTIVE_MODE CONFIG_MODE``.  Full macro
    # expansion is intentionally out of scope; only a single identifier chain is
    # followed, with cycle protection and unresolved names left conditional.
    if _IDENTIFIER_RE.match(value_expr):
        return _macro_value_resolved(value_expr, macros, seen=seen | {name})

    return _EvalValue.unknown_value("unsupported_macro_value", (name,))


def _apply_bitwise(lhs: _EvalValue, op: str, rhs: _EvalValue) -> _EvalValue:
    lhs_int = lhs.to_int()
    rhs_int = rhs.to_int()
    if lhs_int is None or rhs_int is None:
        return _EvalValue.unknown_value()
    if op == "&":
        return _EvalValue.known(lhs_int & rhs_int)
    if op == "|":
        return _EvalValue.known(lhs_int | rhs_int)
    if op == "^":
        return _EvalValue.known(lhs_int ^ rhs_int)
    return _EvalValue.unknown_value()


def _apply_shift(lhs: _EvalValue, op: str, rhs: _EvalValue) -> _EvalValue:
    lhs_int = lhs.to_int()
    rhs_int = rhs.to_int()
    if lhs_int is None or rhs_int is None or rhs_int < 0:
        return _EvalValue.unknown_value()
    if op == "<<":
        return _EvalValue.known(lhs_int << rhs_int)
    if op == ">>":
        return _EvalValue.known(lhs_int >> rhs_int)
    return _EvalValue.unknown_value()


def _apply_arithmetic(lhs: _EvalValue, op: str, rhs: _EvalValue) -> _EvalValue:
    lhs_int = lhs.to_int()
    rhs_int = rhs.to_int()
    if lhs_int is None or rhs_int is None:
        return _EvalValue.unknown_value()
    if op == "+":
        return _EvalValue.known(lhs_int + rhs_int)
    if op == "-":
        return _EvalValue.known(lhs_int - rhs_int)
    if op == "*":
        return _EvalValue.known(lhs_int * rhs_int)
    if op in {"/", "%"} and rhs_int == 0:
        return _EvalValue.unknown_value()
    if op == "/":
        # Match C-style integer division for the small subset we evaluate: the
        # result truncates toward zero rather than Python's floor division.
        return _EvalValue.known(_c_trunc_div(lhs_int, rhs_int))
    if op == "%":
        # C's remainder has the dividend's sign.  Keep the implementation
        # deterministic for simple config expressions while avoiding full
        # preprocessor semantics.
        quotient = _c_trunc_div(lhs_int, rhs_int)
        return _EvalValue.known(lhs_int - quotient * rhs_int)
    return _EvalValue.unknown_value()


def _c_trunc_div(lhs: int, rhs: int) -> int:
    magnitude = abs(lhs) // abs(rhs)
    return -magnitude if (lhs < 0) ^ (rhs < 0) else magnitude


def _compare_values(lhs: _EvalValue, op: str, rhs: _EvalValue) -> TriBool:
    lhs_int = lhs.to_int()
    rhs_int = rhs.to_int()
    if lhs_int is None or rhs_int is None:
        return _UNKNOWN
    if op == "==":
        return _TRUE if lhs_int == rhs_int else _FALSE
    if op == "!=":
        return _TRUE if lhs_int != rhs_int else _FALSE
    if op == "<":
        return _TRUE if lhs_int < rhs_int else _FALSE
    if op == "<=":
        return _TRUE if lhs_int <= rhs_int else _FALSE
    if op == ">":
        return _TRUE if lhs_int > rhs_int else _FALSE
    if op == ">=":
        return _TRUE if lhs_int >= rhs_int else _FALSE
    return _UNKNOWN


def _tri_and(lhs: TriBool, rhs: TriBool) -> TriBool:
    if lhs == _FALSE or rhs == _FALSE:
        return _FALSE
    if lhs == _TRUE and rhs == _TRUE:
        return _TRUE
    return _UNKNOWN


def _tri_or(lhs: TriBool, rhs: TriBool) -> TriBool:
    if lhs == _TRUE or rhs == _TRUE:
        return _TRUE
    if lhs == _FALSE and rhs == _FALSE:
        return _FALSE
    return _UNKNOWN


def _tri_not(value: TriBool) -> TriBool:
    if value == _TRUE:
        return _FALSE
    if value == _FALSE:
        return _TRUE
    return _UNKNOWN


def _tri_to_status(value: _EvalValue) -> str:
    tri_value = value.to_bool()
    if tri_value == _TRUE:
        return "active"
    if tri_value == _FALSE:
        return "inactive"
    return "conditional"


def _macro_name(expression: str) -> str | None:
    return expression if _IDENTIFIER_RE.match(expression) else None


def _parse_int(value: str) -> int | None:
    if not _INTEGER_RE.match(value):
        return None
    try:
        return int(value.rstrip("uUlL"), 0)
    except ValueError:
        return None


def _strip_outer_parens(expression: str) -> str:
    normalized = expression.strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        inner = normalized[1:-1].strip()
        if not inner or not _outer_parens_wrap_whole_expression(normalized):
            break
        normalized = inner
    return normalized


def _outer_parens_wrap_whole_expression(expression: str) -> bool:
    depth = 0
    for idx, char in enumerate(expression):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and idx != len(expression) - 1:
                return False
        if depth < 0:
            return False
    return depth == 0


def _strip_line_comment(expression: str) -> str:
    return expression.split("//", 1)[0]
