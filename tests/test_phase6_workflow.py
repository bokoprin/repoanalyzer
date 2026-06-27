from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.mcp.tools import tool_answer_contract, tool_preflight, tool_verify_answer, tool_workflow_run
from repoanalyzer.workflow.answer_check import verify_answer
from repoanalyzer.workflow.contracts import build_answer_contract
from repoanalyzer.workflow.planner import plan_question
from repoanalyzer.workflow.preflight import preflight
from repoanalyzer.workflow.session import workflow_run
from repoanalyzer.workflow_eval.runner import run_workflow_eval

FIXTURE_ROOT = Path(__file__).parent / "fixtures_cpp"
BASIC = FIXTURE_ROOT / "basic_call"
SEMANTIC = FIXTURE_ROOT / "semantic_phase3_mvp_integration"


def test_phase6_preflight_reports_ready_and_planner_requires_verification_tools() -> None:
    ingest_repo(BASIC, reset=True)

    report = preflight(BASIC)
    assert report.index_ready is True
    assert report.safety_level in {"ready", "caution"}
    assert report.status["clean"] is True
    assert "verify_text" in report.recommended_tools

    plan = plan_question("start_device calls init_device")
    assert plan.interpreted_intent == "claim_verification"
    assert "extract_claims" in plan.required_tools
    assert "verify_claims" in plan.required_tools
    assert "answer_contract" in plan.required_tools


def test_phase6_verify_answer_and_contract_for_supported_and_contradicted_claims() -> None:
    ingest_repo(BASIC, reset=True)

    supported = verify_answer(BASIC, "start_device calls init_device")
    assert supported.safety_level == "safe"
    assert supported.overall_verdict == "supported"

    good_contract = build_answer_contract(str(BASIC), "start_device calls init_device")
    assert good_contract.can_answer is True
    assert good_contract.must_not_send is False
    assert good_contract.allowed_claims

    contradicted = verify_answer(BASIC, "start_device calls missing_target")
    assert contradicted.safety_level == "unsafe"
    assert contradicted.overall_verdict == "contradicted"

    bad_contract = build_answer_contract(str(BASIC), "start_device calls missing_target")
    assert bad_contract.can_answer is False
    assert bad_contract.must_not_send is True
    assert bad_contract.prohibited_claims


def test_phase6_callback_answer_requires_qualification() -> None:
    ingest_repo(SEMANTIC, reset=True)

    report = verify_answer(SEMANTIC, "app::registerCallback は app::callback_target をコールバック登録する")

    assert report.overall_verdict == "conditional"
    assert report.safety_level == "must_qualify"
    assert "qualify_conditional_claims" in report.required_actions

    contract = build_answer_contract(str(SEMANTIC), "app::registerCallback は app::callback_target をコールバック登録する")
    assert contract.can_answer is True
    assert contract.must_not_send is False
    assert contract.qualified_claims
    assert contract.required_qualifications


def test_phase6_workflow_run_and_eval(tmp_path: Path) -> None:
    ingest_repo(BASIC, reset=True)
    trace = workflow_run(BASIC, "Does start_device call init_device?", answer_text="start_device calls init_device")

    assert trace.status == "ready"
    assert trace.answer_verification is not None
    assert trace.answer_verification.safety_level == "safe"
    assert trace.answer_contract is not None
    assert trace.answer_contract.can_answer is True

    cases = tmp_path / "workflow_cases.yaml"
    cases.write_text(
        """
cases:
  - id: supported_answer
    question: Does start_device call init_device?
    answer_text: start_device calls init_device
    expected:
      status: ready
      safety_level: safe
      overall_verdict: supported
      can_answer: true
      must_not_send: false
      required_tools_contains:
        - answer_contract
  - id: contradicted_answer
    question: Does start_device call missing_target?
    answer_text: start_device calls missing_target
    expected:
      status: blocked
      safety_level: unsafe
      overall_verdict: contradicted
      can_answer: false
      must_not_send: true
      required_actions_contains:
        - revise_or_remove_contradicted_claims
""".strip(),
        encoding="utf-8",
    )

    result = run_workflow_eval(BASIC, cases)
    assert result.failed == 0
    assert result.passed == 2


def test_phase6_dirty_index_answer_contract_requires_reingest(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("void target() {}\nvoid caller() { target(); }\n", encoding="utf-8")
    ingest_repo(tmp_path, reset=True)

    (src / "main.cpp").write_text("void target() {}\nvoid caller() {}\n", encoding="utf-8")
    report = verify_answer(tmp_path, "caller calls target")

    assert report.safety_level in {"must_qualify", "needs_more_evidence"}
    assert "rerun_ingest" in report.required_actions
    assert any("Re-run ingest" in constraint for constraint in report.response_constraints)


def test_phase6_mcp_workflow_tools_without_mcp_runtime() -> None:
    ingest_repo(BASIC, reset=True)

    assert tool_preflight(str(BASIC))["schema_version"] == "agent_preflight.v1"
    verified = tool_verify_answer(str(BASIC), "start_device calls init_device")
    assert verified["schema_version"] == "answer_verification_report.v1"
    assert verified["safety_level"] == "safe"

    contract = tool_answer_contract(str(BASIC), "start_device calls init_device")
    assert contract["schema_version"] == "safe_answer_contract.v1"
    assert contract["can_answer"] is True

    trace = tool_workflow_run(str(BASIC), "Does start_device call init_device?", "start_device calls init_device")
    assert trace["schema_version"] == "workflow_trace.v1"
    assert trace["status"] == "ready"


def test_phase6_cli_commands_smoke() -> None:
    ingest_repo(BASIC, reset=True)

    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "verify-answer", str(BASIC), "start_device calls init_device"],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    payload = json.loads(proc.stdout)
    assert payload["schema_version"] == "answer_verification_report.v1"
    assert payload["safety_level"] == "safe"

    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "preflight", str(BASIC)],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    assert json.loads(proc.stdout)["schema_version"] == "agent_preflight.v1"
