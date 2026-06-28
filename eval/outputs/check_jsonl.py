import json
from pathlib import Path


paths = [
    Path("eval/outputs/tinyusb_answers_cline.jsonl"),
    Path("eval/outputs/tinyusb_answers_qwen_code.jsonl"),
]

required = [
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

for path in paths:
    print(f"checking {path}")
    if not path.exists():
        print("  MISSING")
        continue

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"  lines={len(lines)}")

    for i, line in enumerate(lines, 1):
        try:
            obj = json.loads(line)
        except Exception as exc:
            print(f"  JSON ERROR line {i}: {exc}")
            continue

        missing = [key for key in required if key not in obj]
        if missing:
            print(f"  MISSING KEYS line {i}: {missing}")
    print("  done")
