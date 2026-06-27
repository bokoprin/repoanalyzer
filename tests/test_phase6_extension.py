from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.claim_extraction import extract_claims
from repoanalyzer.workflow.answer_check import verify_answer
from repoanalyzer.workflow.contracts import build_answer_contract
from repoanalyzer.workflow.session import workflow_run
from repoanalyzer.workflow.session_log import read_workflow_sessions
from repoanalyzer.workflow_eval.runner import run_workflow_eval

FIXTURE_ROOT = Path(__file__).parent / "fixtures_cpp"
BASIC = FIXTURE_ROOT / "basic_call"


def test_phase6_extension_extracts_negated_and_list_claims() -> None:
    negated = extract_claims("start_device does not call init_device")
    assert len(negated.extracted_claims) == 1
    assert negated.extracted_claims[0].claim.claim_type == "calls"
    assert negated.extracted_claims[0].claim.payload["polarity"] == "negative"

    listed = extract_claims("start_device calls init_device and missing_target")
    assert [item.claim.object for item in listed.extracted_claims] == ["init_device", "missing_target"]

    ja_listed = extract_claims("start_device は init_device と missing_target を呼び出す")
    assert [item.claim.object for item in ja_listed.extracted_claims] == ["init_device", "missing_target"]


def test_phase6_extension_verifies_negative_claims_safely() -> None:
    ingest_repo(BASIC, reset=True)

    refuted = verify_answer(BASIC, "start_device does not call init_device")
    assert refuted.overall_verdict == "contradicted"
    assert refuted.safety_level == "unsafe"
    assert refuted.claim_bundle.verdicts[0].reason_code == "negated_claim_refuted_by_supported_evidence"

    supported_negative = verify_answer(BASIC, "start_device does not call missing_target")
    assert supported_negative.overall_verdict == "supported"
    assert supported_negative.safety_level == "safe"
    assert supported_negative.claim_bundle.verdicts[0].reason_code == "negated_claim_supported_by_contradiction_of_positive"


def test_phase6_extension_policy_flags_absolute_language() -> None:
    ingest_repo(BASIC, reset=True)

    report = verify_answer(BASIC, "start_device definitely calls missing_target")
    assert report.safety_level == "unsafe"
    assert any(v.violation_type == "absolute_language_on_unsettled_claims" for v in report.policy_violations)
    assert "remove_or_qualify_absolute_language" in report.required_actions

    contract = build_answer_contract(str(BASIC), "start_device definitely calls missing_target")
    assert contract.must_not_send is True
    assert contract.policy_violations


def test_phase6_extension_workflow_session_log_and_cli_history(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.cpp").write_text("void target() {}\nvoid caller() { target(); }\n", encoding="utf-8")
    ingest_repo(repo, reset=True)

    workflow_run(repo, "Does caller call target?", answer_text="caller calls target", record=True, label="smoke")
    history = read_workflow_sessions(repo)
    assert history["total"] == 1
    assert history["sessions"][0]["label"] == "smoke"
    assert history["sessions"][0]["trace"]["schema_version"] == "workflow_trace.v1"

    proc = subprocess.run(
        [sys.executable, "-m", "repoanalyzer.cli", "workflow-history", str(repo)],
        check=True,
        text=True,
        capture_output=True,
        env={"PYTHONPATH": "."},
    )
    assert json.loads(proc.stdout)["total"] == 1


def test_phase6_extension_workflow_eval_can_assert_policy_violations(tmp_path: Path) -> None:
    ingest_repo(BASIC, reset=True)
    cases = tmp_path / "workflow_policy_cases.yaml"
    cases.write_text(
        """
cases:
  - id: absolute_contradiction
    question: Does start_device call missing_target?
    answer_text: start_device definitely calls missing_target
    expected:
      status: blocked
      safety_level: unsafe
      overall_verdict: contradicted
      must_not_send: true
      policy_violations_contain:
        - absolute_language_on_unsettled_claims
""".strip(),
        encoding="utf-8",
    )

    result = run_workflow_eval(BASIC, cases)
    assert result.failed == 0
