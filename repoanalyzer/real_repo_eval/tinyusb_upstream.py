from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml
import json

from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.store.status import repo_index_status
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.workflow.preflight import preflight


@dataclass(frozen=True)
class TinyUsbSmokeProfile:
    id: str
    description: str
    config_path: Path
    case_path: Path
    compile_commands_path: Path
    expected_sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "config_path": self.config_path.as_posix(),
            "case_path": self.case_path.as_posix(),
            "compile_commands_path": self.compile_commands_path.as_posix(),
            "expected_sources": list(self.expected_sources),
        }


@dataclass(frozen=True)
class TinyUsbSmokePlan:
    root: Path
    output_dir: Path
    profiles: list[TinyUsbSmokeProfile]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "output_dir": self.output_dir.as_posix(),
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


def prepare_tinyusb_upstream_smoke(repo: str | Path, output_dir: str | Path = ".repoanalyzer-smoke") -> TinyUsbSmokePlan:
    """Generate real-upstream TinyUSB smoke configs and scenario files.

    The generated files intentionally live outside source control by default.
    They give repoanalyzer a deterministic target profile for selected TinyUSB
    examples without requiring TinyUSB's full CMake/Make build to run.
    """

    root = Path(repo).expanduser().resolve()
    out = Path(output_dir)
    if not out.is_absolute():
        out = root / out
    out.mkdir(parents=True, exist_ok=True)

    profiles = [
        _write_device_cdc_msc(root, out),
        _write_host_cdc_msc_hid(root, out),
        _write_hid_composite(root, out),
        _write_typec_power_delivery(root, out),
    ]
    return TinyUsbSmokePlan(root=root, output_dir=out, profiles=profiles)


def run_tinyusb_upstream_smoke(
    repo: str | Path,
    output_dir: str | Path = ".repoanalyzer-smoke",
    profiles: Iterable[str] | None = None,
) -> dict[str, Any]:
    plan = prepare_tinyusb_upstream_smoke(repo, output_dir)
    wanted = set(profiles or [])
    if not wanted:
        raise ValueError("at least one TinyUSB upstream smoke profile must be selected")
    selected = [profile for profile in plan.profiles if profile.id in wanted]
    reports = []
    ok = True
    for profile in selected:
        report = run_real_repo_eval(plan.root, plan.root / profile.case_path)
        payload = report.to_dict()
        reports.append(payload)
        ok = ok and bool(payload.get("ok"))
    return {
        "schema_version": "tinyusb_upstream_smoke_report.v1",
        "ok": ok,
        "root": str(plan.root),
        "output_dir": str(plan.output_dir),
        "profile_count": len(selected),
        "passed_profiles": sum(1 for item in reports if item.get("ok")),
        "failed_profiles": sum(1 for item in reports if not item.get("ok")),
        "profiles": [profile.to_dict() for profile in selected],
        "reports": reports,
    }



def index_tinyusb_upstream(
    repo: str | Path,
    output_dir: str | Path = ".repoanalyzer-smoke",
    profile: str = "tinyusb_upstream_device_cdc_msc",
) -> dict[str, Any]:
    """Prepare one TinyUSB upstream profile and build a repoanalyzer index for MCP use.

    Unlike ``run_tinyusb_upstream_smoke``, this is an operational setup helper:
    it writes the selected profile files, runs a normal full ingest, and returns
    index/preflight metadata that an MCP client can check before answering code
    questions.
    """

    plan = prepare_tinyusb_upstream_smoke(repo, output_dir)
    selected = _select_profile(plan, profile)
    if not selected.expected_sources:
        raise ValueError(f"profile {profile!r} did not match any existing TinyUSB source files under {plan.root}")

    config_path = plan.root / selected.config_path
    ingest_result = ingest_repo(plan.root, config_path=config_path, reset=True)
    status = repo_index_status(plan.root, config_path=config_path)
    diagnostics = query_diagnostics(plan.root)
    readiness = preflight(plan.root)
    return {
        "schema_version": "tinyusb_upstream_index_report.v1",
        "ok": ingest_result.status == "indexed" and not ingest_result.full_reingest_required and readiness.safety_level in {"ready", "caution"} and not readiness.required_actions,
        "root": str(plan.root),
        "output_dir": str(plan.output_dir),
        "profile": selected.to_dict(),
        "config_path": selected.config_path.as_posix(),
        "case_path": selected.case_path.as_posix(),
        "compile_commands_path": selected.compile_commands_path.as_posix(),
        "ingest": ingest_result.__dict__,
        "repo_status": status.to_dict(),
        "diagnostics": diagnostics.to_dict(),
        "preflight": readiness.to_dict(),
        "mcp_server_command": [
            "python",
            "-m",
            "repoanalyzer.mcp.server",
            "--repo",
            str(plan.root),
        ],
    }


