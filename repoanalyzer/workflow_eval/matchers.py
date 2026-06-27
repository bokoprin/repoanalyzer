from __future__ import annotations

from typing import Any

from repoanalyzer.workflow.models import WorkflowTrace


def evaluate_trace(trace: WorkflowTrace, expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    payload = trace.to_dict()

    _expect_equal(failures, payload, "status", expected.get("status"))
    if trace.answer_verification:
        verification = trace.answer_verification.to_dict()
        _expect_equal(failures, verification, "safety_level", expected.get("safety_level"))
        _expect_equal(failures, verification, "overall_verdict", expected.get("overall_verdict"))
    elif "safety_level" in expected or "overall_verdict" in expected:
        failures.append("Expected answer verification fields, but answer_text was not provided or verification did not run.")

    if trace.answer_contract:
        contract = trace.answer_contract.to_dict()
        _expect_equal(failures, contract, "must_not_send", expected.get("must_not_send"))
        _expect_equal(failures, contract, "can_answer", expected.get("can_answer"))
        for snippet in expected.get("contract_constraints_contain", []) or []:
            constraints = "\n".join(contract.get("response_constraints") or [])
            if snippet not in constraints:
                failures.append(f"Expected contract constraint containing {snippet!r}; got {contract.get('response_constraints')!r}")
        for snippet in expected.get("answer_obligations_contain", []) or []:
            obligations = "\n".join(contract.get("answer_obligations") or [])
            if snippet not in obligations:
                failures.append(f"Expected answer obligation containing {snippet!r}; got {contract.get('answer_obligations')!r}")
        for path, expected_value in (expected.get("build_context_path_equals") or {}).items():
            actual = _payload_path(contract.get("build_context") or {}, path)
            if actual != expected_value:
                failures.append(f"Expected build_context.{path}={expected_value!r}; got {actual!r}")
        for path, expected_value in (expected.get("build_context_list_contains") or {}).items():
            actual = _payload_path(contract.get("build_context") or {}, path)
            if not isinstance(actual, list) or expected_value not in actual:
                failures.append(f"Expected build_context.{path} to contain {expected_value!r}; got {actual!r}")
    elif "must_not_send" in expected or "can_answer" in expected:
        failures.append("Expected answer contract fields, but no contract was produced.")

    for expected_action in expected.get("required_actions_contains", []) or []:
        actions = trace.answer_verification.required_actions if trace.answer_verification else []
        if expected_action not in actions:
            failures.append(f"Expected required action {expected_action!r}; got {actions!r}")

    for expected_tool in expected.get("required_tools_contains", []) or []:
        tools = trace.plan.required_tools
        if expected_tool not in tools:
            failures.append(f"Expected required tool {expected_tool!r}; got {tools!r}")

    for expected_warning in expected.get("warnings_contain", []) or []:
        warnings = "\n".join(trace.warnings)
        if expected_warning not in warnings:
            failures.append(f"Expected warning containing {expected_warning!r}; got {trace.warnings!r}")

    for expected_violation in expected.get("policy_violations_contain", []) or []:
        violations = []
        if trace.answer_verification:
            violations.extend(v.get("violation_type") if isinstance(v, dict) else getattr(v, "violation_type", "") for v in trace.answer_verification.policy_violations)
        if trace.answer_contract:
            violations.extend(v.get("violation_type") if isinstance(v, dict) else getattr(v, "violation_type", "") for v in trace.answer_contract.policy_violations)
        if expected_violation not in violations:
            failures.append(f"Expected policy violation {expected_violation!r}; got {violations!r}")

    return {"ok": not failures, "failures": failures}


def _expect_equal(failures: list[str], payload: dict[str, Any], key: str, expected: Any) -> None:
    if expected is None and key not in payload:
        return
    if expected is None:
        return
    actual = payload.get(key)
    if actual != expected:
        failures.append(f"Expected {key}={expected!r}; got {actual!r}")


def _payload_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value
