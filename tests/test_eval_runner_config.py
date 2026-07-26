from __future__ import annotations

import runpy
from pathlib import Path

import pytest


CLINE_RUNNER = Path(__file__).parents[1] / "eval" / "agent_compare" / "run_cline_cli_eval.py"


def test_cline_runner_requires_external_repo_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(CLINE_RUNNER))
    resolve_tinyusb_repo = namespace["resolve_tinyusb_repo"]
    monkeypatch.delenv("REPOANALYZER_TINYUSB_REPO", raising=False)

    with pytest.raises(RuntimeError, match="REPOANALYZER_TINYUSB_REPO"):
        resolve_tinyusb_repo()


def test_cline_runner_resolves_existing_external_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(str(CLINE_RUNNER))
    resolve_tinyusb_repo = namespace["resolve_tinyusb_repo"]
    monkeypatch.setenv("REPOANALYZER_TINYUSB_REPO", str(tmp_path))

    assert resolve_tinyusb_repo() == tmp_path.resolve()
