from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
CASES_CSV = REPO_ROOT / "eval" / "agent_compare" / "tinyusb_mcp_golden_cases.csv"
OUTPUT_DIR = REPO_ROOT / "eval" / "outputs"
DATA_DIR = REPO_ROOT / ".tmp-cline"
CLINE_CWD = DATA_DIR / "workdir"
MCP_SETTINGS = DATA_DIR / "settings" / "cline_mcp_settings.json"
CLINE_ANSWERS = OUTPUT_DIR / "tinyusb_answers_cline.jsonl"
EVENTS_DIR = OUTPUT_DIR / "cline_events"
MODEL = "qwen3.6:27b_q4_k_s"
RUN_ID = "cline-cli-golden-20260627"
SYSTEM_PROMPT = (
    "Follow the Cline Rules. For TinyUSB source-code questions, use repoanalyzer-tinyusb MCP first. "
    "Return exactly one JSON object and no Markdown."
)


REQUIRED_KEYS = [
    "run_id",
    "agent_id",
    "model",
    "case_id",
    "profile",
    "question",
    "tool_trace",
    "evidence",
    "answer",
    "verdict",
    "confidence",
    "self_check",
    "known_limitations",
]


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    CLINE_CWD.mkdir(parents=True, exist_ok=True)
    MCP_SETTINGS.parent.mkdir(parents=True, exist_ok=True)


def ensure_mcp_settings() -> None:
    settings = {
        "mcpServers": {
            "repoanalyzer-tinyusb": {
                "transport": {
                    "type": "stdio",
                    "command": str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
                    "args": [
                        "-m",
                        "repoanalyzer.mcp.server",
                        "--repo",
                        r"C:\shinsuke\app\tinyusb",
                    ],
                },
                "disabled": False,
                "autoApprove": [
                    "server_info",
                    "repo_status",
                    "query_diagnostics",
                    "collect_evidence",
                    "find_definitions",
                    "find_definitions_page",
                    "find_references",
                    "find_references_page",
                    "find_callers",
                    "find_callers_page",
                    "find_callees",
                    "find_callees_page",
                    "read_file_range",
                    "verify_answer",
                    "answer_contract",
                ],
            }
        }
    }
    MCP_SETTINGS.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cases(limit: int | None = None) -> list[dict[str, str]]:
    with CASES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        cases = list(csv.DictReader(f))
    return cases[:limit] if limit else cases


def build_case_prompt(case: dict[str, str]) -> str:
    return f"""
QUESTION_TO_ANSWER: {case["question"]}

case_id: {case["case_id"]}
profile: {case["profile"]}
required_tools: {case["required_tools"]}

TinyUSB golden evaluation. Answer this one case using repoanalyzer-tinyusb MCP.
Use collect_evidence first. Use read_file_range before answering. Do not use ask_question, workflow_history, shell, editor, browser, previous outputs, or direct file reads.
Return exactly this JSON object shape:
{{
  "run_id": "{RUN_ID}",
  "agent_id": "cline",
  "model": "{MODEL}",
  "case_id": "{case["case_id"]}",
  "profile": "{case["profile"]}",
  "question": "{case["question"]}",
  "tool_trace": [],
  "evidence": [],
  "answer": "",
  "verdict": "supported|conditional|unknown|unsupported|mixed",
  "confidence": "high|medium|low",
  "self_check": {{
    "used_collect_evidence": true,
    "used_read_file_range": true,
    "mentioned_required_files": true,
    "mentioned_required_symbols": true,
    "avoided_forbidden_claims": true,
    "notes": ""
  }},
  "known_limitations": [],
  "repoanalyzer_fix_suggestions": [],
  "agent_notes": ""
}}
""".strip()


def build_repair_prompt(case: dict[str, str], previous_text: str, tool_names: list[str]) -> str:
    clipped = previous_text[:12000]
    return f"""
Convert the previous Cline answer for one RepoAnalyzer TinyUSB golden case into valid JSON.

Do not call any tools. Do not inspect files. Do not add Markdown. Output exactly one JSON object on one line.
Use only the information in PREVIOUS_TEXT and TOOL_NAMES. If evidence is incomplete, mark verdict "unknown" or "mixed" and explain in known_limitations.

case_id: {case["case_id"]}
profile: {case["profile"]}
question: {case["question"]}
run_id: {RUN_ID}
agent_id: cline
model: {MODEL}
TOOL_NAMES: {json.dumps(tool_names, ensure_ascii=False)}

PREVIOUS_TEXT:
{clipped}

Required keys:
{", ".join(REQUIRED_KEYS)}, repoanalyzer_fix_suggestions, agent_notes
""".strip()


