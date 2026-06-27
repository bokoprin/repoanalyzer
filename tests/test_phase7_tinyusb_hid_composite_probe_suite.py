from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.query._store import open_store
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_hid_composite_probe"
CASE_FILE = FIXTURE / "phase7_tinyusb_hid_composite_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_tinyusb_hid_composite_real_repo_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["case_id"] == "phase7_tinyusb_hid_composite_class_protocol_probe"
    assert payload["metrics"]["indexed_files"] >= 7
    assert payload["metrics"]["total_facts"] >= 80
    assert payload["metrics"]["scenario_count"] == 10
    assert payload["metrics"]["passed_scenarios"] == 10
    assert payload["metrics"]["failed_scenarios"] == 0

    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] >= 7
    assert diagnostics["total_facts"] >= 80
    assert diagnostics["warnings"] == []


def test_phase7_tinyusb_hid_descriptor_and_report_semantics_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    descriptor_facts = store.query_facts("fact_type='usb_descriptor'")
    assert any(f.payload.get("descriptor_macro") == "TUD_HID_DESCRIPTOR" for f in descriptor_facts)
    assert any(f.subject == "tud_hid_descriptor_report_cb" and f.object == "desc_hid_report" for f in descriptor_facts)

    hid = verify_claim(
        repo,
        {
            "claim_type": "usb_descriptor_semantic",
            "subject": "HID",
            "object": "desc_configuration",
            "payload": {"class": "HID", "interface_symbol": "ITF_NUM_HID", "endpoint_symbol": "EPNUM_HID"},
        },
    )
    assert hid.verdict == "supported"
    payload = hid.supporting_facts[0].payload
    assert payload["descriptor_macro"] == "TUD_HID_DESCRIPTOR"
    assert payload["resolved_arguments"]["interface_number"] == 0
    assert payload["endpoint_directions"]["EPNUM_HID"] == "in"

    keyboard = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "REPORT_ID_KEYBOARD",
            "object": "keyboard",
            "payload": {
                "predicate": "declares_hid_report_descriptor_item",
                "report_kind": "keyboard",
                "report_id": "REPORT_ID_KEYBOARD",
            },
        },
    )
    assert keyboard.verdict == "supported"
    assert keyboard.supporting_facts[0].payload["resolved_report_id"] == 1


def test_phase7_tinyusb_hid_report_api_and_control_callbacks_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    class_facts = store.query_facts("fact_type='tinyusb_class_protocol'")
    assert len(class_facts) >= 8

    mouse = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_hid_mouse_report",
            "object": "mouse",
            "payload": {"predicate": "declares_hid_report_api", "report_kind": "mouse"},
        },
    )
    assert mouse.verdict == "supported"
    assert mouse.supporting_facts[0].payload["transfer_direction"] == "in"

    get_report = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_hid_get_report_cb",
            "object": "get_report",
            "payload": {"predicate": "declares_hid_control_callback", "callback_name": "tud_hid_get_report_cb"},
        },
    )
    assert get_report.verdict == "supported"

    set_report = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_hid_set_report_cb",
            "object": "set_report",
            "payload": {"predicate": "declares_hid_control_callback", "callback_name": "tud_hid_set_report_cb"},
        },
    )
    assert set_report.verdict == "supported"


def test_phase7_tinyusb_cdc_msc_class_protocol_semantics_are_evidence(tmp_path: Path) -> None:
    # Reuse the CDC+MSC device fixture to validate class-specific expansion without
    # disturbing its existing descriptor/runtime scenarios.
    base = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_cdc_msc_probe"
    repo = tmp_path / "repo"
    shutil.copytree(base, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    report = run_real_repo_eval(repo, repo / "phase7_tinyusb_cdc_msc_cases.yaml")
    assert report.ok, report.to_dict()

    cdc_write = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_cdc_write",
            "object": "cdc_write",
            "payload": {"predicate": "declares_cdc_stream_api", "class": "CDC", "transfer_direction": "in"},
        },
    )
    assert cdc_write.verdict == "supported"

    cdc_line_state = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_cdc_line_state_cb",
            "object": "cdc_line_state",
            "payload": {"predicate": "declares_cdc_callback", "class": "CDC"},
        },
    )
    assert cdc_line_state.verdict == "supported"

    msc_read10 = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_msc_read10_cb",
            "object": "READ10",
            "payload": {"predicate": "declares_msc_scsi_callback", "scsi_command": "READ10"},
        },
    )
    assert msc_read10.verdict == "supported"

    msc_write10 = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_class_protocol_semantic",
            "subject": "tud_msc_write10_cb",
            "object": "WRITE10",
            "payload": {"predicate": "declares_msc_scsi_callback", "scsi_command": "WRITE10"},
        },
    )
    assert msc_write10.verdict == "supported"