def _select_profile(plan: TinyUsbSmokePlan, profile_id: str) -> TinyUsbSmokeProfile:
    for profile in plan.profiles:
        if profile.id == profile_id:
            return profile
    available = ", ".join(profile.id for profile in plan.profiles)
    raise ValueError(f"unknown TinyUSB upstream profile {profile_id!r}; available profiles: {available}")

def _write_device_cdc_msc(root: Path, out: Path) -> TinyUsbSmokeProfile:
    profile_id = "tinyusb_upstream_device_cdc_msc"
    sources = [
        "examples/device/cdc_msc/src/main.c",
        "examples/device/cdc_msc/src/usb_descriptors.c",
        "examples/device/cdc_msc/src/msc_disk.c",
        "src/tusb.c",
        "src/device/usbd.c",
        "src/common/tusb_fifo.c",
        "src/class/cdc/cdc_device.c",
        "src/class/msc/msc_device.c",
        "src/portable/synopsys/dwc2/dcd_dwc2.c",
        "src/portable/synopsys/dwc2/dwc2_common.c",
        "hw/bsp/stm32f4/family.c",
        "hw/bsp/stm32f4/boards/stm32f407disco/board.c",
    ]
    include_dirs = [
        ".",
        "src",
        "src/common",
        "src/device",
        "src/osal",
        "src/class/cdc",
        "src/class/msc",
        "src/portable/synopsys/dwc2",
        "examples/device/cdc_msc/src",
        "hw",
        "hw/bsp",
        "hw/bsp/stm32f4",
        "hw/bsp/stm32f4/boards/stm32f407disco",
    ]
    macros = [
        "CFG_TUSB_MCU=OPT_MCU_STM32F4",
        "CFG_TUSB_OS=OPT_OS_NONE",
        "CFG_TUSB_DEBUG=0",
        "CFG_TUSB_RHPORT0_MODE=(OPT_MODE_DEVICE | OPT_MODE_FULL_SPEED)",
        "CFG_TUD_ENABLED=1",
        "CFG_TUH_ENABLED=0",
        "CFG_TUC_ENABLED=0",
        "CFG_TUD_CDC=1",
        "CFG_TUD_MSC=1",
        "CFG_TUD_HID=0",
        "BOARD_TUD_RHPORT=0",
        "BOARD_TUD_MAX_SPEED=OPT_MODE_FULL_SPEED",
        "BOARD_STM32F407DISCO=1",
    ]
    config = _target_config(
        profile_name="tinyusb-upstream-device-cdc-msc-stm32f407disco-none",
        compile_commands=f"{out.name}/compile_commands.device_cdc_msc.json",
        include_dirs=include_dirs,
        macros=macros,
        config_headers=["examples/device/cdc_msc/src/tusb_config.h"],
        active_path_prefixes=[
            "examples/device/cdc_msc/src",
            "src/common",
            "src/device",
            "src/osal",
            "src/class/cdc",
            "src/class/msc",
            "src/portable/synopsys/dwc2",
            "hw/bsp/stm32f4",
            "hw/bsp/stm32f4/boards/stm32f407disco",
        ],
        inactive_path_prefixes=["examples/host", "examples/dual", "examples/typec", "src/host", "src/typec", "test"],
        active_port="src/portable/synopsys/dwc2",
        attrs={"board": "stm32f407disco", "rtos": "none", "usb_role": "device", "example": "examples/device/cdc_msc", "upstream_smoke": True},
    )
    cases = _real_repo_case(
        case_id="tinyusb_upstream_device_cdc_msc_smoke",
        description="Real TinyUSB upstream smoke/profile eval for examples/device/cdc_msc.",
        config=f"{out.name}/repoanalyzer.device_cdc_msc.yml",
        min_files=10,
        min_facts=250,
        max_files=140,
        max_facts=25000,
        scenarios=[
            _claim_case("target_profile_name", "target_profile", "name", "tinyusb-upstream-device-cdc-msc-stm32f407disco-none", verdict="supported", reason_code="target_profile_supported"),
            _claim_case("cdc_enabled", "build_config", "CFG_TUD_CDC", "1", verdict="supported", reason_code="build_config_macro_value_supported"),
            _claim_case("msc_enabled", "build_config", "CFG_TUD_MSC", "1", verdict="supported", reason_code="build_config_macro_value_supported"),
            _semantic_case("cdc_descriptor", "usb_descriptor_semantic", "CDC", "desc_fs_configuration", {"class": "CDC", "interface_symbol": "ITF_NUM_CDC", "endpoint_symbol": "EPNUM_CDC_IN"}, verdict="supported"),
            _semantic_case("msc_descriptor", "usb_descriptor_semantic", "MSC", "desc_fs_configuration", {"class": "MSC", "interface_symbol": "ITF_NUM_MSC", "endpoint_symbol": "EPNUM_MSC_OUT"}, verdict="supported"),
            _semantic_case("cdc_driver_open_binding", "tinyusb_driver_dispatch_semantic", "CDC", "cdcd_open", {"predicate": "binds_driver_callback", "callback_field": "open"}, verdict="conditional"),
            _semantic_case("usbd_xfer_submit", "tinyusb_device_runtime_semantic", "usbd_edpt_xfer", "async_transfer_request", {"predicate": "endpoint_transfer_submit"}, verdict="conditional"),
            _semantic_case("cdc_stream_api", "tinyusb_class_protocol_semantic", "tud_cdc_write", "cdc_write", {"predicate": "declares_cdc_stream_api", "class": "CDC", "transfer_direction": "in"}, verdict="conditional"),
            _semantic_case("msc_read10", "tinyusb_class_protocol_semantic", "tud_msc_read10_cb", "READ10", {"predicate": "declares_msc_scsi_callback", "scsi_command": "READ10"}, verdict="supported"),
        ],
    )
    return _write_profile(root, out, profile_id, "device cdc_msc upstream smoke profile", sources, include_dirs, macros, config, cases, "device_cdc_msc")


