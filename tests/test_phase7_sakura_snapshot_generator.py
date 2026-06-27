from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from repoanalyzer.cli import app
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.snapshot.generator import generate_snapshot

FIXTURE = Path(__file__).parent / "fixtures_cpp" / "phase7_sakura_cross_trace_snapshot"
MANIFEST = FIXTURE / "source_fetch_manifest.yaml"
CASE_FILE_NAME = "phase7_sakura_cross_trace_cases.yaml"


def test_phase7_snapshot_generator_recreates_cross_trace_snapshot_and_eval_passes(tmp_path: Path) -> None:
    out = tmp_path / "generated_snapshot"

    report = generate_snapshot(MANIFEST, out)

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["schema_version"] == "snapshot_generation_report.v1"
    assert payload["snapshot_id"] == "phase7_sakura_cross_trace_snapshot"
    assert payload["source_count"] >= 18
    assert "compile_commands.json" in payload["generated_files"]
    assert "phase7_sakura_cross_trace_cases.yaml" in payload["copied_files"]
    assert (out / ".repoanalyzer-source-fetch-manifest.yaml").exists()

    eval_report = run_real_repo_eval(out, out / CASE_FILE_NAME)
    assert eval_report.ok, eval_report.to_dict()
    metrics = eval_report.to_dict()["metrics"]
    assert metrics["indexed_files"] >= 17
    assert metrics["total_facts"] >= 1000
    assert metrics["scenario_count"] == 12
    assert metrics["passed_scenarios"] == 12


def test_phase7_snapshot_generate_cli_smoke(tmp_path: Path) -> None:
    out = tmp_path / "generated_snapshot"
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot-generate", str(MANIFEST), str(out)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["source_count"] >= 18
    assert (out / "modules" / "search_command" / "src" / "command_dispatch.cpp").exists()
    # The generator should not index implicitly; ingest/eval owns .repoanalyzer-index creation.
    assert not (out / ".repoanalyzer-index").exists()


def test_phase7_snapshot_generator_rejects_sha_mismatch(tmp_path: Path) -> None:
    bad_manifest = tmp_path / "bad_manifest.yaml"
    raw = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    raw["source_root"] = str(FIXTURE)
    raw["sources"] = [dict(raw["sources"][0])]
    raw["sources"][0]["sha256"] = "0" * 64
    bad_manifest.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    report = generate_snapshot(bad_manifest, tmp_path / "out")

    assert not report.ok
    assert any("sha256 mismatch" in error for error in report.errors)


