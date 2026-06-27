from __future__ import annotations

from typing import Mapping

from .preprocessor_model import ConditionalGuard, analyze_preprocessor


def is_always_true_if_expression(expression: str) -> bool:
    from .macro_eval import eval_guard

    return eval_guard("if", expression, {}) == "active" and expression.strip().strip("() ") == "1"


def conditional_guard_stacks_by_line(
    text: str,
    macros: Mapping[str, str | None] | None = None,
) -> dict[int, list[ConditionalGuard]]:
    return analyze_preprocessor(text, macros).conditional_guard_stacks_by_line()
