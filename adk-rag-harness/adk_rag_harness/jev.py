"""Small, dependency-free adapter for TypeSafe's Jev System One API."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import (
    DecisionAnswer,
    DecisionProviderError,
    DecisionQuestion,
    DecisionResult,
    QuestionType,
)


JsonTransport = Callable[[dict[str, Any]], dict[str, Any]]


class JevDecisionProvider:
    """Translate course questions to Jev and normalize typed answers.

    The transport is injectable so policy tests never need a network or API key.
    The adapter only returns decisions; it never executes a workflow action.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "jev-latest",
        endpoint: str = "https://api.typesafe.ai/v1/systemone",
        timeout_s: float = 10.0,
        transport: JsonTransport | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TYPESAFE_API_KEY")
        self.model = model
        self.endpoint = endpoint
        self.timeout_s = timeout_s
        self.transport = transport or self._http_transport

    @staticmethod
    def _serialize_question(question: DecisionQuestion) -> dict[str, Any]:
        if question.type is QuestionType.NOUL or question.type == QuestionType.NOUL.value:
            return {
                "type": "noul",
                "instructions": question.instruction,
                "criteria": {"true": "The answer is yes or true.", "false": "The answer is no or false."},
            }
        if question.type is QuestionType.CHOICE or question.type == QuestionType.CHOICE.value:
            if not question.options:
                raise DecisionProviderError(f"choice question {question.name!r} has no options")
            return {
                "type": "choice",
                "instructions": question.instruction,
                "criteria": {option: f"Select {option}." for option in question.options},
            }
        if question.type is QuestionType.SCORE or question.type == QuestionType.SCORE.value:
            if not question.options:
                raise DecisionProviderError(f"score question {question.name!r} has no score levels")
            return {
                "type": "score",
                "instructions": question.instruction,
                "criteria": list(question.options),
            }
        raise DecisionProviderError(f"unsupported question type: {question.type!r}")

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise DecisionProviderError("TYPESAFE_API_KEY is required for the live Jev provider")
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DecisionProviderError(f"Jev request failed: {exc}") from exc

    @staticmethod
    def _normalize_answer(name: str, raw: Any) -> DecisionAnswer:
        if not isinstance(raw, dict):
            raise DecisionProviderError(f"Jev answer {name!r} is not an object")
        answer_type = raw.get("type")
        if answer_type == "noul":
            probability = raw.get("noul")
            if not isinstance(probability, (int, float)):
                raise DecisionProviderError(f"Jev Noul answer {name!r} has no probability")
            probability = float(probability)
            return DecisionAnswer(probability >= 0.5, max(probability, 1.0 - probability))
        if answer_type == "choice":
            choice = raw.get("choice")
            confidence = raw.get("confidence")
            if not isinstance(choice, str) or not isinstance(confidence, (int, float)):
                raise DecisionProviderError(f"Jev Choice answer {name!r} is incomplete")
            return DecisionAnswer(choice, float(confidence))
        if answer_type == "score":
            score = raw.get("score")
            confidence = raw.get("confidence")
            if not isinstance(score, (int, float)) or not isinstance(confidence, (int, float)):
                raise DecisionProviderError(f"Jev Score answer {name!r} is incomplete")
            return DecisionAnswer(float(score), float(confidence))
        raise DecisionProviderError(f"Jev answer {name!r} has unsupported type: {answer_type!r}")

    def decide(self, state: dict[str, Any], questions: list[DecisionQuestion]) -> DecisionResult:
        if not questions:
            raise DecisionProviderError("at least one decision question is required")
        payload = {
            "state": state,
            "model": self.model,
            "questions": {question.name: self._serialize_question(question) for question in questions},
        }
        try:
            response = self.transport(payload)
        except DecisionProviderError:
            raise
        except Exception as exc:  # injected transports must fail closed too
            raise DecisionProviderError(f"Jev transport failed: {exc}") from exc
        if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
            raise DecisionProviderError("Jev response is missing an answers object")
        answers = {
            question.name: self._normalize_answer(question.name, response["answers"].get(question.name))
            for question in questions
        }
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        return DecisionResult(
            answers=answers,
            provider="jev",
            model=str(response.get("model", self.model)),
            metadata={"usage": usage},
        )
