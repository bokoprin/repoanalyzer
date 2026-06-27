from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.query._store import open_store
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_host_cdc_msc_hid_probe"
CASE_FILE = FIXTURE / "phase7_tinyusb_host_cdc_msc_hid_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_tinyusb_host_cdc_msc_hid_real_repo_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["case_id"] == "phase7_tinyusb_host_cdc_msc_hid_semantics_probe"
    assert payload["metrics"]["indexed_files"] >= 16
    assert payload["metrics"]["total_facts"] >= 100
    assert payload["metrics"]["scenario_count"] == 18
    assert payload["metrics"]["passed_scenarios"] == 18
    assert payload["metrics"]["failed_scenarios"] == 0

    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] >= 16
    assert diagnostics["total_facts"] >= 100
    assert diagnostics["warnings"] == []


def test_phase7_tinyusb_host_profile_and_basic_calls_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    metadata = store.all_metadata()
    profile = metadata["target_profile"]
    assert profile["name"] == "tinyusb-host-cdc-msc-hid-stm32f407disco-none"
    assert profile["usb_role"] == "host"
    assert profile["example"] == "examples/host/cdc_msc_hid"
    assert profile["active_port"] == "src/portable/synopsys/dwc2"

    hid_enabled = verify_claim(repo, {"claim_type": "build_config", "subject": "CFG_TUH_HID", "object": "1"})
    assert hid_enabled.verdict == "supported"

    main_bundle = verify_claim_text(repo, "main calls tusb_init")
    assert main_bundle.overall_verdict == "supported"

    init_bundle = verify_claim_text(repo, "tusb_init calls tuh_init")
    assert init_bundle.overall_verdict == "supported"


def test_phase7_tinyusb_host_class_driver_dispatch_is_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    host_facts = store.query_facts("fact_type='tinyusb_host_runtime'")
    assert len(host_facts) >= 25

    cdc_entry = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "CDC",
            "object": "usbh_class_drivers",
            "payload": {"predicate": "declares_host_class_driver_entry", "config_macro": "CFG_TUH_CDC"},
        },
    )
    assert cdc_entry.verdict == "supported"
    assert cdc_entry.supporting_facts[0].payload["callbacks"]["open"] == "cdch_open"

    hid_open = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "HID",
            "object": "hidh_open",
            "payload": {"predicate": "binds_host_driver_callback", "callback_field": "open"},
        },
    )
    assert hid_open.verdict == "supported"
    assert hid_open.supporting_facts[0].payload["callback_symbol"] == "hidh_open"

    bind = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "drv_id",
            "object": "tu_bind_driver_to_ep_itf",
            "payload": {"predicate": "binds_host_driver_to_endpoint_interface_maps", "map_name": "ep2drv"},
        },
    )
    assert bind.verdict == "supported"
    assert bind.supporting_facts[0].payload["endpoint_map"] == "dev->ep2drv"
    assert bind.supporting_facts[0].payload["interface_map"] == "dev->itf2drv"

    xfer_dispatch = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_task_ext",
            "object": "xfer_cb",
            "payload": {
                "predicate": "host_indirect_dispatches_to_driver_callback",
                "map_name": "ep2drv",
                "via_function": "get_driver",
                "dispatches_class_xfer_callback": True,
            },
        },
    )
    assert xfer_dispatch.verdict == "supported"
    assert xfer_dispatch.supporting_facts[0].payload["event_id"] == "HCD_EVENT_XFER_COMPLETE"


def test_phase7_tinyusb_host_event_queue_and_enumeration_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    defer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "hcd_event_handler",
            "object": "osal_queue_send",
            "payload": {"predicate": "defers_hcd_event_to_host_queue", "queue_api": "osal_queue_send", "queues_event": True},
        },
    )
    assert defer.verdict == "supported"
    assert defer.supporting_facts[0].payload["defer_model"] == "hcd_event_handler_enqueues_for_tuh_task"

    task = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_task_ext",
            "object": "osal_queue_receive",
            "payload": {
                "predicate": "consumes_hcd_event_queue",
                "queue_api": "osal_queue_receive",
                "consumes_event_queue": True,
                "handles_device_attach": True,
                "dispatches_enumeration": True,
            },
        },
    )
    assert task.verdict == "supported"
    assert task.supporting_facts[0].payload["runtime_model"] == "hcd_event_queue_to_tuh_task_dispatch"

    get_device_desc = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_descriptor_get_device",
            "object": "get_device_descriptor",
            "payload": {"predicate": "host_enumeration_stage", "enumeration_stage": "get_device_descriptor"},
        },
    )
    assert get_device_desc.verdict == "supported"

    set_address = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_address_set",
            "object": "set_address",
            "payload": {"predicate": "host_enumeration_stage", "enumeration_stage": "set_address"},
        },
    )
    assert set_address.verdict == "supported"

    mount = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_mount_cb",
            "object": "mount_callback",
            "payload": {"predicate": "host_enumeration_stage", "enumeration_stage": "mount_callback"},
        },
    )
    assert mount.verdict == "supported"


def test_phase7_tinyusb_host_hcd_boundary_and_transfer_submit_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    hcd_boundary = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "hcd_edpt_xfer",
            "object": "host_controller_boundary",
            "payload": {
                "predicate": "hcd_transfer_submit_boundary",
                "controller_port_path": "src/portable/synopsys/dwc2",
                "hardware_boundary": True,
            },
        },
    )
    assert hcd_boundary.verdict == "supported"
    assert hcd_boundary.supporting_facts[0].payload["unknown_type"] == "host_controller_register_semantics_unknown"

    tuh_xfer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_host_runtime_semantic",
            "subject": "tuh_edpt_xfer",
            "object": "async_host_transfer_request",
            "payload": {"predicate": "host_endpoint_transfer_submit", "hcd_api": "hcd_edpt_xfer", "transfer_lifecycle_stage": "submit"},
        },
    )
    assert tuh_xfer.verdict == "supported"
    assert tuh_xfer.supporting_facts[0].payload["hcd_transfer_api"] == "hcd_edpt_xfer"
