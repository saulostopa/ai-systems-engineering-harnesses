"""Pluggable embeddings — n-gram hashing (local fallback), Ollama or OpenRouter.

No external model needed for the POC: the fallback generates deterministic
n-gram embeddings (works offline). Without `HARNESS_EMBED_PROVIDER`, Ollama
(`OLLAMA_BASE_URL`, nomic-embed-text) is used when reachable.
`HARNESS_EMBED_PROVIDER=openrouter` uses the hosted embeddings endpoint
(voyageai/voyage-code-4 by default); it is never chosen automatically because
it is billed per token. `HARNESS_EMBED_MODEL` overrides the model.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .usage import record

DIM = 256
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
DEFAULT_OPENROUTER_EMBED_MODEL = "voyageai/voyage-code-4"

# Removed names fail loudly instead of being ignored silently.
REMOVED_SETTINGS = {
    "RAG_EMBEDDER": "HARNESS_EMBED_PROVIDER",
    "OPENROUTER_EMBED_MODEL": "HARNESS_EMBED_MODEL",
    "OLLAMA_EMBED_MODEL": "HARNESS_EMBED_MODEL",
    "OLLAMA_API_URL": "OLLAMA_BASE_URL",
}


def embedder_id(embedder: Any) -> str:
    """Stable identity of the vector space an embedder produces."""

    return getattr(embedder, "model_id", type(embedder).__name__)


def load_openrouter_api_key() -> str:
    """Load an OpenRouter key from env or the local OpenCode auth file."""

    explicit = os.getenv("OPENROUTER_API_KEY", "")
    if explicit:
        return explicit
    auth_path = Path(os.getenv("OPENROUTER_AUTH_FILE", "~/.local/share/opencode/auth.json")).expanduser()
    try:
        data = json.loads(auth_path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    for provider in ("openrouter", "opencode"):
        value = data.get(provider)
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            return value["key"]
    return ""


class NGramEmbedder:
    """Deterministic local embedding: n-gram hash into a DIM-sized vector.

    Not truly semantic — meant to validate the *architecture* (pipeline,
    cache, RRF) without an external model. Swap for Ollama/API to get real
    semantics.
    """

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.model_id = f"ngram:{dim}"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = "".join(c if c.isalnum() else " " for c in text.lower()).split()
        grams: list[str] = []
        for tok in tokens:
            grams.append(tok)
            if len(tok) >= 3:
                grams.append(tok[:3])
                grams.append(tok[-3:])
        for g in grams:
            idx = int(hashlib.md5(g.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm:
            vec = [v / norm for v in vec]
        return vec


class OllamaEmbedder:
    def __init__(self, api_url: str = OLLAMA_BASE_URL, model: str = DEFAULT_OLLAMA_EMBED_MODEL) -> None:
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.model_id = f"ollama:{model}"

    def _available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.api_url}/api/tags", timeout=2) as res:
                return res.status == 200
        except Exception:
            return False

    def embed(self, text: str) -> list[float]:
        if not self._available():
            raise RuntimeError("Ollama unavailable")
        headers = {"Content-Type": "application/json"}

        # `/api/embed` is the current Ollama endpoint and accepts `input`.
        payload = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        req = urllib.request.Request(f"{self.api_url}/api/embed", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                data = json.loads(res.read())
            return data["embeddings"][0]
        except urllib.error.HTTPError as exc:
            if exc.code not in (404, 405):
                raise

        # Keep compatibility with older Ollama releases.
        payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(f"{self.api_url}/api/embeddings", data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.loads(res.read())
        return data["embedding"]


JsonTransport = Callable[[dict[str, Any]], dict[str, Any]]


class OpenRouterEmbedder:
    """OpenAI-compatible `/embeddings` client; sends chunks in batches."""

    def __init__(
        self,
        model: str = DEFAULT_OPENROUTER_EMBED_MODEL,
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        batch_size: int = 64,
        timeout_s: float = 60.0,
        transport: JsonTransport | None = None,
    ) -> None:
        self.model = model.removeprefix("openrouter/")
        self.model_id = f"openrouter:{self.model}"
        self.api_key = api_key if api_key is not None else load_openrouter_api_key()
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.timeout_s = timeout_s
        self.transport = transport or self._http_transport

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            started = time.monotonic()
            try:
                response = self.transport({"model": self.model, "input": batch})
            except Exception as exc:
                self._record(started, {}, status="error", error_kind=type(exc).__name__)
                raise
            self._record(started, response)
            data = sorted(response.get("data") or [], key=lambda item: item.get("index", 0))
            if len(data) != len(batch):
                raise RuntimeError(f"OpenRouter returned {len(data)} embeddings for {len(batch)} inputs")
            vectors.extend(item["embedding"] for item in data)
        return vectors

    def _record(self, started: float, response: dict[str, Any], **status: Any) -> None:
        """One ledger line per billed request; the component comes from the caller's context."""

        usage = response.get("usage") or {}
        record(
            component="embedding_query",
            provider="openrouter",
            model=self.model,
            routed_model=response.get("model"),
            input_tokens=usage.get("prompt_tokens", 0),
            cost_usd=usage.get("cost"),
            latency_ms=round((time.monotonic() - started) * 1000),
            **status,
        )

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError(
                "OpenRouter credentials are required: set OPENROUTER_API_KEY "
                "or configure ~/.local/share/opencode/auth.json"
            )
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as res:
            return json.loads(res.read())


def check_settings(environ: dict[str, str] = os.environ) -> None:
    problems = [f"{old} was renamed to {new}" for old, new in REMOVED_SETTINGS.items() if old in environ]
    if problems:
        raise RuntimeError("Outdated harness settings: " + "; ".join(problems) + ".")


def make_embedder() -> NGramEmbedder | OllamaEmbedder | OpenRouterEmbedder:
    check_settings()
    provider = os.environ.get("HARNESS_EMBED_PROVIDER", "").lower()
    model = os.environ.get("HARNESS_EMBED_MODEL", "")
    if provider == "ngram":
        return NGramEmbedder()
    if provider == "ollama":
        return OllamaEmbedder(model=model or DEFAULT_OLLAMA_EMBED_MODEL)
    if provider == "openrouter":
        return OpenRouterEmbedder(model=model or DEFAULT_OPENROUTER_EMBED_MODEL)
    if provider:
        raise RuntimeError(f"Unsupported HARNESS_EMBED_PROVIDER={provider!r}; use openrouter, ollama or ngram")
    try:
        ollama = OllamaEmbedder(model=model or DEFAULT_OLLAMA_EMBED_MODEL)
        if ollama._available():
            return ollama
    except Exception:
        pass
    return NGramEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"dimension mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
