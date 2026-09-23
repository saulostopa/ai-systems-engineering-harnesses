"""Deterministic policy decisions applied to typed provider answers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import DecisionResult


class RetrievalRoute(str, Enum):
    DIRECT = "direct"
    RETRIEVE = "retrieve"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class PolicyConfig:
    auto_threshold: float = 0.85
    review_threshold: float = 0.60


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
