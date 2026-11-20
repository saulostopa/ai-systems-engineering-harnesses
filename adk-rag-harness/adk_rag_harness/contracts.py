"""Stable contracts between decision providers, policies and RAG adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class QuestionType(str, Enum):
    NOUL = "noul"
    CHOICE = "choice"
    SCORE = "score"


class ModelTier(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class ToolActionDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ActionGate(str, Enum):
    EXECUTE = "execute"
    CONFIRM = "confirm"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class GuardrailResult:
    is_safe: bool
    confidence: float
    reason: str = ""


@dataclass(frozen=True)
class DecisionQuestion:
    name: str
    instruction: str
    type: QuestionType
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionAnswer:
    value: Any
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, DecisionAnswer]
    provider: str = "unknown"
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def answer(self, name: str) -> DecisionAnswer:
        try:
            return self.answers[name]
        except KeyError as exc:
            raise ValueError(f"missing decision answer: {name}") from exc


class DecisionProvider(Protocol):
    def decide(
        self,
        state: dict[str, Any],
        questions: list[DecisionQuestion],
    ) -> DecisionResult:
        """Return typed answers without generating workflow prose."""


class DecisionProviderError(RuntimeError):
    """A provider failed; callers must use a safe deterministic fallback."""


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    collection: str
    strategy: str
    top_k: int = 5
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceChunk:
    source: str
    text: str
    score: float
    start_line: int | None = None
    end_line: int | None = None
    # The file changed after indexing, so the lines may have moved.
    stale: bool = False


@dataclass(frozen=True)
class RetrievalResponse:
    request: RetrievalRequest
    chunks: tuple[EvidenceChunk, ...]
    answerable: bool
    reason: str = ""


class RagAdapter(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        """Retrieve evidence without deciding workflow transitions."""
