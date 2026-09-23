"""Adapter compatible with the ADK + RAG + Jev workflow contracts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .store import PostgresStore


class PostgresRagAdapter:
    """Implement the same retrieval boundary as the local JSON adapter.

    The `adk-rag-harness` package is loaded from the sibling reference project
    in this repository. A published copy can package those stable contracts as
    a shared dependency later.
    """

    def __init__(self, store: PostgresStore | None = None, rag_root: str | None = None) -> None:
        root = Path(rag_root or Path(__file__).parents[2] / "rag-harness").resolve()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        adk_root = root.parent / "adk-rag-harness"
        if str(adk_root) not in sys.path:
            sys.path.insert(0, str(adk_root))
        from adk_rag_harness.contracts import EvidenceChunk, RetrievalResponse

        self._EvidenceChunk = EvidenceChunk
        self._RetrievalResponse = RetrievalResponse
        self.store = store or PostgresStore()
        self.embedder = None

    def retrieve(self, request):
        if self.embedder is None:
            from rag_harness.embeddings import make_embedder

            self.embedder = make_embedder()
        results = self.store.search(
            request.collection,
            request.query,
            self.embedder.embed(request.query),
            request.top_k,
            request.filters,
        )
        evidence = tuple(
            self._EvidenceChunk(
                source=row["source"],
                text=row["content"],
                score=float(row["score"]),
                start_line=row["start_line"],
                end_line=row["end_line"],
            )
            for row in results
        )
        return self._RetrievalResponse(
            request=request,
            chunks=evidence,
            answerable=bool(evidence),
            reason="postgres returned evidence" if evidence else "postgres returned no evidence",
        )
