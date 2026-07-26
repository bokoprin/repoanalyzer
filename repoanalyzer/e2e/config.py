from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class E2EConfigurationError(RuntimeError):
    """Raised for invalid local-LLM configuration without exposing values."""


@dataclass(frozen=True)
class LLMConnection:
    base_url: str = field(repr=False)
    api_key: str | None = field(default=None, repr=False)
    source: str = "qwen_settings"

    def endpoint(self, path: str) -> str:
        root = self.base_url.rstrip("/")
        suffix = path if path.startswith("/") else f"/{path}"
        if root.endswith("/v1"):
            return f"{root}{suffix}"
        return f"{root}/v1{suffix}"

    def secret_values(self) -> tuple[str, ...]:
        values = [self.base_url]
        if self.api_key:
            values.append(self.api_key)
        return tuple(value for value in values if value)


def default_qwen_settings_path() -> Path:
    return Path.home() / ".qwen" / "settings.json"


def load_llm_connections(settings_path: Path | None = None) -> list[LLMConnection]:
    env_url = os.environ.get("REPOANALYZER_LLM_BASE_URL")
    if env_url:
        return [
            _validated_connection(
                env_url,
                os.environ.get("REPOANALYZER_LLM_API_KEY"),
                source="environment",
            )
        ]
    return load_qwen_connections(settings_path or default_qwen_settings_path())


def load_qwen_connections(settings_path: Path) -> list[LLMConnection]:
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise E2EConfigurationError("Qwen settings file is unavailable") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise E2EConfigurationError("Qwen settings file cannot be parsed") from exc

    if not isinstance(raw, dict):
        raise E2EConfigurationError("Qwen settings root must be an object")

    configured_env = raw.get("env")
    env_values = configured_env if isinstance(configured_env, dict) else {}
    providers = raw.get("modelProviders")
    openai_group = providers.get("openai") if isinstance(providers, dict) else None
    entries = openai_group if isinstance(openai_group, list) else [openai_group]

    connections: list[LLMConnection] = []
    seen: set[tuple[str, str | None]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        base_url = entry.get("baseUrl")
        if not isinstance(base_url, str) or not base_url.strip():
            continue
        env_key = entry.get("envKey")
        api_key: str | None = None
        if isinstance(env_key, str) and env_key:
            configured_value = env_values.get(env_key)
            if isinstance(configured_value, str) and configured_value:
                api_key = configured_value
            else:
                api_key = os.environ.get(env_key)
        connection = _validated_connection(base_url, api_key, source="qwen_settings")
        identity = (connection.base_url, connection.api_key)
        if identity not in seen:
            connections.append(connection)
            seen.add(identity)

    if not connections:
        raise E2EConfigurationError("No OpenAI-compatible provider was found in Qwen settings")
    return connections


def _validated_connection(base_url: str, api_key: str | None, *, source: str) -> LLMConnection:
    value = base_url.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise E2EConfigurationError("Local-LLM base URL is invalid")
    if parsed.username or parsed.password:
        raise E2EConfigurationError("Credentials embedded in a URL are not supported")
    return LLMConnection(base_url=value, api_key=api_key, source=source)


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "base_url",
    "baseurl",
    "endpoint",
    "password",
    "secret",
    "token",
}


def redact_sensitive(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in _SENSITIVE_KEYS or any(marker in normalized for marker in ("password", "secret", "token")):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = redact_sensitive(item, secrets=secrets)
        return result
    if isinstance(value, list):
        return [redact_sensitive(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted((item for item in secrets if item), key=len, reverse=True):
            redacted = redacted.replace(secret, "<redacted>")
        return redacted
    return value


def assert_secrets_absent(text: str, secrets: tuple[str, ...]) -> None:
    if any(secret and secret in text for secret in secrets):
        raise E2EConfigurationError("Refusing to write output containing connection secrets")


def write_safe_json(path: Path, payload: Any, *, secrets: tuple[str, ...] = ()) -> None:
    redacted = redact_sensitive(payload, secrets=secrets)
    text = json.dumps(redacted, ensure_ascii=False, indent=2) + "\n"
    assert_secrets_absent(text, secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
