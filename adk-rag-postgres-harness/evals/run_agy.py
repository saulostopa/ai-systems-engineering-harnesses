"""Ask agy the golden questions through its MCP tools and record what it used.

Run it from the target repository. Permissions last for the session only and are
read-only: headless agy denies anything else, including `remember`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

EVALS = Path(__file__).resolve().parent
READ_ONLY = ["search_code", "find_symbol", "read_lines", "recall"]
ALLOW = [f"mcp(code-memory/{tool})" for tool in READ_ONLY] + ["command(grep)", "command(rg)", "read_file(*)"]


def ask(question: dict, model: str) -> dict:
    prompt = f"{question['question']} Responda em até 5 linhas, citando arquivo. Não altere nada."
    run = subprocess.run(
        ["agy", "--print", prompt, "--mode", "plan", "--model", model,
         "--settings", json.dumps({"permissions": {"allow": ALLOW}}),
         "--output-format", "stream-json", "--print-timeout", "200s"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=260,
    )
    tools: Counter = Counter()
    order: list[str] = []
    result: dict = {}
    for line in run.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        step = event.get("step_update") or {}
        if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
            parameters = (step.get("tool_info") or {}).get("parameters") or {}
            name = step.get("tool_name")
            if name == "call_mcp_tool":
                name = f"mcp:{parameters.get('ToolName')}"
            tools[name] += 1
            order.append(name)
        if event.get("event") == "result":
            result = event["result"]
    answer = result.get("response") or ""
    return {
        "id": question["id"],
        "type": question["type"],
        "tools": dict(tools),
        "first_tool": order[0] if order else None,
        "used_mcp": any(name.startswith("mcp:") for name in tools),
        "cited": any(path in answer for path in question["relevant"]),
        "seconds": round(result.get("duration_seconds") or 0, 1),
        "tokens": (result.get("usage") or {}).get("total_tokens"),
        "denied": result.get("denied_actions"),
        "answer": answer,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True)
    parser.add_argument("--model", default="gemini-3.8-flash-medium")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    questions = {q["id"]: q for q in json.loads((EVALS / "biometrik_questions.json").read_text(encoding="utf-8"))["questions"]}
    rows = []
    for key in args.ids.split(","):
        row = ask(questions[key], args.model)
        rows.append(row)
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(key, "first", row["first_tool"], "mcp", row["used_mcp"], "cited", row["cited"], row["tools"], row["seconds"], row["tokens"], "denied", row["denied"], flush=True)


if __name__ == "__main__":
    main()