def test_phase7_snapshot_generator_copies_from_upstream_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    upstream_file = checkout / "sakura_core" / "cmd" / "CViewCommander.cpp"
    upstream_file.parent.mkdir(parents=True)
    upstream_file.write_text("void CViewCommander::HandleCommand() {}\n", encoding="utf-8")
    upstream_sha = __import__("hashlib").sha256(upstream_file.read_bytes()).hexdigest()

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "upstream_copy_smoke",
                "source_root": ".",
                "sources": [
                    {
                        "destination": "unused/local.cpp",
                        "required": False,
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "ref": "test-ref",
                            "path": "sakura_core/cmd/CViewCommander.cpp",
                            "sha256": upstream_sha,
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    out = tmp_path / "out"
    report = generate_snapshot(
        manifest,
        out,
        source_mode="upstream",
        checkout_roots={"sakura-editor/sakura": checkout},
    )

    assert report.ok, report.to_dict()
    payload = report.to_dict()
    assert payload["source_mode"] == "upstream"
    assert payload["copied_files"] == []
    copied = "upstream_sources/sakura-editor__sakura/sakura_core/cmd/CViewCommander.cpp"
    assert copied in payload["upstream_copied_files"]
    assert (out / copied).read_text(encoding="utf-8") == "void CViewCommander::HandleCommand() {}\n"


def test_phase7_snapshot_generate_cli_upstream_mode(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    upstream_file = checkout / "sakura_core" / "plugin" / "CJackManager.cpp"
    upstream_file.parent.mkdir(parents=True)
    upstream_file.write_text("void CJackManager::InvokePlugins() {}\n", encoding="utf-8")
    upstream_sha = __import__("hashlib").sha256(upstream_file.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "cli_upstream_copy_smoke",
                "source_root": ".",
                "sources": [
                    {
                        "destination": "unused/plugin.cpp",
                        "required": False,
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "path": "sakura_core/plugin/CJackManager.cpp",
                            "sha256": upstream_sha,
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "snapshot-generate",
            str(manifest),
            str(out),
            "--source-mode",
            "upstream",
            "--checkout-root",
            f"sakura-editor/sakura={checkout}",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["source_mode"] == "upstream"
    assert "upstream_sources/sakura-editor__sakura/sakura_core/plugin/CJackManager.cpp" in payload["upstream_copied_files"]


def test_phase7_snapshot_generator_rejects_upstream_sha_mismatch(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    upstream_file = checkout / "sakura_core" / "macro" / "CSMacroMgr.cpp"
    upstream_file.parent.mkdir(parents=True)
    upstream_file.write_text("void CSMacroMgr::Exec() {}\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "bad_upstream_sha",
                "sources": [
                    {
                        "destination": "unused/macro.cpp",
                        "required": False,
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "path": "sakura_core/macro/CSMacroMgr.cpp",
                            "sha256": "0" * 64,
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = generate_snapshot(
        manifest,
        tmp_path / "out",
        source_mode="upstream",
        checkout_roots={"sakura-editor/sakura": checkout},
    )

    assert not report.ok
    assert any("upstream sha256 mismatch" in error for error in report.errors)

from repoanalyzer.snapshot.traceability import generate_traceability_report


def test_phase7_snapshot_traceability_report_links_compact_and_upstream_sources(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    compact = source_root / "modules" / "macro" / "macro.cpp"
    compact.parent.mkdir(parents=True)
    compact.write_text(
        """
namespace sakura {
class CSMacroMgr { public: void Exec(); };
void CSMacroMgr::Exec() { ExecKeyMacro2(); CShareData::getInstance(); }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    compact_sha = __import__("hashlib").sha256(compact.read_bytes()).hexdigest()

    checkout = tmp_path / "checkout"
    upstream = checkout / "sakura_core" / "macro" / "CSMacroMgr.cpp"
    upstream.parent.mkdir(parents=True)
    upstream.write_text(
        """
BOOL CSMacroMgr::Exec(int idx) {
    CShareData::getInstance()->GetMacroFilename(idx, path, 260);
    m_cSavedKeyMacro[idx]->ExecKeyMacro2(pcEditView, flags);
    return TRUE;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "traceability_smoke",
                "source_root": str(source_root),
                "sources": [
                    {
                        "source": "modules/macro/macro.cpp",
                        "destination": "modules/macro/macro.cpp",
                        "sha256": compact_sha,
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "ref": "test-ref",
                            "path": "sakura_core/macro/CSMacroMgr.cpp",
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    gen_report = generate_snapshot(
        manifest,
        out,
        source_mode="both",
        checkout_roots={"sakura-editor/sakura": checkout},
    )
    assert gen_report.ok, gen_report.to_dict()

    trace_report = generate_traceability_report(manifest, out)

    payload = trace_report.to_dict()
    assert payload["ok"] is True
    assert payload["schema_version"] == "snapshot_traceability_report.v1"
    assert payload["metrics"]["entry_count"] == 1
    assert payload["metrics"]["upstream_refs_existing"] == 1
    assert payload["metrics"]["content_anchored_entries"] == 1
    entry = payload["entries"][0]
    assert entry["traceability_status"] == "content_anchored"
    assert "CSMacroMgr" in entry["matched_anchors"]
    assert (out / ".repoanalyzer-traceability-report.json").exists()


def test_phase7_snapshot_traceability_report_cli_smoke(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    compact = source_root / "modules" / "plugin" / "plugin.cpp"
    compact.parent.mkdir(parents=True)
    compact.write_text("void CJackManager::InvokePlugins(){ CPlug::Invoke(); GetUsablePlug(); }\n", encoding="utf-8")
    compact_sha = __import__("hashlib").sha256(compact.read_bytes()).hexdigest()
    checkout = tmp_path / "checkout"
    upstream = checkout / "sakura_core" / "plugin" / "CJackManager.cpp"
    upstream.parent.mkdir(parents=True)
    upstream.write_text("void CJackManager::InvokePlugins(){ GetUsablePlug(); plug->Invoke(); }\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "traceability_cli_smoke",
                "source_root": str(source_root),
                "sources": [
                    {
                        "source": "modules/plugin/plugin.cpp",
                        "destination": "modules/plugin/plugin.cpp",
                        "sha256": compact_sha,
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "path": "sakura_core/plugin/CJackManager.cpp",
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    generate_snapshot(manifest, out, source_mode="both", checkout_roots={"sakura-editor/sakura": checkout})
    runner = CliRunner()

    result = runner.invoke(app, ["snapshot-traceability-report", str(manifest), str(out)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["metrics"]["compact_sha_matches"] == 1
    assert payload["metrics"]["upstream_refs_existing"] == 1


def test_phase7_snapshot_traceability_report_detects_compact_sha_mismatch(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    compact = source_root / "modules" / "bad" / "bad.cpp"
    compact.parent.mkdir(parents=True)
    compact.write_text("void original(){}\n", encoding="utf-8")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "traceability_bad_sha",
                "source_root": str(source_root),
                "sources": [
                    {
                        "source": "modules/bad/bad.cpp",
                        "destination": "modules/bad/bad.cpp",
                        "sha256": "0" * 64,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    (out / "modules" / "bad").mkdir(parents=True)
    (out / "modules" / "bad" / "bad.cpp").write_text("void changed(){}\n", encoding="utf-8")

    trace_report = generate_traceability_report(manifest, out, write_report=False)

    assert not trace_report.ok
    assert any("compact sha256 mismatch" in error for error in trace_report.errors)
