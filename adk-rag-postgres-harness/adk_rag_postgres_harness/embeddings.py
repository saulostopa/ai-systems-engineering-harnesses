"""Embedding helpers: the default local model and the shared vector size."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_RAG_ROOT = Path(__file__).resolve().parents[2] / "rag-harness"
if str(_RAG_ROOT) not in sys.path:
    sys.path.insert(0, str(_RAG_ROOT))

from rag_harness.embeddings import OllamaEmbedder, check_settings, embedder_id, make_embedder  # noqa: E402

# The size of the `embeddings.embedding` column, within the 2,000 dimensions a
# pgvector HNSW index accepts.
EMBED_DIM = 1024
DEFAULT_EMBED_MODEL = "qwen3-embedding:4b"
QWEN3_QUERY_INSTRUCTION = "Given a code search query, retrieve the code or documentation that answers it"

__all__ = ["DEFAULT_EMBED_MODEL", "EMBED_DIM", "embed_query", "embed_texts", "embedder_id", "fit_dimension", "memory_embedder", "query_text"]


def memory_embedder():
    """Local and free by default; a hosted provider only when explicitly chosen."""

    check_settings()
    provider = os.environ.get("HARNESS_EMBED_PROVIDER", "ollama").lower()
    if provider == "ollama":
        return OllamaEmbedder(model=os.environ.get("HARNESS_EMBED_MODEL") or DEFAULT_EMBED_MODEL)
    return make_embedder()


def fit_dimension(vector: list[float], dim: int = EMBED_DIM) -> list[float]:
    """Cut a vector to the column size and normalize it again.

    Only meaningful for models trained to keep their quality when truncated,
    such as Qwen3. A smaller vector cannot be stored, so it fails loudly.
    """

    if len(vector) < dim:
        raise ValueError(f"the embedding model returned {len(vector)} dimensions; the index needs at least {dim}")
    cut = vector[:dim]
    norm = sum(value * value for value in cut) ** 0.5
    return [value / norm for value in cut] if norm else cut


def query_text(model_id: str, query: str) -> str:
    """Qwen3 expects an instruction on queries only, never on documents."""

    if "qwen3-embedding" in model_id:
        return f"Instruct: {QWEN3_QUERY_INSTRUCTION}\nQuery: {query}"
    return query


def embed_texts(embedder, texts: list[str]) -> list[list[float]]:
    if hasattr(embedder, "embed_batch"):
        vectors = embedder.embed_batch(texts)
    else:
        vectors = [embedder.embed(text) for text in texts]
    return [fit_dimension(vector) for vector in vectors]


def embed_query(embedder, query: str) -> list[float]:
    return embed_texts(embedder, [query_text(embedder_id(embedder), query)])[0]