def _write_host_cdc_msc_hid(root: Path, out: Path) -> TinyUsbSmokeProfile:
    profile_id = "tinyusb_upstream_host_cdc_msc_hid"
    sources = [
        "examples/host/cdc_msc_hid/src/main.c",
        "examples/host/cdc_msc_hid/src/cdc_app.c",
        "examples/host/cdc_msc_hid/src/hid_app.c",
        "examples/host/cdc_msc_hid/src/msc_app.c",
        "src/tusb.c",
        "src/host/usbh.c",
        "src/host/hub.c",
        "src/common/tusb_fifo.c",
        "src/class/cdc/cdc_host.c",
        "src/class/msc/msc_host.c",
        "src/class/hid/hid_host.c",
        "src/portable/synopsys/dwc2/hcd_dwc2.c",
        "src/portable/synopsys/dwc2/dwc2_common.c",
        "hw/bsp/stm32f4/family.c",
        "hw/bsp/stm32f4/boards/stm32f407disco/board.c",
    ]
    include_dirs = [
        ".",
        "src",
        "src/common",
        "src/host",
        "src/osal",
        "src/class/cdc",
        "src/class/msc",
        "src/class/hid",
        "src/portable/synopsys/dwc2",
        "examples/host/cdc_msc_hid/src",
        "hw",
        "hw/bsp",
        "hw/bsp/stm32f4",
        "hw/bsp/stm32f4/boards/stm32f407disco",
    ]
    macros = [
        "CFG_TUSB_MCU=OPT_MCU_STM32F4",
        "CFG_TUSB_OS=OPT_OS_NONE",
        "CFG_TUSB_DEBUG=0",
        "CFG_TUSB_RHPORT0_MODE=(OPT_MODE_HOST | OPT_MODE_FULL_SPEED)",
        "CFG_TUD_ENABLED=0",
        "CFG_TUH_ENABLED=1",
        "CFG_TUC_ENABLED=0",
        "CFG_TUH_CDC=1",
        "CFG_TUH_MSC=1",
        "CFG_TUH_HID=3",
        "CFG_TUH_HUB=1",
        "BOARD_TUH_RHPORT=0",
        "BOARD_TUH_MAX_SPEED=OPT_MODE_FULL_SPEED",
        "BOARD_STM32F407DISCO=1",
    ]
    config = _target_config(
        profile_name="tinyusb-upstream-host-cdc-msc-hid-stm32f407disco-none",
        compile_commands=f"{out.name}/compile_commands.host_cdc_msc_hid.json",
        include_dirs=include_dirs,
        macros=macros,
        config_headers=["examples/host/cdc_msc_hid/src/tusb_config.h"],
        active_path_prefixes=[
            "examples/host/cdc_msc_hid/src",
            "src/common",
            "src/host",
            "src/osal",
            "src/class/cdc",
            "src/class/msc",
            "src/class/hid",
            "src/portable/synopsys/dwc2",
            "hw/bsp/stm32f4",
            "hw/bsp/stm32f4/boards/stm32f407disco",
        ],
        inactive_path_prefixes=["examples/device", "examples/dual", "examples/typec", "src/device", "src/typec", "test"],
        active_port="src/portable/synopsys/dwc2",
        attrs={"board": "stm32f407disco", "rtos": "none", "usb_role": "host", "example": "examples/host/cdc_msc_hid", "upstream_smoke": True},
    )
    cases = _real_repo_case(
        case_id="tinyusb_upstream_host_cdc_msc_hid_smoke",
        description="Real TinyUSB upstream smoke/profile eval for examples/host/cdc_msc_hid.",
        config=f"{out.name}/repoanalyzer.host_cdc_msc_hid.yml",
        min_files=12,
        min_facts=250,
        max_files=160,
        max_facts=30000,
        scenarios=[
            _claim_case("target_profile_name", "target_profile", "name", "tinyusb-upstream-host-cdc-msc-hid-stm32f407disco-none", verdict="supported", reason_code="target_profile_supported"),
            _claim_case("host_enabled", "build_config", "CFG_TUH_ENABLED", "1", verdict="supported", reason_code="build_config_macro_value_supported"),
            _semantic_case("hid_host_open", "tinyusb_host_runtime_semantic", "HID", "hidh_open", {"predicate": "binds_host_driver_callback", "callback_field": "open"}, verdict="supported"),
            _semantic_case("host_enum_set_address", "tinyusb_host_runtime_semantic", "tuh_address_set", "set_address", {"predicate": "host_enumeration_stage", "enumeration_stage": "set_address"}, verdict="supported"),
            _semantic_case("hcd_xfer_boundary", "tinyusb_host_runtime_semantic", "hcd_edpt_xfer", "host_controller_boundary", {"predicate": "hcd_transfer_submit_boundary", "hardware_boundary": True}, verdict="conditional"),
        ],
    )
    return _write_profile(root, out, profile_id, "host cdc_msc_hid upstream smoke profile", sources, include_dirs, macros, config, cases, "host_cdc_msc_hid")


