from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.mcp.tools import server_info, tool_find_callers, tool_collect_evidence, tool_extract_claims, tool_verify_text

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "basic_call"


def test_mcp_tool_functions_without_mcp_runtime() -> None:
    ingest_repo(FIXTURE, reset=True)
    info = server_info(str(FIXTURE))
    assert info["index_ready"] is True
    callers = tool_find_callers(str(FIXTURE), "init_device")
    assert callers[0]["caller"] == "start_device"
    bundle = tool_collect_evidence(str(FIXTURE), "init_device はどこから呼ばれる？", "callers")
    assert bundle["answerability"] == "answerable"

    extracted = tool_extract_claims("start_device calls init_device")
    assert extracted["claims"][0]["claim_type"] == "calls"

    verified = tool_verify_text(str(FIXTURE), "start_device calls init_device")
    assert verified["overall_verdict"] == "supported"
