from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.query._store import open_store
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_typec_pd_probe"
CASE_FILE = FIXTURE / "phase7_tinyusb_typec_pd_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_tinyusb_typec_pd_real_repo_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["case_id"] == "phase7_tinyusb_typec_pd_semantics_probe"
    assert payload["metrics"]["indexed_files"] >= 6
    assert payload["metrics"]["total_facts"] >= 80
    assert payload["metrics"]["scenario_count"] == 14
    assert payload["metrics"]["passed_scenarios"] == 14
    assert payload["metrics"]["failed_scenarios"] == 0

    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] >= 6
    assert diagnostics["total_facts"] >= 80
    assert diagnostics["warnings"] == []


def test_phase7_tinyusb_typec_stack_and_tcd_boundary_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    facts = store.query_facts("fact_type='tinyusb_typec_pd'")
    assert len(facts) >= 20
    assert any(f.predicate == "typec_stack_init" and f.subject == "tuc_init" for f in facts)
    assert any(f.predicate == "tcd_init_boundary" and f.subject == "tcd_init" for f in facts)

    init = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tuc_init",
            "object": "tcd_init",
            "payload": {"predicate": "typec_stack_init", "tcd_api": "tcd_init", "uses_osal_queue": True},
        },
    )
    assert init.verdict == "supported"
    assert init.supporting_facts[0].payload["calls_tcd_init"] is True
    assert init.supporting_facts[0].payload["uses_osal_queue"] is True

    boundary = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tcd_msg_send",
            "object": "typec_controller_boundary",
            "payload": {"predicate": "tcd_message_send_boundary", "hardware_boundary": True},
        },
    )
    assert boundary.verdict == "supported"
    assert boundary.supporting_facts[0].payload["unknown_type"] == "typec_controller_register_semantics_unknown"


def test_phase7_tinyusb_typec_event_queue_and_task_semantics_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    defer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tcd_event_handler",
            "object": "osal_queue_send",
            "payload": {"predicate": "defers_tcd_event_to_typec_queue"},
        },
    )
    assert defer.verdict == "supported"
    assert defer.supporting_facts[0].payload["starts_receive_on_cc_attach"] is True

    task = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tuc_task_ext",
            "object": "osal_queue_receive",
            "payload": {"predicate": "consumes_typec_event_queue"},
        },
    )
    assert task.verdict == "supported"
    payload = task.supporting_facts[0].payload
    assert payload["handles_rx_complete"] is True
    assert payload["dispatches_pd_data_parser"] is True
    assert payload["dispatches_pd_control_parser"] is True

    rx = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "TCD_EVENT_RX_COMPLETE",
            "object": "rx_complete",
            "payload": {"predicate": "handles_typec_event", "event_id": "TCD_EVENT_RX_COMPLETE"},
        },
    )
    assert rx.verdict == "supported"


def test_phase7_tinyusb_typec_pd_message_policy_semantics_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    request = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tuc_msg_request",
            "object": "PD_DATA_REQUEST",
            "payload": {
                "predicate": "builds_pd_request_message",
                "pd_message_type": "PD_DATA_REQUEST",
                "power_role": "PD_POWER_ROLE_SINK",
                "data_role": "PD_DATA_ROLE_UFP",
            },
        },
    )
    assert request.verdict == "supported"
    payload = request.supporting_facts[0].payload
    assert payload["pd_message_type"] == "PD_DATA_REQUEST"
    assert payload["power_role"] == "PD_POWER_ROLE_SINK"
    assert payload["data_role"] == "PD_DATA_ROLE_UFP"

    source_cap = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tuc_pd_data_received_cb",
            "object": "PD_DATA_SOURCE_CAP",
            "payload": {
                "predicate": "handles_pd_data_message",
                "pd_message_type": "PD_DATA_SOURCE_CAP",
                "policy_action": "select_pdo_and_send_request",
            },
        },
    )
    assert source_cap.verdict == "supported"
    assert source_cap.supporting_facts[0].payload["builds_request"] is True

    accept = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_typec_pd_semantic",
            "subject": "tuc_pd_control_received_cb",
            "object": "PD_CTRL_ACCEPT",
            "payload": {"predicate": "handles_pd_control_message", "message_category": "control"},
        },
    )
    assert accept.verdict == "supported"
    assert accept.supporting_facts[0].payload["policy_action"] == "request_accepted"
