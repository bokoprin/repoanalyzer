from __future__ import annotations

from typing import Any

from repoanalyzer.claim_eval.matchers import evaluate_verdict
from repoanalyzer.evidence.claims import ClaimEvidenceBundle, ClaimVerdict
from repoanalyzer.evidence_eval.matchers import evaluate_bundle
from repoanalyzer.workflow_eval.matchers import evaluate_trace


def evaluate_claim_bundle(bundle: ClaimEvidenceBundle, expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if expected.get("overall_verdict") and bundle.overall_verdict != expected["overall_verdict"]:
        failures.append(f"overall_verdict mismatch: expected {expected['overall_verdict']}, got {bundle.overall_verdict}")
    verdicts = bundle.verdicts
    for wanted in expected.get("verdicts_include", []) or []:
        if not any(_verdict_matches(verdict, wanted) for verdict in verdicts):
            failures.append(f"missing expected verdict: {wanted}")
    if "extracted_claim_count" in expected and len(bundle.extracted_claims) != int(expected["extracted_claim_count"]):
        failures.append(f"extracted_claim_count mismatch: expected {expected['extracted_claim_count']}, got {len(bundle.extracted_claims)}")
    if "min_extracted_claim_count" in expected and len(bundle.extracted_claims) < int(expected["min_extracted_claim_count"]):
        failures.append(f"min_extracted_claim_count mismatch: expected at least {expected['min_extracted_claim_count']}, got {len(bundle.extracted_claims)}")
    return {"ok": not failures, "failures": failures}


def evaluate_status(status: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if "clean" in expected and bool(status.get("clean")) is not bool(expected["clean"]):
        failures.append(f"clean mismatch: expected {expected['clean']}, got {status.get('clean')}")
    if "status" in expected and status.get("status") != expected["status"]:
        failures.append(f"status mismatch: expected {expected['status']}, got {status.get('status')}")
    if "indexed_files" in expected and int(status.get("indexed_files", -1)) != int(expected["indexed_files"]):
        failures.append(f"indexed_files mismatch: expected {expected['indexed_files']}, got {status.get('indexed_files')}")
    return {"ok": not failures, "failures": failures}


def evaluate_diagnostics(diagnostics: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if "min_total_facts" in expected and int(diagnostics.get("total_facts", 0)) < int(expected["min_total_facts"]):
        failures.append(f"total_facts below minimum: expected >= {expected['min_total_facts']}, got {diagnostics.get('total_facts')}")
    if "max_total_facts" in expected and int(diagnostics.get("total_facts", 0)) > int(expected["max_total_facts"]):
        failures.append(f"total_facts above maximum: expected <= {expected['max_total_facts']}, got {diagnostics.get('total_facts')}")
    if "min_indexed_files" in expected and int(diagnostics.get("indexed_files", 0)) < int(expected["min_indexed_files"]):
        failures.append(f"indexed_files below minimum: expected >= {expected['min_indexed_files']}, got {diagnostics.get('indexed_files')}")
    if "max_warnings" in expected and len(diagnostics.get("warnings", [])) > int(expected["max_warnings"]):
        failures.append(f"too many diagnostics warnings: expected <= {expected['max_warnings']}, got {len(diagnostics.get('warnings', []))}")
    for role, minimum in (expected.get("file_role_min_counts") or {}).items():
        actual = int((diagnostics.get("file_role_counts") or {}).get(role, 0))
        if actual < int(minimum):
            failures.append(f"file role {role!r} below minimum: expected >= {minimum}, got {actual}")
    return {"ok": not failures, "failures": failures}


def evaluate_ingest_result(ingest_result: Any, expected: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    if ingest_result is None:
        if expected:
            failures.append("ingest was not run")
        return {"ok": not failures, "failures": failures}
    payload = ingest_result.__dict__ if hasattr(ingest_result, "__dict__") else dict(ingest_result)
    for key in ("status", "mode"):
        if key in expected and payload.get(key) != expected[key]:
            failures.append(f"ingest {key} mismatch: expected {expected[key]}, got {payload.get(key)}")
    if "min_files" in expected and int(payload.get("files", 0)) < int(expected["min_files"]):
        failures.append(f"ingest files below minimum: expected >= {expected['min_files']}, got {payload.get('files')}")
    if "min_facts" in expected and int(payload.get("facts", 0)) < int(expected["min_facts"]):
        failures.append(f"ingest facts below minimum: expected >= {expected['min_facts']}, got {payload.get('facts')}")
    return {"ok": not failures, "failures": failures}


def _verdict_matches(verdict: ClaimVerdict, wanted: dict[str, Any]) -> bool:
    if wanted.get("claim_type") and verdict.claim.claim_type != wanted["claim_type"]:
        return False
    if wanted.get("subject") and verdict.claim.subject != wanted["subject"]:
        return False
    if wanted.get("object") and verdict.claim.object != wanted["object"]:
        return False
    if wanted.get("verdict") and verdict.verdict != wanted["verdict"]:
        return False
    if wanted.get("reason_code") and verdict.reason_code != wanted["reason_code"]:
        return False
    return True
