from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from pathlib import Path
from typing import Any
import shutil
import tempfile
import time

import yaml

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.verify import verify_claim
from repoanalyzer.evidence.claim_reasoning import fact_build_status
from repoanalyzer.workflow.contracts import build_answer_contract
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.query._store import open_store


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return {k: _to_dict(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_dict(v) for k, v in value.items()}
    return value


@dataclass(frozen=True)
class MatrixProfileSpec:
    id: str
    config: str
    description: str | None = None


@dataclass(frozen=True)
class MatrixTargetSpec:
    id: str
    claim_type: str
    subject: str
    object: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class MatrixAnswerContractSpec:
    id: str
    text: str
    question: str | None = None


@dataclass(frozen=True)
class MatrixTargetResult:
    id: str
    claim_type: str
    subject: str
    object: str | None
    verdict: str
    status: str
    reason_code: str
    support_level: str
    unknown_reasons: list[str] = field(default_factory=list)
    build_guard_chain: list[dict[str, Any]] = field(default_factory=list)
    guard_macro_values: dict[str, str] = field(default_factory=dict)
    supporting_fact_count: int = 0
    contradicting_fact_count: int = 0


@dataclass(frozen=True)
class MatrixAnswerContractResult:
    id: str
    can_answer: bool
    safety_level: str
    build_context: dict[str, Any] = field(default_factory=dict)
    required_qualifications: list[str] = field(default_factory=list)
    response_constraints: list[str] = field(default_factory=list)
    answer_obligations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatrixProfileResult:
    id: str
    config: str
    ok: bool
    duration_ms: int
    target_profile_name: str | None = None
    target_profile: dict[str, Any] = field(default_factory=dict)
    macros: dict[str, str] = field(default_factory=dict)
    allocation_profile: dict[str, str] = field(default_factory=dict)
    ingest_result: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, MatrixTargetResult] = field(default_factory=dict)
    answer_contracts: dict[str, MatrixAnswerContractResult] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MatrixTargetSummary:
    id: str
    claim_type: str
    subject: str
    object: str | None
    statuses: dict[str, str]
    verdicts: dict[str, str]
    changed: bool
    macro_differences: dict[str, dict[str, str | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class ProfileMatrixReport:
    matrix_id: str
    repo: str
    ok: bool
    duration_ms: int
    profiles: list[MatrixProfileResult]
    target_matrix: list[MatrixTargetSummary]
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    coverage_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "profile_matrix_report.v1",
            "matrix_id": self.matrix_id,
            "repo": self.repo,
            "ok": self.ok,
            "duration_ms": self.duration_ms,
            "profiles": _to_dict(self.profiles),
            "target_matrix": _to_dict(self.target_matrix),
            "coverage_summary": _to_dict(self.coverage_summary),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


def load_profile_matrix_spec(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def run_profile_matrix(repo: str | Path, matrix: str | Path, *, work_root: str | Path | None = None) -> ProfileMatrixReport:
    started = time.perf_counter()
    repo_path = Path(repo).resolve()
    matrix_path = Path(matrix).resolve()
    spec = load_profile_matrix_spec(matrix_path)
    matrix_id = str(spec.get("id") or matrix_path.stem)
    profiles = _load_profiles(spec)
    targets = _load_targets(spec)
    answer_contracts = _load_answer_contracts(spec)
    expected = dict(spec.get("expect") or {})
    failures: list[str] = []
    warnings: list[str] = []
    profile_results: list[MatrixProfileResult] = []

    temp_ctx = tempfile.TemporaryDirectory(prefix="repoanalyzer-profile-matrix-") if work_root is None else None
    root = Path(work_root) if work_root is not None else Path(temp_ctx.name)  # type: ignore[union-attr]
    root.mkdir(parents=True, exist_ok=True)
    try:
        for profile in profiles:
            profile_result = _run_one_profile(repo_path, root, profile, targets, answer_contracts)
            profile_results.append(profile_result)
            if not profile_result.ok:
                failures.extend(f"{profile.id}: {item}" for item in profile_result.failures)
        target_matrix = _build_target_matrix(targets, profile_results)
        failures.extend(_evaluate_expectations(expected, profile_results, target_matrix))
        report = ProfileMatrixReport(
            matrix_id=matrix_id,
            repo=str(repo_path),
            ok=not failures,
            duration_ms=int((time.perf_counter() - started) * 1000),
            profiles=profile_results,
            target_matrix=target_matrix,
            failures=failures,
            warnings=warnings,
            coverage_summary=_build_coverage_summary(profile_results, target_matrix),
        )
        return report
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()


def _load_profiles(spec: dict[str, Any]) -> list[MatrixProfileSpec]:
    profiles: list[MatrixProfileSpec] = []
    for index, raw in enumerate(spec.get("profiles", []) or []):
        profiles.append(
            MatrixProfileSpec(
                id=str(raw.get("id") or f"profile_{index + 1}"),
                config=str(raw["config"]),
                description=raw.get("description"),
            )
        )
    if not profiles:
        raise ValueError("profile matrix requires at least one profile")
    return profiles


def _load_targets(spec: dict[str, Any]) -> list[MatrixTargetSpec]:
    targets: list[MatrixTargetSpec] = []
    for index, raw in enumerate(spec.get("targets", []) or []):
        targets.append(
            MatrixTargetSpec(
                id=str(raw.get("id") or f"target_{index + 1}"),
                claim_type=str(raw.get("claim_type") or raw.get("kind") or "build_active"),
                subject=str(raw["subject"]),
                object=None if raw.get("object") is None else str(raw.get("object")),
                description=raw.get("description"),
            )
        )
    return targets


def _load_answer_contracts(spec: dict[str, Any]) -> list[MatrixAnswerContractSpec]:
    contracts: list[MatrixAnswerContractSpec] = []
    for index, raw in enumerate(spec.get("answer_contracts", []) or []):
        contracts.append(
            MatrixAnswerContractSpec(
                id=str(raw.get("id") or f"answer_contract_{index + 1}"),
                text=str(raw["text"]),
                question=raw.get("question"),
            )
        )
    return contracts


def _run_one_profile(
    repo_path: Path,
    work_root: Path,
    profile: MatrixProfileSpec,
    targets: list[MatrixTargetSpec],
    answer_contracts: list[MatrixAnswerContractSpec],
) -> MatrixProfileResult:
    started = time.perf_counter()
    dst = work_root / _safe_name(profile.id)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(repo_path, dst, ignore=shutil.ignore_patterns(".repoanalyzer-index", "__pycache__", ".git"))
    failures: list[str] = []
    ingest_payload: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    target_results: dict[str, MatrixTargetResult] = {}
    contract_results: dict[str, MatrixAnswerContractResult] = {}
    target_profile: dict[str, Any] = {}
    macros: dict[str, str] = {}
    allocation_profile: dict[str, str] = {}
    try:
        config_path = dst / profile.config
        if not config_path.exists():
            raise FileNotFoundError(f"profile config not found: {profile.config}")
        ingest_result = ingest_repo(dst, config_path=config_path)
        ingest_payload = dict(ingest_result.__dict__)
        diagnostics = query_diagnostics(dst).to_dict()
        store = open_store(dst)
        metadata = store.all_metadata()
        target_profile = dict(metadata.get("target_profile") or {})
        macros = _read_macro_facts(store)
        allocation_profile = _read_allocation_profile(store)
        for target in targets:
            if target.claim_type in {"build_active", "file_active"}:
                target_results[target.id] = _target_result_from_store(store, target)
            else:
                verdict = verify_claim(dst, Claim(claim_type=target.claim_type, subject=target.subject, object=target.object))
                target_results[target.id] = _target_result_from_verdict(target, verdict)
        for contract in answer_contracts:
            value = build_answer_contract(str(dst), contract.text, question=contract.question)
            contract_results[contract.id] = MatrixAnswerContractResult(
                id=contract.id,
                can_answer=bool(value.can_answer),
                safety_level=str(value.safety_level),
                build_context=dict(value.build_context or {}),
                required_qualifications=list(value.required_qualifications or []),
                response_constraints=list(value.response_constraints or []),
                answer_obligations=list(value.answer_obligations or []),
            )
    except Exception as exc:  # pragma: no cover - defensive path exercised through report failures.
        failures.append(f"{type(exc).__name__}: {exc}")
    return MatrixProfileResult(
        id=profile.id,
        config=profile.config,
        ok=not failures,
        duration_ms=int((time.perf_counter() - started) * 1000),
        target_profile_name=str(target_profile.get("name") or "") or None,
        target_profile=target_profile,
        macros=macros,
        allocation_profile=allocation_profile,
        ingest_result=ingest_payload,
        diagnostics=diagnostics,
        targets=target_results,
        answer_contracts=contract_results,
        failures=failures,
    )


def _target_result_from_store(store: Any, target: MatrixTargetSpec) -> MatrixTargetResult:
    if target.claim_type == "build_active":
        return _build_active_target_from_store(store, target)
    if target.claim_type == "file_active":
        return _file_active_target_from_store(store, target)
    verdict = verify_claim(".", Claim(claim_type=target.claim_type, subject=target.subject, object=target.object))
    return _target_result_from_verdict(target, verdict)


def _build_active_target_from_store(store: Any, target: MatrixTargetSpec) -> MatrixTargetResult:
    facts = _candidate_build_facts(store, target.subject)
    if not facts:
        return MatrixTargetResult(
            id=target.id,
            claim_type=target.claim_type,
            subject=target.subject,
            object=target.object,
            verdict="unknown",
            status="unknown",
            reason_code="build_target_not_found",
            support_level="unknown",
            unknown_reasons=["build_target_not_found"],
        )
    definition_facts = [f for f in facts if f.predicate == "definition" or f.payload.get("declaration_or_definition") == "definition"]
    status_facts = definition_facts or facts
    active = [f for f in status_facts if fact_build_status(f) == "active"]
    conditional = [f for f in status_facts if fact_build_status(f) == "conditional"]
    inactive = [f for f in status_facts if fact_build_status(f) == "inactive"]
    chosen = active or conditional or inactive
    fact = chosen[0] if chosen else status_facts[0]
    if active:
        verdict, status, reason, support = "supported", "active", "target_has_active_build_evidence", "medium"
    elif conditional:
        verdict, status, reason, support = "conditional", "conditional", "target_has_conditional_build_evidence", "weak"
    elif inactive:
        verdict, status, reason, support = "contradicted", "inactive", "target_only_has_inactive_build_evidence", "weak"
    else:
        verdict, status, reason, support = "unknown", "unknown", "target_build_status_unknown", "unknown"
    return MatrixTargetResult(
        id=target.id,
        claim_type=target.claim_type,
        subject=target.subject,
        object=target.object,
        verdict=verdict,
        status=status,
        reason_code=reason,
        support_level=support,
        unknown_reasons=list(fact.payload.get("unknown_reasons") or []),
        build_guard_chain=list(fact.payload.get("build_guard_chain") or []),
        guard_macro_values={str(k): str(v) for k, v in dict(fact.payload.get("guard_macro_values") or {}).items()},
        supporting_fact_count=len(active or conditional),
        contradicting_fact_count=len(inactive) if not active and not conditional else 0,
    )


def _candidate_build_facts(store: Any, subject: str) -> list[Any]:
    query = subject.split("(", 1)[0]
    suffix = f"%::{query}"
    rows = store.query_facts(
        "(symbol=? OR qualified_name=? OR subject=? OR object=? OR caller=? OR callee=? OR qualified_name LIKE ? OR subject LIKE ? OR object LIKE ? OR caller LIKE ? OR callee LIKE ?)",
        (query, query, query, query, query, query, suffix, suffix, suffix, suffix, suffix),
    )
    return [f for f in rows if _matrix_fact_name_matches(f, subject)]


def _matrix_fact_name_matches(fact: Any, query: str) -> bool:
    values = [
        fact.path,
        fact.symbol,
        fact.qualified_name,
        fact.subject,
        fact.object,
        fact.caller,
        fact.callee,
        fact.payload.get("caller_qualified_name"),
        fact.payload.get("callee_qualified_name"),
    ]
    base = query.split("(", 1)[0]
    for value in values:
        if not value:
            continue
        text = str(value)
        if text == query or text == base or text.endswith("::" + base):
            return True
        if "(" in text and (text.split("(", 1)[0] == base or text.split("(", 1)[0].endswith("::" + base)):
            return True
    return False


def _file_active_target_from_store(store: Any, target: MatrixTargetSpec) -> MatrixTargetResult:
    expected = (target.object or "active").lower()
    facts = store.query_facts("fact_type='target_file' AND subject=?", (target.subject,))
    if not facts:
        return MatrixTargetResult(
            id=target.id,
            claim_type=target.claim_type,
            subject=target.subject,
            object=target.object,
            verdict="unknown",
            status="unknown",
            reason_code="target_file_selection_not_found",
            support_level="unknown",
            unknown_reasons=["target_file_selection_not_found"],
        )
    active = any(f.predicate == "file_active" for f in facts)
    actual = "active" if active else "inactive"
    verdict = "supported" if actual == expected else "contradicted"
    fact = facts[0]
    for candidate in facts:
        if (actual == "active" and candidate.predicate == "file_active") or (actual == "inactive" and candidate.predicate == "file_inactive"):
            fact = candidate
            break
    return MatrixTargetResult(
        id=target.id,
        claim_type=target.claim_type,
        subject=target.subject,
        object=target.object,
        verdict=verdict,
        status=actual,
        reason_code="target_file_selection_supported" if verdict == "supported" else "target_file_selection_mismatch",
        support_level="medium" if verdict == "supported" else "weak",
        unknown_reasons=list(fact.payload.get("unknown_reasons") or []),
        supporting_fact_count=1 if verdict == "supported" else 0,
        contradicting_fact_count=1 if verdict == "contradicted" else 0,
    )


def _target_result_from_verdict(target: MatrixTargetSpec, verdict: Any) -> MatrixTargetResult:
    facts = list(verdict.supporting_facts or verdict.contradicting_facts or [])
    fact_payload = dict(facts[0].payload) if facts else {}
    return MatrixTargetResult(
        id=target.id,
        claim_type=target.claim_type,
        subject=target.subject,
        object=target.object,
        verdict=str(verdict.verdict),
        status=_status_from_verdict(target, verdict),
        reason_code=str(verdict.reason_code),
        support_level=str(getattr(verdict, "support_level", "unknown") or "unknown"),
        unknown_reasons=list(getattr(verdict, "unknown_reasons", []) or []),
        build_guard_chain=list(fact_payload.get("build_guard_chain") or []),
        guard_macro_values={str(k): str(v) for k, v in dict(fact_payload.get("guard_macro_values") or {}).items()},
        supporting_fact_count=len(verdict.supporting_facts or []),
        contradicting_fact_count=len(verdict.contradicting_facts or []),
    )


def _status_from_verdict(target: MatrixTargetSpec, verdict: Any) -> str:
    if target.claim_type == "build_active":
        if verdict.verdict == "supported":
            return "active"
        if verdict.verdict == "contradicted":
            return "inactive"
        return str(verdict.verdict)
    if target.claim_type == "file_active":
        requested = (target.object or "active").lower()
        if verdict.verdict == "supported":
            return requested
        if verdict.verdict == "contradicted":
            return "inactive" if requested == "active" else "active"
        return str(verdict.verdict)
    if target.claim_type in {"build_config", "allocation_profile", "target_profile"}:
        return str(verdict.verdict)
    return str(verdict.verdict)


def _read_macro_facts(store: Any) -> dict[str, str]:
    macros: dict[str, str] = {}
    for fact in store.query_facts("fact_type IN ('build_config','target_profile') AND predicate='macro_value'"):
        macros[str(fact.subject)] = str(fact.object)
    return macros


def _read_allocation_profile(store: Any) -> dict[str, str]:
    allocation: dict[str, str] = {}
    for fact in store.query_facts("fact_type='target_profile' AND predicate='allocation_setting'"):
        mode = fact.payload.get("allocation_mode") or fact.subject
        allocation[str(mode).replace("_allocation", "")] = str(fact.object)
    return allocation


def _build_target_matrix(targets: list[MatrixTargetSpec], profiles: list[MatrixProfileResult]) -> list[MatrixTargetSummary]:
    summaries: list[MatrixTargetSummary] = []
    for target in targets:
        statuses: dict[str, str] = {}
        verdicts: dict[str, str] = {}
        macro_values_by_profile: dict[str, dict[str, str]] = {}
        for profile in profiles:
            result = profile.targets.get(target.id)
            if result is None:
                statuses[profile.id] = "missing"
                verdicts[profile.id] = "missing"
            else:
                statuses[profile.id] = result.status
                verdicts[profile.id] = result.verdict
            macro_values_by_profile[profile.id] = profile.macros
        summaries.append(
            MatrixTargetSummary(
                id=target.id,
                claim_type=target.claim_type,
                subject=target.subject,
                object=target.object,
                statuses=statuses,
                verdicts=verdicts,
                changed=len(set(statuses.values())) > 1,
                macro_differences=_macro_differences(macro_values_by_profile),
            )
        )
    return summaries


def _macro_differences(macros_by_profile: dict[str, dict[str, str]]) -> dict[str, dict[str, str | None]]:
    all_keys = sorted({key for macros in macros_by_profile.values() for key in macros})
    diff: dict[str, dict[str, str | None]] = {}
    for key in all_keys:
        values = {profile: macros.get(key) for profile, macros in macros_by_profile.items()}
        if len(set(values.values())) > 1:
            diff[key] = values
    return diff


def _evaluate_expectations(
    expected: dict[str, Any],
    profiles: list[MatrixProfileResult],
    target_matrix: list[MatrixTargetSummary],
) -> list[str]:
    failures: list[str] = []
    profile_by_id = {profile.id: profile for profile in profiles}
    target_summary_by_id = {target.id: target for target in target_matrix}
    for profile_id, profile_expect in (expected.get("profiles") or {}).items():
        profile = profile_by_id.get(str(profile_id))
        if profile is None:
            failures.append(f"expected profile {profile_id!r} was not run")
            continue
        if "target_profile_name" in profile_expect and profile.target_profile_name != profile_expect["target_profile_name"]:
            failures.append(f"{profile_id}: target_profile_name expected {profile_expect['target_profile_name']}, got {profile.target_profile_name}")
        for macro, wanted in (profile_expect.get("macros") or {}).items():
            actual = profile.macros.get(str(macro))
            if actual != str(wanted):
                failures.append(f"{profile_id}: macro {macro} expected {wanted}, got {actual}")
        for target_id, target_expect in (profile_expect.get("targets") or {}).items():
            target = profile.targets.get(str(target_id))
            if target is None:
                failures.append(f"{profile_id}: target {target_id} was not evaluated")
                continue
            if "status" in target_expect and target.status != target_expect["status"]:
                failures.append(f"{profile_id}:{target_id}: status expected {target_expect['status']}, got {target.status}")
            if "verdict" in target_expect and target.verdict != target_expect["verdict"]:
                failures.append(f"{profile_id}:{target_id}: verdict expected {target_expect['verdict']}, got {target.verdict}")
    for target_id, target_expect in (expected.get("targets") or {}).items():
        target = target_summary_by_id.get(str(target_id))
        if target is None:
            failures.append(f"expected target {target_id!r} was not evaluated")
            continue
        if "changed" in target_expect and bool(target.changed) is not bool(target_expect["changed"]):
            failures.append(f"{target_id}: changed expected {target_expect['changed']}, got {target.changed}")
        for profile_id, wanted_status in (target_expect.get("statuses") or {}).items():
            actual = target.statuses.get(str(profile_id))
            if actual != str(wanted_status):
                failures.append(f"{target_id}:{profile_id}: status expected {wanted_status}, got {actual}")
    return failures


def _build_coverage_summary(profiles: list[MatrixProfileResult], targets: list[MatrixTargetSummary]) -> dict[str, Any]:
    total_targets = len(targets)
    changed_targets = sum(1 for target in targets if target.changed)
    verdict_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for profile in profiles:
        for target in profile.targets.values():
            verdict_counts[target.verdict] = verdict_counts.get(target.verdict, 0) + 1
            status_counts[target.status] = status_counts.get(target.status, 0) + 1
    return {
        "profile_count": len(profiles),
        "target_count": total_targets,
        "changed_target_count": changed_targets,
        "stable_target_count": total_targets - changed_targets,
        "verdict_counts": verdict_counts,
        "status_counts": status_counts,
    }


def _safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return cleaned or "profile"
