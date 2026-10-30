"""Measure search on the golden questions: hit@k, MRR and latency, per strategy and scope."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adk_rag_postgres_harness.embeddings import embedder_id, memory_embedder
from adk_rag_postgres_harness.memory import recall
from adk_rag_postgres_harness.retrieval import search_code
from adk_rag_postgres_harness.store import PostgresStore

CUTOFFS = (1, 3, 5, 8)
TOP_K = max(CUTOFFS)
# The collection a caller that knows the kind of question would choose.
ROUTED = {"code": "code", "symbol": "code", "docs": "docs", "memory": "memory"}


def first_relevant_rank(paths: list[str], relevant: list[str]) -> int | None:
    for rank, path in enumerate(paths, 1):
        if path in relevant:
            return rank
    return None


def summarize(ranks: list[int | None]) -> dict:
    total = len(ranks)
    if not total:
        return {"questions": 0}
    summary = {"questions": total}
    for cutoff in CUTOFFS:
        summary[f"hit@{cutoff}"] = round(sum(1 for rank in ranks if rank and rank <= cutoff) / total, 3)
    summary["mrr"] = round(sum(1 / rank for rank in ranks if rank) / total, 3)
    return summary


def check_questions(questions: list[dict], root: Path, indexed: set[str]) -> None:
    """A golden answer that went stale would quietly distort every number."""

    for question in questions:
        for path in question["relevant"]:
            if path not in indexed:
                raise SystemExit(f"{question['id']}: {path} is not indexed")
            if not re.search(question["evidence"], (root / path).read_text(encoding="utf-8", errors="replace")):
                raise SystemExit(f"{question['id']}: {path} no longer has {question['evidence']!r}")


def search(question: dict, project: str, scope: str, strategy: str, embedder, store) -> list[str]:
    collection = ROUTED[question["type"]] if scope == "routed" else None
    if collection == "memory":
        hits = recall(question["question"], project, top_k=TOP_K, embedder=embedder, store=store)
        return [hit.source for hit in hits]
    hits = search_code(question["question"], project, collection, TOP_K, embedder, store, strategy)
    return [hit.path for hit in hits]


def run(questions: list[dict], project: str, scope: str, strategy: str, embedder, store) -> dict:
    rows, timings = [], []
    for question in questions:
        started = time.perf_counter()
        paths = search(question, project, scope, strategy, embedder, store)
        timings.append((time.perf_counter() - started) * 1000)
        rows.append({
            "id": question["id"],
            "type": question["type"],
            "lang": question["lang"],
            "rank": first_relevant_rank(paths, question["relevant"]),
            "top": paths[:3],
        })
    by_type = {
        kind: summarize([row["rank"] for row in rows if row["type"] == kind])
        for kind in sorted({row["type"] for row in rows})
    }
    by_lang = {
        lang: summarize([row["rank"] for row in rows if row["lang"] == lang])
        for lang in sorted({row["lang"] for row in rows})
    }
    return {
        "scope": scope,
        "strategy": strategy,
        "overall": summarize([row["rank"] for row in rows]),
        "by_type": by_type,
        "by_lang": by_lang,
        "latency_ms": {
            "median": round(statistics.median(timings)),
            "max": round(max(timings)),
        },
        "questions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default=str(ROOT / "evals" / "biometrik_questions.json"))
    parser.add_argument("--strategies", default="hybrid,semantic,keyword")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    golden = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    project = golden["project"]
    store, embedder = PostgresStore(), memory_embedder()
    found = store.project(project)
    if found is None:
        raise SystemExit(f"unknown project {project!r}; index it first")
    questions = [question for question in golden["questions"] if question["relevant"]]
    check_questions(questions, Path(found["root"]), set(store.file_states(found["id"])))

    # A cold model would charge its load time to the first question.
    search(questions[0], project, "all", "hybrid", embedder, store)
    runs = [
        run(questions, project, scope, strategy, embedder, store)
        for scope in ("all", "routed")
        for strategy in args.strategies.split(",")
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps({"model": embedder_id(embedder), "runs": runs}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    for result in runs:
        print(result["scope"], result["strategy"], result["overall"], result["latency_ms"])


if __name__ == "__main__":
    main()
