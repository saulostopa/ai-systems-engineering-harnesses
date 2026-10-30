"""Command line entrypoint for the PostgreSQL RAG reference harness."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .store import PostgresStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="adk-rag-postgres-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate")

    index_parser = sub.add_parser("index", help="sync a repository, embedding only what changed")
    index_parser.add_argument("root")
    index_parser.add_argument("--project", help="defaults to the folder name")

    search_parser = sub.add_parser("search", help="hybrid search; text comes from disk")
    search_parser.add_argument("query")
    search_parser.add_argument("--project", required=True)
    search_parser.add_argument("--collection", choices=("code", "docs"))
    search_parser.add_argument("--top-k", type=int, default=8)
    search_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "migrate":
        PostgresStore().migrate()
        print("migrations applied")
    elif args.command == "index":
        from .ingest import sync

        report = sync(args.root, args.project, verbose=True)
        print(
            f"{report.project}: {report.files} files, {report.changed} changed, {report.removed} removed, "
            f"{report.embedded} chunks embedded with {report.model}"
        )
    else:
        from .retrieval import search_code

        hits = search_code(args.query, args.project, args.collection, args.top_k)
        if args.json:
            print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
            return
        for hit in hits:
            stale = " (changed since indexing)" if hit.stale else ""
            print(f"{hit.score:.4f}  {hit.path}:{hit.start_line}-{hit.end_line}  {hit.kind} {hit.name}{stale}")


if __name__ == "__main__":
    main()
