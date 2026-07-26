from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import LLMConnection


class LLMRequestError(RuntimeError):
    def __init__(self, operation: str, *, status: int | None, error_type: str) -> None:
        super().__init__(f"{operation} failed ({error_type})")
        self.operation = operation
        self.status = status
        self.error_type = error_type

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "http_status": self.status,
            "error_type": self.error_type,
        }


class ModelNotFoundError(RuntimeError):
    def __init__(self, model_id: str, available_models: list[str]) -> None:
        super().__init__(f"Exact model ID is unavailable: {model_id}")
        self.model_id = model_id
        self.available_models = sorted(set(available_models))


@dataclass(frozen=True)
class HTTPResult:
    status: int
    elapsed_ms: int
    payload: dict[str, Any]


@dataclass(frozen=True)
class ModelSelection:
    connection: LLMConnection
    model_id: str
    models_http_status: int
    models_elapsed_ms: int
    models_count: int


class OpenAICompatibleClient:
    def __init__(self, connection: LLMConnection, *, timeout_seconds: float = 180.0) -> None:
        self.connection = connection
        self.timeout_seconds = timeout_seconds

    def list_models(self) -> tuple[list[str], HTTPResult]:
        result = self._request_json("models", "GET", None)
        data = result.payload.get("data")
        entries = data if isinstance(data, list) else []
        models = [
            str(item["id"])
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return models, result

    def chat_completion(
        self,
        *,
        model_id: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> HTTPResult:
        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return self._request_json("chat/completions", "POST", body)

    def _request_json(self, path: str, method: str, body: dict[str, Any] | None) -> HTTPResult:
        headers = {"Accept": "application/json"}
        if self.connection.api_key:
            headers["Authorization"] = f"Bearer {self.connection.api_key}"
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            self.connection.endpoint(path),
            data=payload,
            headers=headers,
            method=method,
        )
        started = time.perf_counter()
        try:
            # The connection loader accepts only explicit HTTP(S) endpoints.
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
                status = int(response.status)
                response_body = response.read()
        except HTTPError as exc:
            raise LLMRequestError(
                path,
                status=int(exc.code),
                error_type=type(exc).__name__,
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise LLMRequestError(
                path,
                status=None,
                error_type=type(exc).__name__,
            ) from None
        elapsed_ms = round((time.perf_counter() - started) * 1000)

        try:
            parsed = json.loads(response_body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LLMRequestError(
                path,
                status=status,
                error_type=type(exc).__name__,
            ) from None
        if not isinstance(parsed, dict):
            raise LLMRequestError(path, status=status, error_type="InvalidResponseShape")
        return HTTPResult(status=status, elapsed_ms=elapsed_ms, payload=parsed)


def select_model_connection(
    connections: list[LLMConnection],
    model_id: str,
    *,
    timeout_seconds: float = 30.0,
) -> ModelSelection:
    available: list[str] = []
    failures: list[LLMRequestError] = []
    for connection in connections:
        client = OpenAICompatibleClient(connection, timeout_seconds=timeout_seconds)
        try:
            models, result = client.list_models()
        except LLMRequestError as exc:
            failures.append(exc)
            continue
        available.extend(models)
        if model_id in models:
            return ModelSelection(
                connection=connection,
                model_id=model_id,
                models_http_status=result.status,
                models_elapsed_ms=result.elapsed_ms,
                models_count=len(models),
            )
    if available:
        raise ModelNotFoundError(model_id, available)
    if failures:
        raise failures[-1]
    raise LLMRequestError("models", status=None, error_type="NoProvider")
