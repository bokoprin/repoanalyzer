from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_dict(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    action: str
    tool: str | None = None
    reason: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "step_id": self.step_id,
            "action": self.action,
            "tool": self.tool,
            "reason": self.reason,
            "inputs": _to_dict(self.inputs),
            "warnings": list(self.warnings),
        }
        return {k: v for k, v in data.items() if v not in (None, [], {})}


@dataclass(frozen=True)
class AgentPreflightReport:
    repo: str
    index_ready: bool
    status: dict[str, Any]
    diagnostics: dict[str, Any]
    safety_level: str
    required_actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommended_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "agent_preflight.v1",
            "repo": self.repo,
            "index_ready": self.index_ready,
            "safety_level": self.safety_level,
            "status": self.status,
            "diagnostics": self.diagnostics,
            "required_actions": list(self.required_actions),
            "warnings": list(self.warnings),
            "recommended_tools": list(self.recommended_tools),
        }


@dataclass(frozen=True)
class AnswerPlan:
    question: str
    interpreted_intent: str
    steps: list[WorkflowStep]
    required_tools: list[str] = field(default_factory=list)
    extracted_claims: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "answer_plan.v1",
            "question": self.question,
            "interpreted_intent": self.interpreted_intent,
            "required_tools": list(self.required_tools),
            "steps": [step.to_dict() for step in self.steps],
            "extracted_claims": _to_dict(self.extracted_claims),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AnswerVerificationReport:
    text: str
    question: str | None
    claim_bundle: Any
    safety_level: str
    overall_verdict: str
    required_actions: list[str] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)
    answer_obligations: list[str] = field(default_factory=list)
    build_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    policy_violations: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "answer_verification_report.v1",
            "text": self.text,
            "question": self.question,
            "overall_verdict": self.overall_verdict,
            "safety_level": self.safety_level,
            "claim_bundle": _to_dict(self.claim_bundle),
            "required_actions": list(self.required_actions),
            "response_constraints": list(self.response_constraints),
            "answer_obligations": list(self.answer_obligations),
            "build_context": _to_dict(self.build_context),
            "warnings": list(self.warnings),
            "policy_violations": _to_dict(self.policy_violations),
        }


@dataclass(frozen=True)
class SafeAnswerContract:
    safety_level: str
    can_answer: bool
    must_not_send: bool
    allowed_claims: list[Any] = field(default_factory=list)
    qualified_claims: list[Any] = field(default_factory=list)
    unknown_claims: list[Any] = field(default_factory=list)
    prohibited_claims: list[Any] = field(default_factory=list)
    required_qualifications: list[str] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)
    answer_obligations: list[str] = field(default_factory=list)
    build_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    policy_violations: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "safe_answer_contract.v1",
            "safety_level": self.safety_level,
            "can_answer": self.can_answer,
            "must_not_send": self.must_not_send,
            "allowed_claims": _to_dict(self.allowed_claims),
            "qualified_claims": _to_dict(self.qualified_claims),
            "unknown_claims": _to_dict(self.unknown_claims),
            "prohibited_claims": _to_dict(self.prohibited_claims),
            "required_qualifications": list(self.required_qualifications),
            "response_constraints": list(self.response_constraints),
            "answer_obligations": list(self.answer_obligations),
            "build_context": _to_dict(self.build_context),
            "warnings": list(self.warnings),
            "policy_violations": _to_dict(self.policy_violations),
        }


@dataclass(frozen=True)
class WorkflowTrace:
    repo: str
    question: str
    status: str
    preflight: AgentPreflightReport
    plan: AnswerPlan
    answer_verification: AnswerVerificationReport | None = None
    answer_contract: SafeAnswerContract | None = None
    steps: list[WorkflowStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "workflow_trace.v1",
            "repo": self.repo,
            "question": self.question,
            "status": self.status,
            "preflight": self.preflight.to_dict(),
            "plan": self.plan.to_dict(),
            "answer_verification": self.answer_verification.to_dict() if self.answer_verification else None,
            "answer_contract": self.answer_contract.to_dict() if self.answer_contract else None,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": list(self.warnings),
        }
