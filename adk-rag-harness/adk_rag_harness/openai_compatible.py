"""Typed decision provider for OpenAI-compatible local and hosted APIs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import DecisionAnswer, DecisionProviderError, DecisionQuestion, DecisionResult, QuestionType


JsonTransport = Callable[[dict[str, Any]], dict[str, Any]]


def load_openrouter_api_key() -> str:
    """Load an OpenRouter key from env or the local OpenCode auth file."""

    explicit = os.getenv("OPENROUTER_API_KEY", "")
    if explicit:
        return explicit
    auth_path = Path(
        os.getenv("OPENROUTER_AUTH_FILE", "~/.local/share/opencode/auth.json")
    ).expanduser()
    try:
        data = json.loads(auth_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    for provider in ("openrouter", "opencode"):
        value = data.get(provider)
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            return value["key"]
    return ""


class OpenAICompatibleDecisionProvider:
    """Use a chat-completions endpoint to answer typed routing questions.

    This preserves the harness contract but does not claim to be the Jev model.
    It is suitable for Ollama and OpenRouter when the model can emit JSON.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_s: float = 30.0,
        transport: JsonTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.transport = transport or self._http_transport

    def decide(self, state: dict[str, Any], questions: list[DecisionQuestion]) -> DecisionResult:
        if not questions:
            raise DecisionProviderError("at least one decision question is required")
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(questions),
                },
                {"role": "user", "content": json.dumps(state, ensure_ascii=True)},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.transport(payload)
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            answers = parsed.get("answers") if isinstance(parsed, dict) else None
            if not isinstance(answers, dict):
                raise DecisionProviderError("compatible model response is missing an answers object")
            normalized = {question.name: self._normalize(question, answers.get(question.name)) for question in questions}
            return DecisionResult(normalized, provider="openai-compatible", model=self.model)
        except DecisionProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DecisionProviderError(f"compatible model returned an invalid decision response: {exc}") from exc
        except Exception as exc:
            raise DecisionProviderError(f"compatible model request failed: {exc}") from exc

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key or 'ollama'}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DecisionProviderError(f"compatible model request failed: {exc}") from exc

    @staticmethod
    def _system_prompt(questions: list[DecisionQuestion]) -> str:
        definitions = []
        for question in questions:
            item = {
                "name": question.name,
                "type": question.type.value if isinstance(question.type, QuestionType) else str(question.type),
                "instruction": question.instruction,
                "options": list(question.options),
            }
            definitions.append(item)
        return (
            "You are a typed decision engine. Do not explain your answer. "
            "Return only valid JSON with this shape: "
            '{"answers":{"question_name":{"type":"noul|choice|score", ...}}}. '
            "For noul, return a probability between 0 and 1 in `noul`. "
            "For choice, return one listed option in `choice` and `confidence` between 0 and 1. "
            "For score, return a numeric `score` and `confidence` between 0 and 1. "
            f"Questions: {json.dumps(definitions, ensure_ascii=True)}"
        )

    @staticmethod
    def _normalize(question: DecisionQuestion, raw: Any) -> DecisionAnswer:
        if not isinstance(raw, dict):
            raise DecisionProviderError(f"answer {question.name!r} is not an object")
        if question.type is QuestionType.NOUL or question.type == QuestionType.NOUL.value:
            probability = raw.get("noul")
            if not isinstance(probability, (int, float)):
                raise DecisionProviderError(f"Noul answer {question.name!r} has no probability")
            probability = float(probability)
            return DecisionAnswer(probability >= 0.5, max(probability, 1.0 - probability))
        confidence = raw.get("confidence")
        if not isinstance(confidence, (int, float)):
            raise DecisionProviderError(f"answer {question.name!r} has no confidence")
        if question.type is QuestionType.CHOICE or question.type == QuestionType.CHOICE.value:
            choice = raw.get("choice")
            if not isinstance(choice, str) or choice not in question.options:
                raise DecisionProviderError(f"Choice answer {question.name!r} is outside its options")
            return DecisionAnswer(choice, float(confidence))
        if question.type is QuestionType.SCORE or question.type == QuestionType.SCORE.value:
            score = raw.get("score")
            if not isinstance(score, (int, float)):
                raise DecisionProviderError(f"Score answer {question.name!r} has no score")
            return DecisionAnswer(float(score), float(confidence))
        raise DecisionProviderError(f"unsupported question type: {question.type!r}")
