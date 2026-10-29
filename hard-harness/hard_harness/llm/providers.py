"""LLM providers — OpenRouter (default), Ollama (optional), Stub (offline).

The hard-harness agents receive an injectable provider
(`complete(prompt) -> str`). The real implementations live here:

  - OpenRouterProvider: OpenAI-compatible API (stdlib urllib).
  - OllamaProvider:    local /v1/chat/completions endpoint.
  - StubProvider:      deterministic, for offline tests/examples.
  - make_provider():   environment-based selection, with NO network surprise:
        1. OPENROUTER_API_KEY defined  -> OpenRouter
        2. OLLAMA_API_URL defined      -> Ollama (short probe)
        3. otherwise                   -> Stub (with a clear warning)

Cost: providers expose `last_usage` (tokens) and `last_cost_usd`; the agents
attach `llm_cost` and `llm_cost_usd` to the payload; the runner applies
`llm_budget`. When the sibling `harness-usage` package is present, every call
also writes one line to the token and cost ledger.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..usage import record

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "deepseek/deepseek-v4-flash-0731"
OLLAMA_BASE = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2"


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMError(RuntimeError):
    pass


class LLMProvider:
    """Minimum contract: complete(prompt) -> str."""

    name = "base"

    def complete(self, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError

    @property
    def last_usage(self) -> Usage:
        return Usage()

    @property
    def last_cost_usd(self) -> float | None:
        return getattr(self, "_cost_usd", None)

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
        """POST and write one ledger line, also when the call fails."""

        started = time.monotonic()
        try:
            data = _http_post_json(url, payload, headers, timeout_s)
        except LLMError as exc:
            record(component="agent", provider=self.name, model=payload.get("model", ""),
                   latency_ms=round((time.monotonic() - started) * 1000), status="error",
                   error_kind=str(exc).split(":", 1)[0])
            raise
        usage = data.get("usage") or {}
        self._cost_usd = usage.get("cost") if self.name == "openrouter" else 0.0
        record(
            component="agent",
            provider=self.name,
            model=payload.get("model", ""),
            routed_model=data.get("model"),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            cost_usd=self._cost_usd if self.name == "openrouter" else None,
            latency_ms=round((time.monotonic() - started) * 1000),
        )
        return data


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout_s: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={**headers, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise LLMError(f"HTTP {exc.code} from provider: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LLMError(f"no connection to provider: {exc}") from exc


class OpenRouterProvider(LLMProvider):
    """Provider via OpenRouter — the same style used by the opencode of this session."""

    name = "openrouter"

    def __init__(self, api_key: str | None = None, model: str = OPENROUTER_MODEL, base_url: str = OPENROUTER_BASE,
                 max_tokens: int = 2048, temperature: float = 0.2, timeout_s: float = 120.0) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            raise LLMError("OPENROUTER_API_KEY not set (env or argument)")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout_s = timeout_s
        self._usage = Usage()

    @property
    def last_usage(self) -> Usage:
        return self._usage

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        data = self._post(
            f"{self.base_url}/chat/completions",
            {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "temperature": self.temperature},
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout_s,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response from OpenRouter: {str(data)[:300]}") from exc
        usage = data.get("usage") or {}
        self._usage = Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
        return text or ""


class OllamaProvider(LLMProvider):
    """Local provider via Ollama (OpenAI-compatible endpoint)."""

    name = "ollama"

    def __init__(self, base_url: str = OLLAMA_BASE, model: str = OLLAMA_MODEL,
                 max_tokens: int = 2048, timeout_s: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self._usage = Usage()

    @property
    def last_usage(self) -> Usage:
        return self._usage

    def complete(self, prompt: str, system: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        data = self._post(
            f"{self.base_url}/v1/chat/completions",
            {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "stream": False},
            {},
            self.timeout_s,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected response from Ollama: {str(data)[:300]}") from exc
        usage = data.get("usage") or {}
        self._usage = Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)))
        return text or ""

    @classmethod
    def available(cls, base_url: str = OLLAMA_BASE, timeout_s: float = 1.5) -> bool:
        try:
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout_s) as res:
                return res.status == 200
        except Exception:
            return False


class StubProvider(LLMProvider):
    """Deterministic — for offline tests/examples. Warns that it is a stub."""

    name = "stub"

    def __init__(self, response: str = "stub response") -> None:
        self.response = response
        self.calls: list[str] = []

    def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls.append(prompt[:200])
        return self.response


def make_provider(prefer_ollama: bool = False) -> LLMProvider:
    """Environment-based selection — no network surprise (course lesson: decide by evidence).

    1. OPENROUTER_API_KEY defined -> OpenRouter (this session's default).
    2. OLLAMA_API_URL defined (or prefer_ollama) and Ollama responds -> Ollama.
    3. otherwise -> Stub with a clear warning.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    ollama_url = os.environ.get("OLLAMA_API_URL", "")
    if api_key:
        try:
            return OpenRouterProvider(api_key=api_key)
        except LLMError as exc:
            print(f"[llm] warning: OpenRouter configured but failed to instantiate: {exc}")
    if ollama_url or prefer_ollama:
        base = ollama_url or OLLAMA_BASE
        if OllamaProvider.available(base):
            return OllamaProvider(base_url=base)
        print(f"[llm] warning: Ollama ({base}) did not respond — using stub")
    if not api_key and not ollama_url and not prefer_ollama:
        print("[llm] warning: no provider configured (OPENROUTER_API_KEY or OLLAMA_API_URL) — using deterministic stub")
    return StubProvider()