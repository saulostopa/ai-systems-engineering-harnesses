"""Run the natural-language contract evals through the real ADK + Ollama path.

This is intentionally an opt-in integration check. The default unittest suite
uses scripted providers and remains offline and deterministic.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from adk_app.agent import root_agent


CASES = {
    "direct-greeting": {
        "prompt": "Write a short greeting for a course participant.",
        "status": "direct",
    },
    "deployment-policy": {
        "prompt": "Find the deployment policy in the course documentation and summarize the evidence.",
        "status": "retrieved",
    },
}


async def run_case(case_id: str, case: dict[str, str]) -> dict[str, object]:
    app_name = "adk_rag_harness"
    user_id = f"ollama-eval-{uuid.uuid4().hex[:8]}"
    session_id = uuid.uuid4().hex
    sessions = InMemorySessionService()
    await sessions.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    runner = Runner(agent=root_agent, app_name=app_name, session_service=sessions)
    content = types.Content(role="user", parts=[types.Part(text=case["prompt"])])

    tool_called = False
    tool_result = None
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        event_content = getattr(event, "content", None)
        for part in getattr(event_content, "parts", None) or []:
            function_call = getattr(part, "function_call", None)
            if function_call is not None and getattr(function_call, "name", "") == "run_workflow":
                tool_called = True
            function_response = getattr(part, "function_response", None)
            if function_response is not None and getattr(function_response, "name", "") == "run_workflow":
                tool_result = getattr(function_response, "response", None)

    if not tool_called:
        raise AssertionError(f"{case_id}: Ollama did not call run_workflow")
    if not isinstance(tool_result, dict):
        raise AssertionError(f"{case_id}: run_workflow returned no structured response")
    if tool_result.get("status") != case["status"]:
        raise AssertionError(
            f"{case_id}: expected status {case['status']!r}, got {tool_result.get('status')!r}"
        )
    if case["status"] == "retrieved" and not tool_result.get("evidence"):
        raise AssertionError(f"{case_id}: retrieved route returned no evidence")
    return {
        "id": case_id,
        "status": tool_result["status"],
        "confidence": tool_result.get("confidence"),
        "tool_called": tool_called,
        "evidence_count": len(tool_result.get("evidence", [])),
    }


async def main() -> None:
    if os.getenv("HARNESS_OFFLINE", "1") != "1":
        raise SystemExit("Run this integration eval with HARNESS_OFFLINE=1.")
    results = []
    for case_id, case in CASES.items():
        results.append(await run_case(case_id, case))
    print(json.dumps({"model": os.getenv("OLLAMA_MODEL", "llama3.1:8b"), "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
