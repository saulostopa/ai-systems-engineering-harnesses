"""Hybrid retrieval: lexical (BM25-ish) + semantic (vectors), merged by
Reciprocal Rank Fusion (RRF). rag-harness.md: 'lexical matches (exact symbol
names) and semantic matches (conceptual similarity) in a single list'.
"""

from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter

from .chunker import Chunk
from .indexer import Index, semantic_search


def tokenize(text: str) -> list[str]:
    """Tokenizes with camelCase splitting (hooksPath -> hooks, path) and
    accent normalization (decompose + strip combining marks)."""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return re.findall(r"[a-z0-9_]+", text.lower())


def _path_tokens(chunk: Chunk) -> list[str]:
    """Tokens of the file name (without extension) — identification boost."""
    base = os.path.basename(chunk.path)
    return tokenize(base.replace("_", " ").replace("-", " ").replace(".", " "))


def _prefix_match(t: str, doc_terms: Counter[str]) -> bool:
    """Mutual prefix (min 5 chars): e.g. instalador<->install, definicao<->definition."""
    for dt in doc_terms:
        if (len(t) >= 5 and dt.startswith(t[:5])) or (len(dt) >= 5 and t.startswith(dt[:5])):
            return True
    return False


def _idf(index: Index) -> dict[str, float]:
    n = max(1, len(index.chunks))
    df: Counter[str] = Counter()
    for c in index.chunks:
        df.update(set(tokenize(c.text)))
    return {term: math.log(1 + n / (1 + df[term])) for term in df}


def lexical_search(index: Index, query: str, top_k: int = 5, idf: dict[str, float] | None = None) -> list[tuple[Chunk, float]]:
    idf = idf or _idf(index)
    qterms = tokenize(query)
    if not qterms:
        return []
    scored: list[tuple[Chunk, float]] = []
    for c in index.chunks:
        terms = Counter(tokenize(c.text))
        path_terms = Counter(_path_tokens(c))
        score = 0.0
        for t in qterms:
            if t in terms:
                score += idf.get(t, 1.0) * (1 + math.log(1 + terms[t]))
            elif path_terms[t] > 0:
                score += idf.get(t, 1.0) * 2.0  # file name counts 2x
            elif _prefix_match(t, path_terms):
                score += idf.get(t, 1.0) * 1.5  # file-name prefix
            elif _prefix_match(t, terms):
                score += idf.get(t, 1.0) * 1.0  # prefix in content (pt-BR <-> en)
        if score > 0:
            scored.append((c, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def rrf_merge(
    *ranked_lists: list[tuple[Chunk, float]], k: int = 60, top_k: int = 5
) -> list[tuple[Chunk, float]]:
    """Reciprocal Rank Fusion: sums 1/(k+rank) per list."""
    scores: dict[str, float] = {}
    chunks_by_hash: dict[str, Chunk] = {}
    for ranked in ranked_lists:
        for rank, (chunk, _score) in enumerate(ranked, start=1):
            scores[chunk.hash] = scores.get(chunk.hash, 0.0) + 1.0 / (k + rank)
            chunks_by_hash[chunk.hash] = chunk
    merged = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    return [(chunks_by_hash[h], s) for h, s in merged[:top_k]]


def hybrid_search(
    index: Index, embedder, query: str, top_k: int = 5, idf: dict[str, float] | None = None
) -> list[tuple[Chunk, float]]:
    lex = lexical_search(index, query, top_k=top_k * 2, idf=idf)
    vec = semantic_search(index, embedder, query, top_k=top_k * 2)
    return rrf_merge(lex, vec, top_k=top_k)