from __future__ import annotations

import json
from pathlib import Path

import typer

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.verify import verify_claim, verify_claims
from repoanalyzer.evidence.claim_extraction import extract_claims, verify_claim_text
from repoanalyzer.evidence_eval.report import render_json, render_text
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.claim_eval.report import render_json as render_claim_json, render_text as render_claim_text
from repoanalyzer.claim_eval.runner import run_claim_eval
from repoanalyzer.query import find_callers, find_callees, find_definitions, find_references, read_file_range
from repoanalyzer.query.pages import find_callers_page, find_callees_page, find_definitions_page, find_references_page
from repoanalyzer.store.status import repo_index_status
from repoanalyzer.store.diagnostics import query_diagnostics
from repoanalyzer.workflow.preflight import preflight
from repoanalyzer.workflow.planner import plan_question
from repoanalyzer.workflow.answer_check import verify_answer
from repoanalyzer.workflow.contracts import build_answer_contract
from repoanalyzer.workflow.session import workflow_run
from repoanalyzer.workflow.session_log import read_workflow_sessions
from repoanalyzer.workflow_eval.report import render_json as render_workflow_json, render_text as render_workflow_text
from repoanalyzer.workflow_eval.runner import run_workflow_eval
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval
from repoanalyzer.real_repo_eval.tinyusb_upstream import prepare_tinyusb_upstream_smoke, run_tinyusb_upstream_smoke
from repoanalyzer.real_repo_eval.report import render_json as render_real_repo_json, render_text as render_real_repo_text
from repoanalyzer.snapshot.generator import generate_snapshot
from repoanalyzer.snapshot.traceability import generate_traceability_report
from repoanalyzer.snapshot.coverage_gap import generate_coverage_gap_report
from repoanalyzer.evidence.target_profile_diff import build_target_profile_diff
from repoanalyzer.evidence.profile_matrix import run_profile_matrix

app = typer.Typer(help="C/C++ Code Evidence Engine for LLM agents.")


