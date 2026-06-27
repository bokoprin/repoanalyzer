from __future__ import annotations

from typing import Mapping

from .preprocessor_model import InactiveRegion, analyze_preprocessor


def is_always_false_if_expression(expression: str) -> bool:
    from .macro_eval import eval_guard

    return eval_guard("if", expression, {}) == "inactive" and expression.strip().strip("() ") == "0"


def inactive_if0_regions(text: str) -> list[InactiveRegion]:
    return inactive_preprocessor_regions(text, {})


def inactive_preprocessor_regions(
    text: str,
    macros: Mapping[str, str | None] | None = None,
) -> list[InactiveRegion]:
    return analyze_preprocessor(text, macros).inactive_regions


def inactive_line_numbers(
    text: str,
    macros: Mapping[str, str | None] | None = None,
) -> set[int]:
    return analyze_preprocessor(text, macros).inactive_lines
