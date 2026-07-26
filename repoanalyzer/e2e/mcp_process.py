from __future__ import annotations

import json
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, AsyncIterator, TextIO, cast

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, Tool


@dataclass(frozen=True)
class MCPCallRecord:
    name: str
    arguments: dict[str, Any]
    response: dict[str, Any]
    elapsed_ms: int

    @property
    def is_error(self) -> bool:
        return bool(self.response.get("is_error"))


class MCPProcessSession:
    def __init__(
        self,
        session: ClientSession,
        *,
        initialize_result: dict[str, Any],
        tools: list[Tool],
    ) -> None:
        self._session = session
        self.initialize_result = initialize_result
        self.tools = tools

    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in self.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallRecord:
        started = time.perf_counter()
        result = await self._session.call_tool(
            name,
            arguments,
            read_timeout_seconds=timedelta(seconds=60),
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return MCPCallRecord(
            name=name,
            arguments=arguments,
            response=serialize_call_result(result),
            elapsed_ms=elapsed_ms,
        )


@asynccontextmanager
async def open_mcp_process(
    repo: Path,
    *,
    python_executable: Path | None = None,
    project_root: Path | None = None,
) -> AsyncIterator[MCPProcessSession]:
    executable = python_executable or Path(sys.executable)
    cwd = project_root or Path(__file__).resolve().parents[2]
    params = StdioServerParameters(
        command=str(executable),
        args=["-m", "repoanalyzer.mcp.server", "--repo", str(repo.resolve())],
        cwd=cwd,
        encoding="utf-8",
        encoding_error_handler="replace",
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with stdio_client(params, errlog=cast(TextIO, stderr)) as streams:
            async with ClientSession(*streams) as session:
                initialized = await session.initialize()
                listed = await session.list_tools()
                payload = initialized.model_dump(mode="json", exclude_none=True)
                yield MCPProcessSession(
                    session,
                    initialize_result=payload,
                    tools=list(listed.tools),
                )


def serialize_call_result(result: CallToolResult) -> dict[str, Any]:
    structured = result.structuredContent
    content: Any
    if structured is not None:
        content = structured
    else:
        blocks = [block.model_dump(mode="json", exclude_none=True) for block in result.content]
        content = _decode_single_text_block(blocks)
    return {
        "is_error": bool(result.isError),
        "content": content,
    }


def _decode_single_text_block(blocks: list[dict[str, Any]]) -> Any:
    if len(blocks) != 1 or blocks[0].get("type") != "text":
        return blocks
    text = blocks[0].get("text")
    if not isinstance(text, str):
        return blocks
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text
