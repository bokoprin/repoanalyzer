from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Mapping

_IF_RE = re.compile(r"^\s*#\s*(?P<directive>ifdef|ifndef|if)\s+(?P<expr>.+?)\s*(?://.*)?$")
_ELIF_RE = re.compile(r"^\s*#\s*elif\s+(?P<expr>.+?)\s*(?://.*)?$")
_ELSE_RE = re.compile(r"^\s*#\s*else\b")
_ENDIF_RE = re.compile(r"^\s*#\s*endif\b")

from .macro_eval import GuardEvaluation, eval_guard, eval_guard_detailed


@dataclass(frozen=True)
class ConditionalGuard:
    directive: str
    expression: str
    line: int
    evaluation_reason: str | None = None
    unsupported_kind: str | None = None
    unresolved_symbols: tuple[str, ...] = ()
    status: str | None = None
    effective_status: str | None = None
    branch_role: str | None = None
    parent_status: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"directive": self.directive, "expression": self.expression, "line": self.line}
        if self.branch_role:
            data["branch_role"] = self.branch_role
        if self.status:
            data["status"] = self.status
        if self.effective_status:
            data["effective_status"] = self.effective_status
        if self.parent_status:
            data["parent_status"] = self.parent_status
        if self.evaluation_reason:
            data["evaluation_reason"] = self.evaluation_reason
        if self.unsupported_kind:
            data["unsupported_kind"] = self.unsupported_kind
        if self.unresolved_symbols:
            data["unresolved_symbols"] = list(self.unresolved_symbols)
        return data


@dataclass(frozen=True)
class InactiveRegion:
    start_line: int
    end_line: int
    expression: str
    reason: str


@dataclass(frozen=True)
class BranchNode:
    directive: str
    expression: str
    directive_line: int
    content_start_line: int
    content_end_line: int
    status: str
    effective_status: str
    branch_index: int
    branch_role: str
    group_start_line: int
    group_end_line: int
    parent_depth: int
    parent_status: str
    evaluation_reason: str | None = None
    unsupported_kind: str | None = None
    unresolved_symbols: tuple[str, ...] = ()

    def guard(self) -> ConditionalGuard:
        return ConditionalGuard(
            self.directive,
            self.expression,
            self.directive_line,
            self.evaluation_reason,
            self.unsupported_kind,
            self.unresolved_symbols,
            status=self.status,
            effective_status=self.effective_status,
            branch_role=self.branch_role,
            parent_status=self.parent_status,
        )


@dataclass(frozen=True)
class LineBuildStatus:
    line: int
    status: str
    inactive_expression: str | None = None
    inactive_reason: str | None = None
    guard_stack: tuple[ConditionalGuard, ...] = ()


@dataclass(frozen=True)
class PreprocessorModel:
    line_status: dict[int, LineBuildStatus]
    branches: list[BranchNode]
    unclosed_branches: list[BranchNode]

    @property
    def inactive_lines(self) -> set[int]:
        return {line for line, status in self.line_status.items() if status.status == "inactive"}

    @property
    def inactive_regions(self) -> list[InactiveRegion]:
        regions: list[InactiveRegion] = []
        current_start: int | None = None
        current_end: int | None = None
        current_expression: str | None = None
        current_reason = "preprocessor_condition"
        for line in sorted(self.line_status):
            status = self.line_status[line]
            if status.status != "inactive":
                if current_start is not None and current_end is not None:
                    regions.append(
                        InactiveRegion(
                            start_line=current_start,
                            end_line=current_end,
                            expression=current_expression or "unknown",
                            reason=current_reason,
                        )
                    )
                current_start = None
                current_end = None
                current_expression = None
                current_reason = "preprocessor_condition"
                continue
            expression = status.inactive_expression or "unknown"
            reason = status.inactive_reason or "preprocessor_condition"
            if current_start is None:
                current_start = current_end = line
                current_expression = expression
                current_reason = reason
            elif current_end == line - 1 and current_expression == expression and current_reason == reason:
                current_end = line
            else:
                regions.append(
                    InactiveRegion(
                        start_line=current_start,
                        end_line=current_end or current_start,
                        expression=current_expression or "unknown",
                        reason=current_reason,
                    )
                )
                current_start = current_end = line
                current_expression = expression
                current_reason = reason
        if current_start is not None:
            regions.append(
                InactiveRegion(
                    start_line=current_start,
                    end_line=current_end or current_start,
                    expression=current_expression or "unknown",
                    reason=current_reason,
                )
            )
        return regions

    def conditional_guard_stacks_by_line(self) -> dict[int, list[ConditionalGuard]]:
        return {
            line: list(status.guard_stack)
            for line, status in self.line_status.items()
            if status.status == "conditional" and status.guard_stack
        }


