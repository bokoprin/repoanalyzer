from __future__ import annotations

from pathlib import Path

from repoanalyzer.core.paths import index_db_path
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.verify import verify_claim, verify_claims
from repoanalyzer.evidence.claim_extraction import extract_claims, verify_claim_text
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
from repoanalyzer.real_repo_eval.runner import run_real_repo_eval


def server_info(repo: str) -> dict:
    db = index_db_path(repo)
    return {
        "repo": str(Path(repo).expanduser().resolve()),
        "index_ready": db.exists(),
        "db_path": str(db),
        "tools": [
            "server_info",
            "read_file_range",
            "find_definitions",
            "find_references",
            "find_callers",
            "find_callees",
            "collect_evidence",
            "verify_claim",
            "verify_claims",
            "extract_claims",
            "verify_text",
            "repo_status",
            "query_diagnostics",
            "find_definitions_page",
            "find_references_page",
            "find_callers_page",
            "find_callees_page",
            "preflight",
            "plan_question",
            "verify_answer",
            "answer_contract",
            "workflow_run",
            "workflow_history",
            "real_repo_eval",
        ],
    }


def tool_read_file_range(repo: str, path: str, start_line: int, end_line: int) -> dict:
    return read_file_range(repo, path, start_line, end_line)


def tool_find_definitions(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
    return [fact.to_dict() for fact in find_definitions(repo, symbol, limit=limit, offset=offset)]


def tool_find_references(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
    return [fact.to_dict() for fact in find_references(repo, symbol, limit=limit, offset=offset)]


def tool_find_callers(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
    return [fact.to_dict() for fact in find_callers(repo, symbol, limit=limit, offset=offset)]


def tool_find_callees(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
    return [fact.to_dict() for fact in find_callees(repo, symbol, limit=limit, offset=offset)]


def tool_find_definitions_page(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> dict:
    return find_definitions_page(repo, symbol, limit=limit, offset=offset).to_dict()


def tool_find_references_page(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> dict:
    return find_references_page(repo, symbol, limit=limit, offset=offset).to_dict()


def tool_find_callers_page(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> dict:
    return find_callers_page(repo, symbol, limit=limit, offset=offset).to_dict()


def tool_find_callees_page(repo: str, symbol: str, limit: int | None = None, offset: int = 0) -> dict:
    return find_callees_page(repo, symbol, limit=limit, offset=offset).to_dict()


def tool_collect_evidence(repo: str, question: str, mode: str | None = None) -> dict:
    return collect_evidence(repo, question, mode=mode).to_dict()


def tool_verify_claim(repo: str, claim: dict) -> dict:
    return verify_claim(repo, Claim.from_dict(claim)).to_dict()


def tool_verify_claims(repo: str, claims: list[dict]) -> dict:
    return verify_claims(repo, [Claim.from_dict(claim) for claim in claims]).to_dict()


def tool_extract_claims(text: str) -> dict:
    return extract_claims(text).to_dict()


def tool_verify_text(repo: str, text: str) -> dict:
    return verify_claim_text(repo, text).to_dict()


def tool_repo_status(repo: str) -> dict:
    return repo_index_status(repo).to_dict()


def tool_query_diagnostics(repo: str) -> dict:
    return query_diagnostics(repo).to_dict()


def tool_preflight(repo: str) -> dict:
    return preflight(repo).to_dict()


def tool_plan_question(question: str) -> dict:
    return plan_question(question).to_dict()


def tool_verify_answer(repo: str, text: str, question: str | None = None) -> dict:
    return verify_answer(repo, text, question=question).to_dict()


def tool_answer_contract(repo: str, text: str, question: str | None = None) -> dict:
    return build_answer_contract(repo, text, question=question).to_dict()


def tool_workflow_run(repo: str, question: str, answer_text: str | None = None) -> dict:
    return workflow_run(repo, question, answer_text=answer_text).to_dict()


def tool_workflow_history(repo: str, limit: int = 20, offset: int = 0) -> dict:
    return read_workflow_sessions(repo, limit=limit, offset=offset)


def tool_real_repo_eval(repo: str, case_file: str) -> dict:
    return run_real_repo_eval(repo, case_file).to_dict()
