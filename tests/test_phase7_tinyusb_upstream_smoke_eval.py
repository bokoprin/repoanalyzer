from __future__ import annotations

import os
from pathlib import Path

import pytest

from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.real_repo_eval.tinyusb_upstream import prepare_tinyusb_upstream_smoke


def test_phase7_tinyusb_upstream_smoke_prepare_generates_profile_files(tmp_path: Path) -> None:
    repo = tmp_path / "tinyusb"
    repo.mkdir()

    plan = prepare_tinyusb_upstream_smoke(repo)

    assert plan.output_dir == repo / ".repoanalyzer-smoke"
    assert [profile.id for profile in plan.profiles] == [
        "tinyusb_upstream_device_cdc_msc",
        "tinyusb_upstream_host_cdc_msc_hid",
        "tinyusb_upstream_device_hid_composite",
        "tinyusb_upstream_typec_power_delivery",
    ]
    for profile in plan.profiles:
        assert (repo / profile.config_path).exists()
        assert (repo / profile.case_path).exists()
        assert (repo / profile.compile_commands_path).exists()


@pytest.mark.upstream
@pytest.mark.skipif(
    not os.environ.get("REPOANALYZER_TINYUSB_UPSTREAM"),
    reason="set REPOANALYZER_TINYUSB_UPSTREAM to a TinyUSB checkout to run upstream smoke eval",
)
def test_phase7_tinyusb_upstream_device_cdc_msc_smoke_eval_passes() -> None:
    repo = Path(os.environ["REPOANALYZER_TINYUSB_UPSTREAM"]).expanduser().resolve()
    plan = prepare_tinyusb_upstream_smoke(repo)
    profile = next(item for item in plan.profiles if item.id == "tinyusb_upstream_device_cdc_msc")

    report = run_real_repo_eval(repo, repo / profile.case_path)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["case_id"] == "tinyusb_upstream_device_cdc_msc_smoke"
    assert payload["metrics"]["scenario_count"] == 9
    assert payload["metrics"]["passed_scenarios"] == 9
    assert payload["metrics"]["failed_scenarios"] == 0