@app.command()
def ingest(
    repo: Path,
    config: Path | None = None,
    incremental: bool = typer.Option(False, "--incremental", help="Safely update changed source files when possible."),
) -> None:
    """Index a C/C++ repository into .repoanalyzer-index/index.sqlite3."""
    result = ingest_repo(repo, config_path=config, reset=not incremental, incremental=incremental)
    typer.echo(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    if result.full_reingest_required:
        raise typer.Exit(code=2)




@app.command("repo-status")
def repo_status_cmd(repo: Path, config: Path | None = None) -> None:
    """Report index freshness using the file manifest from the last ingest."""
    status = repo_index_status(repo, config_path=config)
    typer.echo(json.dumps(status.to_dict(), ensure_ascii=False, indent=2))


@app.command("query-diagnostics")
def query_diagnostics_cmd(repo: Path) -> None:
    """Report large-repo query/index diagnostics."""
    typer.echo(json.dumps(query_diagnostics(repo).to_dict(), ensure_ascii=False, indent=2))



@app.command("preflight")
def preflight_cmd(repo: Path) -> None:
    """Run agent preflight checks before answering repository questions."""
    typer.echo(json.dumps(preflight(repo).to_dict(), ensure_ascii=False, indent=2))


@app.command("plan-question")
def plan_question_cmd(question: str) -> None:
    """Create a deterministic tool plan for an agent question."""
    typer.echo(json.dumps(plan_question(question).to_dict(), ensure_ascii=False, indent=2))


@app.command("verify-answer")
def verify_answer_cmd(
    repo: Path,
    text: str | None = typer.Argument(None),
    question: str | None = typer.Option(None, "--question", "-q"),
    text_file: Path | None = typer.Option(None, "--text-file", "-f"),
) -> None:
    """Verify natural-language answer claims and return an answer_verification_report.v1."""
    source_text = _read_text_argument(text, text_file)
    typer.echo(json.dumps(verify_answer(repo, source_text, question=question).to_dict(), ensure_ascii=False, indent=2))


@app.command("answer-contract")
def answer_contract_cmd(
    repo: Path,
    text: str | None = typer.Argument(None),
    question: str | None = typer.Option(None, "--question", "-q"),
    text_file: Path | None = typer.Option(None, "--text-file", "-f"),
) -> None:
    """Build a safe_answer_contract.v1 from a draft answer."""
    source_text = _read_text_argument(text, text_file)
    typer.echo(json.dumps(build_answer_contract(str(repo), source_text, question=question).to_dict(), ensure_ascii=False, indent=2))


@app.command("workflow-run")
def workflow_run_cmd(
    repo: Path,
    question: str,
    answer_text: str | None = typer.Option(None, "--answer-text", "-a"),
    answer_file: Path | None = typer.Option(None, "--answer-file"),
    record: bool = typer.Option(False, "--record", help="Append the workflow trace to .repoanalyzer-index/workflow_sessions.jsonl."),
    label: str | None = typer.Option(None, "--label", help="Optional label for recorded workflow sessions."),
) -> None:
    """Run preflight, question planning, and optional answer verification as one trace."""
    source_answer = answer_file.read_text(encoding="utf-8") if answer_file else answer_text
    typer.echo(json.dumps(workflow_run(repo, question, answer_text=source_answer, record=record, label=label).to_dict(), ensure_ascii=False, indent=2))


@app.command("workflow-history")
def workflow_history_cmd(repo: Path, limit: int = 20, offset: int = 0) -> None:
    """Read recorded workflow traces from .repoanalyzer-index/workflow_sessions.jsonl."""
    typer.echo(json.dumps(read_workflow_sessions(repo, limit=limit, offset=offset), ensure_ascii=False, indent=2))






@app.command("snapshot-generate")
def snapshot_generate_cmd(
    manifest: Path,
    output: Path,
    clean: bool = typer.Option(True, "--clean/--no-clean", help="Remove the output directory before generating."),
    source_mode: str = typer.Option("local", "--source-mode", help="Source copy mode: local, upstream, or both."),
    checkout_root: list[str] | None = typer.Option(
        None,
        "--checkout-root",
        help="Local checkout root. Use repo=PATH for multiple repositories, or PATH for one checkout.",
    ),
    upstream_output_root: str = typer.Option("upstream_sources", "--upstream-output-root", help="Directory for copied upstream checkout files."),
) -> None:
    """Generate a reproducible compact snapshot from a source-fetch manifest."""
    report = generate_snapshot(
        manifest,
        output,
        clean=clean,
        source_mode=source_mode,
        checkout_roots=_parse_checkout_root_options(checkout_root),
        upstream_output_root=upstream_output_root,
    )
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("snapshot-traceability-report")
def snapshot_traceability_report_cmd(
    manifest: Path,
    snapshot: Path,
    upstream_output_root: str = typer.Option("upstream_sources", "--upstream-output-root", help="Directory containing copied upstream checkout files."),
    write_report: bool = typer.Option(True, "--write-report/--no-write-report", help="Write .repoanalyzer-traceability-report.json into the snapshot root."),
) -> None:
    """Validate compact snapshot files against copied upstream source evidence."""
    report = generate_traceability_report(
        manifest,
        snapshot,
        upstream_output_root=upstream_output_root,
        write_report=write_report,
    )
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not report.ok:
        raise typer.Exit(code=1)


@app.command("snapshot-coverage-gap-report")
def snapshot_coverage_gap_report_cmd(
    manifest: Path,
    snapshot: Path,
    cases: Path,
    upstream_output_root: str = typer.Option("upstream_sources", "--upstream-output-root", help="Directory containing copied upstream checkout files."),
    write_report: bool = typer.Option(True, "--write-report/--no-write-report", help="Write .repoanalyzer-coverage-gap-report.json into the snapshot root."),
) -> None:
    """Report trace/scenario-level compact-vs-upstream evidence coverage gaps."""
    report = generate_coverage_gap_report(
        manifest,
        snapshot,
        cases,
        upstream_output_root=upstream_output_root,
        write_report=write_report,
    )
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not report.ok:
        raise typer.Exit(code=1)


def _parse_checkout_root_options(values: list[str] | None) -> dict[str, str] | str | None:
    if not values:
        return None
    if len(values) == 1 and "=" not in values[0]:
        return values[0]
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise typer.BadParameter("Use repo=PATH when passing multiple --checkout-root values.")
        repo, path = value.split("=", 1)
        repo = repo.strip()
        path = path.strip()
        if not repo or not path:
            raise typer.BadParameter("--checkout-root must be repo=PATH")
        parsed[repo] = path
    return parsed


@app.command("real-repo-eval")
def real_repo_eval_cmd(repo: Path, cases: Path, output: str = typer.Option("text", "--output", "-o")) -> None:
    """Run real C/C++ repository validation scenarios and produce a failure-classified report."""
    result = run_real_repo_eval(repo, cases)
    if output == "json":
        typer.echo(render_real_repo_json(result))
    else:
        typer.echo(render_real_repo_text(result))
    if not result.ok:
        raise typer.Exit(code=1)




@app.command("tinyusb-upstream-smoke-prepare")
def tinyusb_upstream_smoke_prepare_cmd(
    repo: Path,
    output_dir: Path = typer.Option(Path(".repoanalyzer-smoke"), "--output-dir", "-o"),
) -> None:
    """Generate target profiles and real-repo-eval cases for a TinyUSB upstream checkout."""
    plan = prepare_tinyusb_upstream_smoke(repo, output_dir)
    typer.echo(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))


