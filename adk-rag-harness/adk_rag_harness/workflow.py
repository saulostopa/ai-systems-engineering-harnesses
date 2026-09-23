"""Offline-first orchestration slice for the ADK + RAG + Jev harness."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .contracts import (
    DecisionQuestion,
    DecisionProvider,
    DecisionProviderError,
    EvidenceChunk,
    RagAdapter,
    RetrievalRequest,
)
from .policies import RetrievalPolicy, RetrievalRoute


class WorkflowStatus(str, Enum):
    DIRECT = "direct"
    RETRIEVED = "retrieved"
    CLARIFY = "clarify"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class WorkflowResult:
    status: WorkflowStatus
    route_reason: str
    confidence: float
    chunks: tuple[EvidenceChunk, ...] = ()
    collection: str = ""
    strategy: str = ""


class AdkRagWorkflow:
    """Keep provider decisions and RAG retrieval behind explicit boundaries."""

    def __init__(
        self,
        decisions: DecisionProvider,
        rag: RagAdapter,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        self.decisions = decisions
        self.rag = rag
        self.policy = policy or RetrievalPolicy()

    def run(self, request: str) -> WorkflowResult:
        try:
            initial = self.decisions.decide(
                {"request": request},
                [
                    DecisionQuestion(
                        "needs_retrieval",
                        "Does this request require external knowledge or repository evidence?",
                        "noul",
                    )
                ],
            )
        except DecisionProviderError:
            return WorkflowResult(WorkflowStatus.BLOCKED, "decision provider unavailable", 0.0)
        route = self.policy.choose_route(initial)
        if route.route is RetrievalRoute.DIRECT:
            return WorkflowResult(WorkflowStatus.DIRECT, route.reason, route.confidence)
        if route.route is RetrievalRoute.CLARIFY:
            return WorkflowResult(WorkflowStatus.CLARIFY, route.reason, route.confidence)

        try:
            choices = self.decisions.decide(
                {"request": request, "route": route.route.value},
                [
                    DecisionQuestion("collection", "Which knowledge collection should be searched?", "choice", ("docs", "code", "area")),
                    DecisionQuestion("strategy", "Which retrieval strategy should be used?", "choice", ("hybrid", "semantic", "keyword")),
                ],
            )
        except DecisionProviderError:
            return WorkflowResult(WorkflowStatus.BLOCKED, "decision provider unavailable", route.confidence)
        collection = str(choices.answer("collection").value)
        strategy = str(choices.answer("strategy").value)
        if min(choices.answer("collection").confidence, choices.answer("strategy").confidence) < self.policy.config.review_threshold:
            return WorkflowResult(WorkflowStatus.CLARIFY, "retrieval route choices need review", route.confidence)

        try:
            response = self.rag.retrieve(RetrievalRequest(request, collection, strategy))
        except Exception:
            return WorkflowResult(
                WorkflowStatus.BLOCKED,
                "retrieval provider unavailable",
                route.confidence,
                collection=collection,
                strategy=strategy,
            )
        if not response.answerable or not response.chunks:
            return WorkflowResult(WorkflowStatus.BLOCKED, "evidence is insufficient", route.confidence, response.chunks, collection, strategy)
        return WorkflowResult(WorkflowStatus.RETRIEVED, "evidence retrieved", route.confidence, response.chunks, collection, strategy)