def _write_hid_composite(root: Path, out: Path) -> TinyUsbSmokeProfile:
    profile_id = "tinyusb_upstream_device_hid_composite"
    sources = [
        "examples/device/hid_composite/src/main.c",
        "examples/device/hid_composite/src/usb_descriptors.c",
        "src/tusb.c",
        "src/device/usbd.c",
        "src/common/tusb_fifo.c",
        "src/class/hid/hid_device.c",
        "src/portable/synopsys/dwc2/dcd_dwc2.c",
        "src/portable/synopsys/dwc2/dwc2_common.c",
        "hw/bsp/stm32f4/family.c",
        "hw/bsp/stm32f4/boards/stm32f407disco/board.c",
    ]
    include_dirs = [
        ".",
        "src",
        "src/common",
        "src/device",
        "src/osal",
        "src/class/hid",
        "src/portable/synopsys/dwc2",
        "examples/device/hid_composite/src",
        "hw",
        "hw/bsp",
        "hw/bsp/stm32f4",
        "hw/bsp/stm32f4/boards/stm32f407disco",
    ]
    macros = [
        "CFG_TUSB_MCU=OPT_MCU_STM32F4",
        "CFG_TUSB_OS=OPT_OS_NONE",
        "CFG_TUSB_DEBUG=0",
        "CFG_TUSB_RHPORT0_MODE=(OPT_MODE_DEVICE | OPT_MODE_FULL_SPEED)",
        "CFG_TUD_ENABLED=1",
        "CFG_TUH_ENABLED=0",
        "CFG_TUC_ENABLED=0",
        "CFG_TUD_HID=1",
        "CFG_TUD_CDC=0",
        "CFG_TUD_MSC=0",
        "BOARD_TUD_RHPORT=0",
        "BOARD_TUD_MAX_SPEED=OPT_MODE_FULL_SPEED",
        "BOARD_STM32F407DISCO=1",
    ]
    config = _target_config(
        profile_name="tinyusb-upstream-device-hid-composite-stm32f407disco-none",
        compile_commands=f"{out.name}/compile_commands.device_hid_composite.json",
        include_dirs=include_dirs,
        macros=macros,
        config_headers=["examples/device/hid_composite/src/tusb_config.h"],
        active_path_prefixes=[
            "examples/device/hid_composite/src",
            "src/common",
            "src/device",
            "src/osal",
            "src/class/hid",
            "src/portable/synopsys/dwc2",
            "hw/bsp/stm32f4",
            "hw/bsp/stm32f4/boards/stm32f407disco",
        ],
        inactive_path_prefixes=["examples/host", "examples/dual", "examples/typec", "src/host", "src/typec", "test"],
        active_port="src/portable/synopsys/dwc2",
        attrs={"board": "stm32f407disco", "rtos": "none", "usb_role": "device", "example": "examples/device/hid_composite", "upstream_smoke": True},
    )
    cases = _real_repo_case(
        case_id="tinyusb_upstream_device_hid_composite_smoke",
        description="Real TinyUSB upstream smoke/profile eval for examples/device/hid_composite.",
        config=f"{out.name}/repoanalyzer.device_hid_composite.yml",
        min_files=8,
        min_facts=200,
        max_files=130,
        max_facts=25000,
        scenarios=[
            _claim_case("target_profile_name", "target_profile", "name", "tinyusb-upstream-device-hid-composite-stm32f407disco-none", verdict="supported", reason_code="target_profile_supported"),
            _claim_case("hid_enabled", "build_config", "CFG_TUD_HID", "1", verdict="supported", reason_code="build_config_macro_value_supported"),
            _semantic_case("hid_descriptor", "usb_descriptor_semantic", "HID", "interface", {"class": "HID", "interface_symbol": "ITF_NUM_HID", "endpoint_symbol": "EPNUM_HID"}, verdict="supported"),
            _semantic_case("keyboard_report_descriptor", "tinyusb_class_protocol_semantic", "REPORT_ID_KEYBOARD", "keyboard", {"predicate": "declares_hid_report_descriptor_item", "report_kind": "keyboard"}, verdict="supported"),
            _semantic_case("hid_mouse_report_api", "tinyusb_class_protocol_semantic", "tud_hid_mouse_report", "mouse", {"predicate": "declares_hid_report_api", "report_kind": "mouse"}, verdict="conditional"),
        ],
    )
    return _write_profile(root, out, profile_id, "device hid_composite upstream smoke profile", sources, include_dirs, macros, config, cases, "device_hid_composite")


