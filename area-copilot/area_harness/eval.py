"""Area Copilot evaluation — precision with a cited source.

The metric is not just "found the file": it is "the cited source exists and
contains the expected number/keyword". A number without a source is
forbidden (Lesson 09).
"""

from __future__ import annotations

import json
import os

from rag_harness.agentic import AgentController
from rag_harness.embeddings import make_embedder

from .__main__ import load_area_index


def load_queries(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run_area_eval(root: str, queries_path: str, embedder=None) -> dict:
    embedder = embedder or make_embedder()
    index = load_area_index(root)
    ctrl = AgentController(index, embedder)
    queries = load_queries(queries_path)
    hits = 0
    for q in queries:
        results = ctrl.retrieve(q["question"], root)
        ok = any(q["expected_fragment"].lower() in c.text.lower() for c in results[: q.get("top_k", 3)])
        hits += 1 if ok else 0
        mark = "✓" if ok else "✗"
        print(f"\n[{mark}] {q['question']}")
        print(f"     expected to contain: {q['expected_fragment']}")
        for c in results[:3]:
            print(f"     FONTE: {c.path} (L{c.start_line}-{c.end_line})")
    total = len(queries)
    print(f"\n== Precision: {hits}/{total} = {round(hits / max(1, total), 3)}")
    return {"hits": hits, "total": total}


if __name__ == "__main__":
    import sys

    root = sys.argv[1]
    queries = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "tests", "queries.json")
    run_area_eval(root, queries)