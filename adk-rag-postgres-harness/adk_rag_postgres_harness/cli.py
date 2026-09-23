"""Command line entrypoint for the PostgreSQL RAG reference harness."""

from __future__ import annotations

import argparse

from .store import PostgresStore


def main() -> None:
    parser = argparse.ArgumentParser(prog="adk-rag-postgres-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate")
    ingest_parser = sub.add_parser("ingest")
    ingest_parser.add_argument("root")
    ingest_parser.add_argument("--collection", default="docs")

    args = parser.parse_args()
    if args.command == "migrate":
        PostgresStore().migrate()
        print("migrations applied")
    else:
        from .ingest import ingest

        ingest(args.root, args.collection)


if __name__ == "__main__":
    main()