def run_cline(prompt: str, timeout: int, event_path: Path) -> tuple[int, list[dict[str, Any]], str]:
    return run_cline_with_auto_approve(prompt, timeout, event_path, auto_approve=True)


def run_cline_with_auto_approve(
    prompt: str, timeout: int, event_path: Path, *, auto_approve: bool
) -> tuple[int, list[dict[str, Any]], str]:
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    cmd = [
        npx,
        "-y",
        "cline",
        "--data-dir",
        str(DATA_DIR),
        "--cwd",
        str(CLINE_CWD),
        "--json",
        "--thinking",
        "none",
        "--provider",
        "openai-compatible",
        "--model",
        MODEL,
        "--system",
        SYSTEM_PROMPT,
        "--timeout",
        str(timeout),
        "--auto-approve",
        "true" if auto_approve else "false",
        prompt,
    ]
    env = os.environ.copy()
    env["AI_SDK_LOG_WARNINGS"] = "false"
    proc = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        timeout=timeout + 60,
    )
    event_path.write_text(proc.stdout, encoding="utf-8")
    events: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            pass
    return proc.returncode, events, proc.stdout


def extract_run_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("type") == "run_result":
            return str(event.get("text") or "")
    for event in reversed(events):
        inner = event.get("event") or {}
        if inner.get("type") == "done":
            return str(inner.get("text") or "")
    return ""


