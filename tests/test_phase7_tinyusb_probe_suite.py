from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.query._store import open_store
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.store.diagnostics import query_diagnostics

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_cdc_msc_probe"
CASE_FILE = FIXTURE / "phase7_tinyusb_cdc_msc_cases.yaml"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__"))
    return repo


def test_phase7_tinyusb_cdc_msc_profile_real_repo_eval_passes(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    case_file = repo / CASE_FILE.name

    report = run_real_repo_eval(repo, case_file)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "real_repo_eval_report.v1"
    assert payload["case_id"] == "phase7_tinyusb_device_cdc_msc_profile_probe"
    assert payload["metrics"]["indexed_files"] == 18
    assert payload["metrics"]["total_facts"] >= 80
    assert payload["metrics"]["scenario_count"] == 40
    assert payload["metrics"]["passed_scenarios"] == 40
    assert payload["metrics"]["failed_scenarios"] == 0

    diagnostics = query_diagnostics(repo).to_dict()
    assert diagnostics["indexed_files"] == 18
    assert diagnostics["total_facts"] >= 100
    assert diagnostics["warnings"] == []


def test_phase7_tinyusb_target_profile_preserves_embedded_build_scope(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    metadata = store.all_metadata()
    profile = metadata["target_profile"]
    assert profile["name"] == "tinyusb-device-cdc-msc-stm32f407disco-none"
    assert profile["board"] == "stm32f407disco"
    assert profile["rtos"] == "none"
    assert profile["usb_role"] == "device"
    assert profile["example"] == "examples/device/cdc_msc"
    assert profile["active_port"] == "src/portable/synopsys/dwc2"

    target_profile_facts = store.query_facts("fact_type='target_profile'")
    assert any(f.predicate == "selected_profile" and f.subject == "tinyusb-device-cdc-msc-stm32f407disco-none" for f in target_profile_facts)
    assert any(f.predicate == "target_attribute" and f.subject == "board" and f.object == "stm32f407disco" for f in target_profile_facts)
    assert any(f.predicate == "target_attribute" and f.subject == "usb_role" and f.object == "device" for f in target_profile_facts)
    assert any(f.predicate == "target_attribute" and f.subject == "active_port" and f.object == "src/portable/synopsys/dwc2" for f in target_profile_facts)


def test_phase7_tinyusb_config_macros_and_file_selection_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    cdc_enabled = verify_claim(repo, {"claim_type": "build_config", "subject": "CFG_TUD_CDC", "object": "1"})
    assert cdc_enabled.verdict == "supported"
    assert cdc_enabled.supporting_facts[0].payload.get("macro_origins")

    msc_enabled = verify_claim(repo, {"claim_type": "build_config", "subject": "CFG_TUD_MSC", "object": "1"})
    assert msc_enabled.verdict == "supported"

    hid_disabled = verify_claim(repo, {"claim_type": "build_config", "subject": "CFG_TUD_HID", "object": "0"})
    assert hid_disabled.verdict == "supported"

    selected_dcd = verify_claim(repo, {"claim_type": "file_active", "subject": "src/portable/synopsys/dwc2/dcd_dwc2.c", "object": "active"})
    assert selected_dcd.verdict == "supported"
    assert "active_port" in (selected_dcd.supporting_facts[0].payload.get("selection_reasons") or [])

    non_selected_dcd = verify_claim(repo, {"claim_type": "file_active", "subject": "src/portable/st/stm32_fsdev/dcd_stm32_fsdev.c", "object": "inactive"})
    assert non_selected_dcd.verdict == "supported"
    assert non_selected_dcd.supporting_facts[0].payload.get("selection_reasons") == ["non_selected_port"]

    hid_source = verify_claim(repo, {"claim_type": "file_active", "subject": "src/class/hid/hid_device.c", "object": "inactive"})
    assert hid_source.verdict == "supported"
    assert hid_source.supporting_facts[0].payload.get("selection_reasons") == ["not_in_compile_commands"]



def test_phase7_tinyusb_descriptor_macros_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    descriptor_facts = store.query_facts("fact_type='usb_descriptor'")
    assert len(descriptor_facts) == 7
    assert any(
        f.subject == "desc_fs_configuration"
        and f.predicate == "declares_descriptor_array"
        and f.object == "configuration"
        for f in descriptor_facts
    )

    cdc = verify_claim(
        repo,
        {
            "claim_type": "usb_descriptor_semantic",
            "subject": "CDC",
            "object": "desc_fs_configuration",
            "payload": {"class": "CDC", "interface_symbol": "ITF_NUM_CDC", "endpoint_symbol": "EPNUM_CDC_IN"},
        },
    )
    assert cdc.verdict == "supported"
    cdc_payload = cdc.supporting_facts[0].payload
    assert cdc_payload["descriptor_macro"] == "TUD_CDC_DESCRIPTOR"
    assert cdc_payload["resolved_arguments"]["interface_number"] == 0
    assert cdc_payload["resolved_arguments"]["endpoint_in"] == 0x82
    assert cdc_payload["endpoint_directions"]["EPNUM_CDC_IN"] == "in"

    msc = verify_claim(
        repo,
        {
            "claim_type": "usb_descriptor_semantic",
            "subject": "MSC",
            "object": "desc_fs_configuration",
            "payload": {"class": "MSC", "interface_symbol": "ITF_NUM_MSC", "endpoint_symbol": "EPNUM_MSC_OUT"},
        },
    )
    assert msc.verdict == "supported"
    msc_payload = msc.supporting_facts[0].payload
    assert msc_payload["descriptor_macro"] == "TUD_MSC_DESCRIPTOR"
    assert msc_payload["resolved_arguments"]["interface_number"] == 2
    assert msc_payload["endpoint_directions"]["EPNUM_MSC_OUT"] == "out"

    config_cb = verify_claim(
        repo,
        {
            "claim_type": "usb_descriptor_semantic",
            "subject": "tud_descriptor_configuration_cb",
            "object": "desc_fs_configuration",
            "payload": {"predicate": "provides_descriptor_callback", "descriptor_kind": "configuration"},
        },
    )
    assert config_cb.verdict == "supported"
    assert config_cb.supporting_facts[0].payload["callback_kind"] == "descriptor_callback_provider"


def test_phase7_tinyusb_weak_callbacks_and_application_overrides_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    callback_facts = store.query_facts("fact_type='tinyusb_callback'")
    assert len(callback_facts) == 11

    weak_mount = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_callback_semantic",
            "subject": "tud_mount_cb",
            "payload": {"predicate": "declares_weak_callback_default", "linkage": "weak"},
        },
    )
    assert weak_mount.verdict == "supported"
    assert weak_mount.supporting_facts[0].payload["callback_requirement"] == "optional_weak_default"
    assert weak_mount.supporting_facts[0].payload["callback_family"] == "device_lifecycle"

    app_mount = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_callback_semantic",
            "subject": "tud_mount_cb",
            "payload": {
                "predicate": "declares_tinyusb_callback_implementation",
                "implementation_kind": "application_callback",
                "application_path": True,
            },
        },
    )
    assert app_mount.verdict == "supported"
    assert app_mount.supporting_facts[0].path == "examples/device/cdc_msc/src/main.c"

    override = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_callback_semantic",
            "subject": "tud_mount_cb",
            "payload": {"predicate": "overrides_weak_callback", "override_status": "overridden_by_application"},
        },
    )
    assert override.verdict == "supported"
    override_payload = override.supporting_facts[0].payload
    assert override_payload["weak_definition_path"] == "src/device/usbd.c"
    assert override_payload["application_definition_path"] == "examples/device/cdc_msc/src/main.c"

    descriptor_provider = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_callback_semantic",
            "subject": "tud_descriptor_configuration_cb",
            "payload": {
                "predicate": "declares_tinyusb_callback_implementation",
                "callback_family": "descriptor",
                "callback_requirement": "application_descriptor_provider",
                "application_path": True,
            },
        },
    )
    assert descriptor_provider.verdict == "supported"
    assert descriptor_provider.supporting_facts[0].payload["provider_kind"] == "descriptor_callback_provider"

    cdc_optional = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_callback_semantic",
            "subject": "tud_cdc_line_state_cb",
            "payload": {"predicate": "declares_weak_callback_default", "callback_family": "cdc", "weak_default": True},
        },
    )
    assert cdc_optional.verdict == "supported"
    assert cdc_optional.supporting_facts[0].payload["callback_requirement"] == "optional_weak_default"

