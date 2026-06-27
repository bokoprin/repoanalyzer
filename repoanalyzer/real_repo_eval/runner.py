from __future__ import annotations

from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from repoanalyzer.claim_eval.matchers import evaluate_verdict
from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.evidence_eval.matchers import evaluate_bundle
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.store.status import repo_index_status
from repoanalyzer.workflow.session import workflow_run
from repoanalyzer.workflow_eval.matchers import evaluate_trace

from .cases import load_real_repo_case
from .matchers import evaluate_claim_bundle, evaluate_diagnostics, evaluate_ingest_result, evaluate_status
from .models import RealRepoEvalReport, ScenarioResult


def run_real_repo_eval(repo: str | Path, case_file: str | Path) -> RealRepoEvalReport:
    root = Path(repo).expanduser().resolve()
    case = load_real_repo_case(case_file)
    started = perf_counter()
    failures: list[str] = []
    warnings: list[str] = []
    category_counts: Counter[str] = Counter()
    ingest_result = None
    ingest_duration_ms = 0

    if case.ingest.enabled:
        ingest_started = perf_counter()
        config_path = _resolve_optional_path(root, case.ingest.config)
        try:
            ingest_result = ingest_repo(root, config_path=config_path, reset=not case.ingest.incremental, incremental=case.ingest.incremental)
        except Exception as exc:  # pragma: no cover - defensive reporting path
            failures.append(f"ingest failed: {exc}")
            category_counts["ingest_failed"] += 1
        ingest_duration_ms = _elapsed_ms(ingest_started)

    status_payload = repo_index_status(root).to_dict()
    diagnostics_payload = query_diagnostics(root).to_dict()

    metrics = {
        "ingest_duration_ms": ingest_duration_ms,
        "total_duration_ms": 0,
        "indexed_files": status_payload.get("indexed_files", 0),
        "current_files": status_payload.get("current_files", 0),
        "total_facts": diagnostics_payload.get("total_facts", 0),
        "fact_type_counts": diagnostics_payload.get("fact_type_counts", {}),
        "file_role_counts": diagnostics_payload.get("file_role_counts", {}),
    }

    for failure in evaluate_ingest_result(ingest_result, case.expect.get("ingest", {}) or {}).get("failures", []):
        failures.append(failure)
        category_counts["ingest_expectation_failed"] += 1
    for failure in evaluate_status(status_payload, case.expect.get("repo_status", {}) or {}).get("failures", []):
        failures.append(failure)
        category_counts["repo_status_mismatch"] += 1
    for failure in evaluate_diagnostics(diagnostics_payload, case.expect.get("diagnostics", {}) or {}).get("failures", []):
        failures.append(failure)
        category_counts["diagnostics_mismatch"] += 1

    _check_budget("max_ingest_ms", ingest_duration_ms, case.budgets, failures, category_counts)
    _check_budget("max_facts", int(metrics["total_facts"]), case.budgets, failures, category_counts, category="scale_budget_exceeded")
    _check_budget("max_indexed_files", int(metrics["indexed_files"]), case.budgets, failures, category_counts, category="scale_budget_exceeded")

    scenario_results: list[ScenarioResult] = []
    for scenario in case.scenarios:
        scenario_results.append(_run_scenario(root, scenario, category_counts))

    for scenario in scenario_results:
        if not scenario.ok:
            failures.append(f"scenario {scenario.id} failed")

    metrics["scenario_count"] = len(scenario_results)
    metrics["passed_scenarios"] = sum(1 for scenario in scenario_results if scenario.ok)
    metrics["failed_scenarios"] = sum(1 for scenario in scenario_results if not scenario.ok)

    total_duration_ms = _elapsed_ms(started)
    metrics["total_duration_ms"] = total_duration_ms
    _check_budget("max_total_ms", total_duration_ms, case.budgets, failures, category_counts)

    if status_payload.get("status") != "clean":
        warnings.append("Index was not clean during real repo evaluation; completeness/absence results may be degraded.")
        category_counts["index_not_clean"] += 1
    for warning in diagnostics_payload.get("warnings", []) or []:
        warnings.append(str(warning))

    ok = not failures and all(s.ok for s in scenario_results)
    return RealRepoEvalReport(
        repo=str(root),
        case_id=case.id,
        ok=ok,
        status="passed" if ok else "failed",
        duration_ms=total_duration_ms,
        ingest_result=ingest_result,
        repo_status=status_payload,
        diagnostics=diagnostics_payload,
        metrics=metrics,
        scenarios=scenario_results,
        failure_categories=dict(sorted(category_counts.items())),
        failures=failures,
        warnings=_dedupe(warnings),
    )


def _run_scenario(root: Path, scenario, category_counts: Counter[str]) -> ScenarioResult:
    started = perf_counter()
    failures: list[str] = []
    categories: list[str] = []
    output: Any = None
    try:
        if scenario.kind == "collect_evidence":
            output = collect_evidence(root, scenario.question or "", mode=scenario.mode)
            judged = evaluate_bundle(output, scenario.expect, scenario.expect.get("required_unknowns", []) or [], scenario.expect.get("answerability"))
            failures.extend(judged["failures"])
            if failures:
                categories.append("evidence_mismatch")
        elif scenario.kind == "verify_text":
            output = verify_claim_text(root, scenario.text or "")
            judged = evaluate_claim_bundle(output, scenario.expect)
            failures.extend(judged["failures"])
            if failures:
                categories.append("claim_mismatch")
        elif scenario.kind == "verify_claim":
            output = verify_claim(root, Claim.from_dict(scenario.claim or {}))
            judged = evaluate_verdict(output, scenario.expect.get("verdict"), scenario.expect.get("reason_code"), scenario.expect)
            failures.extend(judged["failures"])
            if failures:
                categories.append("claim_mismatch")
        elif scenario.kind == "workflow_run":
            output = workflow_run(root, scenario.question or "", answer_text=scenario.answer_text)
            judged = evaluate_trace(output, scenario.expect)
            failures.extend(judged["failures"])
            if failures:
                categories.append("workflow_mismatch")
        elif scenario.kind == "query_diagnostics":
            output = query_diagnostics(root)
            judged = evaluate_diagnostics(output.to_dict(), scenario.expect)
            failures.extend(judged["failures"])
            if failures:
                categories.append("diagnostics_mismatch")
        elif scenario.kind == "repo_status":
            output = repo_index_status(root)
            judged = evaluate_status(output.to_dict(), scenario.expect)
            failures.extend(judged["failures"])
            if failures:
                categories.append("repo_status_mismatch")
        else:
            failures.append(f"unsupported scenario kind: {scenario.kind}")
            categories.append("unsupported_scenario_kind")
    except Exception as exc:  # pragma: no cover - defensive reporting path
        failures.append(f"scenario raised {type(exc).__name__}: {exc}")
        categories.append("scenario_exception")
    ok = not failures
    for category in categories:
        category_counts[category] += 1
    return ScenarioResult(
        id=scenario.id,
        kind=scenario.kind,
        ok=ok,
        duration_ms=_elapsed_ms(started),
        failures=failures,
        failure_categories=categories,
        output=output,
    )


def _resolve_optional_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path


def _elapsed_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _check_budget(
    key: str,
    actual: int,
    budgets: dict[str, Any],
    failures: list[str],
    category_counts: Counter[str],
    *,
    category: str = "performance_budget_exceeded",
) -> None:
    if key in budgets and actual > int(budgets[key]):
        failures.append(f"budget {key} exceeded: expected <= {budgets[key]}, got {actual}")
        category_counts[category] += 1


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
