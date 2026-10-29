"""POC CLI — agentic indexing and retrieval.

Usage:
    python -m rag_harness index <dir> [--profile default|docs|code] [--verbose]
    python -m rag_harness query <dir> "<query>" [--profile P] [--top-k N]
    python -m rag_harness agent <dir> "<query>" [--profile P]
    python -m rag_harness hybrid <dir> "<query>" [--profile P]

`--profile` selects the file extensions and the index folder:
`default` -> <dir>/.rag_index, `docs`/`code` -> <dir>/.rag_index/<profile>.
"""

from __future__ import annotations

import argparse
import os
import sys

from .agentic import AgentController, pretty
from .embeddings import make_embedder
from .eval import load_queries
from .indexer import PROFILES, index_dir, index_path_for, load_index
from .retrieval import hybrid_search, lexical_search


def main() -> None:
    ap = argparse.ArgumentParser(prog="rag_harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_index = sub.add_parser("index")
    p_index.add_argument("root")
    p_index.add_argument("--verbose", action="store_true")
    p_index.add_argument("--profile", choices=sorted(PROFILES), default="default")

    p_query = sub.add_parser("query")
    p_query.add_argument("root")
    p_query.add_argument("text")
    p_query.add_argument("--top-k", type=int, default=5)
    p_query.add_argument("--profile", choices=sorted(PROFILES), default="default")

    p_hybrid = sub.add_parser("hybrid")
    p_hybrid.add_argument("root")
    p_hybrid.add_argument("text")
    p_hybrid.add_argument("--top-k", type=int, default=5)
    p_hybrid.add_argument("--profile", choices=sorted(PROFILES), default="default")

    p_agent = sub.add_parser("agent")
    p_agent.add_argument("root")
    p_agent.add_argument("text")
    p_agent.add_argument("--profile", choices=sorted(PROFILES), default="default")

    p_eval = sub.add_parser("eval")
    p_eval.add_argument("root")
    p_eval.add_argument("--queries", default=os.path.join(os.path.dirname(__file__), "..", "tests", "queries.json"))
    p_eval.add_argument("--top-k", type=int, default=3)

    args = ap.parse_args()
    embedder = make_embedder()
    print(f"embedder: {type(embedder).__name__}")

    if args.cmd == "eval":
        from .eval import run_eval

        summary = run_eval(args.root, load_queries(args.queries), args.top_k, embedder)
        print(f"\n== Precision@{summary['top_k']}: {summary['hits']}/{summary['total']} = {summary['precision_at_k']}")
        print(f"== Tools used: {', '.join(summary['tools_used'])}")
        for r in summary["rows"]:
            mark = "✓" if r["hit"] else "✗"
            print(f"\n[{mark}] {r['query']}")
            print(f"     expected: {r['expected']}")
            print(f"     tools: {', '.join(r['tools'])}")
            print(f"     top: {', '.join(r['top'])}")
        return

    if args.cmd == "index":
        index = index_dir(args.root, embedder, verbose=args.verbose, profile=args.profile)
        print(f"OK: {len(index.chunks)} chunks in {index_path_for(args.root, args.profile)}")
        return

    idx_dir = index_path_for(args.root, args.profile)
    if not os.path.exists(idx_dir):
        print(f"ERROR: index does not exist in {idx_dir} — run 'index' first", file=sys.stderr)
        sys.exit(1)
    index = load_index(idx_dir)

    if args.cmd == "query":
        print(f"\n== lexical top-{args.top_k} ==")
        print(pretty(lexical_search(index, args.text, args.top_k)))

    elif args.cmd == "hybrid":
        print(f"\n== hybrid (RRF) top-{args.top_k} ==")
        print(pretty(hybrid_search(index, embedder, args.text, args.top_k)))

    elif args.cmd == "agent":
        ctrl = AgentController(index, embedder)
        results = ctrl.retrieve(args.text, args.root)
        print(f"\n== agent (tools used: {', '.join(ctrl.used_tools)}) ==")
        print(pretty(results))


if __name__ == "__main__":
    main()