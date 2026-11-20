"""Adapter for the existing rag-harness indexes and retrieval functions."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .contracts import EvidenceChunk, RagAdapter, RetrievalRequest, RetrievalResponse

# Each strategy the decision provider may choose maps to one rag-harness
# function, so the typed choice actually changes how evidence is retrieved.
STRATEGY_FUNCTIONS = {
    "keyword": "lexical_search",
    "semantic": "semantic_search",
    "hybrid": "hybrid_search",
}


class RagHarnessAdapter(RagAdapter):
    """Expose retrieval as evidence without exposing workflow control.

    `collections` maps an allowed collection name to an index directory. The
    adapter rejects unknown collections and strategies before importing or
    querying RAG.
    """

    def __init__(self, rag_harness_root: str, collections: dict[str, str], embedder=None) -> None:
        self.rag_harness_root = str(Path(rag_harness_root).resolve())
        self.collections = {name: str(Path(path).resolve()) for name, path in collections.items()}
        self.embedder = embedder
        self._indexes: dict[str, object] = {}

    def _module(self, name: str):
        if self.rag_harness_root not in sys.path:
            sys.path.insert(0, self.rag_harness_root)
        return importlib.import_module(f"rag_harness.{name}")

    def _index(self, collection: str):
        if collection not in self._indexes:
            self._indexes[collection] = self._module("indexer").load_index(self.collections[collection])
        return self._indexes[collection]

    def _embedder(self):
        if self.embedder is None:
            self.embedder = self._module("embeddings").make_embedder()
        return self.embedder

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        if request.collection not in self.collections:
            raise ValueError(f"unknown RAG collection: {request.collection}")
        if request.strategy not in STRATEGY_FUNCTIONS:
            raise ValueError(f"unknown retrieval strategy: {request.strategy}")
        index = self._index(request.collection)
        search = getattr(self._module("retrieval"), STRATEGY_FUNCTIONS[request.strategy])
        if request.strategy == "keyword":
            hits = search(index, request.query, request.top_k)
        else:
            hits = search(index, self._embedder(), request.query, request.top_k)
        evidence = tuple(
            EvidenceChunk(
                source=chunk.path,
                text=chunk.text,
                score=float(score),
                start_line=chunk.start_line,
                end_line=chunk.end_line,
            )
            for chunk, score in hits[: request.top_k]
        )
        return RetrievalResponse(
            request=request,
            chunks=evidence,
            answerable=bool(evidence),
            reason=(
                f"rag-harness {request.strategy} search returned evidence"
                if evidence
                else f"rag-harness {request.strategy} search returned no evidence"
            ),
        )
