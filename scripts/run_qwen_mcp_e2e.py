from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from repoanalyzer.e2e.config import (
    default_qwen_settings_path,
    load_llm_connections,
    write_safe_json,
)
from repoanalyzer.e2e.runner import run_qwen_mcp_e2e


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local Qwen-to-repoanalyzer MCP tool loop")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--qwen-settings", type=Path, default=default_qwen_settings_path())
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    connections = load_llm_connections(args.qwen_settings)
    secrets = tuple(secret for connection in connections for secret in connection.secret_values())
    result = asyncio.run(
        run_qwen_mcp_e2e(
            args.repo,
            args.question,
            model_id=args.model,
            settings_path=args.qwen_settings,
            max_turns=args.max_turns,
            max_tokens=args.max_tokens,
        )
    )
    write_safe_json(args.output, result, secrets=secrets)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "model_id": result["model_id"],
                "tool_call_count": result["tool_call_count"],
                "tool_error_count": result["tool_error_count"],
                "elapsed_ms": result["elapsed_ms"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
