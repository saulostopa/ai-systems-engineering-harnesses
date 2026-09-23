"""RagContextProvider — RAG as a CONTEXT PROVIDER, never an orchestrator.

Rules (course requirement):
  - The workflow may ask the rag-harness AgentController for context;
  - the result arrives typed as context (NodeInput.context);
  - RAG does NOT decide transitions: it does not receive the runner, does not
    emit transition events, does not propose the next node.

The rag-harness dependency is optional and injected (import path).
"""

from __future__ import annotations

import importlib
import sys
from typing import Any


class RagContextProvider:
    """Wraps the rag-harness AgentController with a minimum contract."""

    def __init__(self, rag_harness_root: str, index_dir: str | None = None, embedder=None) -> None:
        self.rag_harness_root = rag_harness_root
        self.index_dir = index_dir
        self.embedder = embedder
        self._controller = None

    def _load_controller(self) -> Any:
        if self._controller is not None:
            return self._controller
        if self.rag_harness_root not in sys.path:
            sys.path.insert(0, self.rag_harness_root)
        agentic = importlib.import_module("rag_harness.agentic")
        indexer = importlib.import_module("rag_harness.indexer")
        embeddings = importlib.import_module("rag_harness.embeddings")
        embedder = self.embedder or embeddings.make_embedder()
        if self.index_dir:
            index = indexer.load_index(self.index_dir)
        else:
            raise RuntimeError("RagContextProvider requires index_dir (the rag_harness index)")
        self._controller = agentic.AgentController(index, embedder)
        return self._controller

    # ── Contract with the workflow ──────────────────────────────

    def provide_context(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Returns TYPED context: [{path, start_line, text, kind, name}].

        It is a pure read function — it never changes workflow state.
        """
        controller = self._load_controller()
        chunks = controller.retrieve(question, self.rag_harness_root)
        return [
            {
                "path": c.path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "kind": c.kind,
                "name": c.name,
                "text": c.text[:600],
            }
            for c in chunks[:top_k]
        ]

    # ── Optional deterministic node ─────────────────────────────

    def as_node(self):
        """Creates a deterministic 'context' node that injects context into the
        workflow payload (NodeInput.context). RAG never proposes the next node."""

        def context_node(ninput) -> Any:
            from hard_harness.core.schemas import NodeOutput

            question = ninput.payload.get("question") or str(ninput.payload)
            context = self.provide_context(question)
            return NodeOutput(node_id="context", ok=True, payload={"context": context})

        return context_node