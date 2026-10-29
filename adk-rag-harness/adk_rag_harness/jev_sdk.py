"""Optional adapter for TypeSafe AI's official Python SDK."""

from __future__ import annotations

import os
import time
from typing import Any

from .contracts import (
    DecisionAnswer,
    DecisionProvider,
    DecisionProviderError,
    DecisionQuestion,
    DecisionResult,
)
from .usage import record_decision


class TypeSafeSdkDecisionProvider(DecisionProvider):
    """Use ``typesafe-sdk`` while keeping the course contract provider-neutral."""

    def __init__(self, api_key: str | None = None, model: str = "jev-latest", *, client: Any | None = None, sdk: Any | None = None) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY")
        self.model = model
        self._client = client
        self._sdk = sdk

    def decide(self, state: dict[str, Any], questions: list[DecisionQuestion]) -> DecisionResult:
        started = time.monotonic()
        try:
            client = self._client or self._new_client()
            response = client.system_one(
                state=state,
                questions={question.name: self._to_sdk_question(question) for question in questions},
                model=self.model,
            )
        except Exception as exc:
            record_decision(provider="typesafe", model=self.model, questions=questions, started=started, error=exc)
            if isinstance(exc, DecisionProviderError):
                raise
            raise DecisionProviderError(f"TypeSafe SDK request failed: {exc}") from exc
        usage = self._to_mapping(getattr(response, "usage", None))
        routed_model = str(getattr(response, "model", "")) or None
        try:
            answers = {
                question.name: self._from_sdk_answer(question, response.answers[question.name])
                for question in questions
            }
        except Exception as exc:
            record_decision(
                provider="typesafe", model=self.model, questions=questions, started=started,
                usage=usage, routed_model=routed_model, error=exc, invalid=True,
            )
            if isinstance(exc, DecisionProviderError):
                raise
            raise DecisionProviderError(f"TypeSafe SDK request failed: {exc}") from exc
        record_decision(
            provider="typesafe", model=self.model, questions=questions, started=started,
            usage=usage, routed_model=routed_model,
        )
        try:
            return DecisionResult(
                answers,
                provider="typesafe-sdk",
                model=str(getattr(response, "model", self.model)),
                metadata={"usage": self._to_mapping(getattr(response, "usage", None))},
            )
        except DecisionProviderError:
            raise
        except Exception as exc:  # SDK errors must fail closed at the contract boundary.
            raise DecisionProviderError(f"TypeSafe SDK request failed: {exc}") from exc

    def _new_client(self) -> Any:
        try:
            TypeSafeClient = self._load_sdk().TypeSafeClient
        except ImportError as exc:
            raise DecisionProviderError(
                "TypeSafe SDK is unavailable; install adk-rag-harness[jev-sdk]."
            ) from exc
        return TypeSafeClient(api_key=self.api_key) if self.api_key else TypeSafeClient()

    def _to_sdk_question(self, question: DecisionQuestion) -> Any:
        try:
            sdk = self._load_sdk()
            Choice, Noul, Score = sdk.Choice, sdk.Noul, sdk.Score
        except ImportError as exc:
            raise DecisionProviderError(
                "TypeSafe SDK is unavailable; install adk-rag-harness[jev-sdk]."
            ) from exc
        if question.type == "noul":
            return Noul(instructions=question.instruction)
        if question.type == "choice":
            if not question.options:
                raise DecisionProviderError(f"Choice question '{question.name}' requires options")
            return Choice(
                instructions=question.instruction,
                criteria={option: f"Select {option}." for option in question.options},
            )
        if question.type == "score":
            if not question.options:
                raise DecisionProviderError(f"Score question '{question.name}' requires options")
            return Score(instructions=question.instruction, criteria=list(question.options))
        raise DecisionProviderError(f"Unsupported question type: {question.type}")

    def _load_sdk(self) -> Any:
        if self._sdk is not None:
            return self._sdk
        try:
            import typesafe_sdk
        except ImportError as exc:
            raise DecisionProviderError(
                "TypeSafe SDK is unavailable; install adk-rag-harness[jev-sdk]."
            ) from exc
        self._sdk = typesafe_sdk
        return typesafe_sdk

    @classmethod
    def _from_sdk_answer(cls, question: DecisionQuestion, answer: Any) -> DecisionAnswer:
        if question.type == "noul":
            probability = float(getattr(answer, "noul"))
            return DecisionAnswer(probability >= 0.5, max(probability, 1.0 - probability))
        if question.type == "choice":
            return DecisionAnswer(
                getattr(answer, "choice"),
                float(getattr(answer, "confidence", 0.0)),
            )
        if question.type == "score":
            return DecisionAnswer(
                float(getattr(answer, "score")),
                float(getattr(answer, "confidence", 0.0)),
            )
        raise DecisionProviderError(f"Unsupported question type: {question.type}")

    @staticmethod
    def _to_mapping(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if hasattr(value, "model_dump"):
            return dict(value.model_dump())
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return {"value": value}
