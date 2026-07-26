from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.e2e.config import (
    default_qwen_settings_path,
    load_llm_connections,
    write_safe_json,
)
from repoanalyzer.e2e.external import ensure_external_checkout, load_external_scenario
from repoanalyzer.e2e.runner import run_qwen_mcp_e2e, validate_answer
from repoanalyzer.store.status import repo_index_status


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the pinned external-repository Qwen+MCP smoke scenario")
    parser.add_argument(
        "--scenario",
        type=Path,
        default=REPO_ROOT / "eval" / "preparation" / "inih_smoke.json",
    )
    parser.add_argument("--work-root", type=Path, default=REPO_ROOT / ".e2e-work")
    parser.add_argument("--qwen-settings", type=Path, default=default_qwen_settings_path())
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "eval" / "preparation" / "results" / "inih_smoke_result.json",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    started = time.perf_counter()
    scenario = load_external_scenario(args.scenario)
    checkout = ensure_external_checkout(scenario, args.work_root)
    ingest = ingest_repo(checkout, reset=True)
    status = repo_index_status(checkout)
    e2e = asyncio.run(
        run_qwen_mcp_e2e(
            checkout,
            scenario.question,
            model_id=scenario.model_id,
            settings_path=args.qwen_settings,
            repo_placeholder="<external_repo>",
        )
    )
    validation = validate_answer(
        e2e,
        required_answer_strings=scenario.required_answer_strings,
        required_tools=scenario.required_tools,
        source_root=checkout,
        source_anchors=scenario.source_anchors,
    )
    result: dict[str, Any] = {
        "schema_version": "repoanalyzer_external_smoke.v1",
        "ok": ingest.status == "indexed" and status.clean and validation["ok"],
        "scenario_id": scenario.scenario_id,
        "repository": {
            "url": scenario.repository_url,
            "commit_sha": scenario.commit_sha,
            "license": scenario.license_name,
        },
        "ingest": {
            "status": ingest.status,
            "mode": ingest.mode,
            "files": ingest.files,
            "facts": ingest.facts,
        },
        "index_status": {
            "status": status.status,
            "clean": status.clean,
            "indexed_files": status.indexed_files,
            "current_files": status.current_files,
        },
        "e2e": e2e,
        "validation": validation,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "phase": "preparation",
        "completion_claimed": False,
    }
    connections = load_llm_connections(args.qwen_settings)
    secrets = tuple(secret for connection in connections for secret in connection.secret_values())
    write_safe_json(args.output, result, secrets=secrets)
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "scenario_id": scenario.scenario_id,
                "commit_sha": scenario.commit_sha,
                "model_id": scenario.model_id,
                "ingest_status": ingest.status,
                "index_clean": status.clean,
                "tool_call_count": e2e["tool_call_count"],
                "validation_ok": validation["ok"],
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
