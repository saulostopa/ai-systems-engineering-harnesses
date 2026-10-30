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

    symbol_parser = sub.add_parser("symbol", help="where a function, component or type is defined")
    symbol_parser.add_argument("name")
    symbol_parser.add_argument("--project", required=True)

    uses_parser = sub.add_parser("uses", help="which files import a name or a file path")
    uses_parser.add_argument("name")
    uses_parser.add_argument("--project", required=True)

    read_parser = sub.add_parser("read", help="read lines of an indexed file")
    read_parser.add_argument("path")
    read_parser.add_argument("--project", required=True)
    read_parser.add_argument("--start", type=int, default=1)
    read_parser.add_argument("--end", type=int)

    mcp_parser = sub.add_parser("mcp", help="serve the same tools to an agent over MCP (stdio)")
    mcp_parser.add_argument("--project", required=True)

    remember_parser = sub.add_parser("remember", help="save a decision to the repository file and the database")
    remember_parser.add_argument("text")
    remember_parser.add_argument("--project", required=True)
    remember_parser.add_argument("--source", required=True, help="where it came from: a file, a PR, a conversation")
    remember_parser.add_argument("--kind", default="note", choices=("decision", "convention", "handoff", "note"))
    remember_parser.add_argument("--supersedes", help="the id of the memory this one replaces")

    recall_parser = sub.add_parser("recall", help="search memories and feature progress and handoff logs")
    recall_parser.add_argument("query")
    recall_parser.add_argument("--project", required=True)
    recall_parser.add_argument("--kind", choices=("decision", "convention", "handoff", "note", "progress"))
    recall_parser.add_argument("--top-k", type=int, default=8)
    recall_parser.add_argument("--include-superseded", action="store_true")
    recall_parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.command == "migrate":
        PostgresStore().migrate()
        print("migrations applied")
    elif args.command == "index":
        from .ingest import sync

        report = sync(args.root, args.project, verbose=True)
        print(
            f"{report.project}: {report.files} files, {report.changed} changed, {report.removed} removed, "
            f"{report.embedded} chunks embedded with {report.model}, {report.memories} memories restored"
        )
    elif args.command == "read":
        from .retrieval import read_file

        try:
            result = read_file(args.path, args.project, args.start, args.end)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(result.text)
    elif args.command == "mcp":
        from .mcp_server import build_server

        build_server(args.project).run("stdio")
    elif args.command == "remember":
        from .memory import MemoryRefused, remember

        try:
            memory, embedded = remember(args.text, args.project, args.source, args.kind, args.supersedes)
        except MemoryRefused as exc:
            raise SystemExit(str(exc)) from exc
        print(f"saved {memory.id}" + ("" if embedded else " without a vector; the next index embeds it"))
    elif args.command == "recall":
        from .memory import recall

        hits = recall(args.query, args.project, args.kind, args.top_k, args.include_superseded)
        if args.json:
            print(json.dumps([asdict(hit) for hit in hits], ensure_ascii=False, indent=2))
            return
        for hit in hits:
            where = hit.memory_id if hit.origin == "memory" else f"{hit.source}:{hit.start_line}-{hit.end_line}"
            first_line = hit.text.splitlines()[0][:80] if hit.text else ""
            print(f"{hit.score:.4f}  {hit.kind}  {where}  {first_line}")
    elif args.command == "symbol":
        from .retrieval import find_symbol

        for row in find_symbol(args.name, args.project):
            exported = "exported " if row["exported"] else ""
            print(f"{row['path']}:{row['start_line']}-{row['end_line']}  {exported}{row['kind']} {row['name']}")
    elif args.command == "uses":
        from .retrieval import where_used

        for row in where_used(args.name, args.project):
            target = row["resolved_path"] or row["specifier"]
            print(f"{row['path']}  {row['name']} as {row['alias'] or '-'} from {target}")
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
