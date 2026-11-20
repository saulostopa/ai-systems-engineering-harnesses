"""Run the feature planning graph with evidence from the demo repository."""

import os
import sys
from pathlib import Path

from .workflow import Ollama, build_workflow

RAG_ROOT = Path(__file__).resolve().parents[2] / "rag-harness"
sys.path.insert(0, str(RAG_ROOT))

from rag_harness.chunker import chunk_file
from rag_harness.indexer import Index
from rag_harness.retrieval import lexical_search

DEMO_ROOT = Path(__file__).resolve().parent / "demo_repository"


def demo_search(query):
    chunks = []
    for path in sorted(DEMO_ROOT.glob("*.md")):
        for chunk in chunk_file(str(path)):
            chunk.path = path.relative_to(DEMO_ROOT).as_posix()
            chunks.append(chunk)
    return [
        {
            "id": f"E{position}",
            "path": chunk.path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "text": chunk.text,
        }
        for position, (chunk, _) in enumerate(
            lexical_search(Index(chunks, {}, {}), query, top_k=6), start=1
        )
    ]


root_agent = build_workflow(
    demo_search,
    Ollama(os.getenv("HARNESS_PLANNER_MODEL", "qwen2.5:14b")),
    Ollama(os.getenv("HARNESS_VERIFIER_MODEL", "qwen2.5:14b")),
)
