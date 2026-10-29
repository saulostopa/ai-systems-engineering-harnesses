"""Specialized agents — reasoning, never authority.

Contract: run(NodeInput) -> NodeOutput.
  - They receive a view of the state (NodeInput.state) — they never mutate it.
  - They produce PROPOSALS (payload, artifacts, proposed_next, review, evidence).
  - They NEVER transition status.

Injectable LLM provider (llm/providers.py): OpenRouter by default (env
OPENROUTER_API_KEY), optional Ollama (OLLAMA_API_URL), offline Stub.
The cost (provider usage) travels in the payload as `llm_cost` — the runner
applies the budget (Limits.llm_budget).
"""

from __future__ import annotations

from typing import Any

from hard_harness.core.schemas import NodeInput, NodeOutput
from hard_harness.llm.providers import LLMProvider, StubProvider, make_provider


class BaseAgent:
    """Common base: receives an injected provider; exposes run(NodeInput)."""

    name = "agent"

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider if provider is not None else make_provider()
        self.system = "You are a Webmotors harness engineering specialist. Be direct and verifiable."

    def _prompt(self, ninput: NodeInput, instructions: str) -> str:
        return f"{instructions}\n\nCONTEXT:\n{ninput.payload}\n"

    def _cost_payload(self) -> dict[str, Any]:
        """Attaches the provider cost (usage) to the payload — the runner decides the budget."""
        usage = getattr(self.provider, "last_usage", None)
        tokens = usage.total if usage else 0
        return {
            "llm_cost": float(tokens) / 1000.0 if tokens else 1.0,
            "llm_tokens": tokens,
            "llm_cost_usd": getattr(self.provider, "last_cost_usd", None),
        }

    def run(self, ninput: NodeInput) -> NodeOutput:
        raise NotImplementedError


class PlannerAgent(BaseAgent):
    """Plans the work: plan proposal, no side effects on the world."""

    name = "planner"

    def run(self, ninput: NodeInput) -> NodeOutput:
        raw = self.provider.complete(
            self._prompt(ninput, "Propose an execution plan in short steps. Start each step with '- '."),
            system=self.system,
        )
        steps = [line.lstrip("- ").strip() for line in raw.splitlines() if line.strip().startswith("-")]
        plan = {"plan_steps": steps[:8], "source": f"llm:{self.provider.name}"}
        plan.update(self._cost_payload())
        return NodeOutput(node_id=self.name, ok=True, payload=plan, proposed_next="validate_plan")


class CoderAgent(BaseAgent):
    """Generates or changes code: produces a PATCH as an artifact (proposal)."""

    name = "coder"

    def run(self, ninput: NodeInput) -> NodeOutput:
        raw = self.provider.complete(
            self._prompt(ninput, "Propose the implementation diff/patch in a ```diff ... ``` block."),
            system=self.system,
        )
        patch_path = ninput.payload.get("patch_path", "/tmp/hard-harness-proposal.patch")
        try:
            with open(patch_path, "w", encoding="utf-8") as fh:
                fh.write(raw)
            artifacts = [{"path": patch_path, "kind": "patch"}]
        except OSError as exc:
            return NodeOutput(node_id=self.name, ok=False, error=f"could not write patch: {exc}")
        payload = {"patch": raw[:2000], "patch_path": patch_path}
        payload.update(self._cost_payload())
        return NodeOutput(node_id=self.name, ok=True, payload=payload, artifacts=artifacts, proposed_next="fanout")


class ReviewerAgent(BaseAgent):
    """Review reasoning: produces ReviewResult as a PROPOSAL."""

    name = "reviewer"

    def run(self, ninput: NodeInput) -> NodeOutput:
        raw = self.provider.complete(
            self._prompt(
                ninput,
                "Review the work. Reply on the last line with VERDICT: approved | changes_requested | rejected",
            ),
            system=self.system,
        )
        verdict = "changes_requested"
        lowered = raw.lower()
        for token in ("approved", "changes_requested", "rejected"):
            if f"verdict: {token}" in lowered:
                verdict = token
                break
        from hard_harness.core.schemas import ReviewResult

        review = ReviewResult(
            verdict=verdict,
            findings=[{"severity": "info", "location": "diff", "issue": raw.strip()[:200]}],
            summary=raw.strip()[:300],
        )
        payload = {"review": review.to_dict(), "reviewer": f"llm:{self.provider.name}"}
        payload.update(self._cost_payload())
        return NodeOutput(node_id=self.name, ok=True, payload=payload, review=review)


class EvidenceAgent(BaseAgent):
    """Evidence synthesis: consolidates gate results into a report."""

    name = "evidence"

    def run(self, ninput: NodeInput) -> NodeOutput:
        joined = ninput.state.data.get("fanout_coder_agent", ninput.payload)
        passed = all(item.get("error") is None for item in joined.values())
        summary = {
            "fanout": {k: ("ok" if v.get("error") is None else v["error"]) for k, v in joined.items()},
            "passed": passed,
        }
        raw = self.provider.complete(
            self._prompt(ninput, "Write 3 lines: what was delivered, what was verified and what remains open."),
            system=self.system,
        )
        summary["synthesis"] = raw.strip()[:600]
        summary.update(self._cost_payload())
        return NodeOutput(node_id=self.name, ok=True, payload=summary)