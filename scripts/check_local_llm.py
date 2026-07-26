from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from repoanalyzer.e2e.config import (
    default_qwen_settings_path,
    load_llm_connections,
    redact_sensitive,
    write_safe_json,
)
from repoanalyzer.e2e.llm import ModelNotFoundError, OpenAICompatibleClient, select_model_connection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check a local OpenAI-compatible LLM without exposing connection values")
    parser.add_argument("--model", required=True)
    parser.add_argument("--qwen-settings", type=Path, default=default_qwen_settings_path())
    parser.add_argument("--output", type=Path)
    return parser


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any], tuple[str, ...]]:
    connections = load_llm_connections(args.qwen_settings)
    secrets = tuple(secret for connection in connections for secret in connection.secret_values())
    try:
        selection = select_model_connection(connections, args.model)
    except ModelNotFoundError as exc:
        return (
            3,
            {
                "schema_version": "repoanalyzer_llm_connectivity.v1",
                "ok": False,
                "model_id": args.model,
                "failure": "exact_model_not_found",
                "available_models": exc.available_models,
            },
            secrets,
        )
    client = OpenAICompatibleClient(selection.connection)
    response = client.chat_completion(
        model_id=args.model,
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=64,
    )
    choice = _first_choice(response.payload)
    result = {
        "schema_version": "repoanalyzer_llm_connectivity.v1",
        "ok": response.status == 200,
        "model_id": args.model,
        "models": {
            "http_status": selection.models_http_status,
            "elapsed_ms": selection.models_elapsed_ms,
            "count": selection.models_count,
            "exact_match": True,
        },
        "chat": {
            "http_status": response.status,
            "elapsed_ms": response.elapsed_ms,
            "model_id": response.payload.get("model"),
            "finish_reason": choice.get("finish_reason"),
        },
        "connection_source": selection.connection.source,
    }
    return 0, result, secrets


def _first_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        return choices[0]
    return {}


def main() -> int:
    args = build_parser().parse_args()
    code, result, secrets = run(args)
    safe_result = redact_sensitive(result, secrets=secrets)
    if args.output:
        write_safe_json(args.output, safe_result, secrets=secrets)
    print(json.dumps(safe_result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
