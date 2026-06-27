from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from repoanalyzer.core.models import CodeFact
from .macro_eval import eval_guard_detailed
from .preprocessor_model import BranchNode, analyze_preprocessor

_IF_RE = re.compile(r'^\s*#\s*(?P<directive>ifdef|ifndef|if)\s+(?P<expr>.+?)\s*(?://.*)?$')
_ENDIF_RE = re.compile(r'^\s*#\s*endif\b')


@dataclass
class _LegacyFrame:
    directive: str
    expression: str
    start_line: int


def extract_build_guards(path: str, text: str, macros: Mapping[str, str | None] | None = None) -> list[CodeFact]:
    macro_defs = macros or {}
    model = analyze_preprocessor(text, macro_defs)
    return [
        *_extract_legacy_guard_blocks(path, text, macro_defs),
        *[_branch_fact(path, branch) for branch in model.branches],
    ]


def _extract_legacy_guard_blocks(path: str, text: str, macros: Mapping[str, str | None]) -> list[CodeFact]:
    stack: list[_LegacyFrame] = []
    facts: list[CodeFact] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = _IF_RE.match(line)
        if m:
            stack.append(_LegacyFrame(m.group("directive"), m.group("expr").strip(), lineno))
            continue
        if _ENDIF_RE.match(line) and stack:
            frame = stack.pop()
            facts.append(_guard_block_fact(path, frame, lineno, macros))
    for frame in stack:
        facts.append(
            CodeFact(
                fact_type="build_guard",
                path=path,
                start_line=frame.start_line,
                end_line=frame.start_line,
                subject=path,
                predicate="guarded_by",
                object=frame.expression,
                confidence="low",
                source="regex_cpp_minimal",
                payload={
                    "kind": "guard_block",
                    "directive": frame.directive,
                    "expression": frame.expression,
                    "status": "unclosed",
                },
            )
        )
    return facts


def _guard_block_fact(path: str, frame: _LegacyFrame, end_line: int, macros: Mapping[str, str | None]) -> CodeFact:
    evaluation = eval_guard_detailed(frame.directive, frame.expression, macros)
    payload = {
        "kind": "guard_block",
        "directive": frame.directive,
        "expression": frame.expression,
        "status": evaluation.status,
    }
    payload.update({key: value for key, value in evaluation.to_payload().items() if key != "status"})
    return CodeFact(
        fact_type="build_guard",
        path=path,
        start_line=frame.start_line,
        end_line=end_line,
        subject=path,
        predicate="guarded_by",
        object=frame.expression,
        confidence="medium",
        source="regex_cpp_minimal",
        payload=payload,
    )


def _branch_fact(path: str, branch: BranchNode) -> CodeFact:
    end_line = max(branch.directive_line, branch.content_end_line)
    unclosed = branch in []  # compatibility placeholder; unclosed is represented by group_end_line at EOF.
    payload = {
        "kind": "guard_branch",
        "directive": branch.directive,
        "expression": branch.expression,
        "status": branch.status,
        "effective_status": branch.effective_status,
        "branch_index": branch.branch_index,
        "branch_role": branch.branch_role,
        "directive_line": branch.directive_line,
        "content_start_line": branch.content_start_line,
        "content_end_line": branch.content_end_line,
        "group_start_line": branch.group_start_line,
        "group_end_line": branch.group_end_line,
        "parent_depth": branch.parent_depth,
        "parent_status": branch.parent_status,
    }
    if branch.evaluation_reason:
        payload["evaluation_reason"] = branch.evaluation_reason
    if branch.unsupported_kind:
        payload["unsupported_kind"] = branch.unsupported_kind
    if branch.unresolved_symbols:
        payload["unresolved_symbols"] = list(branch.unresolved_symbols)
    return CodeFact(
        fact_type="build_guard",
        path=path,
        start_line=branch.directive_line,
        end_line=end_line,
        subject=path,
        predicate="guard_branch",
        object=branch.expression,
        confidence="low" if unclosed else "medium",
        source="regex_cpp_minimal",
        payload=payload,
    )
