from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from repoanalyzer.e2e.config import write_safe_json
from repoanalyzer.e2e.runner import normalize_repository_paths, run_mcp_process_smoke


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise repoanalyzer through a real stdio MCP child process")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--symbol", default="init_device")
    parser.add_argument("--caller-symbol", default="start_device")
    parser.add_argument("--source-path", default="src/device.cpp")
    parser.add_argument("--source-start", type=int, default=1)
    parser.add_argument("--source-end", type=int, default=12)
    parser.add_argument("--question", default="init_device はどこから呼ばれる？")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = asyncio.run(
        run_mcp_process_smoke(
            args.repo,
            symbol=args.symbol,
            caller_symbol=args.caller_symbol,
            source_path=args.source_path,
            source_start=args.source_start,
            source_end=args.source_end,
            evidence_question=args.question,
        )
    )
    result = normalize_repository_paths(result, args.repo)
    if args.output:
        write_safe_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
