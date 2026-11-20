"""Deterministic policy decisions applied to typed provider answers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import (
    ActionGate,
    DecisionResult,
    GuardrailResult,
    ModelTier,
    ToolActionDecision,
)


class RetrievalRoute(str, Enum):
    DIRECT = "direct"
    RETRIEVE = "retrieve"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class PolicyConfig:
    auto_threshold: float = 0.85
    review_threshold: float = 0.60
    guardrail_threshold: float = 0.80


@dataclass(frozen=True)
class RetrievalDecision:
    route: RetrievalRoute
    confidence: float
    reason: str


class RetrievalPolicy:
    """Convert the bounded 'needs retrieval' decision into a code route."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def choose_route(self, result: DecisionResult) -> RetrievalDecision:
        answer = result.answer("needs_retrieval")
        if answer.confidence < self.config.review_threshold:
            return RetrievalDecision(RetrievalRoute.CLARIFY, answer.confidence, "low confidence")
        if bool(answer.value):
            return RetrievalDecision(RetrievalRoute.RETRIEVE, answer.confidence, "retrieval requested")
        if answer.confidence >= self.config.auto_threshold:
            return RetrievalDecision(RetrievalRoute.DIRECT, answer.confidence, "retrieval not needed")
        return RetrievalDecision(RetrievalRoute.CLARIFY, answer.confidence, "below auto threshold")


class TripartitePolicy:
    """Apply the three-tier confidence release gate (Executa, Confirma, Humano)."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def evaluate_gate(self, confidence: float) -> ActionGate:
        if confidence >= self.config.auto_threshold:
            return ActionGate.EXECUTE
        if confidence >= self.config.review_threshold:
            return ActionGate.CONFIRM
        return ActionGate.HUMAN_REVIEW


class ModelTierPolicy:
    """Map decision results or routing context to the cost-calibrated model tier."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def choose_tier(self, route: RetrievalRoute, result: DecisionResult | None = None) -> ModelTier:
        if result and "model_tier" in result.answers:
            val = str(result.answer("model_tier").value).lower()
            if val in ("small", "medium", "large"):
                return ModelTier(val)
        if route is RetrievalRoute.RETRIEVE:
            return ModelTier.LARGE
        return ModelTier.SMALL


class GuardrailPolicy:
    """Evaluate input safety and prompt injection before LLM execution."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def check_input(self, result: DecisionResult) -> GuardrailResult:
        if "is_safe" in result.answers:
            ans = result.answer("is_safe")
            is_safe = bool(ans.value) and ans.confidence >= self.config.guardrail_threshold
            return GuardrailResult(is_safe, ans.confidence, "guardrail passed" if is_safe else "blocked by guardrail")
        if "prompt_injection" in result.answers:
            ans = result.answer("prompt_injection")
            has_injection = bool(ans.value) and ans.confidence >= self.config.guardrail_threshold
            is_safe = not has_injection
            return GuardrailResult(is_safe, ans.confidence, "clean input" if is_safe else "prompt injection detected")
        return GuardrailResult(True, 1.0, "guardrail skipped")


class ToolPolicy:
    """Authorize tool calls deterministically (allow, ask, deny)."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    def authorize(self, result: DecisionResult) -> ToolActionDecision:
        if "tool_action" not in result.answers:
            return ToolActionDecision.ALLOW
        ans = result.answer("tool_action")
        if ans.confidence < self.config.review_threshold:
            return ToolActionDecision.ASK
        val = str(ans.value).lower()
        if val in ("allow", "ask", "deny"):
            return ToolActionDecision(val)
        return ToolActionDecision.ASK