@dataclass
class _Frame:
    opening_directive: str
    opening_expression: str
    group_start_line: int
    current_branch: BranchNode
    current_local_status: str
    prior_known_active: bool
    prior_conditional: bool
    branch_index: int
    branches: list[BranchNode]


def analyze_preprocessor(text: str, macros: Mapping[str, str | None] | None = None) -> PreprocessorModel:
    macro_defs = macros or {}
    lines = text.splitlines()
    stack: list[_Frame] = []
    completed: list[BranchNode] = []
    unclosed: list[BranchNode] = []
    line_status: dict[int, LineBuildStatus] = {}

    for lineno, line in enumerate(lines, start=1):
        m_if = _IF_RE.match(line)
        if m_if:
            directive = m_if.group("directive")
            expression = m_if.group("expr").strip()
            evaluation = eval_guard_detailed(directive, expression, macro_defs)
            local_status = evaluation.status
            parent_status = _combined_parent_status(stack)
            branch = _new_branch(
                directive=directive,
                expression=expression,
                directive_line=lineno,
                content_start_line=lineno + 1,
                local_status=local_status,
                parent_status=parent_status,
                branch_index=0,
                branch_role=directive,
                group_start_line=lineno,
                parent_depth=len(stack),
                evaluation=evaluation,
            )
            stack.append(
                _Frame(
                    opening_directive=directive,
                    opening_expression=expression,
                    group_start_line=lineno,
                    current_branch=branch,
                    current_local_status=local_status,
                    prior_known_active=local_status == "active",
                    prior_conditional=local_status == "conditional",
                    branch_index=0,
                    branches=[],
                )
            )
            continue

        m_elif = _ELIF_RE.match(line)
        if m_elif:
            if not stack:
                continue
            frame = stack[-1]
            _close_current_branch(frame, lineno - 1, group_end_line=lineno)
            expression = m_elif.group("expr").strip()
            evaluation = _next_elif_evaluation(frame, expression, macro_defs)
            local_status = evaluation.status
            if local_status == "active":
                frame.prior_known_active = True
            elif local_status == "conditional":
                frame.prior_conditional = True
            frame.branch_index += 1
            parent_status = _combined_parent_status(stack[:-1])
            frame.current_branch = _new_branch(
                directive="elif",
                expression=expression,
                directive_line=lineno,
                content_start_line=lineno + 1,
                local_status=local_status,
                parent_status=parent_status,
                branch_index=frame.branch_index,
                branch_role="elif",
                group_start_line=frame.group_start_line,
                parent_depth=len(stack) - 1,
                evaluation=evaluation,
            )
            frame.current_local_status = local_status
            continue

        if _ELSE_RE.match(line):
            if not stack:
                continue
            frame = stack[-1]
            _close_current_branch(frame, lineno - 1, group_end_line=lineno)
            evaluation = _else_evaluation(frame)
            local_status = evaluation.status
            if local_status == "active":
                frame.prior_known_active = True
            elif local_status == "conditional":
                frame.prior_conditional = True
            frame.branch_index += 1
            parent_status = _combined_parent_status(stack[:-1])
            frame.current_branch = _new_branch(
                directive="else",
                expression=f"else of {frame.opening_expression}",
                directive_line=lineno,
                content_start_line=lineno + 1,
                local_status=local_status,
                parent_status=parent_status,
                branch_index=frame.branch_index,
                branch_role="else",
                group_start_line=frame.group_start_line,
                parent_depth=len(stack) - 1,
                evaluation=evaluation,
            )
            frame.current_local_status = local_status
            continue

        if _ENDIF_RE.match(line):
            if stack:
                frame = stack.pop()
                _close_current_branch(frame, lineno - 1, group_end_line=lineno)
                completed.extend(_with_group_end(frame.branches, lineno))
            continue

        line_status[lineno] = _line_build_status(lineno, stack)

    end_line = len(lines)
    while stack:
        frame = stack.pop()
        _close_current_branch(frame, end_line, group_end_line=end_line)
        unclosed.extend(_with_group_end(frame.branches, end_line))

    return PreprocessorModel(line_status=line_status, branches=completed + unclosed, unclosed_branches=unclosed)


