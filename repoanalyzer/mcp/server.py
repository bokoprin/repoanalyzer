from __future__ import annotations

import argparse

from . import tools


def main() -> None:
    parser = argparse.ArgumentParser(description="repoanalyzer MCP server")
    parser.add_argument("--repo", required=True)
    args = parser.parse_args()

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - optional dependency path
        raise SystemExit("The 'mcp' package is required. Install with `pip install -e .[mcp]`.") from exc

    mcp = FastMCP("repoanalyzer")
    repo = args.repo

    @mcp.tool()
    def server_info() -> dict:
        return tools.server_info(repo)

    @mcp.tool()
    def repo_status() -> dict:
        return tools.tool_repo_status(repo)

    @mcp.tool()
    def query_diagnostics() -> dict:
        return tools.tool_query_diagnostics(repo)

    @mcp.tool()
    def read_file_range(path: str, start_line: int, end_line: int) -> dict:
        return tools.tool_read_file_range(repo, path, start_line, end_line)

    @mcp.tool()
    def find_definitions(symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
        return tools.tool_find_definitions(repo, symbol, limit, offset)

    @mcp.tool()
    def find_definitions_page(symbol: str, limit: int | None = None, offset: int = 0) -> dict:
        return tools.tool_find_definitions_page(repo, symbol, limit, offset)

    @mcp.tool()
    def find_references(symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
        return tools.tool_find_references(repo, symbol, limit, offset)

    @mcp.tool()
    def find_references_page(symbol: str, limit: int | None = None, offset: int = 0) -> dict:
        return tools.tool_find_references_page(repo, symbol, limit, offset)

    @mcp.tool()
    def find_callers(symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
        return tools.tool_find_callers(repo, symbol, limit, offset)

    @mcp.tool()
    def find_callers_page(symbol: str, limit: int | None = None, offset: int = 0) -> dict:
        return tools.tool_find_callers_page(repo, symbol, limit, offset)

    @mcp.tool()
    def find_callees(symbol: str, limit: int | None = None, offset: int = 0) -> list[dict]:
        return tools.tool_find_callees(repo, symbol, limit, offset)

    @mcp.tool()
    def find_callees_page(symbol: str, limit: int | None = None, offset: int = 0) -> dict:
        return tools.tool_find_callees_page(repo, symbol, limit, offset)

    @mcp.tool()
    def collect_evidence(question: str, mode: str | None = None) -> dict:
        return tools.tool_collect_evidence(repo, question, mode)

    @mcp.tool()
    def verify_claim(claim: dict) -> dict:
        return tools.tool_verify_claim(repo, claim)

    @mcp.tool()
    def verify_claims(claims: list[dict]) -> dict:
        return tools.tool_verify_claims(repo, claims)

    @mcp.tool()
    def extract_claims(text: str) -> dict:
        return tools.tool_extract_claims(text)

    @mcp.tool()
    def verify_text(text: str) -> dict:
        return tools.tool_verify_text(repo, text)

    @mcp.tool()
    def preflight() -> dict:
        return tools.tool_preflight(repo)

    @mcp.tool()
    def plan_question(question: str) -> dict:
        return tools.tool_plan_question(question)

    @mcp.tool()
    def verify_answer(text: str, question: str | None = None) -> dict:
        return tools.tool_verify_answer(repo, text, question)

    @mcp.tool()
    def answer_contract(text: str, question: str | None = None) -> dict:
        return tools.tool_answer_contract(repo, text, question)

    @mcp.tool()
    def workflow_run(question: str, answer_text: str | None = None) -> dict:
        return tools.tool_workflow_run(repo, question, answer_text)

    @mcp.tool()
    def workflow_history(limit: int = 20, offset: int = 0) -> dict:
        return tools.tool_workflow_history(repo, limit, offset)

    @mcp.tool()
    def real_repo_eval(case_file: str) -> dict:
        return tools.tool_real_repo_eval(repo, case_file)

    mcp.run()


if __name__ == "__main__":
    main()
