"""Adapter compatible with the ADK + RAG + Jev workflow contracts."""

from __future__ import annotations

import sys
from pathlib import Path

from .memory import recall
from .retrieval import search_code
from .store import PostgresStore

COLLECTIONS = ("code", "docs", "memory")
STRATEGIES = ("hybrid", "semantic", "keyword")


class PostgresRagAdapter:
    """Implement the same retrieval boundary as the local JSON adapter.

    The `adk-rag-harness` package is loaded from the sibling reference project
    in this repository. A published copy can package those stable contracts as
    a shared dependency later.
    """

    def __init__(self, project: str, store: PostgresStore | None = None, embedder=None) -> None:
        adk_root = Path(__file__).resolve().parents[2] / "adk-rag-harness"
        if str(adk_root) not in sys.path:
            sys.path.insert(0, str(adk_root))
        from adk_rag_harness.contracts import EvidenceChunk, RetrievalResponse

        self._EvidenceChunk = EvidenceChunk
        self._RetrievalResponse = RetrievalResponse
        self.project = project
        self.store = store or PostgresStore()
        self.embedder = embedder

    def _code_or_docs(self, request):
        hits = search_code(
            request.query, self.project, request.collection, request.top_k, self.embedder, self.store, request.strategy
        )
        return tuple(
            self._EvidenceChunk(
                source=hit.path,
                text=hit.text,
                score=hit.score,
                start_line=hit.start_line,
                end_line=hit.end_line,
                stale=hit.stale,
            )
            for hit in hits
        )

    def _memory(self, request):
        """Saved decisions and feature logs; they are always searched by both meaning and text."""

        hits = recall(request.query, self.project, top_k=request.top_k, embedder=self.embedder, store=self.store)
        return tuple(
            self._EvidenceChunk(
                source=f"{hit.memory_id} ({hit.source})" if hit.origin == "memory" else hit.source,
                text=hit.text,
                score=hit.score,
                start_line=hit.start_line,
                end_line=hit.end_line,
            )
            for hit in hits
        )

    def retrieve(self, request):
        if request.collection not in COLLECTIONS:
            raise ValueError(f"unknown RAG collection: {request.collection}")
        if request.strategy not in STRATEGIES:
            raise ValueError(f"unknown retrieval strategy: {request.strategy}")
        evidence = self._memory(request) if request.collection == "memory" else self._code_or_docs(request)
        return self._RetrievalResponse(
            request=request,
            chunks=evidence,
            answerable=bool(evidence),
            reason="postgres returned evidence" if evidence else "postgres returned no evidence",
        )
