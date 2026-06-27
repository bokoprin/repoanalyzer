# TinyUSB MCP E2E setup

This document sets up the first operational end-to-end loop for repoanalyzer:

`user question -> LLM -> repoanalyzer MCP -> collect_evidence / find_* -> read_file_range -> LLM answer`

The recommended first target is TinyUSB `examples/device/cdc_msc` using the generated `tinyusb_upstream_device_cdc_msc` profile.

## 1. Install repoanalyzer with MCP support

```powershell
git clone https://github.com/bokoprin/repoanalyzer.git
cd repoanalyzer
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,mcp]"
```

## 2. Clone TinyUSB

```powershell
cd C:\Users\bokop\OneDrive\デスクトップ
git clone https://github.com/hathach/tinyusb.git
```

## 3. Build a TinyUSB index for MCP

From the repoanalyzer checkout:

```powershell
cd C:\Users\bokop\OneDrive\デスクトップ\repoanalyzer
.\.venv\Scripts\Activate.ps1
python -m repoanalyzer.cli tinyusb-upstream-index C:\Users\bokop\OneDrive\デスクトップ\tinyusb --profile tinyusb_upstream_device_cdc_msc
```

The command prepares `.repoanalyzer-smoke/` inside the TinyUSB checkout, runs a full ingest with the selected profile, and prints the MCP server command to use.

## 4. Start the MCP server manually

```powershell
python -m repoanalyzer.mcp.server --repo C:\Users\bokop\OneDrive\デスクトップ\tinyusb
```

Keep this process running while the LLM client is connected.

## 5. Register in an MCP client

Use `docs/examples/cline_mcp_config.json` as a template.  Adjust paths to match your checkout and virtual environment.

## 6. LLM operating rules

Give the LLM the contents of `docs/LLM_REPOANALYZER_USAGE_RULES.md` as project rules or system/developer instructions in the MCP client.

The critical rule is: repoanalyzer facts are candidates.  The LLM must call `read_file_range` on returned file/line ranges before finalizing the answer.

## 7. Golden E2E questions

Use these first:

```text
TinyUSBのCDC/MSC configuration descriptorはどこで定義されている？

dcd_event_handler から tud_task まではどうつながる？

endpoint transfer完了時にclass driverのxfer_cbへdispatchされる流れは？
```

Expected tool pattern:

1. `preflight()`
2. `collect_evidence(question)`
3. inspect relevant `facts`
4. `read_file_range(path, start_line, end_line)`
5. answer with supported / conditional / unknown distinctions
6. optional `verify_answer(answer, question)` or `answer_contract(answer, question)`

## 8. Troubleshooting

- If `preflight` says the index is missing, rerun `tinyusb-upstream-index`.
- If `preflight` says the index is dirty, rerun `tinyusb-upstream-index` before making completeness or absence claims.
- If `collect_evidence` is low confidence, use focused tools such as `find_definitions_page`, `find_callers_page`, `find_callees_page`, and then `read_file_range`.
- If the MCP client cannot start the server, first run the `python -m repoanalyzer.mcp.server --repo ...` command manually in PowerShell to see the real error.
