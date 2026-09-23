"""Adapter for the existing rag-harness AgentController."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from .contracts import EvidenceChunk, RagAdapter, RetrievalRequest, RetrievalResponse


class RagHarnessAdapter(RagAdapter):
    """Expose retrieval as evidence without exposing workflow control.

    `collections` maps an allowed collection name to an index directory. The
    adapter rejects unknown collections before importing or querying RAG.
    """

    def __init__(self, rag_harness_root: str, collections: dict[str, str], embedder=None) -> None:
        self.rag_harness_root = str(Path(rag_harness_root).resolve())
        self.collections = {name: str(Path(path).resolve()) for name, path in collections.items()}
        self.embedder = embedder
        self._controllers: dict[str, object] = {}

    def _controller(self, collection: str):
        if collection not in self.collections:
            raise ValueError(f"unknown RAG collection: {collection}")
        if collection in self._controllers:
            return self._controllers[collection]
        if self.rag_harness_root not in sys.path:
            sys.path.insert(0, self.rag_harness_root)
        agentic = importlib.import_module("rag_harness.agentic")
        indexer = importlib.import_module("rag_harness.indexer")
        embeddings = importlib.import_module("rag_harness.embeddings")
        index = indexer.load_index(self.collections[collection])
        controller = agentic.AgentController(index, self.embedder or embeddings.make_embedder())
        self._controllers[collection] = controller
        return controller

    def retrieve(self, request: RetrievalRequest) -> RetrievalResponse:
        controller = self._controller(request.collection)
        chunks = controller.retrieve(request.query, self.rag_harness_root)[: request.top_k]
        evidence = tuple(
            EvidenceChunk(
                source=chunk.path,
                text=chunk.text,
                score=0.0,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
            )
            for chunk in chunks
        )
        return RetrievalResponse(
            request=request,
            chunks=evidence,
            answerable=bool(evidence),
            reason="rag-harness returned evidence" if evidence else "rag-harness returned no evidence",
        )
