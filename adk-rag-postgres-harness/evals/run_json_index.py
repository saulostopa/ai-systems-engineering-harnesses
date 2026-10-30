"""Measure the JSON indexes of rag-harness on the golden questions, for comparison."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "evals")]

from run_retrieval import TOP_K, first_relevant_rank, summarize

from adk_rag_postgres_harness.embeddings import embedder_id  # noqa: F401, adds rag-harness to the path
from rag_harness.embeddings import make_embedder
from rag_harness.indexer import load_index
from rag_harness.retrieval import hybrid_search, lexical_search, semantic_search

# The JSON indexes have no memory collection, so logs live in docs.
ROUTED = {"code": "code", "symbol": "code", "docs": "docs", "memory": "docs"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--questions", default=str(ROOT / "evals" / "biometrik_questions.json"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root)
    questions = [q for q in json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"] if q["relevant"]]
    indexes = {name: load_index(str(root / ".rag_index" / name)) for name in ("code", "docs")}
    embedder = make_embedder()
    runs = []
    for strategy in ("hybrid", "semantic", "keyword"):
        rows = []
        for question in questions:
            index = indexes[ROUTED[question["type"]]]
            if strategy == "keyword":
                hits = lexical_search(index, question["question"], TOP_K)
            else:
                search = hybrid_search if strategy == "hybrid" else semantic_search
                hits = search(index, embedder, question["question"], TOP_K)
            paths = [str(Path(chunk.path).resolve().relative_to(root.resolve())) if Path(chunk.path).is_absolute() else chunk.path for chunk, _ in hits]
            rows.append({"id": question["id"], "type": question["type"], "rank": first_relevant_rank(paths, question["relevant"]), "top": paths[:3]})
        overall = summarize([row["rank"] for row in rows])
        by_type = {kind: summarize([row["rank"] for row in rows if row["type"] == kind]) for kind in sorted({row["type"] for row in rows})}
        runs.append({"scope": "routed", "strategy": strategy, "overall": overall, "by_type": by_type, "questions": rows})
        print(strategy, overall, {kind: value["hit@5"] for kind, value in by_type.items()})
    Path(args.out).write_text(json.dumps({"model": "json:" + indexes["code"].embedder, "runs": runs}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
