from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.e2e.config import (
    E2EConfigurationError,
    assert_secrets_absent,
    load_qwen_connections,
    redact_sensitive,
    write_safe_json,
)
from repoanalyzer.e2e.llm import HTTPResult
from repoanalyzer.e2e.mcp_process import MCPCallRecord
from repoanalyzer.e2e.runner import (
    execute_tool_loop,
    normalize_repository_paths,
    run_mcp_process_smoke,
    validate_answer,
)


FIXTURE = Path(__file__).parent / "fixtures_cpp" / "basic_call"


def test_qwen_settings_loader_keeps_connection_values_out_of_repr(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "env": {"LOCAL_KEY": "top-secret-value"},
                "modelProviders": {
                    "openai": [
                        {
                            "id": "local",
                            "baseUrl": "http://127.0.0.1:9999/v1",
                            "envKey": "LOCAL_KEY",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    connections = load_qwen_connections(settings)

    assert len(connections) == 1
    assert connections[0].endpoint("models").endswith("/v1/models")
    assert "127.0.0.1" not in repr(connections[0])
    assert "top-secret-value" not in repr(connections[0])


def test_qwen_settings_loader_rejects_credentials_embedded_in_url(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "modelProviders": {
                    "openai": [
                        {
                            "baseUrl": "http://user:password@127.0.0.1:9999/v1",
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(E2EConfigurationError, match="embedded"):
        load_qwen_connections(settings)


def test_safe_json_redacts_nested_secrets_before_writing(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    secret = "do-not-write"
    payload = {
        "authorization": secret,
        "message": f"prefix {secret} suffix",
        "nested": [{"api_key": secret}],
    }

    write_safe_json(output, payload, secrets=(secret,))
    text = output.read_text(encoding="utf-8")

    assert secret not in text
    assert text.count("<redacted>") == 3
    assert_secrets_absent(text, (secret,))


def test_redactor_preserves_non_secret_tool_payload() -> None:
    payload = {
        "name": "find_definitions",
        "arguments": {"symbol": "ini_parse"},
        "path": "ini.c",
        "url": "https://github.com/benhoyt/inih.git",
    }

    assert redact_sensitive(payload) == payload


def test_repository_paths_are_normalized_before_secret_redaction(tmp_path: Path) -> None:
    repo = tmp_path / "checkout"
    payload = {
        "repo": str(repo),
        "db_path": str(repo / ".repoanalyzer-index" / "index.sqlite3"),
    }

    normalized = normalize_repository_paths(
        payload,
        repo,
        replacement="<external_repo>",
    )

    assert normalized == {
        "repo": "<external_repo>",
        "db_path": "<external_repo>\\.repoanalyzer-index\\index.sqlite3",
    }


class _FakeClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)

    def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> HTTPResult:
        del model_id, messages, tools, max_tokens
        return HTTPResult(status=200, elapsed_ms=5, payload=self.responses.pop(0))


class _FakeToolSession:
    tools: list[Any] = []

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "find_definitions",
                    "description": "",
                    "parameters": {"type": "object"},
                },
            }
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallRecord:
        return MCPCallRecord(
            name=name,
            arguments=arguments,
            response={
                "is_error": False,
                "content": [{"path": "ini.c", "symbol": arguments["symbol"]}],
            },
            elapsed_ms=2,
        )


def _tool_response(arguments: str = '{"symbol":"ini_parse"}') -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "find_definitions",
                                "arguments": arguments,
                            },
                        }
                    ],
                },
            }
        ],
    }


def _answer_response(text: str) -> dict[str, Any]:
    return {
        "model": "test-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
    }


def test_tool_loop_records_mcp_call_and_final_answer() -> None:
    client = _FakeClient([_tool_response(), _answer_response("ini_parse is in ini.c")])

    result = asyncio.run(
        execute_tool_loop(
            client,
            _FakeToolSession(),
            model_id="test-model",
            question="Where is ini_parse?",
        )
    )

    assert result["ok"] is True
    assert result["tool_call_count"] == 1
    assert result["tool_history"][0]["name"] == "find_definitions"
    assert result["final_answer"] == "ini_parse is in ini.c"


def test_tool_loop_rejects_answer_without_mcp_use() -> None:
    client = _FakeClient([_answer_response("I already know the answer")])

    result = asyncio.run(
        execute_tool_loop(
            client,
            _FakeToolSession(),
            model_id="test-model",
            question="Where is ini_parse?",
        )
    )

    assert result["ok"] is False
    assert result["failure"] == "model_did_not_call_mcp_tools"
    assert result["tool_call_count"] == 0


def test_tool_loop_records_invalid_tool_arguments_as_error() -> None:
    client = _FakeClient([_tool_response("not-json"), _answer_response("unknown")])

    result = asyncio.run(
        execute_tool_loop(
            client,
            _FakeToolSession(),
            model_id="test-model",
            question="Where is ini_parse?",
        )
    )

    assert result["ok"] is False
    assert result["tool_error_count"] == 1
    assert result["tool_history"][0]["response"]["content"]["error"] == "tool_arguments_are_not_valid_json"


def test_tool_loop_stops_at_maximum_turn_boundary() -> None:
    client = _FakeClient([_tool_response()])

    result = asyncio.run(
        execute_tool_loop(
            client,
            _FakeToolSession(),
            model_id="test-model",
            question="Where is ini_parse?",
            max_turns=1,
        )
    )

    assert result["ok"] is False
    assert result["failure"] == "maximum_tool_turns_exceeded"


def test_validate_answer_requires_tools_source_and_tool_evidence(tmp_path: Path) -> None:
    source = tmp_path / "ini.c"
    source.write_text("int ini_parse(void) { return ini_parse_file(); }\n", encoding="utf-8")
    result = {
        "ok": True,
        "final_answer": "ini_parse is defined in ini.c and calls ini_parse_file.",
        "tool_history": [
            {
                "name": "find_definitions",
                "response": {
                    "is_error": False,
                    "content": {"path": "ini.c", "symbol": "ini_parse", "callee": "ini_parse_file"},
                },
            }
        ],
    }

    validation = validate_answer(
        result,
        required_answer_strings=["ini.c", "ini_parse", "ini_parse_file"],
        required_tools=["find_definitions"],
        source_root=tmp_path,
        source_anchors=[{"path": "ini.c", "contains": "return ini_parse_file();"}],
    )

    assert validation["ok"] is True


def test_mcp_smoke_uses_real_stdio_child_process(tmp_path: Path) -> None:
    repo = tmp_path / "basic_call"
    shutil.copytree(FIXTURE, repo, ignore=shutil.ignore_patterns(".repoanalyzer-index"))
    ingest_repo(repo, reset=True)

    result = asyncio.run(
        run_mcp_process_smoke(
            repo,
            symbol="init_device",
            caller_symbol="start_device",
            source_path="src/device.cpp",
            source_start=1,
            source_end=12,
            evidence_question="init_device はどこから呼ばれる？",
        )
    )

    assert result["ok"] is True
    assert result["transport"] == "stdio"
    assert result["tool_count"] >= 24
    assert [call["name"] for call in result["calls"]] == [
        "server_info",
        "repo_status",
        "find_definitions",
        "find_references",
        "find_callers",
        "find_callees",
        "read_file_range",
        "collect_evidence",
    ]
    evidence = result["calls"][-1]["response"]["content"]
    assert evidence["answerability"] == "answerable"