def test_phase7_tinyusb_cdc_msc_probe_keeps_basic_call_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    main_bundle = verify_claim_text(repo, "main calls tusb_init")
    assert main_bundle.overall_verdict == "supported"
    assert main_bundle.verdicts[0].supporting_facts[0].payload.get("tu_context", {}).get("target_profile") == "tinyusb-device-cdc-msc-stm32f407disco-none"

    dcd_bundle = verify_claim_text(repo, "tusb_init calls dcd_init")
    assert dcd_bundle.overall_verdict == "supported"


def test_phase7_tinyusb_class_driver_dispatch_and_endpoint_binding_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    dispatch_facts = store.query_facts("fact_type='tinyusb_driver_dispatch'")
    assert len(dispatch_facts) == 16

    cdc_entry = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "CDC",
            "object": "_usbd_driver",
            "payload": {"predicate": "declares_class_driver_entry", "config_macro": "CFG_TUD_CDC"},
        },
    )
    assert cdc_entry.verdict == "supported"
    assert cdc_entry.supporting_facts[0].payload["callbacks"]["open"] == "cdcd_open"

    cdc_open = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "CDC",
            "object": "cdcd_open",
            "payload": {"predicate": "binds_driver_callback", "callback_field": "open"},
        },
    )
    assert cdc_open.verdict == "supported"
    assert cdc_open.supporting_facts[0].payload["resolution_status"] == "resolved"

    msc_xfer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "MSC",
            "object": "mscd_xfer_cb",
            "payload": {"predicate": "binds_driver_callback", "callback_field": "xfer_cb"},
        },
    )
    assert msc_xfer.verdict == "supported"
    assert msc_xfer.supporting_facts[0].payload["callback_symbol"] == "mscd_xfer_cb"

    ep_map = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "ep2drv",
            "payload": {"predicate": "declares_endpoint_driver_map", "map_kind": "endpoint_to_driver_map"},
        },
    )
    assert ep_map.verdict == "supported"

    bind = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "drv_id",
            "object": "tu_bind_driver_to_ep_itf",
            "payload": {"predicate": "binds_driver_to_endpoint_interface_maps", "map_name": "ep2drv"},
        },
    )
    assert bind.verdict == "supported"
    assert bind.supporting_facts[0].payload["endpoint_map"] == "_usbd_dev.ep2drv"
    assert bind.supporting_facts[0].payload["interface_map"] == "_usbd_dev.itf2drv"

    xfer_dispatch = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_driver_dispatch_semantic",
            "subject": "dcd_event_xfer_complete",
            "object": "xfer_cb",
            "payload": {
                "predicate": "indirect_dispatches_to_driver_callback",
                "map_name": "ep2drv",
                "via_function": "get_driver",
            },
        },
    )
    assert xfer_dispatch.verdict == "supported"
    xfer_payload = xfer_dispatch.supporting_facts[0].payload
    assert xfer_payload["map_kind"] == "endpoint_to_driver_map"
    assert xfer_payload["uses_endpoint_map"] is True



