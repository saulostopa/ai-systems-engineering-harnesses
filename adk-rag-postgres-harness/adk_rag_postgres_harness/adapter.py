"""Adapter compatible with the ADK + RAG + Jev workflow contracts."""

from __future__ import annotations

import sys
from pathlib import Path

from .retrieval import search_code
from .store import PostgresStore


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

    def retrieve(self, request):
        hits = search_code(
            request.query, self.project, request.collection, request.top_k, self.embedder, self.store
        )
        evidence = tuple(
            self._EvidenceChunk(
                source=hit.path,
                text=hit.text,
                score=hit.score,
                start_line=hit.start_line,
                end_line=hit.end_line,
            )
            for hit in hits
        )
        return self._RetrievalResponse(
            request=request,
            chunks=evidence,
            answerable=bool(evidence),
            reason="postgres returned evidence" if evidence else "postgres returned no evidence",
        )
