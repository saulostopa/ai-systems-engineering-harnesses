"""Ask Claude Code the golden questions through its MCP tools and record what it used.

Run it from the target repository. Grep and Read stay allowed, to see what the agent
prefers by itself; nothing that writes is allowed, and remember is blocked.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

EVALS = Path(__file__).resolve().parent
READ_ONLY = ["search_code", "find_symbol", "read_lines", "recall"]
ALLOWED = [f"mcp__code-memory__{tool}" for tool in READ_ONLY] + ["Read", "Grep", "Glob", "Bash(grep:*)", "Bash(rtk grep:*)"]
BLOCKED = ["Edit", "Write", "NotebookEdit", "mcp__code-memory__remember"]


def ask(question: dict, model: str) -> dict:
    prompt = f"{question['question']} Responda em até 5 linhas, citando arquivo. Não altere nada."
    run = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--allowedTools", ",".join(ALLOWED),
         "--disallowedTools", ",".join(BLOCKED), "--output-format", "stream-json", "--verbose"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300,
    )
    tools: Counter = Counter()
    order: list[str] = []
    result: dict = {}
    for line in run.stdout.splitlines():
        event = json.loads(line)
        if event.get("type") == "assistant":
            for block in event["message"]["content"]:
                if block.get("type") == "tool_use":
                    tools[block["name"]] += 1
                    order.append(block["name"])
        if event.get("type") == "result":
            result = event
    answer = result.get("result") or ""
    return {
        "id": question["id"],
        "type": question["type"],
        "tools": dict(tools),
        "first_tool": order[0] if order else None,
        "used_mcp": any(name.startswith("mcp__code-memory__") for name in tools),
        "cited": any(path in answer for path in question["relevant"]),
        "seconds": round((result.get("duration_ms") or 0) / 1000, 1),
        "listed_cost_usd": result.get("total_cost_usd"),
        "answer": answer,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    questions = {q["id"]: q for q in json.loads((EVALS / "biometrik_questions.json").read_text(encoding="utf-8"))["questions"]}
    rows = []
    for key in args.ids.split(","):
        row = ask(questions[key], args.model)
        rows.append(row)
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(key, "first", row["first_tool"], "mcp", row["used_mcp"], "cited", row["cited"], row["tools"], row["seconds"], row["listed_cost_usd"], flush=True)


if __name__ == "__main__":
    main()
