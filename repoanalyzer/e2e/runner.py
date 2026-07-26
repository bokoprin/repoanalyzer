from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from .config import load_llm_connections, redact_sensitive
from .llm import HTTPResult, OpenAICompatibleClient, select_model_connection
from .mcp_process import MCPCallRecord, open_mcp_process


class ChatClient(Protocol):
    def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> HTTPResult: ...


class ToolSession(Protocol):
    tools: list[Any]

    def openai_tools(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallRecord: ...


SYSTEM_PROMPT = """\
You are running a source-grounded C/C++ repository evaluation.
You must use the available repoanalyzer MCP tools before answering.
Start by checking repo_status. Use symbol/call tools and read_file_range as needed.
Base every factual claim on tool output. If evidence is incomplete, say what is unknown.
Return a concise answer with exact symbol names, repository-relative file paths, and line numbers.
"""


async def run_qwen_mcp_e2e(
    repo: Path,
    question: str,
    *,
    model_id: str,
    settings_path: Path | None = None,
    max_turns: int = 8,
    max_tokens: int = 2048,
    repo_placeholder: str = "<repo>",
) -> dict[str, Any]:
    connections = load_llm_connections(settings_path)
    selection = select_model_connection(connections, model_id)
    client = OpenAICompatibleClient(selection.connection)
    started = time.perf_counter()
    async with open_mcp_process(repo) as mcp:
        result = await execute_tool_loop(
            client,
            mcp,
            model_id=model_id,
            question=question,
            max_turns=max_turns,
            max_tokens=max_tokens,
        )
        result["mcp_initialize"] = {
            "protocol_version": mcp.initialize_result.get("protocolVersion"),
            "server_name": (mcp.initialize_result.get("serverInfo") or {}).get("name"),
            "tool_count": len(mcp.tools),
        }
        result["available_tools"] = [tool.name for tool in mcp.tools]
    result["models_check"] = {
        "http_status": selection.models_http_status,
        "elapsed_ms": selection.models_elapsed_ms,
        "models_count": selection.models_count,
        "exact_match": True,
    }
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    result["model_id"] = model_id
    result["connection_source"] = selection.connection.source
    normalized = normalize_repository_paths(result, repo, replacement=repo_placeholder)
    return redact_sensitive(normalized, secrets=selection.connection.secret_values())


def normalize_repository_paths(
    value: Any,
    repo: Path,
    *,
    replacement: str = "<repo>",
) -> Any:
    needle = str(repo.expanduser().resolve())
    if isinstance(value, dict):
        return {
            key: normalize_repository_paths(item, repo, replacement=replacement)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_repository_paths(item, repo, replacement=replacement)
            for item in value
        ]
    if isinstance(value, str):
        return value.replace(needle, replacement).replace(
            needle.replace("\\", "/"),
            replacement,
        )
    return value


async def execute_tool_loop(
    client: ChatClient,
    mcp: ToolSession,
    *,
    model_id: str,
    question: str,
    max_turns: int = 8,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_history: list[dict[str, Any]] = []
    llm_history: list[dict[str, Any]] = []
    final_answer = ""
    failure: str | None = None
    tools = mcp.openai_tools()

    for turn in range(1, max_turns + 1):
        response = client.chat_completion(
            model_id=model_id,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        choice = _first_choice(response.payload)
        message = choice.get("message")
        if not isinstance(message, dict):
            failure = "invalid_assistant_message"
            break
        finish_reason = choice.get("finish_reason")
        raw_calls = message.get("tool_calls")
        tool_calls = raw_calls if isinstance(raw_calls, list) else []
        llm_history.append(
            {
                "turn": turn,
                "http_status": response.status,
                "elapsed_ms": response.elapsed_ms,
                "model_id": response.payload.get("model"),
                "finish_reason": finish_reason,
                "tool_call_count": len(tool_calls),
            }
        )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        if not tool_calls:
            content = message.get("content")
            final_answer = content if isinstance(content, str) else ""
            if not tool_history:
                failure = "model_did_not_call_mcp_tools"
            elif not final_answer.strip():
                failure = "model_returned_empty_final_answer"
            break

        for call in tool_calls:
            record, tool_message = await _execute_tool_call(mcp, call, turn)
            tool_history.append(record)
            messages.append(tool_message)
    else:
        failure = "maximum_tool_turns_exceeded"

    tool_errors = [item for item in tool_history if item["response"].get("is_error")]
    return {
        "schema_version": "repoanalyzer_qwen_mcp_e2e.v1",
        "ok": failure is None and not tool_errors,
        "question": question,
        "final_answer": final_answer,
        "failure": failure,
        "llm_history": llm_history,
        "tool_history": tool_history,
        "tool_call_count": len(tool_history),
        "tool_error_count": len(tool_errors),
    }


async def _execute_tool_call(
    mcp: ToolSession,
    call: Any,
    turn: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    call_id = ""
    name = ""
    arguments: dict[str, Any] = {}
    parse_error: str | None = None
    if isinstance(call, dict):
        call_id = str(call.get("id") or "")
        function = call.get("function")
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            raw_arguments = function.get("arguments")
            try:
                decoded = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                if isinstance(decoded, dict):
                    arguments = decoded
                else:
                    parse_error = "tool_arguments_must_be_an_object"
            except json.JSONDecodeError:
                parse_error = "tool_arguments_are_not_valid_json"
        else:
            parse_error = "tool_call_function_is_missing"
    else:
        parse_error = "tool_call_is_not_an_object"

    if parse_error:
        response = {"is_error": True, "content": {"error": parse_error}}
        elapsed_ms = 0
    else:
        try:
            result = await mcp.call_tool(name, arguments)
            response = result.response
            elapsed_ms = result.elapsed_ms
        except Exception as exc:
            response = {
                "is_error": True,
                "content": {"error_type": type(exc).__name__},
            }
            elapsed_ms = 0

    record = {
        "turn": turn,
        "tool_call_id": call_id,
        "name": name,
        "arguments": arguments,
        "response": response,
        "elapsed_ms": elapsed_ms,
    }
    tool_message = {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(response, ensure_ascii=False, separators=(",", ":")),
    }
    return record, tool_message


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return {}
    return choices[0]


async def run_mcp_process_smoke(
    repo: Path,
    *,
    symbol: str,
    caller_symbol: str,
    source_path: str,
    source_start: int,
    source_end: int,
    evidence_question: str,
) -> dict[str, Any]:
    calls: list[tuple[str, dict[str, Any]]] = [
        ("server_info", {}),
        ("repo_status", {}),
        ("find_definitions", {"symbol": symbol}),
        ("find_references", {"symbol": symbol}),
        ("find_callers", {"symbol": symbol}),
        ("find_callees", {"symbol": caller_symbol}),
        (
            "read_file_range",
            {"path": source_path, "start_line": source_start, "end_line": source_end},
        ),
        ("collect_evidence", {"question": evidence_question, "mode": "callers"}),
    ]
    started = time.perf_counter()
    async with open_mcp_process(repo) as mcp:
        available = {tool.name for tool in mcp.tools}
        records: list[dict[str, Any]] = []
        for name, arguments in calls:
            if name not in available:
                records.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "response": {"is_error": True, "content": {"error": "tool_missing"}},
                        "elapsed_ms": 0,
                    }
                )
                continue
            result = await mcp.call_tool(name, arguments)
            records.append(
                {
                    "name": result.name,
                    "arguments": result.arguments,
                    "response": result.response,
                    "elapsed_ms": result.elapsed_ms,
                }
            )
        failures = [record["name"] for record in records if record["response"].get("is_error")]
        return {
            "schema_version": "repoanalyzer_mcp_process_smoke.v1",
            "ok": not failures,
            "transport": "stdio",
            "initialize": {
                "protocol_version": mcp.initialize_result.get("protocolVersion"),
                "server_name": (mcp.initialize_result.get("serverInfo") or {}).get("name"),
            },
            "tool_count": len(mcp.tools),
            "available_tools": sorted(available),
            "calls": records,
            "failed_tools": failures,
            "elapsed_ms": round((time.perf_counter() - started) * 1000),
        }


def validate_answer(
    result: dict[str, Any],
    *,
    required_answer_strings: list[str],
    required_tools: list[str],
    source_root: Path,
    source_anchors: list[dict[str, str]],
) -> dict[str, Any]:
    answer = str(result.get("final_answer") or "")
    called = [str(item.get("name") or "") for item in result.get("tool_history") or []]
    missing_answer = [item for item in required_answer_strings if item not in answer]
    missing_tools = [item for item in required_tools if item not in called]
    source_checks: list[dict[str, Any]] = []
    for anchor in source_anchors:
        relative_path = anchor["path"]
        expected = anchor["contains"]
        candidate = (source_root / relative_path).resolve()
        try:
            candidate.relative_to(source_root.resolve())
            text = candidate.read_text(encoding="utf-8")
            matched = expected in text
        except (OSError, UnicodeError, ValueError):
            matched = False
        source_checks.append(
            {
                "path": relative_path,
                "anchor": expected,
                "matched": matched,
            }
        )
    evidence_text = json.dumps(result.get("tool_history") or [], ensure_ascii=False)
    evidence_matches = [item for item in required_answer_strings if item in evidence_text]
    source_ok = all(item["matched"] for item in source_checks)
    return {
        "ok": (
            bool(result.get("ok"))
            and not missing_answer
            and not missing_tools
            and source_ok
            and len(evidence_matches) == len(required_answer_strings)
        ),
        "missing_answer_strings": missing_answer,
        "missing_tools": missing_tools,
        "evidence_strings_found": evidence_matches,
        "source_checks": source_checks,
    }
