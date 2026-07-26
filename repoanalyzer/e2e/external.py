from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExternalScenarioError(RuntimeError):
    """Raised when a pinned external checkout cannot be prepared safely."""


@dataclass(frozen=True)
class ExternalScenario:
    scenario_id: str
    repository_url: str
    commit_sha: str
    license_name: str
    license_file: str
    checkout_directory: str
    compile_commands: list[dict[str, str]]
    question: str
    model_id: str
    required_answer_strings: list[str]
    required_tools: list[str]
    source_anchors: list[dict[str, str]]


def load_external_scenario(path: Path) -> ExternalScenario:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExternalScenarioError("External smoke scenario cannot be parsed") from exc
    if not isinstance(raw, dict):
        raise ExternalScenarioError("External smoke scenario root must be an object")
    repository = _object(raw, "repository")
    evaluation = _object(raw, "evaluation")
    return ExternalScenario(
        scenario_id=_string(raw, "scenario_id"),
        repository_url=_string(repository, "url"),
        commit_sha=_string(repository, "commit_sha"),
        license_name=_string(repository, "license"),
        license_file=_string(repository, "license_file"),
        checkout_directory=_string(repository, "checkout_directory"),
        compile_commands=_list_of_objects(raw, "compile_commands"),
        question=_string(evaluation, "question"),
        model_id=_string(evaluation, "model_id"),
        required_answer_strings=_list_of_strings(evaluation, "required_answer_strings"),
        required_tools=_list_of_strings(evaluation, "required_tools"),
        source_anchors=_list_of_objects(evaluation, "source_anchors"),
    )


def ensure_external_checkout(scenario: ExternalScenario, work_root: Path) -> Path:
    checkout = (work_root / scenario.checkout_directory).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    if not checkout.exists():
        _run_git(["clone", "--no-checkout", scenario.repository_url, str(checkout)])
        _run_git(["-C", str(checkout), "checkout", "--detach", scenario.commit_sha])
    elif not (checkout / ".git").exists():
        raise ExternalScenarioError("External checkout path exists but is not a Git repository")

    remote = _run_git(["-C", str(checkout), "remote", "get-url", "origin"]).strip()
    if remote.rstrip("/") != scenario.repository_url.rstrip("/"):
        raise ExternalScenarioError("Existing external checkout has an unexpected origin remote")

    head = _run_git(["-C", str(checkout), "rev-parse", "HEAD"]).strip()
    if head != scenario.commit_sha:
        dirty = _run_git(
            ["-C", str(checkout), "status", "--porcelain", "--untracked-files=no"]
        ).strip()
        if dirty:
            raise ExternalScenarioError(
                "Existing external checkout has tracked changes and cannot switch commits safely"
            )
        _run_git(["-C", str(checkout), "checkout", "--detach", scenario.commit_sha])
        head = _run_git(["-C", str(checkout), "rev-parse", "HEAD"]).strip()
    if head != scenario.commit_sha:
        raise ExternalScenarioError("External checkout HEAD does not match the pinned commit")

    if not (checkout / scenario.license_file).is_file():
        raise ExternalScenarioError("Pinned external checkout does not contain the expected license file")
    _write_compile_commands(checkout, scenario.compile_commands)
    return checkout


def _write_compile_commands(repo: Path, entries: list[dict[str, str]]) -> None:
    rendered: list[dict[str, str]] = []
    for entry in entries:
        command = entry.get("command")
        source_file = entry.get("file")
        if not command or not source_file:
            raise ExternalScenarioError("compile_commands entries require command and file")
        rendered.append(
            {
                "directory": str(repo),
                "command": command,
                "file": source_file,
            }
        )
    (repo / "compile_commands.json").write_text(
        json.dumps(rendered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_git(arguments: list[str]) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise ExternalScenarioError("Git executable is unavailable")
    try:
        # The command is an absolute executable and subprocess never invokes a shell.
        result = subprocess.run(
            [git_executable, *arguments],  # nosec B603
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExternalScenarioError(f"Git operation failed ({type(exc).__name__})") from None
    if result.returncode != 0:
        raise ExternalScenarioError(f"Git operation failed (exit {result.returncode})")
    return result.stdout


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ExternalScenarioError(f"Scenario field {key} must be an object")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ExternalScenarioError(f"Scenario field {key} must be a non-empty string")
    return item


def _list_of_strings(value: dict[str, Any], key: str) -> list[str]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ExternalScenarioError(f"Scenario field {key} must be a string list")
    return list(items)


def _list_of_objects(value: dict[str, Any], key: str) -> list[dict[str, str]]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ExternalScenarioError(f"Scenario field {key} must be an object list")
    normalized: list[dict[str, str]] = []
    for item in items:
        if not all(isinstance(entry_key, str) and isinstance(entry_value, str) for entry_key, entry_value in item.items()):
            raise ExternalScenarioError(f"Scenario field {key} contains a non-string value")
        normalized.append(dict(item))
    return normalized