@app.command("tinyusb-upstream-smoke")
def tinyusb_upstream_smoke_cmd(
    repo: Path,
    output_dir: Path = typer.Option(Path(".repoanalyzer-smoke"), "--output-dir", "-o"),
    profile: list[str] | None = typer.Option(None, "--profile", "-p", help="Profile id to run. Repeat to run multiple; running one profile per command is recommended for large checkouts."),
    output: str = typer.Option("text", "--output"),
) -> None:
    """Prepare and run selected real TinyUSB upstream smoke/profile evaluations."""
    if not profile:
        raise typer.BadParameter("Pass at least one --profile. Use tinyusb-upstream-smoke-prepare to list generated profile ids.")
    result = run_tinyusb_upstream_smoke(repo, output_dir, profiles=profile)
    if output == "json":
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        typer.echo(f"TinyUSB upstream smoke: {'PASS' if result['ok'] else 'FAIL'}")
        typer.echo(f"profiles: {result['passed_profiles']}/{result['profile_count']} passed")
        for report in result["reports"]:
            typer.echo(f"- {'PASS' if report.get('ok') else 'FAIL'} {report.get('case_id')} facts={report.get('metrics', {}).get('total_facts')} files={report.get('metrics', {}).get('indexed_files')}")
            for failure in report.get("failures", [])[:8]:
                typer.echo(f"    {failure}")
    if not result["ok"]:
        raise typer.Exit(code=1)


@app.command("workflow-eval")
def workflow_eval_cmd(repo: Path, cases: Path, output: str = typer.Option("text", "--output", "-o")) -> None:
    """Run workflow safety evaluation cases."""
    result = run_workflow_eval(repo, cases)
    if output == "json":
        typer.echo(render_workflow_json(result))
    else:
        typer.echo(render_workflow_text(result))
    if result.failed:
        raise typer.Exit(code=1)


@app.command("collect-evidence")
def collect_evidence_cmd(repo: Path, question: str, mode: str | None = None) -> None:
    """Collect an EvidenceBundle for a question."""
    bundle = collect_evidence(repo, question, mode=mode)
    typer.echo(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))


@app.command("eval")
def eval_cmd(repo: Path, cases: Path, output: str = typer.Option("text", "--output", "-o")) -> None:
    """Run expected-evidence evaluation cases."""
    result = run_eval(repo, cases)
    if output == "json":
        typer.echo(render_json(result))
    else:
        typer.echo(render_text(result))
    if result.failed:
        raise typer.Exit(code=1)


@app.command("verify-claim")
def verify_claim_cmd(
    repo: Path,
    claim_type: str = typer.Option(..., "--claim-type", "-t"),
    subject: str | None = typer.Option(None, "--subject", "-s"),
    object: str | None = typer.Option(None, "--object", "-o"),
) -> None:
    """Verify one structured claim and return a claim_verdict.v1 object."""
    verdict = verify_claim(repo, Claim(claim_type=claim_type, subject=subject, object=object))
    typer.echo(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))