def _write_typec_power_delivery(root: Path, out: Path) -> TinyUsbSmokeProfile:
    profile_id = "tinyusb_upstream_typec_power_delivery"
    sources = [
        "examples/typec/power_delivery/src/main.c",
        "src/typec/usbc.c",
    ]
    include_dirs = [
        ".",
        "src",
        "src/common",
        "src/osal",
        "src/typec",
        "examples/typec/power_delivery/src",
        "hw",
    ]
    macros = [
        "CFG_TUSB_MCU=OPT_MCU_STM32F4",
        "CFG_TUSB_OS=OPT_OS_NONE",
        "CFG_TUSB_DEBUG=0",
        "CFG_TUC_ENABLED=1",
        "CFG_TUD_ENABLED=0",
        "CFG_TUH_ENABLED=0",
        "BOARD_STM32F407DISCO=1",
    ]
    config = _target_config(
        profile_name="tinyusb-upstream-typec-power-delivery-stm32f407disco-none",
        compile_commands=f"{out.name}/compile_commands.typec_power_delivery.json",
        include_dirs=include_dirs,
        macros=macros,
        config_headers=["examples/typec/power_delivery/src/tusb_config.h"],
        active_path_prefixes=["examples/typec/power_delivery/src", "src/typec", "src/common", "src/osal"],
        inactive_path_prefixes=["examples/device", "examples/host", "examples/dual", "src/device", "src/host", "test"],
        active_port=None,
        attrs={"board": "stm32f407disco", "rtos": "none", "usb_role": "typec", "example": "examples/typec/power_delivery", "upstream_smoke": True},
    )
    cases = _real_repo_case(
        case_id="tinyusb_upstream_typec_power_delivery_smoke",
        description="Real TinyUSB upstream smoke/profile eval for examples/typec/power_delivery.",
        config=f"{out.name}/repoanalyzer.typec_power_delivery.yml",
        min_files=2,
        min_facts=80,
        max_files=80,
        max_facts=15000,
        scenarios=[
            _claim_case("target_profile_name", "target_profile", "name", "tinyusb-upstream-typec-power-delivery-stm32f407disco-none", verdict="supported", reason_code="target_profile_supported"),
            _claim_case("typec_enabled", "build_config", "CFG_TUC_ENABLED", "1", verdict="supported", reason_code="build_config_macro_value_supported"),
            _semantic_case("typec_stack_init", "tinyusb_typec_pd_semantic", "tuc_init", "tcd_init", {"predicate": "typec_stack_init", "tcd_api": "tcd_init"}, verdict="supported"),
            _semantic_case("pd_request", "tinyusb_typec_pd_semantic", "tuc_msg_request", "PD_DATA_REQUEST", {"predicate": "builds_pd_request_message", "pd_message_type": "PD_DATA_REQUEST"}, verdict="supported"),
            _semantic_case("source_cap", "tinyusb_typec_pd_semantic", "tuc_pd_data_received_cb", "PD_DATA_SOURCE_CAP", {"predicate": "handles_pd_data_message", "pd_message_type": "PD_DATA_SOURCE_CAP"}, verdict="supported"),
        ],
    )
    return _write_profile(root, out, profile_id, "typec power_delivery upstream smoke profile", sources, include_dirs, macros, config, cases, "typec_power_delivery")


