"""Precision@k evaluation of agentic retrieval (D2).

Runs queries with an expected target (path substring) and measures how many
hit within top-k. Decide by evidence (Lesson 11): the number produced here
is the health metric of the code RAG.

Usage:
    python -m rag_harness eval <root> [--queries tests/queries.json] [--top-k 3]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agentic import AgentController
from .embeddings import make_embedder
from .indexer import index_dir, load_index


def load_queries(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def precision_at_k(results: list, expected_substring: str, k: int = 3) -> bool:
    for c in results[:k]:
        if expected_substring.lower() in c.path.lower():
            return True
    return False


def run_eval(root: str, queries: list[dict], top_k: int = 3, embedder=None) -> dict:
    embedder = embedder or make_embedder()
    idx_dir = os.path.join(root, ".rag_index")
    if not os.path.exists(idx_dir):
        index = index_dir(root, embedder, verbose=True)
    else:
        index = load_index(idx_dir)

    ctrl = AgentController(index, embedder)
    hits = 0
    rows = []
    for q in queries:
        results = ctrl.retrieve(q["query"], root)
        ok = precision_at_k(results, q["expected_path"], top_k)
        hits += 1 if ok else 0
        rows.append(
            {
                "query": q["query"],
                "expected": q["expected_path"],
                "hit": ok,
                "tools": list(ctrl.used_tools),
                "top": [f"{c.path}:{c.start_line}" for c in results[:top_k]],
            }
        )
    total = len(queries)
    summary = {
        "precision_at_k": round(hits / max(1, total), 3),
        "hits": hits,
        "total": total,
        "top_k": top_k,
        "tools_used": sorted({t for r in rows for t in r["tools"]}),
        "rows": rows,
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(prog="rag_harness eval")
    ap.add_argument("root")
    ap.add_argument("--queries", default=os.path.join(os.path.dirname(__file__), "..", "tests", "queries.json"))
    ap.add_argument("--top-k", type=int, default=3)
    args = ap.parse_args()

    queries = load_queries(args.queries)
    summary = run_eval(args.root, queries, args.top_k)
    print(f"\n== Precision@{summary['top_k']}: {summary['hits']}/{summary['total']} = {summary['precision_at_k']}")
    print(f"== Tools used: {', '.join(summary['tools_used'])}")
    for r in summary["rows"]:
        mark = "✓" if r["hit"] else "✗"
        print(f"\n[{mark}] {r['query']}")
        print(f"     expected: {r['expected']}")
        print(f"     tools: {', '.join(r['tools'])}")
        print(f"     top: {', '.join(r['top'])}")
    sys.exit(0 if summary["hits"] == summary["total"] else 2)


if __name__ == "__main__":
    main()