def test_phase7_tinyusb_device_runtime_semantics_are_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    report = run_real_repo_eval(repo, repo / CASE_FILE.name)
    assert report.ok, report.to_dict()

    store = open_store(repo)
    runtime_facts = store.query_facts("fact_type='tinyusb_device_runtime'")
    assert len(runtime_facts) >= 18

    edpt_xfer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_device_runtime_semantic",
            "subject": "usbd_edpt_xfer",
            "object": "async_transfer_request",
            "payload": {"predicate": "endpoint_transfer_submit", "dcd_api": "dcd_edpt_xfer", "transfer_lifecycle_stage": "submit"},
        },
    )
    assert edpt_xfer.verdict == "supported"
    edpt_payload = edpt_xfer.supporting_facts[0].payload
    assert edpt_payload["dcd_transfer_api"] == "dcd_edpt_xfer"
    assert edpt_payload["is_async_transfer_submit"] is True

    dcd_boundary = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_device_runtime_semantic",
            "subject": "dcd_edpt_xfer",
            "object": "hardware_controller_boundary",
            "payload": {
                "predicate": "dcd_transfer_submit_boundary",
                "controller_port_path": "src/portable/synopsys/dwc2",
                "hardware_boundary": True,
            },
        },
    )
    assert dcd_boundary.verdict == "supported"
    assert dcd_boundary.supporting_facts[0].payload["unknown_type"] == "hardware_register_semantics_unknown"

    queue = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_device_runtime_semantic",
            "subject": "_usbd_q",
            "object": "osal_queue",
            "payload": {"predicate": "declares_osal_event_queue", "queue_name": "_usbd_q", "osal_profile": "none"},
        },
    )
    assert queue.verdict == "supported"
    assert queue.supporting_facts[0].payload["config_macro"] == "CFG_TUSB_OS"

    defer = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_device_runtime_semantic",
            "subject": "dcd_event_handler",
            "object": "osal_queue_send",
            "payload": {"predicate": "defers_dcd_event_to_task_queue", "queue_api": "osal_queue_send"},
        },
    )
    assert defer.verdict == "supported"
    assert defer.supporting_facts[0].payload["isr_safe_arg_detected"] is True

    tud_task = verify_claim(
        repo,
        {
            "claim_type": "tinyusb_device_runtime_semantic",
            "subject": "tud_task",
            "object": "osal_queue_receive",
            "payload": {
                "predicate": "consumes_dcd_event_queue",
                "queue_api": "osal_queue_receive",
                "consumes_event_queue": True,
                "dispatches_transfer_complete": True,
            },
        },
    )
    assert tud_task.verdict == "supported"
    assert tud_task.supporting_facts[0].payload["runtime_model"] == "dcd_event_queue_to_tud_task_dispatch"
