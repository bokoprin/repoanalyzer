from __future__ import annotations

import json
from pathlib import Path

from repoanalyzer.core.models import CodeFact, UnknownFact
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.quality_gate import build_support_profile
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.cpp.ingest import ingest_repo


def test_quality_profile_marks_unresolved_semantic_evidence_weak(tmp_path: Path) -> None:
    fact = CodeFact(
        fact_type="call",
        path="src/a.cpp",
        start_line=1,
        end_line=1,
        caller="A::run",
        callee="B::go",
        payload={"resolution_status": "unresolved", "unknown_type": "unresolved_member_receiver_type"},
    )
    unknown = UnknownFact("unresolved_member_receiver_type", "receiver unknown")
    profile = build_support_profile(tmp_path, [fact], [unknown])

    assert profile.support_level == "weak"
    assert profile.semantic_resolution_status == "unresolved"
    assert "unresolved_member_receiver_type" in profile.unknown_reasons


def test_quality_profile_uses_coverage_gap_report(tmp_path: Path) -> None:
    (tmp_path / ".repoanalyzer-coverage-gap-report.json").write_text(
        json.dumps(
            {
                "schema_version": "snapshot_coverage_gap_report.v1",
                "entries": [
                    {
                        "scenario_id": "search_trace",
                        "support_status": "upstream_missing",
                        "compact_evidence": [{"compact_path": "modules/search/src/search.cpp"}],
                        "unknown_reasons": ["upstream_source_missing"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fact = CodeFact("call", "modules/search/src/search.cpp", 10, 10, caller="A", callee="B")
    profile = build_support_profile(tmp_path, [fact], [])

    assert profile.support_level == "weak"
    assert profile.source_coverage_status == "upstream_missing"
    assert "upstream_source_missing" in profile.unknown_reasons


def test_verify_claim_downgrades_supported_when_coverage_is_missing(tmp_path: Path) -> None:
    (tmp_path / "main.cpp").write_text("void b(){}\nvoid a(){ b(); }\n", encoding="utf-8")
    ingest_repo(tmp_path)
    (tmp_path / ".repoanalyzer-coverage-gap-report.json").write_text(
        json.dumps(
            {
                "schema_version": "snapshot_coverage_gap_report.v1",
                "entries": [
                    {
                        "scenario_id": "a_calls_b",
                        "support_status": "upstream_missing",
                        "compact_evidence": [{"compact_path": "main.cpp"}],
                        "unknown_reasons": ["upstream_source_missing"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    verdict = verify_claim(tmp_path, Claim("calls", subject="a", object="b"))

    assert verdict.verdict == "conditional"
    assert verdict.support_level == "weak"
    assert verdict.quality_profile is not None
    assert verdict.quality_profile.source_coverage_status == "upstream_missing"
    assert any(unknown.unknown_type == "upstream_source_missing" for unknown in verdict.unknowns)
