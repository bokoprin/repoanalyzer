from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from repoanalyzer.cli import app
from repoanalyzer.snapshot.coverage_gap import generate_coverage_gap_report
from repoanalyzer.snapshot.generator import generate_snapshot


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_snapshot_coverage_gap_reports_trace_level_partial_upstream_coverage(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    compact = source_root / "modules" / "extension_execution" / "src" / "extension.cpp"
    compact.parent.mkdir(parents=True)
    compact.write_text(
        """
namespace sakura {
// route_kind: macro_command_execution_trace
class CSMacroMgr { public: void Exec(); };
void CSMacroMgr::Exec() { ExecKeyMacro2(); }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    checkout = tmp_path / "checkout"
    present = checkout / "sakura_core" / "macro" / "CSMacroMgr.cpp"
    present.parent.mkdir(parents=True)
    present.write_text("void CSMacroMgr::Exec(){ ExecKeyMacro2(); }\n", encoding="utf-8")
    # Deliberately do not create sakura_core/plugin/CJackManager.cpp.

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "coverage_gap_partial_smoke",
                "source_root": str(source_root),
                "sources": [
                    {
                        "source": "modules/extension_execution/src/extension.cpp",
                        "destination": "modules/extension_execution/src/extension.cpp",
                        "sha256": _sha(compact),
                        "upstream": {
                            "repository": "sakura-editor/sakura",
                            "ref": "test-ref",
                            "paths": "sakura_core/macro/CSMacroMgr.cpp + sakura_core/plugin/CJackManager.cpp",
                        },
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        yaml.safe_dump(
            {
                "id": "coverage_gap_cases",
                "scenarios": [
                    {
                        "id": "extension_execution_trace",
                        "kind": "collect_evidence",
                        "question": "プラグイン / マクロ / 外部コマンド実行経路はどう行われる？",
                        "expect": {
                            "must_include": [
                                {
                                    "fact_type": "call_path",
                                    "payload_contains": {"route_kind": "macro_command_execution_trace"},
                                }
                            ]
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
    gen_report = generate_snapshot(manifest, out, source_mode="both", checkout_roots={"sakura-editor/sakura": checkout})
    assert gen_report.ok, gen_report.to_dict()
    assert gen_report.warnings, "missing optional upstream file should be a generation warning"

    report = generate_coverage_gap_report(manifest, out, cases)
    payload = report.to_dict()

    assert payload["ok"] is True
    assert payload["schema_version"] == "snapshot_coverage_gap_report.v1"
    assert payload["metrics"]["scenario_count"] == 1
    assert payload["metrics"]["partially_supported_scenarios"] == 1
    entry = payload["entries"][0]
    assert entry["scenario_id"] == "extension_execution_trace"
    assert entry["support_status"] == "partially_supported"
    assert entry["compact_evidence"][0]["compact_path"] == "modules/extension_execution/src/extension.cpp"
    assert [item["upstream_path"] for item in entry["upstream_evidence"]["present"]] == ["sakura_core/macro/CSMacroMgr.cpp"]
    assert [item["upstream_path"] for item in entry["upstream_evidence"]["missing"]] == ["sakura_core/plugin/CJackManager.cpp"]
    assert entry["recommended_additions"] == ["sakura_core/plugin/CJackManager.cpp"]
    assert "upstream_source_missing" in entry["unknown_reasons"]
    assert (out / ".repoanalyzer-coverage-gap-report.json").exists()


def test_snapshot_coverage_gap_reports_compact_only_when_manifest_has_no_upstream(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    compact = source_root / "modules" / "local_only" / "src" / "local.cpp"
    compact.parent.mkdir(parents=True)
    compact.write_text("// route_kind: local_only_trace\nvoid LocalOnlyTrace(){}\n", encoding="utf-8")

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "schema_version": "snapshot_manifest.v1",
                "snapshot_id": "coverage_gap_compact_only",
                "source_root": str(source_root),
                "sources": [
                    {
                        "source": "modules/local_only/src/local.cpp",
                        "destination": "modules/local_only/src/local.cpp",
                        "sha256": _sha(compact),
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        yaml.safe_dump(
            {
                "scenarios": [
                    {
                        "id": "local_only_trace",
                        "kind": "collect_evidence",
                        "expect": {
                            "must_include": [
                                {"fact_type": "call_path", "payload_contains": {"route_kind": "local_only_trace"}}
                            ]
                        },
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    assert generate_snapshot(manifest, out).ok

    payload = generate_coverage_gap_report(manifest, out, cases).to_dict()

    entry = payload["entries"][0]
    assert entry["support_status"] == "compact_only"
    assert entry["recommended_additions"] == []
    assert "no_upstream_metadata" in entry["unknown_reasons"]


def test_snapshot_coverage_gap_cli_smoke_on_phase7_fixture(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures_cpp" / "phase7_sakura_cross_trace_snapshot"
    manifest = fixture / "source_fetch_manifest.yaml"
    cases = fixture / "phase7_sakura_cross_trace_cases.yaml"
    out = tmp_path / "snapshot"
    assert generate_snapshot(manifest, out).ok

    runner = CliRunner()
    result = runner.invoke(app, ["snapshot-coverage-gap-report", str(manifest), str(out), str(cases)])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["schema_version"] == "snapshot_coverage_gap_report.v1"
    assert payload["metrics"]["scenario_count"] == 12
    assert payload["metrics"]["upstream_missing_scenarios"] >= 1
    search_entry = next(entry for entry in payload["entries"] if entry["scenario_id"] == "search_command_execution_trace")
    assert search_entry["compact_evidence"]
    assert search_entry["support_status"] in {"upstream_missing", "partially_supported", "compact_only"}
