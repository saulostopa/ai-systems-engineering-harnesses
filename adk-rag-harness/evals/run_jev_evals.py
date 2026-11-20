"""Run the workflow against the live Jev decision provider.

This is an opt-in integration check. It requires TYPESAFE_API_KEY and never
prints the key or the raw provider response.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from adk_rag_harness.contracts import EvidenceChunk, RetrievalResponse
from adk_rag_harness.jev import JevDecisionProvider
from adk_rag_harness.workflow import AdkRagWorkflow


class DemoRag:
    def retrieve(self, request):
        chunk = EvidenceChunk(
            source="jev-integration/demo-policy.md",
            text=f"Live Jev integration evidence for: {request.query}",
            score=1.0,
        )
        return RetrievalResponse(request, (chunk,), True, "integration evidence")


class RecordingJev:
    def __init__(self):
        self.provider = JevDecisionProvider()
        self.calls = 0
        self.models = []

    def decide(self, state, questions):
        self.calls += 1
        result = self.provider.decide(state, questions)
        self.models.append(result.model)
        return result


PROMPTS = {
    "direct-greeting": "Write a short greeting for a course participant.",
    "deployment-policy": "Find the deployment policy in the course documentation and summarize the evidence.",
}


def main() -> None:
    if not os.getenv("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY is required for the live Jev evaluation.")

    results = []
    for case_id, prompt in PROMPTS.items():
        decisions = RecordingJev()
        result = AdkRagWorkflow(decisions, DemoRag()).run(prompt)
        results.append(
            {
                "id": case_id,
                "status": result.status.value,
                "confidence": result.confidence,
                "collection": result.collection,
                "strategy": result.strategy,
                "evidence_count": len(result.chunks),
                "decision_calls": decisions.calls,
                "provider_models": decisions.models,
            }
        )

    print(json.dumps({"provider": "jev", "results": results}, indent=2))


if __name__ == "__main__":
    main()