def _target_config(
    *,
    profile_name: str,
    compile_commands: str,
    include_dirs: list[str],
    macros: list[str],
    config_headers: list[str],
    active_path_prefixes: list[str],
    inactive_path_prefixes: list[str],
    active_port: str | None,
    attrs: dict[str, Any],
) -> dict[str, Any]:
    profile = {
        "name": profile_name,
        "compile_commands": compile_commands,
        **attrs,
        "include_dirs": include_dirs,
        "macros": macros,
        "config_headers": config_headers,
        "active_path_prefixes": active_path_prefixes,
        "inactive_path_prefixes": inactive_path_prefixes,
    }
    if active_port:
        profile["active_port"] = active_port
    return {
        "index": {
            "exclude_patterns": [
                ".git/**",
                ".github/**",
                ".repoanalyzer-index/**",
                ".repoanalyzer-smoke/**",
                "docs/**",
                "lib/**",
                "tools/**",
                "test/**",
            ]
        },
        "cpp": {"target_profile": profile},
    }


def _write_profile(
    root: Path,
    out: Path,
    profile_id: str,
    description: str,
    sources: list[str],
    include_dirs: list[str],
    macros: list[str],
    config: dict[str, Any],
    cases: dict[str, Any],
    stem: str,
) -> TinyUsbSmokeProfile:
    compile_path = out / f"compile_commands.{stem}.json"
    config_path = out / f"repoanalyzer.{stem}.yml"
    case_path = out / f"cases.{stem}.yaml"

    existing_sources = [source for source in sources if (root / source).exists()]
    entries = [_compile_command_entry(root, source, include_dirs, macros) for source in existing_sources]
    compile_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    case_path.write_text(yaml.safe_dump(cases, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return TinyUsbSmokeProfile(
        id=profile_id,
        description=description,
        config_path=config_path.relative_to(root),
        case_path=case_path.relative_to(root),
        compile_commands_path=compile_path.relative_to(root),
        expected_sources=existing_sources,
    )


def _compile_command_entry(root: Path, source: str, include_dirs: list[str], macros: list[str]) -> dict[str, str]:
    command = "cc -std=c11 " + " ".join(f"-I{value}" for value in include_dirs) + " " + " ".join(f"-D{value}" for value in macros) + f" -c {source}"
    return {"directory": str(root), "command": command, "file": source}


def _real_repo_case(
    *,
    case_id: str,
    description: str,
    config: str,
    min_files: int,
    min_facts: int,
    max_files: int,
    max_facts: int,
    scenarios: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": case_id,
        "description": description,
        "ingest": {"enabled": True, "config": config},
        "budgets": {"max_total_ms": 90000, "max_facts": max_facts, "max_indexed_files": max_files},
        "expect": {
            "ingest": {"status": "indexed", "min_files": min_files, "min_facts": min_facts},
            "repo_status": {"clean": True},
            "diagnostics": {"min_total_facts": min_facts, "min_indexed_files": min_files},
        },
        "scenarios": scenarios,
    }


def _claim_case(id: str, claim_type: str, subject: str, object_: str, *, verdict: str, reason_code: str | None = None) -> dict[str, Any]:
    expect = {"verdict": verdict}
    if reason_code:
        expect["reason_code"] = reason_code
    return {"id": id, "kind": "verify_claim", "claim": {"claim_type": claim_type, "subject": subject, "object": str(object_)}, "expect": expect}


def _semantic_case(id: str, claim_type: str, subject: str, object_: str, payload: dict[str, Any], *, verdict: str) -> dict[str, Any]:
    return {"id": id, "kind": "verify_claim", "claim": {"claim_type": claim_type, "subject": subject, "object": object_, "payload": payload}, "expect": {"verdict": verdict}}