@app.command("verify-claims")
def verify_claims_cmd(repo: Path, claims_json: Path) -> None:
    """Verify a JSON file containing one claim object or a list/{claims:[...]} of claims."""
    raw = json.loads(claims_json.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "claims" in raw:
        raw_claims = raw["claims"]
    elif isinstance(raw, list):
        raw_claims = raw
    else:
        raw_claims = [raw]
    bundle = verify_claims(repo, [Claim.from_dict(item) for item in raw_claims])
    typer.echo(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))


@app.command("extract-claims")
def extract_claims_cmd(
    text: str | None = typer.Argument(None),
    text_file: Path | None = typer.Option(None, "--text-file", "-f"),
) -> None:
    """Extract structured claims from deterministic natural-language patterns."""
    source_text = _read_text_argument(text, text_file)
    bundle = extract_claims(source_text)
    typer.echo(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))


@app.command("verify-text")
def verify_text_cmd(
    repo: Path,
    text: str | None = typer.Argument(None),
    text_file: Path | None = typer.Option(None, "--text-file", "-f"),
) -> None:
    """Extract natural-language claims from text and verify them as a batch."""
    source_text = _read_text_argument(text, text_file)
    bundle = verify_claim_text(repo, source_text)
    typer.echo(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2))




@app.command("profile-matrix")
def profile_matrix_cmd(repo: Path, matrix: Path) -> None:
    """Run multiple target profiles against one repo and compare build-sensitive evidence."""
    report = run_profile_matrix(repo, matrix)
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if not report.ok:
        raise typer.Exit(code=1)

@app.command("target-profile-diff")
def target_profile_diff_cmd(left_repo: Path, right_repo: Path, target: str = typer.Option(..., "--target", "-t")) -> None:
    """Compare target active/conditional/inactive provenance across two indexed repos/profiles."""
    report = build_target_profile_diff(left_repo, right_repo, target)
    typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def _read_text_argument(text: str | None, text_file: Path | None) -> str:
    if text_file is not None:
        return text_file.read_text(encoding="utf-8")
    if text is not None:
        return text
    raise typer.BadParameter("Provide text as an argument or pass --text-file.")


@app.command("claim-eval")
def claim_eval_cmd(repo: Path, cases: Path, output: str = typer.Option("text", "--output", "-o")) -> None:
    """Run claim verification evaluation cases."""
    result = run_claim_eval(repo, cases)
    if output == "json":
        typer.echo(render_claim_json(result))
    else:
        typer.echo(render_claim_text(result))
    if result.failed:
        raise typer.Exit(code=1)


@app.command("inspect-file")
def inspect_file(repo: Path, path: str, start: int = 1, end: int = 80) -> None:
    typer.echo(json.dumps(read_file_range(repo, path, start, end), ensure_ascii=False, indent=2))


@app.command("find-definitions")
def find_definitions_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps([f.to_dict() for f in find_definitions(repo, symbol, limit=limit, offset=offset)], ensure_ascii=False, indent=2))


@app.command("find-references")
def find_references_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps([f.to_dict() for f in find_references(repo, symbol, limit=limit, offset=offset)], ensure_ascii=False, indent=2))


@app.command("find-callers")
def find_callers_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps([f.to_dict() for f in find_callers(repo, symbol, limit=limit, offset=offset)], ensure_ascii=False, indent=2))


@app.command("find-callees")
def find_callees_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps([f.to_dict() for f in find_callees(repo, symbol, limit=limit, offset=offset)], ensure_ascii=False, indent=2))


@app.command("find-callers-page")
def find_callers_page_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps(find_callers_page(repo, symbol, limit=limit, offset=offset).to_dict(), ensure_ascii=False, indent=2))


@app.command("find-callees-page")
def find_callees_page_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps(find_callees_page(repo, symbol, limit=limit, offset=offset).to_dict(), ensure_ascii=False, indent=2))


@app.command("find-definitions-page")
def find_definitions_page_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps(find_definitions_page(repo, symbol, limit=limit, offset=offset).to_dict(), ensure_ascii=False, indent=2))


@app.command("find-references-page")
def find_references_page_cmd(repo: Path, symbol: str, limit: int | None = None, offset: int = 0) -> None:
    typer.echo(json.dumps(find_references_page(repo, symbol, limit=limit, offset=offset).to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
