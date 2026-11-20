"""Run the golden questions through the real ADK agent and record routing, evidence and answers.

Run it from adk-rag-harness, with HARNESS_RAG_PROVIDER=postgres. It stops before the
next question once the OpenRouter spend in the ledger reaches --budget.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from google.adk.runners import InMemoryRunner
from google.genai import types

from adk_app.agent import root_agent

EVALS = Path(__file__).resolve().parent


def spent(ledger: Path, since: str) -> float:
    total = 0.0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["ts"] >= since and row.get("provider") == "openrouter":
                total += float(row.get("cost_usd") or 0)
    return total


async def ask(runner, question: dict) -> dict:
    user = f"eval-{question['id']}"
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id=user)
    message = types.Content(role="user", parts=[types.Part(text=question["question"])])
    result = {"id": question["id"], "type": question["type"], "lang": question["lang"], "calls": 0, "answer": ""}
    started = time.perf_counter()
    async for event in runner.run_async(user_id=user, session_id=session.id, new_message=message):
        for part in (event.content.parts if event.content else []) or []:
            if part.function_response:
                response = part.function_response.response or {}
                result["calls"] += 1
                result.update({key: response.get(key) for key in ("status", "route_reason", "collection", "strategy", "action_gate", "confidence")})
                result["evidence"] = [item["source"] for item in response.get("evidence") or []]
            if part.text and not part.thought and event.author != "user":
                result["answer"] += part.text
    result["seconds"] = round(time.perf_counter() - started, 1)
    relevant = question["relevant"]
    result["rank"] = next((rank for rank, source in enumerate(result.get("evidence", []), 1) if source in relevant), None)
    result["cited"] = any(path in result["answer"] for path in relevant)
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--budget", type=float, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    questions = json.loads((EVALS / "biometrik_questions.json").read_text(encoding="utf-8"))["questions"]
    runner = InMemoryRunner(agent=root_agent, app_name="adk_rag_harness")
    results = []
    for question in questions:
        cost = spent(Path(args.ledger), args.since)
        if cost >= args.budget:
            print(f"stopped at {question['id']}: US$ {cost:.4f} of {args.budget}", flush=True)
            break
        try:
            row = await ask(runner, question)
        except Exception as exc:  # noqa: BLE001, one failed question must not lose the others
            row = {"id": question["id"], "type": question["type"], "error": type(exc).__name__}
        results.append(row)
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(row["id"], row.get("status"), row.get("collection"), row.get("strategy"), "rank", row.get("rank"), "cited", row.get("cited"), row.get("seconds"), row.get("error", ""), flush=True)
    print(f"spent US$ {spent(Path(args.ledger), args.since):.4f}", flush=True)


asyncio.run(main())
