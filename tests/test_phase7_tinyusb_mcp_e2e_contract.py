from __future__ import annotations

import shutil
from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.mcp import tools
from repoanalyzer.real_repo_eval.tinyusb_upstream import index_tinyusb_upstream


FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_tinyusb_cdc_msc_probe"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "tinyusb_cdc_msc"
    shutil.copytree(FIXTURE, repo)
    ingest_repo(repo, config_path=repo / "repoanalyzer.yml")
    return repo


def test_tinyusb_mcp_e2e_descriptor_question_returns_readable_source(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)

    info = tools.server_info(str(repo))
    assert info["index_ready"] is True
    preflight = tools.tool_preflight(str(repo))
    assert preflight["index_ready"] is True
    assert not preflight["required_actions"]

    bundle = tools.tool_collect_evidence(
        str(repo),
        "TinyUSBのCDC/MSC configuration descriptorはどこで定義されている？",
        None,
    )
    assert bundle["interpreted_intent"] == "tinyusb_descriptor_trace"
    assert bundle["facts"]
    descriptor_facts = [fact for fact in bundle["facts"] if fact["fact_type"] == "usb_descriptor"]
    assert descriptor_facts

    fact = descriptor_facts[0]
    snippet = tools.tool_read_file_range(str(repo), fact["path"], fact["start_line"], fact["end_line"])
    assert snippet["path"] == fact["path"]
    assert snippet["text"].strip()


def test_tinyusb_mcp_e2e_event_and_dispatch_questions_have_evidence(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)

    event_bundle = tools.tool_collect_evidence(
        str(repo),
        "dcd_event_handler から tud_task まではどうつながる？",
        None,
    )
    assert event_bundle["interpreted_intent"] == "tinyusb_device_event_queue_trace"
    assert any(fact["fact_type"] == "tinyusb_device_runtime" for fact in event_bundle["facts"])

    dispatch_bundle = tools.tool_collect_evidence(
        str(repo),
        "endpoint transfer完了時にclass driverのxfer_cbへdispatchされる流れは？",
        None,
    )
    assert dispatch_bundle["interpreted_intent"] == "tinyusb_endpoint_xfer_dispatch_trace"
    assert any(fact["fact_type"] == "tinyusb_driver_dispatch" for fact in dispatch_bundle["facts"])


def test_tinyusb_upstream_index_builds_mcp_ready_index(tmp_path: Path) -> None:
    repo = tmp_path / "tinyusb"
    (repo / "examples/device/cdc_msc/src").mkdir(parents=True)
    (repo / "examples/device/cdc_msc/src/main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")

    result = index_tinyusb_upstream(repo, profile="tinyusb_upstream_device_cdc_msc")

    assert result["schema_version"] == "tinyusb_upstream_index_report.v1"
    assert result["profile"]["id"] == "tinyusb_upstream_device_cdc_msc"
    assert result["ingest"]["status"] == "indexed"
    assert result["preflight"]["index_ready"] is True
    assert not result["preflight"]["required_actions"]
    assert result["mcp_server_command"][-2:] == ["--repo", str(repo.resolve())]
    assert (repo / ".repoanalyzer-index" / "index.sqlite3").exists()
