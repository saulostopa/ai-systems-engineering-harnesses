"""MCP server over the same functions as the CLI, one project per server."""

from __future__ import annotations

from dataclasses import asdict
from functools import wraps
from typing import Literal

import psycopg
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .memory import MemoryRefused, memory_file, recall as recall_memories, remember as remember_memory
from .retrieval import find_symbol as find_definitions, read_file, search_code as search_hits, where_used
from .store import PostgresStore

MAX_TOP_K = 30
# Claude Code hides MCP tools behind its tool search by default, and an agent that
# cannot see them falls back to grep.
ALWAYS_LOAD = {"anthropic/alwaysLoad": True}
INSTRUCTIONS = """\
Code memory of one repository, kept in a local index.
Use search_code to find code by meaning, when you do not know the exact name.
Use find_symbol to go from a name to its definition and importers.
Use recall before a change, to find earlier decisions and feature logs.
Use remember for a decision or convention a later session needs, never for a secret.
Keep using grep for exact text. `stale` means the file changed after indexing, so its lines may have moved.
"""


def _guarded(tool):
    """Turn an unavailable database into a message the agent can act on."""

    @wraps(tool)
    def run(*args, **kwargs):
        try:
            return tool(*args, **kwargs)
        except psycopg.OperationalError as exc:
            raise ToolError("PostgreSQL is not reachable: run `docker compose up -d postgres`, or use grep.") from exc
        except psycopg.errors.UndefinedTable as exc:
            raise ToolError("the database has no index yet: run the `index` command.") from exc

    return run


def _top_k(value: int) -> int:
    return max(1, min(value, MAX_TOP_K))


def build_server(project: str, embedder=None, store: PostgresStore | None = None) -> FastMCP:
    store = store or PostgresStore()
    server = FastMCP("harness-code-memory", instructions=INSTRUCTIONS, log_level="WARNING")

    @server.tool(structured_output=False, meta=ALWAYS_LOAD)
    @_guarded
    def search_code(query: str, collection: Literal["code", "docs"] | None = None, top_k: int = 8) -> dict:
        """Search the repository by meaning and by text. Returns path, lines and text read from disk."""

        hits = search_hits(query, project, collection, _top_k(top_k), embedder=embedder, store=store)
        return {"hits": [asdict(hit) for hit in hits]}

    @server.tool(structured_output=False, meta=ALWAYS_LOAD)
    @_guarded
    def find_symbol(name: str) -> dict:
        """Where a function, component or type is defined and which files import it. Also accepts a file path, for its importers."""

        return {
            "definitions": find_definitions(name, project, store=store),
            "importers": where_used(name, project, store=store),
        }

    @server.tool(structured_output=False, meta=ALWAYS_LOAD)
    @_guarded
    def read_lines(path: str, start_line: int = 1, end_line: int | None = None) -> dict:
        """Read lines of an indexed file, by its path relative to the repository. Long ranges are cut, and `truncated` says so."""

        return asdict(read_file(path, project, start_line, end_line, store=store))

    @server.tool(structured_output=False, meta=ALWAYS_LOAD)
    @_guarded
    def remember(
        text: str,
        source: str,
        kind: Literal["decision", "convention", "handoff", "note"] = "note",
        supersedes: str | None = None,
    ) -> dict:
        """Save a decision to a file in the repository, which must be committed. `source` says where it came from; `supersedes` is the id of the memory it replaces. Refuses text that looks like a credential."""

        try:
            memory, embedded = remember_memory(text, project, source, kind, supersedes, embedder=embedder, store=store)
        except MemoryRefused as exc:
            raise ToolError(str(exc)) from exc
        root = store.project(project)["root"]
        return {
            "id": memory.id,
            "file": str(memory_file(root).relative_to(root)),
            "embedded": embedded,
        }

    @server.tool(structured_output=False, meta=ALWAYS_LOAD)
    @_guarded
    def recall(
        query: str,
        kind: Literal["decision", "convention", "handoff", "note", "progress"] | None = None,
        top_k: int = 8,
        include_superseded: bool = False,
    ) -> dict:
        """Search saved memories and the feature progress and handoff logs. Replaced decisions stay hidden unless asked for."""

        hits = recall_memories(query, project, kind, _top_k(top_k), include_superseded, embedder=embedder, store=store)
        return {"hits": [asdict(hit) for hit in hits]}

    return server