def _new_branch(
    *,
    directive: str,
    expression: str,
    directive_line: int,
    content_start_line: int,
    local_status: str,
    parent_status: str,
    branch_index: int,
    branch_role: str,
    group_start_line: int,
    parent_depth: int,
    evaluation: GuardEvaluation | None = None,
) -> BranchNode:
    return BranchNode(
        directive=directive,
        expression=expression,
        directive_line=directive_line,
        content_start_line=content_start_line,
        content_end_line=content_start_line - 1,
        status=local_status,
        effective_status=_combine_status(parent_status, local_status),
        branch_index=branch_index,
        branch_role=branch_role,
        group_start_line=group_start_line,
        group_end_line=group_start_line,
        parent_depth=parent_depth,
        parent_status=parent_status,
        evaluation_reason=evaluation.reason if evaluation else None,
        unsupported_kind=evaluation.unsupported_kind if evaluation else None,
        unresolved_symbols=evaluation.unresolved_symbols if evaluation else (),
    )


def _close_current_branch(frame: _Frame, content_end_line: int, *, group_end_line: int) -> None:
    branch = frame.current_branch
    frame.branches.append(
        replace(
            branch,
            content_end_line=max(branch.content_start_line - 1, content_end_line),
            group_end_line=group_end_line,
        )
    )


def _with_group_end(branches: list[BranchNode], group_end_line: int) -> list[BranchNode]:
    return [replace(branch, group_end_line=group_end_line) for branch in branches]


def _combined_parent_status(stack: list[_Frame]) -> str:
    statuses = [frame.current_branch.effective_status for frame in stack]
    if any(status == "inactive" for status in statuses):
        return "inactive"
    if any(status == "conditional" for status in statuses):
        return "conditional"
    return "active"


def _combine_status(parent_status: str, child_status: str) -> str:
    if parent_status == "inactive" or child_status == "inactive":
        return "inactive"
    if parent_status == "conditional" or child_status == "conditional":
        return "conditional"
    return "active"


def _next_elif_evaluation(frame: _Frame, expression: str, macros: Mapping[str, str | None]) -> GuardEvaluation:
    expression_evaluation = eval_guard_detailed("elif", expression, macros)
    if frame.prior_known_active:
        return GuardEvaluation("inactive", reason="preceded_by_active_branch")
    if frame.prior_conditional:
        if expression_evaluation.status == "inactive":
            return GuardEvaluation("inactive", reason="preceded_by_conditional_branch_and_expression_inactive")
        return GuardEvaluation(
            "conditional",
            reason=expression_evaluation.reason or "preceded_by_conditional_branch",
            unsupported_kind=expression_evaluation.unsupported_kind,
            unresolved_symbols=expression_evaluation.unresolved_symbols,
            details=expression_evaluation.details,
        )
    return expression_evaluation


def _else_evaluation(frame: _Frame) -> GuardEvaluation:
    if frame.prior_known_active:
        return GuardEvaluation("inactive", reason="preceded_by_active_branch")
    if frame.prior_conditional:
        return GuardEvaluation("conditional", reason="preceded_by_conditional_branch")
    return GuardEvaluation("active")


def _line_build_status(line: int, stack: list[_Frame]) -> LineBuildStatus:
    guard_stack = tuple(frame.current_branch.guard() for frame in stack)
    inactive = [frame.current_branch for frame in stack if frame.current_branch.effective_status == "inactive"]
    if inactive:
        branch = inactive[-1]
        return LineBuildStatus(
            line=line,
            status="inactive",
            inactive_expression=branch.expression,
            inactive_reason=_inactive_reason(branch.branch_role, branch.expression),
            guard_stack=guard_stack,
        )

    conditional_guards = tuple(frame.current_branch.guard() for frame in stack if frame.current_branch.effective_status == "conditional")
    if conditional_guards:
        return LineBuildStatus(line=line, status="conditional", guard_stack=guard_stack or conditional_guards)
    return LineBuildStatus(line=line, status="active", guard_stack=guard_stack)


def _inactive_reason(directive: str, expression: str) -> str:
    return "if0" if directive in {"if", "elif"} and expression.strip().strip("() ") == "0" else "preprocessor_condition"