def extract_tool_trace(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    trace: list[dict[str, str]] = []
    for event in events:
        inner = event.get("event") or {}
        if inner.get("type") == "content_start" and inner.get("contentType") == "tool":
            tool = str(inner.get("toolName") or "")
            input_obj = inner.get("input")
            trace.append(
                {
                    "tool": tool.replace("repoanalyzer-tinyusb__", ""),
                    "purpose": "called by Cline CLI during golden case execution",
                    "input_summary": compact_json(input_obj),
                    "output_summary": "",
                }
            )
        elif inner.get("type") == "content_end" and inner.get("contentType") == "tool":
            if trace:
                trace[-1]["output_summary"] = summarize_tool_output(inner.get("output"))
    return trace


def compact_json(value: Any, limit: int = 260) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    return text[:limit] + ("..." if len(text) > limit else "")


def summarize_tool_output(value: Any, limit: int = 360) -> str:
    if not value:
        return ""
    text = compact_json(value, limit=2000)
    if '"isError": true' in text or "Error executing tool" in text:
        prefix = "error: "
    else:
        prefix = "ok: "
    return prefix + text[:limit] + ("..." if len(text) > limit else "")


def parse_json_answer(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None


def split_case_list(value: str) -> list[str]:
    return [item.strip() for item in str(value or "").split(";") if item.strip()]


def answer_search_text(obj: dict[str, Any], trace: list[dict[str, str]]) -> str:
    searchable = {
        "answer": obj.get("answer"),
        "details": obj.get("details"),
        "evidence": obj.get("evidence"),
        "tool_trace": trace,
    }
    try:
        return json.dumps(searchable, ensure_ascii=False)
    except Exception:
        return str(searchable)


def contains_all_needles(haystack: str, needles: list[str]) -> bool:
    return all(needle in haystack for needle in needles)


def contains_any_forbidden_claim(haystack: str, forbidden_claims: list[str]) -> bool:
    for claim in forbidden_claims:
        if claim and claim in haystack:
            return True
    return False


def build_runner_self_check(
    case: dict[str, str],
    obj: dict[str, Any],
    trace: list[dict[str, str]],
    note: str = "self_check recomputed by runner",
) -> dict[str, Any]:
    text = answer_search_text(obj, trace)
    required_files = split_case_list(case.get("required_files", ""))
    required_symbols = split_case_list(case.get("required_symbols", ""))
    forbidden_claims = split_case_list(case.get("forbidden_claims", ""))
    return {
        "used_collect_evidence": any(t["tool"] == "collect_evidence" for t in trace),
        "used_read_file_range": any(t["tool"] == "read_file_range" for t in trace),
        "mentioned_required_files": contains_all_needles(text, required_files),
        "mentioned_required_symbols": contains_all_needles(text, required_symbols),
        "avoided_forbidden_claims": not contains_any_forbidden_claim(text, forbidden_claims),
        "notes": note,
        "required_files_missing": [path for path in required_files if path not in text],
        "required_symbols_missing": [symbol for symbol in required_symbols if symbol not in text],
    }


def normalize_answer(case: dict[str, str], obj: dict[str, Any], trace: list[dict[str, str]]) -> dict[str, Any]:
    obj["run_id"] = str(obj.get("run_id") or RUN_ID)
    obj["agent_id"] = "cline"
    obj["model"] = MODEL
    obj["case_id"] = case["case_id"]
    obj["profile"] = case["profile"]
    obj["question"] = case["question"]
    obj["tool_trace"] = trace
    obj.setdefault("evidence", [])
    obj.setdefault("answer", "")
    obj.setdefault("verdict", "unknown")
    obj.setdefault("confidence", "low")
    obj.setdefault("known_limitations", [])
    obj.setdefault("repoanalyzer_fix_suggestions", [])
    obj.setdefault("agent_notes", "")
    existing_self_check = obj.get("self_check") if isinstance(obj.get("self_check"), dict) else {}
    runner_self_check = build_runner_self_check(case, obj, trace)
    obj["self_check"] = {**existing_self_check, **runner_self_check}
    return obj


def disallowed_tools(trace: list[dict[str, str]]) -> list[str]:
    allowed = {
        "collect_evidence",
        "read_file_range",
        "find_definitions",
        "find_definitions_page",
        "find_references",
        "find_references_page",
        "find_callers",
        "find_callers_page",
        "find_callees",
        "find_callees_page",
    }
    return sorted({t["tool"] for t in trace if t["tool"] not in allowed})


def failure_answer(case: dict[str, str], trace: list[dict[str, str]], reason: str) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "agent_id": "cline",
        "model": MODEL,
        "case_id": case["case_id"],
        "profile": case["profile"],
        "question": case["question"],
        "tool_trace": trace,
        "evidence": [],
        "answer": "",
        "verdict": "unknown",
        "confidence": "low",
        "self_check": build_runner_self_check(case, {"answer": "", "evidence": []}, trace, note=reason),
        "known_limitations": [reason],
        "repoanalyzer_fix_suggestions": [],
        "agent_notes": "generated by runner failure path",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()

    ensure_dirs()
    ensure_mcp_settings()
    cases = load_cases(args.limit)
    CLINE_ANSWERS.write_text("", encoding="utf-8")

    summary: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        case_id = case["case_id"]
        print(f"[{index}/{len(cases)}] running {case_id}", flush=True)
        event_path = EVENTS_DIR / f"{case_id}.events.jsonl"
        repair_event_path = EVENTS_DIR / f"{case_id}.repair.events.jsonl"

        try:
            code, events, _ = run_cline(build_case_prompt(case), args.timeout, event_path)
            text = extract_run_text(events)
            trace = extract_tool_trace(events)
            obj = parse_json_answer(text)
            repaired = False
            if obj is None:
                print(f"[{index}/{len(cases)}] repair {case_id}", flush=True)
                tool_names = [t["tool"] for t in trace]
                _, repair_events, _ = run_cline_with_auto_approve(
                    build_repair_prompt(case, text, tool_names),
                    180,
                    repair_event_path,
                    auto_approve=False,
                )
                repair_text = extract_run_text(repair_events)
                repair_trace = extract_tool_trace(repair_events)
                obj = parse_json_answer(repair_text)
                trace.extend(repair_trace)
                repaired = True
            if obj is None:
                answer = failure_answer(case, trace, f"Cline output was not parseable as JSON; exit_code={code}")
                ok = False
            else:
                answer = normalize_answer(case, obj, trace)
                ok = True
            bad_tools = disallowed_tools(trace)
            if bad_tools:
                answer.setdefault("known_limitations", []).append(
                    "Cline called disallowed non-evaluation tools: " + ", ".join(bad_tools)
                )
                answer["agent_notes"] = (str(answer.get("agent_notes") or "") + " disallowed_tools_detected").strip()
            with CLINE_ANSWERS.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(answer, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary.append(
                {
                    "case_id": case_id,
                    "ok": ok,
                    "repaired": repaired,
                    "tool_count": len(trace),
                    "used_collect_evidence": any(t["tool"] == "collect_evidence" for t in trace),
                    "used_read_file_range": any(t["tool"] == "read_file_range" for t in trace),
                    "disallowed_tools": bad_tools,
                    "event_file": str(event_path.relative_to(REPO_ROOT)),
                }
            )
            print(f"[{index}/{len(cases)}] done {case_id} ok={ok} repaired={repaired}", flush=True)
        except Exception as exc:
            trace: list[dict[str, str]] = []
            answer = failure_answer(case, trace, f"runner exception: {type(exc).__name__}: {exc}")
            with CLINE_ANSWERS.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(answer, ensure_ascii=False, separators=(",", ":")) + "\n")
            summary.append({"case_id": case_id, "ok": False, "error": str(exc)})
            print(f"[{index}/{len(cases)}] error {case_id}: {exc}", flush=True)

    summary_path = OUTPUT_DIR / "cline_cli_eval_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {CLINE_ANSWERS}")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
